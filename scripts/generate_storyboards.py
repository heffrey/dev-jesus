#!/usr/bin/env python3
import argparse
import base64
import glob
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request


DEFAULT_MODEL = "gemini-3-pro-image-preview"
DEFAULT_ASPECT_RATIO = "16:9"
DEFAULT_IMAGE_SIZE = "2K"


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def load_definitions(path: str) -> dict:
    """Load character, setting, and extra definitions from JSON file."""
    if not os.path.isfile(path):
        return {"characters": {}, "settings": {}, "extras": {}, "style": {}}
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
        # Ensure all expected keys exist
        if "extras" not in data:
            data["extras"] = {}
        if "style" not in data:
            data["style"] = {}
        return data


def load_character_references(path: str) -> dict:
    """Load character visual references from JSON file.
    
    Returns a dict mapping character names to lists of storyboard image paths
    where they appear. Format: {"CharacterName": ["path/to/image1.jpg", ...]}
    """
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (json.JSONDecodeError, IOError):
        return {}


def save_character_references(path: str, references: dict) -> None:
    """Save character visual references to JSON file."""
    ensure_dir(os.path.dirname(path) if os.path.dirname(path) else ".")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(references, handle, indent=2, sort_keys=True)


def load_extra_references(path: str) -> dict:
    """Load extra visual references from JSON file.
    
    Returns a dict mapping extra names to lists of reference image paths.
    Format: {"ExtraName": ["path/to/image1.jpg", ...]}
    """
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (json.JSONDecodeError, IOError):
        return {}


def save_extra_references(path: str, references: dict) -> None:
    """Save extra visual references to JSON file."""
    ensure_dir(os.path.dirname(path) if os.path.dirname(path) else ".")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(references, handle, indent=2, sort_keys=True)


def load_setting_references(path: str) -> dict:
    """Load setting visual references from JSON file.
    
    Returns a dict mapping setting names to lists of reference image paths.
    Format: {"SettingName": {"indoor": ["path/to/indoor1.jpg", ...], "outdoor": ["path/to/outdoor1.jpg", ...]}}
    """
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (json.JSONDecodeError, IOError):
        return {}


def save_setting_references(path: str, references: dict) -> None:
    """Save setting visual references to JSON file."""
    ensure_dir(os.path.dirname(path) if os.path.dirname(path) else ".")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(references, handle, indent=2, sort_keys=True)


def sync_canonical_references(
    character_references: dict,
    definitions: dict,
    output_dir: str,
) -> bool:
    """Scan output_dir for canonical ref-*.jpg/png files and add missing ones to character_references.
    
    This ensures that manually created or externally generated reference images are properly
    linked to their characters in the reference database.
    
    Returns True if any changes were made.
    """
    changed = False
    
    # Build a mapping of character names (lowercase) to their canonical names
    char_name_map = {}  # lowercase -> canonical name
    for char_key, char_data in definitions.get("characters", {}).items():
        canonical_name = char_data.get("name", char_key)
        # Map the canonical name
        char_name_map[canonical_name.lower()] = canonical_name
        # Also map aliases
        for alias in char_data.get("aliases", []):
            char_name_map[alias.lower()] = canonical_name
    
    # Scan for ref-*.jpg and ref-*.png files in output_dir
    for ext in ["jpg", "jpeg", "png"]:
        pattern = os.path.join(output_dir, f"ref-*.{ext}")
        for ref_path in glob.glob(pattern):
            basename = os.path.basename(ref_path)
            # Skip non-character refs (settings, extras, style)
            if basename.startswith("ref-setting-") or basename.startswith("ref-extra-") or basename.startswith("ref-style"):
                continue
            
            # Extract character name from filename: ref-joel.jpg -> joel
            # Handle names with dashes: ref-joel's-brother.jpg -> joel's brother
            name_part = basename[4:]  # Remove "ref-" prefix
            name_part = os.path.splitext(name_part)[0]  # Remove extension
            name_part = name_part.replace("-", " ").replace("'", "'")  # Normalize
            
            # Try to find matching character (exact match only to avoid false positives)
            canonical_name = None
            
            # Try exact match with the extracted name
            if name_part.lower() in char_name_map:
                canonical_name = char_name_map[name_part.lower()]
            else:
                # Try title case version
                title_name = name_part.title()
                if title_name.lower() in char_name_map:
                    canonical_name = char_name_map[title_name.lower()]
                # Note: We intentionally do NOT do partial matching here to avoid
                # false positives like "the pharisees" matching "Aris"
            
            if canonical_name:
                # Get relative path for storage (relative to script root/repo root)
                script_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
                rel_path = os.path.relpath(ref_path, script_root)
                
                # Check if this ref is already in the character's references
                if canonical_name not in character_references:
                    character_references[canonical_name] = []
                
                # Check if ref path is already in the list (in any form)
                ref_basename = os.path.basename(ref_path)
                already_present = any(
                    os.path.basename(existing_path) == ref_basename
                    for existing_path in character_references[canonical_name]
                )
                
                if not already_present:
                    # Insert at the beginning (canonical refs should be first)
                    character_references[canonical_name].insert(0, rel_path)
                    changed = True
    
    return changed


def get_style_reference_path(output_dir: str) -> str:
    """Get the path to the master style reference image."""
    # Check for common extensions
    for ext in ["jpg", "jpeg", "png"]:
        path = os.path.join(output_dir, f"ref-style.{ext}")
        if os.path.isfile(path):
            return path
    return None


def find_character_reference_images(
    character_name: str,
    character_references: dict,
    output_dir: str,
    max_references: int = 2,
) -> list[str]:
    """Find existing storyboard images that contain a character.
    
    Prioritizes ref- images (canonical reference images) over storyboard images.
    Returns a list of absolute paths to reference images, up to max_references.
    """
    if character_name not in character_references:
        return []
    
    reference_paths = character_references[character_name]
    
    # Separate ref- images (canonical references) from storyboard images
    ref_images = []
    storyboard_images = []
    
    for ref_path in reference_paths:
        # Check if this is a canonical reference image (ref-*.jpg/png)
        path_basename = os.path.basename(ref_path).lower()
        if path_basename.startswith("ref-"):
            ref_images.append(ref_path)
        else:
            storyboard_images.append(ref_path)
    
    # Prioritize: use ref- image first, then storyboard images
    prioritized_paths = ref_images[:1]  # Always use canonical ref if available
    if len(prioritized_paths) < max_references:
        # Add storyboard images up to max_references
        remaining = max_references - len(prioritized_paths)
        prioritized_paths.extend(storyboard_images[:remaining])
    
    # Get script root for resolving cross-directory references
    script_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    
    valid_paths = []
    for ref_path in prioritized_paths:
        # Handle both relative and absolute paths
        if os.path.isabs(ref_path):
            full_path = ref_path
        else:
            # Try multiple resolution strategies:
            # 1. Relative to output_dir
            # 2. Relative to current working directory
            # 3. Relative to script root (for cross-directory references like executive/boards/ref-*.jpg)
            full_path = os.path.join(output_dir, ref_path)
            if not os.path.isfile(full_path):
                full_path = os.path.join(os.getcwd(), ref_path)
            if not os.path.isfile(full_path):
                full_path = os.path.join(script_root, ref_path)
        
        if os.path.isfile(full_path):
            # Ensure we return absolute paths
            abs_path = os.path.abspath(full_path)
            valid_paths.append(abs_path)
    
    return valid_paths


def update_character_references(
    character_references: dict,
    character_name: str,
    image_path: str,
    output_dir: str,
) -> None:
    """Add a new image reference for a character."""
    if character_name not in character_references:
        character_references[character_name] = []
    
    # Store path relative to output_dir for portability
    if os.path.isabs(image_path):
        rel_path = os.path.relpath(image_path, output_dir)
    else:
        rel_path = image_path
    
    # Add to front of list (most recent first) and keep only last 10
    if rel_path not in character_references[character_name]:
        character_references[character_name].insert(0, rel_path)
        character_references[character_name] = character_references[character_name][:10]


