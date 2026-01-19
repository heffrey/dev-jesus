#!/usr/bin/env python3
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request


DEFAULT_MODEL = "gemini-3-flash-preview"


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


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def load_definitions(path: str) -> dict:
    """Load character and setting definitions from JSON file."""
    if not os.path.isfile(path):
        return {"characters": {}, "settings": {}}
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def call_gemini(api_key: str, model: str, prompt: str, max_retries: int, retry_base: float, verbose: bool = False) -> dict:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 1.0,
            "topP": 0.95,
            "topK": 40,
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


def extract_text(response: dict) -> str:
    candidates = response.get("candidates") or []
    for candidate in candidates:
        content = candidate.get("content") or {}
        for part in content.get("parts") or []:
            text = part.get("text")
            if text:
                return text.strip()
    return ""


def extract_characters_from_purpose(scene_purpose: str, all_characters: dict) -> dict:
    """Extract characters mentioned in scene purpose by matching names and aliases.
    
    Returns a filtered dict containing only characters that are mentioned in the scene purpose.
    """
    if not scene_purpose or not all_characters:
        return {}
    
    scene_purpose_lower = scene_purpose.lower()
    matching_characters = {}
    
    for char_key, char_data in all_characters.items():
        # Check if character name appears in scene purpose
        char_name = char_data.get("name", char_key)
        if char_name.lower() in scene_purpose_lower:
            matching_characters[char_key] = char_data
            continue
        
        # Check if any alias appears in scene purpose
        aliases = char_data.get("aliases", [])
        for alias in aliases:
            if alias.lower() in scene_purpose_lower:
                matching_characters[char_key] = char_data
                break
    
    return matching_characters


def extract_settings_from_purpose(scene_purpose: str, all_settings: dict) -> dict:
    """Extract settings mentioned in scene purpose by matching names and aliases.
    
    Returns a filtered dict containing only settings that are mentioned in the scene purpose.
    """
    if not scene_purpose or not all_settings:
        return {}
    
    scene_purpose_lower = scene_purpose.lower()
    matching_settings = {}
    
    for setting_key, setting_data in all_settings.items():
        # Check if setting name appears in scene purpose
        setting_name = setting_data.get("name", setting_key)
        if setting_name.lower() in scene_purpose_lower:
            matching_settings[setting_key] = setting_data
            continue
        
        # Check if any alias appears in scene purpose
        aliases = setting_data.get("aliases", [])
        for alias in aliases:
            if alias.lower() in scene_purpose_lower:
                matching_settings[setting_key] = setting_data
                break
    
    return matching_settings


def get_eras_from_settings(settings: dict) -> set:
    """Extract unique eras from a dict of settings.
    
    Returns a set of era strings (e.g., {"biblical", "present-day"}).
    """
    eras = set()
    for setting_data in settings.values():
        era = setting_data.get("era", "")
        if era:
            eras.add(era.lower())
    return eras


def filter_characters_by_era(characters: dict, allowed_eras: set) -> dict:
    """Filter characters to only include those whose era matches one of the allowed eras.
    
    If allowed_eras is empty, returns all characters (no filtering).
    Characters without an era field are always included.
    """
    if not allowed_eras:
        return characters
    
    filtered = {}
    for char_key, char_data in characters.items():
        char_era = char_data.get("era", "").lower()
        # Include if no era specified, or if era matches
        if not char_era or char_era in allowed_eras:
            filtered[char_key] = char_data
    
    return filtered


