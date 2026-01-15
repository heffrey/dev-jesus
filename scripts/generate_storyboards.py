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
    
    valid_paths = []
    for ref_path in prioritized_paths:
        # Handle both relative and absolute paths
        if os.path.isabs(ref_path):
            full_path = ref_path
        else:
            # Try relative to output_dir first, then relative to current working directory
            full_path = os.path.join(output_dir, ref_path)
            if not os.path.isfile(full_path):
                full_path = os.path.join(os.getcwd(), ref_path)
        
        if os.path.isfile(full_path):
            valid_paths.append(full_path)
    
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
    """Detect which characters, settings, and extras appear in the scene text."""
    scene_lower = scene_text.lower()
    found_characters = []
    found_settings = []
    found_extras = []

    # Check for characters
    for char_key, char_data in definitions.get("characters", {}).items():
        # Check name and aliases
        names_to_check = [char_key, char_data.get("name", "")]
        if "aliases" in char_data:
            names_to_check.extend(char_data["aliases"])
        
        for name in names_to_check:
            if name and name.lower() in scene_lower:
                if char_data not in found_characters:
                    found_characters.append(char_data)
                break

    # Check for settings
    for setting_key, setting_data in definitions.get("settings", {}).items():
        # Check name and aliases
        names_to_check = [setting_key, setting_data.get("name", "")]
        if "aliases" in setting_data:
            names_to_check.extend(setting_data["aliases"])
        
        for name in names_to_check:
            if name and name.lower() in scene_lower:
                if setting_data not in found_settings:
                    found_settings.append(setting_data)
                break

    # Check for extras
    for extra_key, extra_data in definitions.get("extras", {}).items():
        # Check name and aliases
        names_to_check = [extra_key, extra_data.get("name", "")]
        if "aliases" in extra_data:
            names_to_check.extend(extra_data["aliases"])
        
        for name in names_to_check:
            if name and name.lower() in scene_lower:
                if extra_data not in found_extras:
                    found_extras.append(extra_data)
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