def detect_entities(scene_text: str, definitions: dict) -> tuple[list[dict], list[dict], list[dict]]:
    """Detect which characters, settings, and extras appear in the scene text.
    
    Improved detection that distinguishes between:
    - Visually present: characters doing actions, speaking, or being directly observed
    - Just mentioned: names in narration, metaphors, or references to other locations
    """
    scene_lower = scene_text.lower()
    found_characters = []
    found_settings = []
    found_extras = []
    
    # Extract section headers to identify the actual setting
    section_headers = []
    for line in scene_text.splitlines():
        if line.startswith("## "):
            section_headers.append(line.lower())

    # Indicators of visual presence (defined once for reuse)
    action_verbs = ['stood', 'walked', 'moved', 'looked', 'turned', 'entered', 'sat', 'hailed', 'said', 'spoke', 'reached', 'watched', 'felt', 'stepped', 'stepping', 'was', 'is', 'did', 'had', 'found', 'began', 'stopped', 'pulled', 'reached', 'stepped', 'slumped', 'sliding', 'waiting', 'began', 'struggled', 'calibrate', 'seized', 'leaving', 'forcing', 'exhaled', 'swallowing', 'adjust']
    location_preps = [' at ', ' in ', ' on ', ' inside ', ' outside ', ' within ', ' of ', ' from ']
    
    # Check for characters - prioritize visually present (doing actions, speaking)
    for char_key, char_data in definitions.get("characters", {}).items():
        # Check name and aliases
        names_to_check = [char_key, char_data.get("name", "")]
        if "aliases" in char_data:
            names_to_check.extend(char_data["aliases"])
        
        matched = False
        is_visually_present = False
        
        for name in names_to_check:
            if not name:
                continue
            name_lower = name.lower()
            
            # Check for exact match with word boundaries
            pattern = r'\b' + re.escape(name_lower) + r'\b'
            matches = list(re.finditer(pattern, scene_lower))
            
            if matches:
                # Check if character is visually present (doing actions, speaking, or being directly observed)
                for match in matches:
                    start, end = match.span()
                    # Get context around the match (50 chars before and after)
                    context_start = max(0, start - 50)
                    context_end = min(len(scene_lower), end + 50)
                    context = scene_lower[context_start:context_end]
                    
                    # Indicators of visual presence:
                    # - Character doing actions (verbs before/after name)
                    # - Character speaking (quotes nearby)
                    has_quotes = '"' in context or "'" in context
                    # - Character being directly observed (pronouns, "he", "she", "they" nearby)
                    has_pronouns = any(pronoun in context for pronoun in [' he ', ' she ', ' they ', ' his ', ' her ', ' their '])
                    # - Character name in subject position (followed by verb)
                    followed_by_verb = any(context[end - context_start:end - context_start + 20].startswith(verb) for verb in [' was ', ' is ', ' did ', ' had ', ' stood', ' walked', ' moved', ' looked', ' turned', ' entered', ' sat', ' hailed', ' said', ' spoke'])
                    
                    if any(verb in context for verb in action_verbs) or has_quotes or (has_pronouns and followed_by_verb):
                        is_visually_present = True
                        break
                
                # If visually present, add immediately; otherwise check if it's a strong mention
                if is_visually_present:
                    if char_data not in found_characters:
                        found_characters.append(char_data)
                    matched = True
                    break
                # If not visually present but mentioned, only add if it's a direct reference (not just in narration)
                elif any(match for match in matches if '"' in scene_lower[max(0, match.start()-20):match.end()+20]):
                    # Character mentioned in dialogue - likely present
                    if char_data not in found_characters:
                        found_characters.append(char_data)
                    matched = True
                    break
            
            # For multi-word names/aliases, check individual words but require visual presence indicators
            # Exclude common words that cause false positives
            # IMPORTANT: For multi-word aliases, require at least 2 significant words to match (not just one)
            # to avoid false positives from common words like "pulse", "life", etc.
            common_words = {'the', 'of', 'in', 'a', 'an', 'and', 'or', 'to', 'for', 'with', 'from', 'on', 'at', 'by', 'as', 'is', 'was', 'are', 'were', 'be', 'been', 'being', 'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could', 'should', 'may', 'might', 'must', 'can'}
            words = name_lower.split()
            
            if len(words) > 1 and not matched:
                # Extract significant words (4+ chars, not common words)
                significant_words = [w for w in words if len(w) >= 4 and w not in common_words]
                
                # Require at least 2 significant words to match for multi-word aliases
                # This prevents false positives from single common words like "pulse", "life", etc.
                if len(significant_words) >= 2:
                    matched_words = []
                    for word in significant_words:
                        word_pattern = r'\b' + re.escape(word) + r'\b'
                        word_matches = list(re.finditer(word_pattern, scene_lower))
                        
                        for match in word_matches:
                            start, end = match.span()
                            context = scene_lower[max(0, start-30):min(len(scene_lower), end+30)]
                            # Only match if there are action indicators nearby (stronger requirement)
                            if any(verb in context for verb in action_verbs) or '"' in context:
                                matched_words.append((word, start))
                                break
                    
                    # Only add character if at least 2 significant words matched
                    # AND they appear within reasonable proximity (within 100 chars of each other)
                    if len(matched_words) >= 2:
                        # Check if matched words are in proximity
                        positions = [pos for _, pos in matched_words]
                        min_pos = min(positions)
                        max_pos = max(positions)
                        if max_pos - min_pos <= 100:  # Words within 100 chars
                            if char_data not in found_characters:
                                found_characters.append(char_data)
                                matched = True
                                break
                        # If words are too far apart, they might be false matches (e.g., "Thorne" in "Thorne Industries")
                        # Fall through to single-word matching logic below
                    
                    # If only one word matched, OR if 2+ words matched but are too far apart,
                    # check if the single word is a valid match (capitalized, with action context)
                    if len(matched_words) == 1 or (len(matched_words) >= 2 and not matched):
                        # Only one significant word matched - check if it's a strong match with action context
                        # This handles cases like "Elias" from "Elias Thorne" appearing alone
                        # BUT: Avoid false positives from compound nouns (e.g., "ghost ship" matching "ghost" from "The Ghost in the Hamptons")
                        word, word_pos = matched_words[0]
                        word_pattern = r'\b' + re.escape(word) + r'\b'
                        word_matches = list(re.finditer(word_pattern, scene_lower))
                        
                        for match in word_matches:
                            start, end = match.span()
                            context = scene_lower[max(0, start-30):min(len(scene_lower), end+30)]
                            
                            # Check if word is part of a compound noun (e.g., "ghost ship", "wall street")
                            # If the next word after the match is a noun (not a verb), it might be a compound
                            after_match = scene_lower[end:min(len(scene_lower), end+15)].strip()
                            # Common compound patterns: word + noun (not verb)
                            # If word is immediately followed by another word (not punctuation/space), check if it's a compound
                            next_char = scene_lower[end] if end < len(scene_lower) else ' '
                            if next_char == ' ':
                                # Check the next word - if it's a noun (not a verb), might be compound
                                next_word_match = re.match(r'\s+(\w+)', after_match)
                                if next_word_match:
                                    next_word = next_word_match.group(1)
                                    # If next word is likely a noun (not in action_verbs), it might be a compound
                                    # But we still want to match if there's strong action context
                                    is_likely_compound = next_word not in action_verbs and len(next_word) > 3
                                else:
                                    is_likely_compound = False
                            else:
                                is_likely_compound = False
                            
                            # Strong action context required for single word from multi-word alias
                            # CRITICAL: Require the word to be capitalized (proper noun) to avoid compound noun false positives
                            # This prevents "ghost" in "ghost ship" from matching "The Ghost in the Hamptons"
                            # Proper names are always capitalized, so this is a safe requirement
                            has_action = any(verb in context for verb in action_verbs) or '"' in context
                            
                            if has_action:
                                # Check if word is capitalized (proper noun) - REQUIRED for single word from multi-word alias
                                # This avoids false positives from compound nouns like "ghost ship", "wall street", etc.
                                original_match = scene_text[start:end] if start < len(scene_text) else scene_lower[start:end]
                                is_capitalized = original_match and original_match[0].isupper() if original_match else False
                                has_quotes = '"' in context or "'" in context
                                
                                # REQUIRE capitalization (or quotes) for single word from multi-word alias
                                # This is safe because character names/aliases are proper nouns
                                if not (is_capitalized or has_quotes):
                                    continue  # Skip this match - word is not capitalized, likely not a proper noun reference
                                
                                # Word is capitalized or in quotes - safe to match as proper noun
                                if char_data not in found_characters:
                                    found_characters.append(char_data)
                                    matched = True
                                    break
                        if matched:
                            break
                elif len(significant_words) == 1:
                    # For single significant word in multi-word alias, require the FULL alias phrase to appear
                    # This is stricter to avoid false positives
                    full_phrase_pattern = r'\b' + r'\s+'.join([re.escape(w) for w in words if w not in common_words]) + r'\b'
                    
                    # NEW: Also check if the single significant word appears alone with action context
                    # This handles cases like "Elias" from "Elias Thorne" appearing alone
                    if not re.search(full_phrase_pattern, scene_lower) and significant_words:
                        single_word = significant_words[0]
                        single_word_pattern = r'\b' + re.escape(single_word) + r'\b'
                        single_word_matches = list(re.finditer(single_word_pattern, scene_lower))
                        
                        for match in single_word_matches:
                            start, end = match.span()
                            context = scene_lower[max(0, start-30):min(len(scene_lower), end+30)]
                            # Check for action context - character doing something
                            if any(verb in context for verb in action_verbs) or '"' in context:
                                if char_data not in found_characters:
                                    found_characters.append(char_data)
                                    matched = True
                                    break
                        if matched:
                            break
                    
                    if re.search(full_phrase_pattern, scene_lower):
                        # Full phrase found - check for action context
                        match = re.search(full_phrase_pattern, scene_lower)
                        if match:
                            start, end = match.span()
                            context = scene_lower[max(0, start-30):min(len(scene_lower), end+30)]
                            if any(verb in context for verb in action_verbs) or '"' in context:
                                if char_data not in found_characters:
                                    found_characters.append(char_data)
                                    matched = True
                                    break
        
        # Fallback: only if substantial name and in dialogue or action context
        if not matched:
            for name in names_to_check:
                if not name or len(name) < 4:
                    continue
                name_lower = name.lower()
                
                if name_lower in scene_lower:
                    # Check if in dialogue or action context
                    idx = scene_lower.find(name_lower)
                    context = scene_lower[max(0, idx-30):min(len(scene_lower), idx+len(name_lower)+30)]
                    
                    if '"' in context or any(verb in context for verb in [' said', ' spoke', ' asked', ' replied', ' stood', ' walked', ' moved']):
                        if char_data not in found_characters:
                            found_characters.append(char_data)
                        break

    # Check for settings - prioritize actual location vs just mentioned
    for setting_key, setting_data in definitions.get("settings", {}).items():
        # Check name and aliases
        names_to_check = [setting_key, setting_data.get("name", "")]
        if "aliases" in setting_data:
            names_to_check.extend(setting_data["aliases"])
        
        matched = False
        is_actual_location = False
        
        for name in names_to_check:
            if not name:
                continue
            name_lower = name.lower()
            pattern = r'\b' + re.escape(name_lower) + r'\b'
            matches = list(re.finditer(pattern, scene_lower))
            
            if matches:
                # Check if it's the actual location (in section header, or with location indicators)
                for match in matches:
                    start, end = match.span()
                    before_context = scene_lower[max(0, start-60):start]
                    after_context = scene_lower[end:min(len(scene_lower), end+40)]
                    context = scene_lower[max(0, start-30):min(len(scene_lower), end+30)]
                    
                    # FIRST: Check if it's clearly just a reference (exclude these immediately)
                    # Check both before and after context for reference phrases
                    combined_context = before_context + ' ' + after_context
                    reference_indicators = [
                        ' from ', 'from the', ' toward ', 'toward the', ' heading toward', ' heading to',
                        ' leaving ', ' behind ', ' observing ', ' no longer ', ' height of the',
                        ' monuments of ', ' decaying husk of ', ' returning to ', ' back to ',
                        ' going to ', ' destination ', 'heading toward the', 'toward the decaying',
                        ' compared to ', 'compared to the', ' compared with ', 'compared with the',
                        ' versus ', ' vs ', ' unlike ', ' like the ', ' similar to ',
                        ' clarity of the ', ' of the ', ' vacuum of the ', ' sterile height of the '
                    ]
                    is_just_reference = any(indicator in combined_context for indicator in reference_indicators)
                    
                    if is_just_reference:
                        # Skip this match - it's just a reference, not the actual location
                        continue
                    
                    # Indicators of actual location:
                    # - In section header (time/location markers) - strongest indicator
                    in_header = any(name_lower in header for header in section_headers)
                    if in_header:
                        is_actual_location = True
                        break
                    
                    # - Positive location prepositions (at, in, inside, outside, on, within)
                    positive_location_preps = [' at ', ' in ', ' inside ', ' outside ', ' within ', ' on ']
                    has_positive_prep = any(prep in context for prep in positive_location_preps)
                    if has_positive_prep:
                        is_actual_location = True
                        break
                
                if is_actual_location:
                    if setting_data not in found_settings:
                        found_settings.append(setting_data)
                    matched = True
                    break
            
            # For multi-word settings, check individual words but require location indicators
            # Exclude common words and be very strict about reference phrases
            # IMPORTANT: If the full name was found but skipped as a reference, don't try word matching
            # (this prevents "street" from "142 Miller Street" matching "street" in "street level")
            common_words = {'the', 'of', 'in', 'a', 'an', 'and', 'or', 'to', 'for', 'with', 'from', 'on', 'at', 'by', 'as'}
            words = name_lower.split()
            # Only do word matching if we haven't found any matches yet AND the full name wasn't a reference
            full_name_was_reference = False
            if matches:
                for match in matches:
                    start, end = match.span()
                    before_context = scene_lower[max(0, start-60):start]
                    after_context = scene_lower[end:min(len(scene_lower), end+40)]
                    combined_context = before_context + ' ' + after_context
                    reference_indicators = [
                        ' from ', 'from the', ' toward ', 'toward the', ' heading toward', ' heading to',
                        ' leaving ', ' behind ', ' observing ', ' no longer ', ' height of the',
                        ' monuments of ', ' decaying husk of ', ' returning to ', ' back to ',
                        ' going to ', ' destination ', 'heading toward the', 'toward the decaying',
                        ' compared to ', 'compared to the', ' compared with ', 'compared with the',
                        ' versus ', ' vs ', ' unlike ', ' like the ', ' similar to ',
                        ' clarity of the ', ' of the ', ' vacuum of the ', ' sterile height of the '
                    ]
                    if any(indicator in combined_context for indicator in reference_indicators):
                        full_name_was_reference = True
                        break
            
            if len(words) > 1 and not matched and not full_name_was_reference:
                for word in words:
                    # Skip common words and require substantial words (4+ chars)
                    if len(word) >= 4 and word not in common_words:
                        word_pattern = r'\b' + re.escape(word) + r'\b'
                        word_matches = list(re.finditer(word_pattern, scene_lower))
                        for match in word_matches:
                            start, end = match.span()
                            before_context = scene_lower[max(0, start-60):start]
                            after_context = scene_lower[end:min(len(scene_lower), end+40)]
                            combined_context = before_context + ' ' + after_context
                            
                            # Check if it's a reference (same check as above - must match the full name check)
                            reference_indicators = [
                                ' from ', 'from the', ' toward ', 'toward the', ' heading toward', ' heading to',
                                ' leaving ', ' behind ', ' observing ', ' no longer ', ' height of the',
                                ' monuments of ', ' decaying husk of ', ' returning to ', ' back to ',
                                ' going to ', ' destination ', 'heading toward the', 'toward the decaying',
                                ' compared to ', 'compared to the', ' compared with ', 'compared with the',
                                ' versus ', ' vs ', ' unlike ', ' like the ', ' similar to ',
                                ' clarity of the ', ' of the ', ' vacuum of the ', ' sterile height of the '
                            ]
                            is_just_reference = any(indicator in combined_context for indicator in reference_indicators)
                            
                            if is_just_reference:
                                continue
                            
                            # Only match if positive location indicators present (not references)
                            # But be careful: if word appears in header, make sure it's actually referring to this setting
                            # (e.g., "street" in "The Street Level" shouldn't match "142 Miller Street")
                            positive_location_preps = [' at ', ' in ', ' inside ', ' outside ', ' within ', ' on ']
                            has_positive_prep = any(prep in combined_context for prep in positive_location_preps)
                            # Check if word in header is actually referring to this setting (not just a common word)
                            in_header = False
                            if len(word) >= 5:  # Only check substantial words (avoid "the", "of", etc.)
                                for header in section_headers:
                                    # Make sure the word appears in context that suggests it's this setting
                                    if word in header and word in combined_context:
                                        # Check if the full setting name is nearby
                                        full_name_nearby = name_lower in combined_context
                                        if full_name_nearby:
                                            in_header = True
                                            break
                            
                            if (has_positive_prep or in_header) and not is_just_reference:
                                if setting_data not in found_settings:
                                    found_settings.append(setting_data)
                                matched = True
                                break
                        if matched:
                            break
                if matched:
                    break

    # Check for extras
    # For extras, be more strict - only match full names/aliases to avoid false positives
    # Extras are specific objects and partial word matches are likely incorrect
    for extra_key, extra_data in definitions.get("extras", {}).items():
        # Check name and aliases
        names_to_check = [extra_key, extra_data.get("name", "")]
        if "aliases" in extra_data:
            names_to_check.extend(extra_data["aliases"])
        
        matched = False
        for name in names_to_check:
            if not name:
                continue
            name_lower = name.lower()
            # Only match full name/alias with word boundaries (no partial word matching)
            pattern = r'\b' + re.escape(name_lower) + r'\b'
            if re.search(pattern, scene_lower):
                if extra_data not in found_extras:
                    found_extras.append(extra_data)
                matched = True
                break

    return found_characters, found_settings, found_extras