def extract_continuity_notes(
    api_key: str,
    model: str,
    scene_text: str,
    scene_number: int,
    max_retries: int,
    retry_base: float,
) -> str:
    """Extract key continuity information from a scene using LLM.
    
    Returns a concise summary of continuity elements: vehicles, locations, objects,
    character states, and important plot developments.
    """
    prompt = f"""Extract key continuity information from this scene. Focus on facts that need to be maintained in subsequent scenes:

- Vehicles/transportation (make, model, color, condition)
- Current location and where characters are heading
- Objects/items characters possess or interact with
- Character physical/emotional states
- Important plot developments or revelations
- Time of day and passage of time

Scene {scene_number}:
{scene_text}

Provide a concise bullet-point summary (3-8 points max) of continuity elements. Be specific but brief. Format as:
- [continuity element]: [specific detail]

Example:
- Vehicle: red 1985 Camaro, low on fuel
- Location: Henderson's gas station, heading to farmhouse
- Character state: Sarah is tense, watching for threats; Annie is alert but trying to stay calm
- Plot: Dale was seen in black pickup truck, made eye contact with Annie"""

    try:
        response = call_gemini(api_key, model, prompt, max_retries, retry_base, verbose=False)
        continuity_text = extract_text(response)
        return continuity_text.strip() if continuity_text else ""
    except Exception:
        # If extraction fails, return empty - we'll fall back to summaries
        return ""


def load_continuity_notes(
    output_dir: str,
    current_scene_number: int,
    api_key: str,
    model: str,
    max_retries: int,
    retry_base: float,
    max_scenes: int = 2,
) -> str:
    """Load continuity notes from previously generated scenes.
    
    Uses cached continuity notes if available, otherwise extracts them.
    Returns concise continuity summaries from the last max_scenes scenes.
    """
    continuity_notes = []
    scenes_dir = os.path.join(output_dir, "scenes")
    
    # Load scenes in reverse order (most recent first)
    for scene_num in range(current_scene_number - 1, max(0, current_scene_number - max_scenes - 1), -1):
        scene_path = os.path.join(scenes_dir, f"scene-{scene_num:04d}.md")
        continuity_cache_path = os.path.join(scenes_dir, f"scene-{scene_num:04d}.continuity.md")
        
        if os.path.isfile(scene_path):
            notes = ""
            
            # Try to load from cache first
            if os.path.isfile(continuity_cache_path):
                try:
                    notes = read_text(continuity_cache_path).strip()
                except Exception:
                    pass
            
            # If no cache or cache is empty, extract continuity notes
            if not notes:
                try:
                    scene_text = read_text(scene_path)
                    if scene_text.strip():
                        notes = extract_continuity_notes(
                            api_key, model, scene_text, scene_num, max_retries, retry_base
                        )
                        # Cache the extracted notes
                        if notes:
                            try:
                                with open(continuity_cache_path, "w", encoding="utf-8") as handle:
                                    handle.write(notes)
                                    if not notes.endswith("\n"):
                                        handle.write("\n")
                            except Exception:
                                # If caching fails, continue without cache
                                pass
                except Exception:
                    # If we can't read or extract, skip it
                    pass
            
            if notes:
                continuity_notes.append(f"Scene {scene_num} continuity:\n{notes}")
    
    if continuity_notes:
        # Reverse to show chronological order
        continuity_notes.reverse()
        return "\n\n".join(continuity_notes)
    return ""