def divide_scene_into_storyboards(scene_text: str, min_storyboards: int = 3, max_storyboards: int = 5) -> list[tuple[str, str]]:
    """Divide a scene into multiple storyboard chunks. Returns list of (chunk_title, chunk_text) tuples."""
    sections = extract_sections(scene_text)
    storyboards = []
    
    if sections:
        # If we have sections, try to group them into storyboards
        # Each storyboard should cover 1-2 sections
        sections_per_storyboard = max(1, len(sections) // max_storyboards)
        if sections_per_storyboard < 1:
            sections_per_storyboard = 1
        
        for i in range(0, len(sections), sections_per_storyboard):
            chunk_sections = sections[i:i + sections_per_storyboard]
            chunk_title = chunk_sections[0][0] if chunk_sections else "Scene"
            chunk_text = "\n\n".join([f"## {title}\n\n{body}" for title, body in chunk_sections])
            storyboards.append((chunk_title, chunk_text))
    else:
        # If no sections, divide by paragraphs
        paragraphs = [p.strip() for p in scene_text.split("\n\n") if p.strip() and not p.strip().startswith("#")]
        if not paragraphs:
            paragraphs = [scene_text]
        
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


def derive_panel_instructions(chunk_text: str, panel_count: int) -> list[str]:
    """Generate panel instructions for a storyboard chunk."""
    sections = extract_sections(chunk_text)
    instructions = []

    if sections:
        for title, body in sections:
            # Extract key moments from the body
            paragraphs = [p.strip() for p in body.split("\n\n") if p.strip()]
            for para in paragraphs[:2]:  # Take up to 2 paragraphs per section
                sentence = first_sentence(para)
                if sentence:
                    instructions.append(f"{title}: {sentence}")
    else:
        paragraphs = [p.strip() for p in chunk_text.split("\n\n") if p.strip()]
        for paragraph in paragraphs:
            sentence = first_sentence(paragraph)
            if sentence:
                instructions.append(sentence)

    if not instructions:
        instructions = ["Establish the setting and key characters."]

    if panel_count is None:
        panel_count = max(3, min(5, len(instructions)))

    if len(instructions) > panel_count:
        instructions = instructions[:panel_count]
    elif len(instructions) < panel_count:
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
        "- Show multiple examples: character close-up, action scene, dialogue panel, establishing shot",
        "- Demonstrate consistent application of all style elements",
    ])
    
    if style_details:
        lines.append("")
        lines.extend(style_details)
    
    lines.extend([
        "",
        "Requirements:",
        "- Single panel or multi-panel reference showing the complete visual style",
        "- Include examples of: lettering/typography, inking, coloring, line work, shading",
        "- Show how dialogue bubbles, captions, and sound effects are styled",
        "- Demonstrate the color palette usage and limitations",
        "- Show consistent line width and inking technique",
        "- This image will be used as the PRIMARY style reference for ALL future storyboards",
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
                char_lines.append(f"  Visual Reference: A canonical reference image is provided below. Use it as the PRIMARY source for this character's appearance. Match it EXACTLY.")
            
            lines.extend(char_lines)
        lines.append("")
        
        # Add visual reference section if we have references
        if character_references:
            has_references = False
            ref_lines = []
            for char in characters:
                char_name = char.get('name', 'Unknown')
                if char_name in character_references and character_references[char_name]:
                    has_references = True
                    # Check if we have a canonical ref- image
                    ref_paths = character_references[char_name]
                    has_canonical = any(
                        os.path.basename(p).lower().startswith("ref-") 
                        for p in ref_paths
                    )
                    if has_canonical:
                        ref_lines.append(f"- {char_name}: A canonical reference image is provided below. This is the DEFINITIVE visual reference. Match this character's appearance EXACTLY as shown in the reference image. Do NOT improvise or modify the character's appearance. Use the reference image as the sole source of truth for facial features, clothing, hair, build, and all physical characteristics.")
                    else:
                        ref_lines.append(f"- {char_name}: Reference images from previous storyboards are included below. Match the character's appearance EXACTLY as shown in those reference images.")
            
            if has_references:
                lines.append("CRITICAL Visual Reference Instructions:")
                lines.extend(ref_lines)
                lines.append("")

    # Add setting definitions
    if settings:
        lines.append("Setting Definitions (MUST be drawn consistently):")
        for setting in settings:
            setting_name = setting.get('name', 'Unknown')
            setting_lines = [f"- {setting_name}:"]
            if "description" in setting:
                setting_lines.append(f"  Description: {setting['description']}")
            
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
        
        # Add visual reference section for extras if we have references
        if extra_references:
            has_references = False
            ref_lines = []
            for extra in extras:
                extra_name = extra.get('name', 'Unknown')
                if extra_name in extra_references and extra_references[extra_name]:
                    has_references = True
                    ref_paths = extra_references[extra_name]
                    has_canonical = any(
                        os.path.basename(p).lower().startswith("ref-extra-") 
                        for p in ref_paths
                    )
                    if has_canonical:
                        ref_lines.append(f"- {extra_name}: A canonical reference image is provided below. This is the DEFINITIVE visual reference. Match this extra's appearance EXACTLY as shown in the reference image.")
            
            if has_references:
                lines.append("CRITICAL Extra Visual Reference Instructions:")
                lines.extend(ref_lines)
                lines.append("")
    
    # Add setting visual reference section if we have references
    if setting_references:
        has_references = False
        ref_lines = []
        for setting in settings:
            setting_name = setting.get('name', 'Unknown')
            if setting_name in setting_references:
                refs = setting_references[setting_name]
                if refs.get("indoor") or refs.get("outdoor"):
                    has_references = True
                    ref_lines.append(f"- {setting_name}: Reference images are provided below. Use them as the PRIMARY source for this setting's appearance. Match them EXACTLY.")
        
        if has_references:
            lines.append("CRITICAL Setting Visual Reference Instructions:")
            lines.extend(ref_lines)
            lines.append("")
    
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

    lines.extend(
        [
            "",
            "Style:",
            "- format: comic book",
            "- color: limited-palette",
            "- linework: inked",
            "- era: biblical-meets-sci-fi",
            f"- mood: {mood}",
            f"- camera: {camera}",
            "",
            "Lettering and Typography:",
            "- Font: Comic Sans (or Comic Sans-style lettering) for all text",
            "- Use consistent lettering style across all panels",
            "- All dialogue and text should use the same font family and size",
            "- Lettering should be clear, readable, and professionally rendered",
            "- Maintain uniform text placement (speech bubbles, captions)",
            "- Use consistent speech bubble style and shape throughout",
            "- Ensure text is properly integrated with the art (not floating or misaligned)",
            "- All panels must share the same typographic treatment",
            "",
            "CRITICAL: Visual consistency:",
            "- If reference images are provided for characters, use them as the PRIMARY and DEFINITIVE source for appearance",
            "- Do NOT improvise or modify character appearance when reference images are provided",
            "- Match reference images EXACTLY - facial features, clothing, hair, build, all physical characteristics",
            "- If reference images are provided for extras, use them as the PRIMARY source and match them EXACTLY",
            "- If reference images are provided for settings, use them as the PRIMARY source and match them EXACTLY",
            "- Only use text descriptions if no reference images are available",
            "- If a master style reference is provided, it takes precedence over all other style instructions",
            "- Maintain consistent visual details, architecture, and atmosphere for each setting",
            "- If a character, extra, or setting appears in multiple panels, they must look identical",
            "",
            "Negative prompts:",
            f"- {negative_prompt}",
            "- inconsistent fonts, mismatched lettering, varying text styles",
            "- inconsistent character appearance, changing facial features, different clothing",
            "- inconsistent setting details, changing architecture, varying visual style",
        ]
    )

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
    parser.add_argument("--panel-count", type=int, default=None, help="Panels per storyboard (default: 3-5 based on content)")
    parser.add_argument("--storyboards-per-scene", type=int, default=None, help="Number of storyboards per scene (default: 3-5 based on content)")
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
        min_sb = 3
        max_sb = 5
        if args.storyboards_per_scene:
            min_sb = max_sb = args.storyboards_per_scene
        
        storyboard_chunks = divide_scene_into_storyboards(scene_text, min_sb, max_sb)
        total_storyboards = len(storyboard_chunks)
        
        if args.verbose:
            print(f"  Dividing scene into {total_storyboards} storyboard(s)...", flush=True)
        
        # Check for first-time characters and generate reference images
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
        for sb_idx, (chunk_title, chunk_text) in enumerate(storyboard_chunks, start=1):
            if args.verbose:
                print(f"  Storyboard {sb_idx}/{total_storyboards}: {chunk_title}", flush=True)
            
            # Detect which characters, settings, and extras actually appear in THIS chunk
            chunk_characters, chunk_settings, chunk_extras = detect_entities(chunk_text, definitions)
            
            panel_instructions = derive_panel_instructions(chunk_text, args.panel_count)
            if args.verbose:
                print(f"    Generating {len(panel_instructions)} panel(s)...", flush=True)
            
            # Collect reference images for characters, extras, settings, and style
            # Prioritize canonical ref- images (use max 1 if canonical exists, otherwise 2)
            reference_images = []
            
            # Add character references
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
            if style_reference_path and os.path.isfile(style_reference_path):
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
            
            prompt = build_prompt(
                scene_id=f"{scene_id}-{sb_idx}",
                scene_title=f"{scene_title} - {chunk_title}",
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
            )

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