def first_sentence(text: str) -> str:
    text = " ".join(text.strip().split())
    if not text:
        return ""
    match = re.split(r"(?<=[.!?])\s+", text, maxsplit=1)
    return match[0]


def extract_sections(scene_text: str) -> list[tuple[str, str]]:
    sections = []
    current_title = None
    current_lines = []

    for line in scene_text.splitlines():
        if line.startswith("## "):
            if current_title is not None:
                sections.append((current_title, "\n".join(current_lines).strip()))
            current_title = line.replace("## ", "").strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_title is not None:
        sections.append((current_title, "\n".join(current_lines).strip()))

    return sections


def divide_scene_into_storyboards(scene_text: str, min_storyboards: int = 4, max_storyboards: int = 6) -> list[tuple[str, str]]:
    """Divide a scene into multiple storyboard chunks. Returns list of (chunk_title, chunk_text) tuples.
    
    Improved to be dialog-aware: splits at dialog boundaries when possible to allow richer dialog scenes.
    """
    sections = extract_sections(scene_text)
    storyboards = []
    
    if sections:
        # If we have sections, try to group them into storyboards
        # Each storyboard should cover 1-2 sections, but be more flexible for dialog-heavy sections
        sections_per_storyboard = max(1, len(sections) // max_storyboards)
        if sections_per_storyboard < 1:
            sections_per_storyboard = 1
        
        # Check if any section is dialog-heavy (has multiple quoted passages)
        dialog_heavy_sections = []
        for idx, (title, body) in enumerate(sections):
            dialog_count = len(re.findall(r'["\']', body))
            # If section has 3+ dialog quotes, it might benefit from being split
            if dialog_count >= 3:
                dialog_heavy_sections.append(idx)
        
        # If we have dialog-heavy sections and room, split them further
        if dialog_heavy_sections and len(sections) < max_storyboards * 1.5:
            sections_per_storyboard = 1  # One section per storyboard for dialog-heavy scenes
        
        for i in range(0, len(sections), sections_per_storyboard):
            chunk_sections = sections[i:i + sections_per_storyboard]
            chunk_title = chunk_sections[0][0] if chunk_sections else "Scene"
            chunk_text = "\n\n".join([f"## {title}\n\n{body}" for title, body in chunk_sections])
            storyboards.append((chunk_title, chunk_text))
    else:
        # If no sections, divide by paragraphs, but be dialog-aware
        paragraphs = [p.strip() for p in scene_text.split("\n\n") if p.strip() and not p.strip().startswith("#")]
        if not paragraphs:
            paragraphs = [scene_text]
        
        # Check dialog density - if paragraphs have lots of dialog, use smaller chunks
        total_dialog = sum(len(re.findall(r'["\']', p)) for p in paragraphs)
        avg_dialog_per_para = total_dialog / len(paragraphs) if paragraphs else 0
        
        # If average dialog per paragraph is high, use smaller chunks
        if avg_dialog_per_para >= 2:
            paragraphs_per_storyboard = max(1, len(paragraphs) // (max_storyboards + 1))
        else:
            paragraphs_per_storyboard = max(1, len(paragraphs) // max_storyboards)
        
        if paragraphs_per_storyboard < 1:
            paragraphs_per_storyboard = 1
        
        for i in range(0, len(paragraphs), paragraphs_per_storyboard):
            chunk_paragraphs = paragraphs[i:i + paragraphs_per_storyboard]
            chunk_title = f"Part {len(storyboards) + 1}"
            chunk_text = "\n\n".join(chunk_paragraphs)
            storyboards.append((chunk_title, chunk_text))
    
    # Ensure we have at least min_storyboards and at most max_storyboards
    if len(storyboards) < min_storyboards:
        # Split existing storyboards further
        new_storyboards = []
        for title, text in storyboards:
            paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
            if len(paragraphs) > 1:
                mid = len(paragraphs) // 2
                new_storyboards.append((f"{title} (Part 1)", "\n\n".join(paragraphs[:mid])))
                new_storyboards.append((f"{title} (Part 2)", "\n\n".join(paragraphs[mid:])))
            else:
                new_storyboards.append((title, text))
        storyboards = new_storyboards[:max_storyboards]
    elif len(storyboards) > max_storyboards:
        storyboards = storyboards[:max_storyboards]
    
    return storyboards


def derive_panel_instructions(chunk_text: str, panel_count: int, detected_characters: list[dict] = None) -> list[str]:
    """Generate panel instructions for a storyboard chunk, with special attention to dialog.
    
    Args:
        chunk_text: The text content of the chunk
        panel_count: Number of panels to generate
        detected_characters: List of character dicts detected in this chunk (for explicit naming)
    """
    sections = extract_sections(chunk_text)
    instructions = []
    
    # Extract character names for explicit mention in instructions
    character_names = []
    if detected_characters:
        for char in detected_characters:
            name = char.get('name', '')
            if name:
                character_names.append(name)
                # Also check for aliases
                if 'aliases' in char:
                    character_names.extend(char['aliases'])

    if sections:
        for title, body in sections:
            # Extract key moments from the body, prioritizing dialog
            paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
            
            # First, look for dialog (quoted text) - these get their own panels
            # Use a more robust regex to find dialog with context
            dialog_pattern = r'["\']([^"\']+)["\']'
            dialog_matches = list(re.finditer(dialog_pattern, body))
            
            for match in dialog_matches[:4]:  # Up to 4 dialog quotes per section
                quote = match.group(1)
                start_pos = match.start()
                end_pos = match.end()
                
                # Find the paragraph containing this quote
                para_start = body.rfind('\n\n', 0, start_pos) + 2
                if para_start < 2:
                    para_start = 0
                para_end = body.find('\n\n', end_pos)
                if para_end == -1:
                    para_end = len(body)
                
                para_text = body[para_start:para_end].strip()
                
                # Get the sentence containing the quote
                sentences = re.split(r'(?<=[.!?])\s+', para_text)
                quote_context = ""
                for sent in sentences:
                    if quote in sent:
                        quote_context = sent.strip()
                        break
                
                if quote_context and quote_context not in instructions:
                    instructions.append(f"{title}: {quote_context}")
                elif quote and f'"{quote}"' not in str(instructions):
                    instructions.append(f"{title}: Character says: \"{quote}\"")
            
            # Then extract key narrative moments (up to 3 per section to allow for dialog)
            narrative_count = 0
            for para in paragraphs:
                if narrative_count >= 3:  # Increased from 2 to allow more panels
                    break
                # Skip if this paragraph is mostly dialog (has 2+ quotes)
                quote_count = len(re.findall(r'["\']', para))
                if quote_count >= 2:
                    continue
                sentence = first_sentence(para)
                if sentence and sentence not in instructions:
                    # If we have detected characters, try to make the sentence more explicit
                    enhanced_sentence = ensure_character_mentioned(sentence, character_names, para)
                    instructions.append(f"{title}: {enhanced_sentence}")
                    narrative_count += 1
    else:
        paragraphs = [p.strip() for p in chunk_text.split("\n\n") if p.strip()]
        
        # First extract dialog - process paragraph by paragraph to avoid cross-paragraph issues
        for paragraph in paragraphs:
            # Find all dialog quotes in this paragraph
            dialog_pattern = r'["\']([^"\']+)["\']'
            dialog_matches = list(re.finditer(dialog_pattern, paragraph))
            
            for match in dialog_matches[:2]:  # Up to 2 quotes per paragraph
                quote = match.group(1)
                # Skip very short quotes (likely punctuation artifacts)
                if len(quote.strip()) < 3:
                    continue
                
                # Get the sentence containing the quote
                sentences = re.split(r'(?<=[.!?])\s+', paragraph)
                quote_context = ""
                for sent in sentences:
                    if quote in sent:
                        quote_context = sent.strip()
                        break
                
                if quote_context and quote_context not in instructions:
                    instructions.append(quote_context)
                    if len(instructions) >= 5:  # Limit total dialog panels
                        break
            if len(instructions) >= 5:
                break
        
        # Then extract narrative moments
        for paragraph in paragraphs:
            # Skip if mostly dialog (has 2+ quotes)
            quote_count = len(re.findall(r'["\']', paragraph))
            if quote_count >= 2:
                continue
            sentence = first_sentence(paragraph)
            if sentence and sentence not in instructions:
                # If we have detected characters, try to make the sentence more explicit
                enhanced_sentence = ensure_character_mentioned(sentence, character_names, paragraph)
                instructions.append(enhanced_sentence)

    if not instructions:
        instructions = ["Establish the setting and key characters."]

    if panel_count is None:
        # Increased default range to 4-6 panels to allow for richer dialog
        panel_count = max(4, min(6, len(instructions)))

    if len(instructions) > panel_count:
        instructions = instructions[:panel_count]
    elif len(instructions) < panel_count:
        # Generate character-specific padding if characters are detected
        if character_names:
            primary_char = character_names[0]  # Use first detected character
            padding = [
                f"Atmospheric wide shot showing {primary_char} in the environment.",
                f"Close-up on {primary_char}'s reaction or expression.",
                f"Transition shot with {primary_char} that hints at the next beat.",
                f"Establishing shot of the environment with {primary_char} visible.",
                f"Detail shot showing {primary_char} and important visual elements."
            ]
        else:
            padding = [
                "Atmospheric wide shot that reinforces the mood.",
                "Close-up on a key character reaction.",
                "Transition shot that hints at the next beat.",
                "Establishing shot of the environment.",
                "Detail shot showing important visual elements."
            ]
        while len(instructions) < panel_count:
            instructions.append(padding[(len(instructions) - 1) % len(padding)])

    return instructions


def ensure_character_mentioned(sentence: str, character_names: list[str], context: str = "") -> str:
    """Ensure a sentence explicitly mentions a character if one is detected.
    
    Replaces pronouns (he, she, they) with character names when character_names are provided.
    """
    if not character_names:
        return sentence
    
    # Find the primary character (first one in the list)
    primary_char = character_names[0]
    
    # Check if sentence already mentions any character name
    sentence_lower = sentence.lower()
    for name in character_names:
        if name.lower() in sentence_lower:
            return sentence  # Already mentions a character
    
    # Try to replace pronouns with character name
    enhanced = sentence
    sentence_lower = sentence.lower()
    
    # Pattern: "he/she/they [verb]" -> "[Character] [verb]"
    # Replace all instances, not just first - process in order to avoid double replacement
    pronoun_replacements = [
        (r'\bhis\s+', f'{primary_char}\'s '),  # Do possessive first to avoid matching "his" in "he"
        (r'\bher\s+', f'{primary_char}\'s '),  # Do possessive first
        (r'\btheir\s+', f'{primary_char}\'s '),  # Do possessive first
        (r'\bhe\s+', f'{primary_char} '),
        (r'\bshe\s+', f'{primary_char} '),
        (r'\bthey\s+', f'{primary_char} '),
        (r'\bhim\s+', f'{primary_char} '),
        (r'\bher\b', f'{primary_char}'),  # Without space for end of sentence
    ]
    
    for pattern, replacement in pronoun_replacements:
        if re.search(pattern, sentence_lower):
            enhanced = re.sub(pattern, replacement, enhanced, flags=re.IGNORECASE)
            sentence_lower = enhanced.lower()  # Update for next check
    
    # If still no character mentioned and sentence uses pronouns, prepend character name
    if enhanced == sentence or (not any(name.lower() in enhanced.lower() for name in character_names) and any(pronoun in sentence_lower for pronoun in [' he ', ' she ', ' they ', ' his ', ' her ', ' their '])):
        # Try to replace at the start if sentence begins with pronoun-like structure
        if re.match(r'^(the|a|an)\s+', sentence_lower):
            enhanced = f"{primary_char}: {sentence}"
        else:
            # Insert character name before first verb or after first few words
            words = sentence.split()
            if len(words) > 3:
                # Insert after first few words if sentence is long
                enhanced = ' '.join(words[:2] + [primary_char] + words[2:])
            else:
                enhanced = f"{primary_char}: {sentence}"
    
    return enhanced


def build_character_reference_prompt(
    character: dict,
    definitions: dict,
) -> str:
    """Build a prompt for generating a single-panel reference image of a character."""
    char_name = character.get("name", "Unknown")
    lines = [
        f"Create a single-panel character reference image for {char_name}.",
        "",
        "This is a REFERENCE IMAGE that will be used to maintain visual consistency in future storyboards.",
        "",
        f"Character: {char_name}",
    ]
    
    if "description" in character:
        lines.append(f"Description: {character['description']}")
    if "appearance" in character:
        lines.append(f"Appearance: {character['appearance']}")
    
    lines.extend([
        "",
        "Requirements:",
        "- Single panel showing ONLY this character",
        "- Full body or upper body shot that clearly shows all distinctive features",
        "- Neutral pose, clear lighting",
        "- Focus on character design consistency: facial features, clothing, hair, physical characteristics",
        "- Style: comic book, limited-palette, inked",
        "- This image will be used as a visual reference for future storyboards",
        "",
        "CRITICAL: This is a reference image. Draw the character EXACTLY as described above.",
        "All future storyboards must match this character's appearance precisely.",
    ])
    
    return "\n".join(lines).strip() + "\n"


def generate_character_reference_image(
    api_key: str,
    model: str,
    character: dict,
    definitions: dict,
    output_dir: str,
    max_retries: int,
    retry_base: float,
    verbose: bool = False,
) -> str:
    """Generate a single-panel reference image for a character. Returns the path to the generated image."""
    char_name = character.get("name", "Unknown")
    prompt = build_character_reference_prompt(character, definitions)
    
    if verbose:
        print(f"    Generating reference image for {char_name}...", flush=True)
    
    try:
        response = call_gemini(
            api_key,
            model,
            prompt,
            max_retries,
            retry_base,
            verbose,
            reference_images=None,
        )
        images = extract_images(response)
        if not images:
            if verbose:
                print(f"    ⚠️  No reference image returned for {char_name}", file=sys.stderr, flush=True)
            return None
        
        # Use the first image
        mime, data = images[0]
        ext = "png" if mime == "image/png" else "jpg"
        output_path = os.path.join(output_dir, f"ref-{char_name.lower().replace(' ', '-')}.{ext}")
        
        with open(output_path, "wb") as handle:
            handle.write(data)
        
        if verbose:
            size_kb = len(data) / 1024
            print(f"    ✓ Generated reference image: {output_path} ({size_kb:.1f} KB)", flush=True)
        
        return output_path
    except Exception as exc:
        if verbose:
            print(f"    ✗ Error generating reference for {char_name}: {exc}", file=sys.stderr, flush=True)
        return None


def build_extra_reference_prompt(extra: dict) -> str:
    """Build a prompt for generating a single-panel reference image of an extra."""
    extra_name = extra.get("name", "Unknown")
    lines = [
        f"Create a single-panel reference image for {extra_name}.",
        "",
        "This is a REFERENCE IMAGE that will be used to maintain visual consistency in future storyboards.",
        "",
        f"Extra: {extra_name}",
    ]
    
    if "description" in extra:
        lines.append(f"Description: {extra['description']}")
    if "appearance" in extra:
        lines.append(f"Appearance: {extra['appearance']}")
    
    lines.extend([
        "",
        "Requirements:",
        "- Single panel showing ONLY this extra (non-character entity)",
        "- Clear, detailed view that shows all distinctive features",
        "- Neutral presentation, clear lighting",
        "- Focus on design consistency: shape, color, texture, details",
        "- Style: comic book, limited-palette, inked",
        "- This image will be used as a visual reference for future storyboards",
        "",
        "CRITICAL: This is a reference image. Draw the extra EXACTLY as described above.",
        "All future storyboards must match this extra's appearance precisely.",
    ])
    
    return "\n".join(lines).strip() + "\n"


def generate_extra_reference_image(
    api_key: str,
    model: str,
    extra: dict,
    output_dir: str,
    max_retries: int,
    retry_base: float,
    verbose: bool = False,
) -> str:
    """Generate a single-panel reference image for an extra. Returns the path to the generated image."""
    extra_name = extra.get("name", "Unknown")
    prompt = build_extra_reference_prompt(extra)
    
    if verbose:
        print(f"    Generating reference image for extra: {extra_name}...", flush=True)
    
    try:
        response = call_gemini(
            api_key,
            model,
            prompt,
            max_retries,
            retry_base,
            verbose,
            reference_images=None,
        )
        images = extract_images(response)
        if not images:
            if verbose:
                print(f"    ⚠️  No reference image returned for {extra_name}", file=sys.stderr, flush=True)
            return None
        
        # Use the first image
        mime, data = images[0]
        ext = "png" if mime == "image/png" else "jpg"
        output_path = os.path.join(output_dir, f"ref-extra-{extra_name.lower().replace(' ', '-')}.{ext}")
        
        with open(output_path, "wb") as handle:
            handle.write(data)
        
        if verbose:
            size_kb = len(data) / 1024
            print(f"    ✓ Generated reference image: {output_path} ({size_kb:.1f} KB)", flush=True)
        
        return output_path
    except Exception as exc:
        if verbose:
            print(f"    ✗ Error generating reference for {extra_name}: {exc}", file=sys.stderr, flush=True)
        return None


def build_setting_reference_prompt(setting: dict, view_type: str) -> str:
    """Build a prompt for generating a reference image of a setting.
    
    view_type should be "indoor" or "outdoor".
    """
    setting_name = setting.get("name", "Unknown")
    lines = [
        f"Create a single-panel reference image for {setting_name} ({view_type} view).",
        "",
        "This is a REFERENCE IMAGE that will be used to maintain visual consistency in future storyboards.",
        "",
        f"Setting: {setting_name}",
        f"View: {view_type}",
    ]
    
    if "description" in setting:
        lines.append(f"Description: {setting['description']}")
    if "visual_details" in setting:
        lines.append(f"Visual details: {setting['visual_details']}")
    
    lines.extend([
        "",
        "Requirements:",
        f"- Single panel showing {setting_name} from an {view_type} perspective",
        "- Wide establishing shot that shows the full setting",
        "- Clear lighting, showing all architectural and environmental details",
        "- Focus on design consistency: architecture, colors, textures, atmosphere",
        "- Style: comic book, limited-palette, inked",
        "- This image will be used as a visual reference for continuity between scenes",
        "",
        "CRITICAL: This is a reference image. Draw the setting EXACTLY as described above.",
        f"All future storyboards showing {setting_name} from {view_type} must match this reference precisely.",
    ])
    
    return "\n".join(lines).strip() + "\n"


def generate_setting_reference_image(
    api_key: str,
    model: str,
    setting: dict,
    view_type: str,
    output_dir: str,
    max_retries: int,
    retry_base: float,
    verbose: bool = False,
) -> str:
    """Generate a reference image for a setting. Returns the path to the generated image.
    
    view_type should be "indoor" or "outdoor".
    """
    setting_name = setting.get("name", "Unknown")
    prompt = build_setting_reference_prompt(setting, view_type)
    
    if verbose:
        print(f"    Generating {view_type} reference image for {setting_name}...", flush=True)
    
    try:
        response = call_gemini(
            api_key,
            model,
            prompt,
            max_retries,
            retry_base,
            verbose,
            reference_images=None,
        )
        images = extract_images(response)
        if not images:
            if verbose:
                print(f"    ⚠️  No reference image returned for {setting_name} ({view_type})", file=sys.stderr, flush=True)
            return None
        
        # Use the first image
        mime, data = images[0]
        ext = "png" if mime == "image/png" else "jpg"
        output_path = os.path.join(output_dir, f"ref-setting-{setting_name.lower().replace(' ', '-')}-{view_type}.{ext}")
        
        with open(output_path, "wb") as handle:
            handle.write(data)
        
        if verbose:
            size_kb = len(data) / 1024
            print(f"    ✓ Generated reference image: {output_path} ({size_kb:.1f} KB)", flush=True)
        
        return output_path
    except Exception as exc:
        if verbose:
            print(f"    ✗ Error generating reference for {setting_name} ({view_type}): {exc}", file=sys.stderr, flush=True)
        return None


def build_style_reference_prompt(style: dict) -> str:
    """Build a prompt for generating the master style reference image."""
    lines = [
        "Create a MASTER STYLE REFERENCE IMAGE for the entire comic series.",
        "",
        "This is a REFERENCE IMAGE that defines the visual style for ALL storyboards in the series.",
        "",
    ]
    
    if "description" in style:
        lines.append(f"Style Description: {style['description']}")
    
    # Build detailed style requirements
    style_details = []
    if "typeface" in style:
        style_details.append(f"- Typeface/Font: {style['typeface']}")
    if "inking" in style:
        style_details.append(f"- Inking Style: {style['inking']}")
    if "coloring" in style:
        style_details.append(f"- Coloring Style: {style['coloring']}")
    if "line_width" in style:
        style_details.append(f"- Line Width: {style['line_width']}")
    if "palette" in style:
        style_details.append(f"- Color Palette: {style['palette']}")
    if "shading" in style:
        style_details.append(f"- Shading Style: {style['shading']}")
    if "texture" in style:
        style_details.append(f"- Texture Treatment: {style['texture']}")
    
    lines.extend([
        "",
        "Style Requirements:",
        "- Format: comic book panels",
        "- Show multiple examples: empty dialogue panel, establishing shot (environment only), prop/object detail, background scene",
        "- Demonstrate consistent application of all style elements",
        "- CRITICAL: DO NOT include any individuals, people, or characters in this style reference",
        "- Focus on environments, objects, props, backgrounds, and typography only",
    ])
    
    if style_details:
        lines.append("")
        lines.extend(style_details)
    
    lines.extend([
        "",
        "Requirements:",
        "- Single panel or multi-panel reference showing the complete visual style",
        "- Include examples of: lettering/typography, inking, coloring, line work, shading",
        "- Show how dialogue bubbles, captions, and sound effects are styled (use placeholder text, no characters)",
        "- Demonstrate the color palette usage and limitations",
        "- Show consistent line width and inking technique",
        "- This image will be used as the PRIMARY style reference for ALL future storyboards",
        "",
        "CRITICAL RESTRICTIONS:",
        "- DO NOT include any people, individuals, or characters in this style reference image",
        "- DO NOT show faces, bodies, or any human forms",
        "- Focus on environments, objects, props, backgrounds, typography, and abstract style elements only",
        "- This ensures the style reference does not interfere with character generation",
        "",
        "CRITICAL: This is the master style reference. ALL future storyboards must match this style EXACTLY.",
        "Every panel must use the same typeface, inking style, coloring approach, line width, and palette.",
    ])
    
    return "\n".join(lines).strip() + "\n"


def generate_style_reference_image(
    api_key: str,
    model: str,
    style: dict,
    output_dir: str,
    max_retries: int,
    retry_base: float,
    verbose: bool = False,
) -> str:
    """Generate the master style reference image. Returns the path to the generated image."""
    prompt = build_style_reference_prompt(style)
    
    if verbose:
        print("    Generating master style reference image...", flush=True)
    
    try:
        response = call_gemini(
            api_key,
            model,
            prompt,
            max_retries,
            retry_base,
            verbose,
            reference_images=None,
        )
        images = extract_images(response)
        if not images:
            if verbose:
                print("    ⚠️  No style reference image returned", file=sys.stderr, flush=True)
            return None
        
        # Use the first image
        mime, data = images[0]
        ext = "png" if mime == "image/png" else "jpg"
        output_path = os.path.join(output_dir, f"ref-style.{ext}")
        
        with open(output_path, "wb") as handle:
            handle.write(data)
        
        if verbose:
            size_kb = len(data) / 1024
            print(f"    ✓ Generated master style reference: {output_path} ({size_kb:.1f} KB)", flush=True)
        
        return output_path
    except Exception as exc:
        if verbose:
            print(f"    ✗ Error generating style reference: {exc}", file=sys.stderr, flush=True)
        return None


def build_prompt(
    scene_id: str,
    scene_title: str,
    scene_text: str,
    panel_instructions: list[str],
    mood: str,
    camera: str,
    negative_prompt: str,
    characters: list[dict],
    settings: list[dict],
    extras: list[dict] = None,
    character_references: dict = None,
    extra_references: dict = None,
    setting_references: dict = None,
    style_reference_path: str = None,
    style: dict = None,
) -> str:
    lines = [
        f"Create a {len(panel_instructions)}-panel comic book.",
        "",
        f"Scene ID: {scene_id}",
        f"Scene title: {scene_title}",
        "",
    ]

    # Add character definitions
    if characters:
        lines.append("Character Definitions (MUST be drawn consistently):")
        for char in characters:
            char_name = char.get('name', 'Unknown')
            char_lines = [f"- {char_name}:"]
            
            # Only include description, not detailed appearance if we have reference images
            if "description" in char:
                char_lines.append(f"  Description: {char['description']}")
            
            # Check if we have reference images for this character
            has_ref_images = False
            if character_references and char_name in character_references:
                ref_paths = character_references[char_name]
                # Check if any are ref- images (canonical references)
                has_ref_images = any(
                    os.path.basename(p).lower().startswith("ref-") 
                    for p in ref_paths
                )
            
            # Only include detailed appearance if NO reference images exist
            # If reference images exist, rely on them instead of text descriptions
            if not has_ref_images and "appearance" in char:
                char_lines.append(f"  Appearance: {char['appearance']}")
            elif has_ref_images:
                char_lines.append(f"  Visual Reference: A CANONICAL reference image (ref-*.jpg/png) is provided below. This is the ABSOLUTE, DEFINITIVE source for this character's appearance. You MUST match it EXACTLY - do NOT improvise or modify. The canonical reference image overrides ALL text descriptions.")
            
            lines.extend(char_lines)
        lines.append("")
        
        # Add consolidated visual reference section if we have references
        if character_references:
            has_canonical_refs = False
            has_storyboard_refs = False
            canonical_chars = []
            storyboard_chars = []
            
            for char in characters:
                char_name = char.get('name', 'Unknown')
                if char_name in character_references and character_references[char_name]:
                    ref_paths = character_references[char_name]
                    has_canonical = any(
                        os.path.basename(p).lower().startswith("ref-") 
                        for p in ref_paths
                    )
                    if has_canonical:
                        has_canonical_refs = True
                        canonical_chars.append(char_name)
                    else:
                        has_storyboard_refs = True
                        storyboard_chars.append(char_name)
            
            if has_canonical_refs or has_storyboard_refs:
                lines.append("CRITICAL: Visual Reference Instructions")
                if has_canonical_refs:
                    lines.append(f"- Characters with CANONICAL references ({', '.join(canonical_chars)}): Match EXACTLY as shown in the canonical reference images. These are the ABSOLUTE source of truth. Do NOT modify or interpret.")
                if has_storyboard_refs:
                    lines.append(f"- Characters with storyboard references ({', '.join(storyboard_chars)}): Match EXACTLY as shown in previous storyboard images.")
                lines.append("")

    # Add setting definitions
    if settings:
        lines.append("Setting Definitions (MUST be drawn consistently):")
        for setting in settings:
            setting_name = setting.get('name', 'Unknown')
            setting_lines = [f"- {setting_name}:"]
            if "description" in setting:
                setting_lines.append(f"  Description: {setting['description']}")
            
            # Include era information for the setting
            if "era" in setting:
                setting_lines.append(f"  Era: {setting['era']}")
            
            # Check if we have reference images for this setting
            has_ref_images = False
            if setting_references and setting_name in setting_references:
                refs = setting_references[setting_name]
                has_ref_images = bool(refs.get("indoor") or refs.get("outdoor"))
            
            # Only include detailed visual details if NO reference images exist
            if not has_ref_images and "visual_details" in setting:
                setting_lines.append(f"  Visual details: {setting['visual_details']}")
            elif has_ref_images:
                setting_lines.append(f"  Visual Reference: Reference images are provided below. Use them as the PRIMARY source for this setting's appearance. Match them EXACTLY.")
            
            lines.extend(setting_lines)
        lines.append("")
        
        # Add era context based on detected settings
        eras = set()
        for setting in settings:
            if "era" in setting:
                eras.add(setting["era"])
        
        if eras:
            lines.append("CRITICAL - ERA CONTEXT:")
            if "biblical" in eras:
                lines.append("- Biblical-era scenes (1st century Judea/Galilee): ALL characters must wear period-appropriate clothing.")
                lines.append("  * Jewish religious officials: Simple wool or linen robes, prayer shawls (tallitot), head coverings. NOT Catholic vestments.")
                lines.append("  * Temple officials/Pharisees: Distinguished by quality of robes, phylacteries, fringed garments. Bearded, with traditional Jewish appearance.")
                lines.append("  * Laborers/common people: Simple undyed wool tunics, sandals, head cloths for sun protection.")
                lines.append("  * Roman officials: Military attire with leather armor, red cloaks, metal helmets if soldiers.")
                lines.append("  * Architecture: Stone buildings, flat roofs, arched doorways, oil lamps, no modern elements.")
            if "present-day" in eras:
                lines.append("- Present-day scenes (modern/futuristic): Characters wear contemporary or high-tech attire.")
                lines.append("  * Technicians/operators: Sterile uniforms, form-fitting tech-integrated clothing.")
                lines.append("  * Environments: Clean, minimalist, with holographic displays, glass surfaces, filtered lighting.")
            lines.append("")
    
    # Add extra definitions
    if extras:
        lines.append("Extra Definitions (non-character entities - MUST be drawn consistently):")
        for extra in extras:
            extra_name = extra.get('name', 'Unknown')
            extra_lines = [f"- {extra_name}:"]
            
            if "description" in extra:
                extra_lines.append(f"  Description: {extra['description']}")
            
            # Check if we have reference images for this extra
            has_ref_images = False
            if extra_references and extra_name in extra_references:
                ref_paths = extra_references[extra_name]
                has_ref_images = any(
                    os.path.basename(p).lower().startswith("ref-extra-") 
                    for p in ref_paths
                )
            
            # Only include detailed appearance if NO reference images exist
            if not has_ref_images and "appearance" in extra:
                extra_lines.append(f"  Appearance: {extra['appearance']}")
            elif has_ref_images:
                extra_lines.append(f"  Visual Reference: A canonical reference image is provided below. Use it as the PRIMARY source for this extra's appearance. Match it EXACTLY.")
            
            lines.extend(extra_lines)
        lines.append("")
        
        # Extras and settings references are handled in the main reference section below
    
    # Add master style reference if available
    if style_reference_path:
        lines.append("CRITICAL Master Style Reference:")
        lines.append("A master style reference image is provided below. This defines the visual style for the ENTIRE comic series.")
        lines.append("You MUST match this style EXACTLY:")
        lines.append("- Use the same typeface/lettering style shown in the reference")
        lines.append("- Match the inking technique, line width, and line quality")
        lines.append("- Use the same coloring approach and palette limitations")
        lines.append("- Apply the same shading and texture treatments")
        lines.append("- Use the same speech bubble and caption styling")
        lines.append("This style reference takes precedence over all other style instructions.")
        lines.append("")

    lines.extend(
        [
            "Scene text:",
            scene_text.strip(),
            "",
            "Panel instructions:",
        ]
    )
    for index, instruction in enumerate(panel_instructions, start=1):
        lines.append(f"{index}) {instruction}")

    # Build style section from definitions if available, otherwise use generic defaults
    style_lines = [
            "",
            "Style:",
            "- format: comic book",
    ]
    
    # Use style definitions if available
    if style:
        if "coloring" in style:
            style_lines.append(f"- color: {style['coloring']}")
        else:
            style_lines.append("- color: limited-palette")
        
        if "inking" in style:
            style_lines.append(f"- linework: {style['inking']}")
        else:
            style_lines.append("- linework: inked")
        
        if "palette" in style:
            style_lines.append(f"- palette: {style['palette']}")
        
        if "shading" in style:
            style_lines.append(f"- shading: {style['shading']}")
        
        if "texture" in style:
            style_lines.append(f"- texture: {style['texture']}")
    else:
        # Generic defaults if no style definitions
        style_lines.append("- color: limited-palette")
        style_lines.append("- linework: inked")
    
    style_lines.extend([
            f"- mood: {mood}",
            f"- camera: {camera}",
            "",
            "Lettering and Typography:",
    ])
    
    # Use typeface from style definitions if available
    if style and "typeface" in style:
        style_lines.append(f"- Font: {style['typeface']}")
    else:
        style_lines.append("- Font: Use consistent comic book lettering style for all text")
    
    style_lines.extend([
            "- Use consistent lettering style across all panels",
            "- All dialogue and text should use the same font family and size",
            "- Lettering should be clear, readable, and professionally rendered",
            "- Maintain uniform text placement (speech bubbles, captions)",
            "- Use consistent speech bubble style and shape throughout",
            "- Ensure text is properly integrated with the art (not floating or misaligned)",
            "- All panels must share the same typographic treatment",
            "",
    ])
    
    lines.extend(style_lines)
    # Consolidated consistency section
    has_any_refs = bool(characters and character_references) or bool(extras and extra_references) or bool(settings and setting_references)
    has_canonical = False
    if character_references:
        for char in characters:
            char_name = char.get('name', 'Unknown')
            if char_name in character_references:
                ref_paths = character_references[char_name]
                if any(os.path.basename(p).lower().startswith("ref-") for p in ref_paths):
                    has_canonical = True
                    break
    
    if has_any_refs:
        lines.extend([
            "",
            "CRITICAL: Visual Consistency Requirements",
            "",
        ])
        
        if has_canonical:
            lines.append("⚠️ CANONICAL REFERENCES: Match characters EXACTLY as shown in canonical reference images (ref-*.jpg/png). These override all text descriptions.")
            lines.append("")
        
        lines.extend([
            "- Reference images are the PRIMARY source for appearance - match them EXACTLY",
            "- Characters, extras, and settings must look IDENTICAL across all panels",
            "- Only use text descriptions if no reference images are available",
            "- Master style reference takes precedence over all style instructions",
            "",
            "Negative prompts:",
            f"- {negative_prompt}",
            "- inconsistent character/setting appearance, varying visual style",
        ])

    return "\n".join(lines).strip() + "\n"


def load_image_as_base64(image_path: str) -> tuple[str, str]:
    """Load an image file and return (mime_type, base64_data) tuple."""
    ext = os.path.splitext(image_path)[1].lower()
    mime_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }
    mime_type = mime_types.get(ext, "image/jpeg")
    
    with open(image_path, "rb") as handle:
        image_data = handle.read()
        base64_data = base64.b64encode(image_data).decode("utf-8")
    
    return mime_type, base64_data


def call_gemini(
    api_key: str,
    model: str,
    prompt: str,
    max_retries: int,
    retry_base: float,
    verbose: bool = False,
    reference_images: list[str] = None,
) -> dict:
    """Call Gemini API with optional reference images for character consistency."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    
    # Build parts list with text prompt
    parts = [{"text": prompt}]
    
    # Add reference images if provided
    if reference_images:
        for img_path in reference_images:
            if os.path.isfile(img_path):
                try:
                    mime_type, base64_data = load_image_as_base64(img_path)
                    parts.append({
                        "inlineData": {
                            "mimeType": mime_type,
                            "data": base64_data,
                        }
                    })
                    if verbose:
                        print(f"    Added reference image: {os.path.basename(img_path)}", flush=True)
                except Exception as exc:
                    if verbose:
                        print(f"    Warning: Could not load reference image {img_path}: {exc}", flush=True)
    
    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "responseModalities": ["IMAGE"],
            "imageConfig": {"aspectRatio": DEFAULT_ASPECT_RATIO, "imageSize": DEFAULT_IMAGE_SIZE},
        },
    }
    data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    attempt = 0
    while True:
        try:
            if verbose and attempt > 0:
                print(f"  Retrying request (attempt {attempt + 1}/{max_retries + 1})...", flush=True)
            with urllib.request.urlopen(request, timeout=120) as response:
                if verbose:
                    print("  Request successful", flush=True)
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            if exc.code != 429 or attempt >= max_retries:
                raise
            retry_after = exc.headers.get("Retry-After")
            if retry_after:
                delay = float(retry_after)
                if verbose:
                    print(f"  Rate limited. Waiting {delay:.1f}s (server requested)...", flush=True)
            else:
                delay = retry_base * (2 ** attempt)
                if verbose:
                    print(f"  Rate limited. Waiting {delay:.1f}s (exponential backoff)...", flush=True)
            time.sleep(delay)
            attempt += 1


def extract_images(response: dict) -> list[tuple[str, bytes]]:
    images = []
    candidates = response.get("candidates") or []
    for candidate in candidates:
        content = candidate.get("content") or {}
        for part in content.get("parts") or []:
            inline = part.get("inlineData")
            if not inline:
                continue
            data = inline.get("data")
            mime = inline.get("mimeType", "image/png")
            if data:
                images.append((mime, base64.b64decode(data)))
    return images


def infer_scene_title(scene_text: str) -> str:
    for line in scene_text.splitlines():
        if line.startswith("## "):
            return line.replace("## ", "").strip()
    return "Scene"


def build_scene_id(path: str) -> str:
    base = os.path.basename(path)
    return os.path.splitext(base)[0]


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def load_env_file(path: str) -> None:
    if not os.path.isfile(path):
        return
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("'").strip('"')
            if key and key not in os.environ:
                os.environ[key] = value


def main() -> int:
    script_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    load_env_file(os.path.join(script_root, ".env"))
    load_env_file(os.path.join(os.getcwd(), ".env"))

    parser = argparse.ArgumentParser(description="Generate comic panels from scene files.")
    parser.add_argument("--api-key", default=os.environ.get("GEMINI_API_KEY"))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--scene-glob", default="story/scene-*.md")
    parser.add_argument("--output-dir", default="story/boards")
    parser.add_argument("--panel-count", type=int, default=None, help="Panels per storyboard (default: 4-6 based on content, with dialog prioritized)")
    parser.add_argument("--storyboards-per-scene", type=int, default=None, help="Number of storyboards per scene (default: 4-6 based on content)")
    parser.add_argument("--chunks", type=str, default=None, help="Comma-separated list of chunk indices to regenerate (e.g., '1,3,5' or '2'). If not specified, all chunks are generated. Indices are 1-based.")
    parser.add_argument("--mood", default="quiet tension, contemplative")
    parser.add_argument("--camera", default="cinematic, varied shots")
    parser.add_argument("--max-retries", type=int, default=5)
    parser.add_argument("--retry-base", type=float, default=5.0, help="Base delay in seconds for exponential backoff")
    parser.add_argument("--sleep-between", type=float, default=10.0, help="Seconds to wait between scenes (default: 10)")
    parser.add_argument(
        "--negative-prompt",
        default="modern clothing, cars, guns, neon signage, text overlays, watermarks",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed progress")
    parser.add_argument("--definitions-file", default=None, help="Path to character and setting definitions JSON file (defaults to {scene-glob directory}/definitions.json)")
    parser.add_argument("--debug-prompt", action="store_true", default=True, help="Print every prompt sent to Gemini API (for debugging). Default: enabled. Use --no-debug-prompt to disable.")
    parser.add_argument("--no-debug-prompt", dest="debug_prompt", action="store_false", help="Disable prompt debugging")
    parser.add_argument("--save-prompt", default=None, help="Save each prompt to a file (specify directory path, or use 'auto' to save alongside output)")
    parser.add_argument("--dry-run", action="store_true", help="Build and display prompts without calling the Gemini API. Useful for debugging prompt generation.")
    args = parser.parse_args()

    if not args.api_key:
        print("Missing API key. Set GEMINI_API_KEY or pass --api-key.", file=sys.stderr)
        return 2

    # Determine definitions file path if not specified
    if args.definitions_file is None:
        # Extract directory from scene-glob pattern (e.g., "story/scene-*.md" -> "story")
        scene_dir = os.path.dirname(args.scene_glob) if os.path.dirname(args.scene_glob) else "story"
        args.definitions_file = os.path.join(scene_dir, "definitions.json")

    # Load character and setting definitions
    definitions = load_definitions(args.definitions_file)
    if args.verbose and definitions.get("characters") or definitions.get("settings"):
        char_count = len(definitions.get("characters", {}))
        setting_count = len(definitions.get("settings", {}))
        print(f"Loaded {char_count} character(s) and {setting_count} setting(s) from definitions", flush=True)
    
    # Load all visual references
    scene_dir = os.path.dirname(args.scene_glob) if os.path.dirname(args.scene_glob) else "story"
    character_references_path = os.path.join(scene_dir, "character_references.json")
    extra_references_path = os.path.join(scene_dir, "extra_references.json")
    setting_references_path = os.path.join(scene_dir, "setting_references.json")
    
    character_references = load_character_references(character_references_path)
    extra_references = load_extra_references(extra_references_path)
    setting_references = load_setting_references(setting_references_path)
    style_reference_path = get_style_reference_path(args.output_dir)
    
    # Sync canonical reference images (ref-*.jpg) that may exist on disk but aren't in the JSON
    if sync_canonical_references(character_references, definitions, args.output_dir):
        save_character_references(character_references_path, character_references)
        if args.verbose:
            print(f"Synced canonical reference images to {character_references_path}", flush=True)
    
    if args.verbose:
        if character_references:
            total_refs = sum(len(refs) for refs in character_references.values())
            print(f"Loaded visual references for {len(character_references)} character(s) ({total_refs} total references)", flush=True)
        if extra_references:
            total_refs = sum(len(refs) for refs in extra_references.values())
            print(f"Loaded visual references for {len(extra_references)} extra(s) ({total_refs} total references)", flush=True)
        if setting_references:
            total_refs = sum(len(refs.get("indoor", [])) + len(refs.get("outdoor", [])) for refs in setting_references.values())
            print(f"Loaded visual references for {len(setting_references)} setting(s) ({total_refs} total references)", flush=True)
        if style_reference_path:
            print(f"Found master style reference: {style_reference_path}", flush=True)
    
    # Check if we need to generate the master style reference
    if not style_reference_path and definitions.get("style"):
        style_def = definitions.get("style", {})
        if style_def:
            style_reference_path = generate_style_reference_image(
                args.api_key,
                args.model,
                style_def,
                args.output_dir,
                args.max_retries,
                args.retry_base,
                args.verbose,
            )
            if style_reference_path and args.sleep_between > 0:
                time.sleep(args.sleep_between)

    scene_paths = sorted(glob.glob(args.scene_glob))
    # Filter out continuity files
    scene_paths = [p for p in scene_paths if not p.endswith(".continuity.md")]
    if not scene_paths:
        print(f"No scenes found with glob: {args.scene_glob}", file=sys.stderr)
        return 1

    ensure_dir(args.output_dir)

    total_scenes = len(scene_paths)
    print(f"Found {total_scenes} scene(s) to process", flush=True)

    for idx, scene_path in enumerate(scene_paths, start=1):
        scene_text = read_text(scene_path)
        scene_id = build_scene_id(scene_path)
        scene_title = infer_scene_title(scene_text)
        
        print(f"\n[{idx}/{total_scenes}] Processing {scene_id}: {scene_title}", flush=True)
        
        # Detect characters, settings, and extras in this scene (for all storyboards)
        characters, settings, extras = detect_entities(scene_text, definitions)
        if args.verbose and (characters or settings or extras):
            if characters:
                char_names = [c.get("name", "Unknown") for c in characters]
                print(f"  Detected characters: {', '.join(char_names)}", flush=True)
            if settings:
                setting_names = [s.get("name", "Unknown") for s in settings]
                print(f"  Detected settings: {', '.join(setting_names)}", flush=True)
            if extras:
                extra_names = [e.get("name", "Unknown") for e in extras]
                print(f"  Detected extras: {', '.join(extra_names)}", flush=True)
        
        # Divide scene into multiple storyboards
        # Increased defaults to allow for richer dialog and more detailed scenes
        min_sb = 4
        max_sb = 6
        if args.storyboards_per_scene:
            min_sb = max_sb = args.storyboards_per_scene
        
        storyboard_chunks = divide_scene_into_storyboards(scene_text, min_sb, max_sb)
        total_storyboards = len(storyboard_chunks)
        
        # Filter to specific chunks if requested
        chunk_indices_to_generate = None
        if args.chunks:
            try:
                # Parse comma-separated chunk indices (1-based)
                requested_indices = sorted(set(int(x.strip()) for x in args.chunks.split(',')))
                # Validate indices
                valid_indices = [idx for idx in requested_indices if 1 <= idx <= total_storyboards]
                invalid_indices = [idx for idx in requested_indices if idx < 1 or idx > total_storyboards]
                
                if invalid_indices:
                    if args.verbose:
                        print(f"  Warning: Chunk index(es) {invalid_indices} are out of range (1-{total_storyboards}), ignoring", flush=True)
                
                if valid_indices:
                    chunk_indices_to_generate = valid_indices
                    if args.verbose:
                        print(f"  Filtering to {len(valid_indices)} requested chunk(s): {valid_indices}", flush=True)
                else:
                    if args.verbose:
                        print(f"  Warning: No valid chunks specified, generating all chunks", flush=True)
            except ValueError as e:
                if args.verbose:
                    print(f"  Warning: Invalid chunk specification '{args.chunks}', expected comma-separated numbers (e.g., '1,3,5'). Error: {e}. Generating all chunks.", flush=True)
        
        if args.verbose:
            if chunk_indices_to_generate:
                print(f"  Generating {len(chunk_indices_to_generate)} of {total_storyboards} storyboard(s)...", flush=True)
            else:
                print(f"  Dividing scene into {total_storyboards} storyboard(s)...", flush=True)
        
        # Check for first-time defined characters and generate reference images
        for char in characters:
            char_name = char.get("name", "")
            if char_name and char_name not in character_references:
                # First time seeing this character - generate reference image
                ref_path = generate_character_reference_image(
                    args.api_key,
                    args.model,
                    char,
                    definitions,
                    args.output_dir,
                    args.max_retries,
                    args.retry_base,
                    args.verbose,
                )
                if ref_path:
                    # Add reference image to database
                    update_character_references(
                        character_references, char_name, ref_path, args.output_dir
                    )
                    save_character_references(character_references_path, character_references)
                    if args.verbose:
                        print(f"    Created reference image for first-time character: {char_name}", flush=True)
                    # Sleep after generating reference to avoid rate limits
                    if args.sleep_between > 0:
                        time.sleep(args.sleep_between)
        
        # Check for first-time extras and generate reference images
        for extra in extras:
            extra_name = extra.get("name", "")
            if extra_name and extra_name not in extra_references:
                # First time seeing this extra - generate reference image
                ref_path = generate_extra_reference_image(
                    args.api_key,
                    args.model,
                    extra,
                    args.output_dir,
                    args.max_retries,
                    args.retry_base,
                    args.verbose,
                )
                if ref_path:
                    # Add reference image to database
                    if extra_name not in extra_references:
                        extra_references[extra_name] = []
                    if os.path.isabs(ref_path):
                        rel_path = os.path.relpath(ref_path, args.output_dir)
                    else:
                        rel_path = ref_path
                    if rel_path not in extra_references[extra_name]:
                        extra_references[extra_name].insert(0, rel_path)
                        extra_references[extra_name] = extra_references[extra_name][:10]
                    save_extra_references(extra_references_path, extra_references)
                    if args.verbose:
                        print(f"    Created reference image for first-time extra: {extra_name}", flush=True)
                    # Sleep after generating reference to avoid rate limits
                    if args.sleep_between > 0:
                        time.sleep(args.sleep_between)
        
        # Check for first-time settings and generate reference images (indoor and outdoor)
        for setting in settings:
            setting_name = setting.get("name", "")
            if setting_name:
                # Check if we need indoor reference
                needs_indoor = True
                if setting_name in setting_references:
                    needs_indoor = not bool(setting_references[setting_name].get("indoor"))
                
                if needs_indoor:
                    ref_path = generate_setting_reference_image(
                        args.api_key,
                        args.model,
                        setting,
                        "indoor",
                        args.output_dir,
                        args.max_retries,
                        args.retry_base,
                        args.verbose,
                    )
                    if ref_path:
                        if setting_name not in setting_references:
                            setting_references[setting_name] = {"indoor": [], "outdoor": []}
                        if os.path.isabs(ref_path):
                            rel_path = os.path.relpath(ref_path, args.output_dir)
                        else:
                            rel_path = ref_path
                        if rel_path not in setting_references[setting_name]["indoor"]:
                            setting_references[setting_name]["indoor"].insert(0, rel_path)
                            setting_references[setting_name]["indoor"] = setting_references[setting_name]["indoor"][:5]
                        save_setting_references(setting_references_path, setting_references)
                        if args.verbose:
                            print(f"    Created indoor reference image for setting: {setting_name}", flush=True)
                        if args.sleep_between > 0:
                            time.sleep(args.sleep_between)
                
                # Check if we need outdoor reference
                needs_outdoor = True
                if setting_name in setting_references:
                    needs_outdoor = not bool(setting_references[setting_name].get("outdoor"))
                
                if needs_outdoor:
                    ref_path = generate_setting_reference_image(
                        args.api_key,
                        args.model,
                        setting,
                        "outdoor",
                        args.output_dir,
                        args.max_retries,
                        args.retry_base,
                        args.verbose,
                    )
                    if ref_path:
                        if setting_name not in setting_references:
                            setting_references[setting_name] = {"indoor": [], "outdoor": []}
                        if os.path.isabs(ref_path):
                            rel_path = os.path.relpath(ref_path, args.output_dir)
                        else:
                            rel_path = ref_path
                        if rel_path not in setting_references[setting_name]["outdoor"]:
                            setting_references[setting_name]["outdoor"].insert(0, rel_path)
                            setting_references[setting_name]["outdoor"] = setting_references[setting_name]["outdoor"][:5]
                        save_setting_references(setting_references_path, setting_references)
                        if args.verbose:
                            print(f"    Created outdoor reference image for setting: {setting_name}", flush=True)
                        if args.sleep_between > 0:
                            time.sleep(args.sleep_between)
        
        # Generate a storyboard for each chunk
        # If specific chunks were requested, only generate those
        if chunk_indices_to_generate:
            # Generate only the requested chunks, preserving original indices for file naming
            chunks_to_process = [(idx, storyboard_chunks[idx - 1]) for idx in chunk_indices_to_generate]
        else:
            # Generate all chunks
            chunks_to_process = [(idx, chunk) for idx, chunk in enumerate(storyboard_chunks, start=1)]
        
        for sb_idx, (chunk_title, chunk_text) in chunks_to_process:
            if args.verbose:
                print(f"  Storyboard {sb_idx}/{total_storyboards}: {chunk_title}", flush=True)
            
            # Detect which characters, settings, and extras actually appear in THIS chunk
            chunk_characters, chunk_settings, chunk_extras = detect_entities(chunk_text, definitions)
            
            # Fallback: If chunk has pronouns + action verbs but no character names detected,
            # and we know from scene-level detection which characters are present,
            # include those characters (they're likely being referred to by pronouns)
            if not chunk_characters and characters:
                chunk_lower = chunk_text.lower()
                # Check for pronouns + action verbs (indicating a character is present but unnamed)
                # Use word boundaries to catch pronouns at sentence boundaries too
                import re
                pronoun_patterns = [r'\bhe\b', r'\bshe\b', r'\bthey\b', r'\bhis\b', r'\bher\b', r'\btheir\b', r'\bhim\b']
                has_pronouns = any(re.search(pattern, chunk_lower) for pattern in pronoun_patterns)
                action_verbs = ['stood', 'walked', 'moved', 'looked', 'turned', 'entered', 'sat', 'hailed', 'said', 'spoke', 'reached', 'watched', 'felt', 'stepped', 'stopped', 'pulled', 'slumped', 'sliding', 'waiting', 'began', 'struggled', 'calibrate', 'seized', 'leaving', 'forcing', 'exhaled', 'swallowing', 'adjust', 'intensified', 'vibrated', 'was', 'is', 'did', 'had']
                has_actions = any(verb in chunk_lower for verb in action_verbs)
                
                if has_pronouns and has_actions:
                    # Use scene-level characters (they're likely being referred to by pronouns in this chunk)
                    chunk_characters = characters
            
            # Fallback for settings: If no settings detected in chunk but scene has settings,
            # and the chunk doesn't start with a new section header (## ), carry over the previous setting
            # This handles continuity when a scene spans multiple chunks without repeating the location
            if not chunk_settings and settings:
                # Check if this chunk starts with a new section header (indicating location change)
                chunk_lines = chunk_text.strip().splitlines()
                has_new_header = chunk_lines and chunk_lines[0].startswith("## ")
                
                if not has_new_header:
                    # No new location header - carry over the most recent setting from the scene
                    # Use the last setting detected at scene level (most likely the current location)
                    chunk_settings = settings[-1:] if settings else []
            
            # Pass detected characters to panel instruction generation for explicit naming
            panel_instructions = derive_panel_instructions(chunk_text, args.panel_count, detected_characters=chunk_characters)
            if args.verbose:
                print(f"    Generating {len(panel_instructions)} panel(s)...", flush=True)
            
            # Collect reference images for characters, extras, settings, and style
            # Prioritize canonical ref- images (use max 1 if canonical exists, otherwise 2)
            reference_images = []
            
            # Add character references (for defined characters)
            for char in chunk_characters:
                char_name = char.get("name", "")
                if char_name:
                    # Check if we have a canonical ref- image
                    has_canonical = False
                    if char_name in character_references:
                        ref_paths = character_references[char_name]
                        has_canonical = any(
                            os.path.basename(p).lower().startswith("ref-") 
                            for p in ref_paths
                        )
                    
                    # Use only canonical ref if available, otherwise use up to 2 references
                    max_refs = 1 if has_canonical else 2
                    ref_images = find_character_reference_images(
                        char_name, character_references, args.output_dir, max_references=max_refs
                    )
                    reference_images.extend(ref_images)
            
            # Add extra references
            for extra in chunk_extras:
                extra_name = extra.get("name", "")
                if extra_name and extra_name in extra_references:
                    ref_paths = extra_references[extra_name]
                    # Prioritize canonical ref-extra- images
                    ref_images = []
                    storyboard_images = []
                    for ref_path in ref_paths:
                        path_basename = os.path.basename(ref_path).lower()
                        if path_basename.startswith("ref-extra-"):
                            ref_images.append(ref_path)
                        else:
                            storyboard_images.append(ref_path)
                    
                    prioritized_paths = ref_images[:1]  # Use canonical ref if available
                    if len(prioritized_paths) < 2:
                        remaining = 2 - len(prioritized_paths)
                        prioritized_paths.extend(storyboard_images[:remaining])
                    
                    for ref_path in prioritized_paths:
                        if os.path.isabs(ref_path):
                            full_path = ref_path
                        else:
                            full_path = os.path.join(args.output_dir, ref_path)
                            if not os.path.isfile(full_path):
                                full_path = os.path.join(os.getcwd(), ref_path)
                        if os.path.isfile(full_path):
                            reference_images.append(full_path)
            
            # Add setting references (indoor and outdoor)
            for setting in chunk_settings:
                setting_name = setting.get("name", "")
                if setting_name and setting_name in setting_references:
                    refs = setting_references[setting_name]
                    # Add indoor reference if available
                    for ref_path in refs.get("indoor", [])[:1]:  # Use only first indoor ref
                        if os.path.isabs(ref_path):
                            full_path = ref_path
                        else:
                            full_path = os.path.join(args.output_dir, ref_path)
                            if not os.path.isfile(full_path):
                                full_path = os.path.join(os.getcwd(), ref_path)
                        if os.path.isfile(full_path):
                            reference_images.append(full_path)
                    # Add outdoor reference if available
                    for ref_path in refs.get("outdoor", [])[:1]:  # Use only first outdoor ref
                        if os.path.isabs(ref_path):
                            full_path = ref_path
                        else:
                            full_path = os.path.join(args.output_dir, ref_path)
                            if not os.path.isfile(full_path):
                                full_path = os.path.join(os.getcwd(), ref_path)
                        if os.path.isfile(full_path):
                            reference_images.append(full_path)
            
            # Add master style reference if available
            if style_reference_path:
                # Ensure style reference path is absolute
                if not os.path.isabs(style_reference_path):
                    style_reference_path = os.path.abspath(style_reference_path)
                if os.path.isfile(style_reference_path):
                    reference_images.append(style_reference_path)
            
            # Remove duplicates while preserving order
            seen = set()
            unique_reference_images = []
            for img_path in reference_images:
                if img_path not in seen:
                    seen.add(img_path)
                    unique_reference_images.append(img_path)
            reference_images = unique_reference_images
            
            if args.verbose and reference_images:
                print(f"    Using {len(reference_images)} reference image(s) for character consistency", flush=True)
            
            # Use only the chunk_title for scene_title, not the inferred scene title
            # The inferred scene title is the first section header, which may not match this chunk
            prompt = build_prompt(
                scene_id=f"{scene_id}-{sb_idx}",
                scene_title=chunk_title,  # Use chunk title directly, not concatenated with scene title
                scene_text=chunk_text,
                panel_instructions=panel_instructions,
                mood=args.mood,
                camera=args.camera,
                negative_prompt=args.negative_prompt,
                characters=chunk_characters,  # Use chunk-specific characters, not scene-wide
                settings=chunk_settings,  # Use chunk-specific settings
                extras=chunk_extras,  # Use chunk-specific extras
                character_references=character_references,
                extra_references=extra_references,
                setting_references=setting_references,
                style_reference_path=style_reference_path,
                style=definitions.get("style"),
            )

            # Debug: Print or save prompt if requested
            if args.debug_prompt or args.save_prompt or args.dry_run:
                prompt_info = f"\n{'='*80}\n"
                prompt_info += f"PROMPT FOR: {scene_id}-{sb_idx}\n"
                prompt_info += f"{'='*80}\n\n"
                prompt_info += prompt
                prompt_info += f"\n\n{'='*80}\n"
                prompt_info += f"REFERENCE IMAGES ({len(reference_images)}):\n"
                for img_path in reference_images:
                    prompt_info += f"  - {img_path}\n"
                prompt_info += f"\n{'='*80}\n"
                prompt_info += f"DETECTED ENTITIES FOR THIS CHUNK:\n"
                prompt_info += f"  Characters: {', '.join([c.get('name', 'Unknown') for c in chunk_characters])}\n"
                prompt_info += f"  Settings: {', '.join([s.get('name', 'Unknown') for s in chunk_settings])}\n"
                prompt_info += f"  Extras: {', '.join([e.get('name', 'Unknown') for e in chunk_extras])}\n"
                prompt_info += f"{'='*80}\n"
                
                if args.debug_prompt or args.dry_run:
                    print(prompt_info, flush=True)
                
                if args.save_prompt:
                    if args.save_prompt.lower() == "auto":
                        save_dir = args.output_dir
                    else:
                        save_dir = args.save_prompt
                    ensure_dir(save_dir)
                    prompt_file = os.path.join(save_dir, f"{scene_id}-{sb_idx}-prompt.txt")
                    with open(prompt_file, "w", encoding="utf-8") as handle:
                        handle.write(prompt_info)
                    if args.verbose:
                        print(f"    Saved prompt to {prompt_file}", flush=True)
            
            # Skip API call in dry-run mode
            if args.dry_run:
                print(f"    [DRY RUN] Would generate storyboard image (skipped API call)", flush=True)
                continue
            
            try:
                response = call_gemini(
                    args.api_key,
                    args.model,
                    prompt,
                    args.max_retries,
                    args.retry_base,
                    args.verbose,
                    reference_images=reference_images,
                )
                images = extract_images(response)
                if not images:
                    print(f"    ⚠️  No images returned for {scene_id}-{sb_idx}", file=sys.stderr, flush=True)
                    continue

                for img_idx, (mime, data) in enumerate(images, start=1):
                    ext = "png" if mime == "image/png" else "jpg"
                    suffix = f"-{sb_idx}" if total_storyboards > 1 else ""
                    if len(images) > 1:
                        suffix += f"-{img_idx}"
                    output_path = os.path.join(args.output_dir, f"{scene_id}{suffix}.{ext}")
                    with open(output_path, "wb") as handle:
                        handle.write(data)
                    size_kb = len(data) / 1024
                    print(f"    ✓ Wrote {output_path} ({size_kb:.1f} KB)", flush=True)
                    
                    # Only update character references for characters that appear in THIS chunk
                    # (chunk_characters, not the full scene characters list)
                    for char in chunk_characters:
                        char_name = char.get("name", "")
                        if char_name:
                            update_character_references(
                                character_references, char_name, output_path, args.output_dir
                            )
                
                # Save updated character references after each storyboard
                save_character_references(character_references_path, character_references)
            except urllib.error.HTTPError as exc:
                print(f"    ✗ HTTP Error {exc.code}: {exc.reason}", file=sys.stderr, flush=True)
                if args.verbose:
                    print(f"       URL: {exc.url}", file=sys.stderr, flush=True)
            except Exception as exc:
                print(f"    ✗ Error: {exc}", file=sys.stderr, flush=True)
                if args.verbose:
                    import traceback
                    traceback.print_exc()
            
            # Sleep between storyboards to avoid rate limits
            if sb_idx < total_storyboards and args.sleep_between > 0:
                if args.verbose:
                    print(f"    Waiting {args.sleep_between:.1f}s before next storyboard...", flush=True)
                time.sleep(args.sleep_between)
        
        # Sleep between scenes to avoid rate limits (except after the last one)
        if idx < total_scenes and args.sleep_between > 0:
            if args.verbose:
                print(f"  Waiting {args.sleep_between:.1f}s before next scene...", flush=True)
            time.sleep(args.sleep_between)

    print(f"\n✓ Completed processing {total_scenes} scene(s)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