def build_scene_prompt(
    act_number: int,
    act_title: str,
    act_description: str,
    scene_number: int,
    scene_purpose: str,
    previous_scenes: list[str],
    core_premise: str,
    definitions: dict,
    output_dir: str,
    api_key: str = None,
    model: str = None,
    max_retries: int = 5,
    retry_base: float = 5.0,
) -> str:
    # Load continuity notes from previous scenes (smart extraction, not full text)
    previous_context = ""
    if scene_number > 1 and api_key:
        continuity_notes = load_continuity_notes(
            output_dir, scene_number, api_key, model, max_retries, retry_base, max_scenes=2
        )
        if continuity_notes:
            previous_context = f"\n\nContinuity from previous scenes (maintain consistency with these details):\n\n{continuity_notes}\n"
    
    # Fallback to purpose summaries if continuity extraction isn't available
    if not previous_context and previous_scenes:
        previous_context = "\n\nPrevious scenes summary:\n" + "\n".join(f"- {s}" for s in previous_scenes[-3:])

    # Build character and setting context
    character_context = ""
    setting_context = ""
    
    all_characters = definitions.get("characters", {})
    all_settings = definitions.get("settings", {})
    
    # IMPORTANT: Characters and settings have "era" fields that must match.
    # Characters should only appear in settings from their own era.
    # e.g., a "biblical" era character should not appear in a "present-day" setting.
    
    # First, determine which settings are mentioned in this scene
    settings_from_purpose = extract_settings_from_purpose(scene_purpose, all_settings)
    
    # Get the eras from the settings mentioned in this scene
    scene_eras = get_eras_from_settings(settings_from_purpose)
    
    # Strategy: Always include main characters to ensure consistency
    # 1. First, get characters mentioned in scene purpose
    characters_from_purpose = extract_characters_from_purpose(scene_purpose, all_characters)
    
    # 2. Filter characters by era to match the scene's settings
    #    This prevents biblical-era characters appearing in present-day settings and vice versa
    if scene_eras:
        # Filter all characters by era before any other selection
        era_filtered_characters = filter_characters_by_era(all_characters, scene_eras)
        # Also filter characters from purpose by era
        characters_from_purpose = filter_characters_by_era(characters_from_purpose, scene_eras)
    else:
        era_filtered_characters = all_characters
    
    # 3. If no characters found in purpose, or if we have few characters total, include all (era-filtered)
    # 4. Otherwise, prioritize main characters (those with "protagonist" or "main" in role)
    if not era_filtered_characters:
        characters = {}
    elif len(era_filtered_characters) <= 5:
        # Few characters: include all era-appropriate characters to ensure consistency
        characters = era_filtered_characters
    elif characters_from_purpose:
        # Some characters found in purpose: use those (already era-filtered)
        characters = characters_from_purpose
    else:
        # Many characters but none in purpose: include main characters from appropriate era
        characters = {}
        for char_key, char_data in era_filtered_characters.items():
            role = char_data.get("role", "").lower()
            if any(keyword in role for keyword in ["protagonist", "main", "hero", "heroine", "lead"]):
                characters[char_key] = char_data
        # If no main characters identified, include first 3 era-appropriate characters
        if not characters:
            characters = dict(list(era_filtered_characters.items())[:3])
    
    if characters:
        character_context = "\n\nAvailable Characters for this scene (use these consistently):\n"
        for char_key, char_data in characters.items():
            char_context = f"- {char_data.get('name', char_key)}"
            if "aliases" in char_data:
                char_context += f" (also known as: {', '.join(char_data['aliases'])})"
            if "era" in char_data:
                char_context += f" [ERA: {char_data['era']}]"
            if "description" in char_data:
                char_context += f": {char_data['description']}"
            if "role" in char_data:
                char_context += f" [{char_data['role']}]"
            character_context += char_context + "\n"
        
        # Add era warning if we filtered by era
        if scene_eras:
            character_context += f"\nNOTE: Only characters from era(s): {', '.join(scene_eras)} are shown above. Do NOT use characters from other eras in this scene.\n"
    
    # Show only era-appropriate settings, or all if no era filter
    if scene_eras:
        # Filter settings to match scene eras
        settings = {k: v for k, v in all_settings.items() 
                   if not v.get("era") or v.get("era", "").lower() in scene_eras}
    else:
        settings = all_settings
    
    if settings:
        setting_context = "\n\nAvailable Settings for this scene (use these consistently):\n"
        for setting_key, setting_data in settings.items():
            setting_info = f"- {setting_data.get('name', setting_key)}"
            if "aliases" in setting_data:
                setting_info += f" (also known as: {', '.join(setting_data['aliases'])})"
            if "era" in setting_data:
                setting_info += f" [ERA: {setting_data['era']}]"
            if "description" in setting_data:
                setting_info += f": {setting_data['description']}"
            setting_context += setting_info + "\n"
    
    # Extract story name from output directory (e.g., "executive" from "executive" or "executive/")
    story_name = os.path.basename(os.path.normpath(output_dir))
    if story_name == "story":
        story_name = "this story"  # Fallback for default "story" directory
    else:
        story_name = f'"{story_name}"'
    
    # Only include core premise if it's provided
    premise_section = ""
    if core_premise:
        premise_section = f"\nCore premise: {core_premise}\n"
    
    prompt = f"""Generate a scene for a story called {story_name}. Write in the same style and format as the existing scenes.{premise_section}{character_context}{setting_context}
Act {act_number}: {act_title}
Act description: {act_description}

Scene {scene_number} purpose: {scene_purpose}
{previous_context}

Requirements:
- Write in third person, past tense
- Use descriptive, literary prose
- Include specific sensory details
- Create 2-3 distinct sections with ## headings (time/location markers)
- Each section should be 3-5 paragraphs
- Maintain the tone: avoid reverence, avoid mockery, treat humanity as understandable
- Use the characters and settings defined above consistently - reference them by name when they appear
- Follow the existing scene format exactly

Generate the complete scene text now, starting with "# Scene {scene_number}" and including all sections:"""

    return prompt


def ensure_dir(path: str) -> None:
    os.makedirs(path, exist_ok=True)


def main() -> int:
    script_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    load_env_file(os.path.join(script_root, ".env"))
    load_env_file(os.path.join(os.getcwd(), ".env"))

    parser = argparse.ArgumentParser(description="Generate scenes procedurally based on act structure.")
    parser.add_argument("--api-key", default=os.environ.get("GEMINI_API_KEY"))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--acts-file", default="stories/story/acts.json", help="JSON file defining acts and scenes")
    parser.add_argument("--core-premise-file", default="stories/story/core-premise.md", help="File with core premise")
    parser.add_argument("--output-dir", default="stories/story", help="Story directory (scenes saved to {output-dir}/scenes/)")
    parser.add_argument("--definitions-file", default=None, help="Path to character and setting definitions JSON file (defaults to {output-dir}/definitions.json)")
    parser.add_argument("--max-retries", type=int, default=5)
    parser.add_argument("--retry-base", type=float, default=5.0)
    parser.add_argument("--sleep-between", type=float, default=5.0, help="Seconds to wait between scenes")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed progress")
    parser.add_argument("--start-scene", type=int, default=1, help="Scene number to start from")
    parser.add_argument("--end-scene", type=int, default=None, help="Scene number to end at (inclusive)")
    args = parser.parse_args()

    if not args.api_key:
        print("Missing API key. Set GEMINI_API_KEY or pass --api-key.", file=sys.stderr)
        return 2

    if not os.path.isfile(args.acts_file):
        print(f"Acts file not found: {args.acts_file}", file=sys.stderr)
        print("Create a JSON file with this structure:", file=sys.stderr)
        print("""
{
  "acts": [
    {
      "number": 1,
      "title": "Act Title",
      "description": "Description of the act",
      "scenes": [
        {
          "number": 1,
          "purpose": "Purpose of this scene"
        }
      ]
    }
  ]
}""", file=sys.stderr)
        return 1

    core_premise = ""
    if os.path.isfile(args.core_premise_file):
        core_premise = read_text(args.core_premise_file).strip()
    # If no core premise file exists, leave it empty - don't inject story-specific assumptions

    # Determine definitions file path
    if args.definitions_file is None:
        args.definitions_file = os.path.join(args.output_dir, "definitions.json")
    
    # Load definitions
    definitions = load_definitions(args.definitions_file)
    if args.verbose:
        char_count = len(definitions.get("characters", {}))
        setting_count = len(definitions.get("settings", {}))
        if char_count > 0 or setting_count > 0:
            print(f"Loaded {char_count} character(s) and {setting_count} setting(s) from {args.definitions_file}", flush=True)
        else:
            print(f"No definitions found at {args.definitions_file} (this is okay)", flush=True)

    with open(args.acts_file, "r", encoding="utf-8") as handle:
        acts_data = json.load(handle)

    ensure_dir(args.output_dir)
    scenes_dir = os.path.join(args.output_dir, "scenes")
    ensure_dir(scenes_dir)

    all_scenes = []
    for act in acts_data.get("acts", []):
        for scene_def in act.get("scenes", []):
            all_scenes.append({
                "act_number": act["number"],
                "act_title": act["title"],
                "act_description": act.get("description", ""),
                "scene_number": scene_def["number"],
                "scene_purpose": scene_def["purpose"],
            })

    scenes_to_generate = [
        s for s in all_scenes
        if s["scene_number"] >= args.start_scene
        and (args.end_scene is None or s["scene_number"] <= args.end_scene)
    ]

    if not scenes_to_generate:
        print("No scenes to generate.", file=sys.stderr)
        return 1

    print(f"Found {len(scenes_to_generate)} scene(s) to generate", flush=True)

    previous_scenes = []
    for idx, scene_def in enumerate(scenes_to_generate, start=1):
        scene_num = scene_def["scene_number"]
        print(f"\n[{idx}/{len(scenes_to_generate)}] Generating Scene {scene_num}", flush=True)
        print(f"  Act {scene_def['act_number']}: {scene_def['act_title']}", flush=True)
        print(f"  Purpose: {scene_def['scene_purpose']}", flush=True)
        
        # Show which characters and settings were selected for this scene (with era info)
        if args.verbose:
            all_chars = definitions.get("characters", {})
            all_settings = definitions.get("settings", {})
            
            # Get settings from purpose to determine era
            settings_from_purpose = extract_settings_from_purpose(scene_def["scene_purpose"], all_settings)
            scene_eras = get_eras_from_settings(settings_from_purpose)
            
            if settings_from_purpose:
                setting_names = [s.get("name", key) for key, s in settings_from_purpose.items()]
                print(f"  Detected settings: {', '.join(setting_names)}", flush=True)
            
            if scene_eras:
                print(f"  Scene era(s): {', '.join(scene_eras)}", flush=True)
            
            # Show characters (filtered by era if applicable)
            selected_chars = extract_characters_from_purpose(scene_def["scene_purpose"], all_chars)
            if scene_eras:
                selected_chars = filter_characters_by_era(selected_chars, scene_eras)
            
            if selected_chars:
                char_info = []
                for key, char_data in selected_chars.items():
                    name = char_data.get("name", key)
                    era = char_data.get("era", "")
                    char_info.append(f"{name} [{era}]" if era else name)
                print(f"  Selected characters: {', '.join(char_info)}", flush=True)
            else:
                print(f"  No era-appropriate characters found in scene purpose", flush=True)

        prompt = build_scene_prompt(
            act_number=scene_def["act_number"],
            act_title=scene_def["act_title"],
            act_description=scene_def["act_description"],
            scene_number=scene_num,
            scene_purpose=scene_def["scene_purpose"],
            previous_scenes=previous_scenes,
            core_premise=core_premise,
            definitions=definitions,
            output_dir=args.output_dir,
            api_key=args.api_key,
            model=args.model,
            max_retries=args.max_retries,
            retry_base=args.retry_base,
        )

        try:
            response = call_gemini(args.api_key, args.model, prompt, args.max_retries, args.retry_base, args.verbose)
            scene_text = extract_text(response)
            
            if not scene_text:
                print(f"  ✗ No text returned for Scene {scene_num}", file=sys.stderr, flush=True)
                continue

            output_path = os.path.join(scenes_dir, f"scene-{scene_num:04d}.md")
            with open(output_path, "w", encoding="utf-8") as handle:
                handle.write(scene_text)
                if not scene_text.endswith("\n"):
                    handle.write("\n")

            print(f"  ✓ Wrote {output_path}", flush=True)
            previous_scenes.append(f"Scene {scene_num}: {scene_def['scene_purpose']}")

        except urllib.error.HTTPError as exc:
            print(f"  ✗ HTTP Error {exc.code}: {exc.reason}", file=sys.stderr, flush=True)
            if args.verbose:
                print(f"     URL: {exc.url}", file=sys.stderr, flush=True)
        except Exception as exc:
            print(f"  ✗ Error: {exc}", file=sys.stderr, flush=True)
            if args.verbose:
                import traceback
                traceback.print_exc()

        if idx < len(scenes_to_generate) and args.sleep_between > 0:
            if args.verbose:
                print(f"  Waiting {args.sleep_between:.1f}s before next scene...", flush=True)
            time.sleep(args.sleep_between)

    print(f"\n✓ Completed generating {len(scenes_to_generate)} scene(s)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
