#!/usr/bin/env python3
"""
Interactive narrative scaffolding script based on Jorge Luis Borges' "Los Cuatro Ciclos" (The Four Cycles).

This script interviews the user to create a new story structure with acts based on:
1. The Troy Cycle (War, destruction, rebuilding)
2. The Search Cycle (Quest, journey, discovery)
3. The Return Cycle (Homecoming, recognition, restoration)
4. The Sacrifice Cycle (Ritual, transformation, transcendence)
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request


DEFAULT_MODEL = "gemini-3-flash-preview"

# Borges' Four Cycles framework
FOUR_CYCLES = {
    1: {
        "name": "The Troy Cycle",
        "description": "War, destruction, and rebuilding. Conflict, siege, and fall. The cycle of conflict and its aftermath.",
        "themes": ["conflict", "siege", "destruction", "rebuilding", "war", "resistance", "fall"]
    },
    2: {
        "name": "The Search Cycle",
        "description": "Quest, journey, and discovery. The pursuit of something lost or desired. The cycle of seeking.",
        "themes": ["quest", "journey", "discovery", "seeking", "pursuit", "exploration", "finding"]
    },
    3: {
        "name": "The Return Cycle",
        "description": "Homecoming, recognition, and restoration. Coming back to where one began. The cycle of return.",
        "themes": ["homecoming", "recognition", "restoration", "return", "reunion", "rediscovery", "coming home"]
    },
    4: {
        "name": "The Sacrifice Cycle",
        "description": "Ritual, transformation, and transcendence. Giving up something for a higher purpose. The cycle of sacrifice.",
        "themes": ["sacrifice", "ritual", "transformation", "transcendence", "giving up", "higher purpose", "redemption"]
    }
}


def load_env_file(path: str) -> None:
    """Load environment variables from .env file."""
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


def call_gemini(api_key: str, model: str, prompt: str, max_retries: int = 5, retry_base: float = 5.0, verbose: bool = False) -> dict:
    """Call Gemini API with a text prompt."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.8,
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
    """Extract text from Gemini API response."""
    candidates = response.get("candidates") or []
    for candidate in candidates:
        content = candidate.get("content") or {}
        for part in content.get("parts") or []:
            text = part.get("text")
            if text:
                return text.strip()
    return ""


def prompt_user(question: str, default: str = None, required: bool = True) -> str:
    """Prompt user for input with optional default."""
    while True:
        if default:
            response = input(f"{question} [{default}]: ").strip()
            if not response:
                return default
            return response
        else:
            response = input(f"{question}: ").strip()
            if response or not required:
                return response
            print("  This field is required. Please provide an answer.")


def prompt_yes_no(question: str, default: bool = True) -> bool:
    """Prompt user for yes/no answer."""
    default_str = "Y/n" if default else "y/N"
    while True:
        response = input(f"{question} [{default_str}]: ").strip().lower()
        if not response:
            return default
        if response in ["y", "yes"]:
            return True
        if response in ["n", "no"]:
            return False
        print("  Please enter 'y' or 'n'.")


def prompt_multiple(question: str, options: list[str], allow_multiple: bool = True) -> list[str]:
    """Prompt user to select from multiple options."""
    print(f"\n{question}")
    for i, option in enumerate(options, 1):
        print(f"  {i}. {option}")
    
    while True:
        if allow_multiple:
            response = input("Enter numbers (comma-separated) or 'all': ").strip()
            if response.lower() == "all":
                return options
            try:
                indices = [int(x.strip()) - 1 for x in response.split(",")]
                selected = [options[i] for i in indices if 0 <= i < len(options)]
                if selected:
                    return selected
            except ValueError:
                pass
            print("  Invalid input. Please enter numbers separated by commas.")
        else:
            response = input("Enter number: ").strip()
            try:
                index = int(response) - 1
                if 0 <= index < len(options):
                    return [options[index]]
            except ValueError:
                pass
            print("  Invalid input. Please enter a number.")


def expand_with_gemini(api_key: str, model: str, user_input: str, context: str, max_retries: int, retry_base: float, verbose: bool = False) -> str:
    """Use Gemini API to expand on user input with additional details."""
    prompt = f"""You are a creative writing assistant helping to develop a narrative structure.

Context: {context}

User provided: {user_input}

Expand on this with rich, detailed, and creative additions. Fill in missing details while staying true to the user's vision. Be specific and vivid. Return only the expanded content, no explanations or meta-commentary."""
    
    try:
        response = call_gemini(api_key, model, prompt, max_retries, retry_base, verbose)
        expanded = extract_text(response)
        return expanded if expanded else user_input
    except Exception as exc:
        if verbose:
            print(f"  Warning: Could not expand with Gemini: {exc}", file=sys.stderr, flush=True)
        return user_input


def generate_acts_structure(api_key: str, model: str, story_concept: str, cycles: list[int], max_retries: int, retry_base: float, verbose: bool = False) -> list[dict]:
    """Generate acts structure based on the Four Cycles framework."""
    cycle_descriptions = [FOUR_CYCLES[c] for c in cycles]
    
    # Determine scene count per act based on total acts
    scenes_per_act = 4 if len(cycles) == 3 else 3  # 3 acts get 4 scenes each, 5 acts get 3 scenes each
    
    prompt = f"""You are a narrative structure expert working with Jorge Luis Borges' "Los Cuatro Ciclos" (The Four Cycles) framework.

Story Concept: {story_concept}

The Four Cycles to use:
{chr(10).join([f"{i+1}. {c['name']}: {c['description']}" for i, c in enumerate(cycle_descriptions)])}

Create a compelling narrative structure with {len(cycles)} acts, each corresponding to one of the cycles above. For each act:
1. Provide a distinctive, evocative title that reflects the cycle's theme and fits the story
2. Write a rich description (2-3 sentences) explaining how this act embodies the cycle and advances the story
3. Suggest exactly {scenes_per_act} scenes for each act, with specific, dramatic purposes that build tension and character

Be creative and specific. Make each act title memorable and each scene purpose clear and compelling.

Return your response as a JSON array with this exact structure:
[
  {{
    "number": 1,
    "title": "Act Title",
    "description": "Act description",
    "scenes": [
      {{"number": 1, "purpose": "Scene purpose"}},
      {{"number": 2, "purpose": "Scene purpose"}}
    ]
  }}
]

Return ONLY valid JSON, no explanations or markdown formatting."""
    
    try:
        response = call_gemini(api_key, model, prompt, max_retries, retry_base, verbose)
        text = extract_text(response)
        
        # Clean up the response - remove markdown code blocks if present
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        
        acts = json.loads(text)
        
        # Ensure proper numbering and scene count
        scene_num = 1
        scenes_per_act = 4 if len(cycles) == 3 else 3
        for i, act in enumerate(acts):
            act["number"] = i + 1
            # Ensure each act has the right number of scenes
            scenes = act.get("scenes", [])
            if len(scenes) < scenes_per_act:
                # Add placeholder scenes if needed
                for j in range(len(scenes), scenes_per_act):
                    scenes.append({"number": scene_num, "purpose": f"Scene in {act.get('title', 'Act')}"})
                    scene_num += 1
            elif len(scenes) > scenes_per_act:
                # Trim excess scenes
                scenes = scenes[:scenes_per_act]
            # Renumber all scenes
            for j, scene in enumerate(scenes):
                scene["number"] = scene_num
                scene_num += 1
            act["scenes"] = scenes
        
        return acts
    except json.JSONDecodeError as exc:
        if verbose:
            print(f"  Warning: Could not parse acts structure: {exc}", file=sys.stderr, flush=True)
            print(f"  Response was: {text[:500]}", file=sys.stderr, flush=True)
        # Return a default structure
        scenes_per_act = 4 if len(cycles) == 3 else 3
        scene_num = 1
        default_acts = []
        for i in range(len(cycles)):
            act_scenes = [
                {"number": scene_num + j, "purpose": f"Scene {j+1} in {cycle_descriptions[i]['name']}"}
                for j in range(scenes_per_act)
            ]
            scene_num += scenes_per_act
            default_acts.append({
                "number": i + 1,
                "title": cycle_descriptions[i]["name"],
                "description": cycle_descriptions[i]["description"],
                "scenes": act_scenes
            })
        return default_acts
    except Exception as exc:
        if verbose:
            print(f"  Warning: Could not generate acts structure: {exc}", file=sys.stderr, flush=True)
        # Return a default structure
        scenes_per_act = 4 if len(cycles) == 3 else 3
        scene_num = 1
        default_acts = []
        for i in range(len(cycles)):
            act_scenes = [
                {"number": scene_num + j, "purpose": f"Scene {j+1} in {cycle_descriptions[i]['name']}"}
                for j in range(scenes_per_act)
            ]
            scene_num += scenes_per_act
            default_acts.append({
                "number": i + 1,
                "title": cycle_descriptions[i]["name"],
                "description": cycle_descriptions[i]["description"],
                "scenes": act_scenes
            })
        return default_acts


def generate_definitions(api_key: str, model: str, story_concept: str, characters_info: str, settings_info: str, extras_info: str, style_info: str, eras: list[str], max_retries: int, retry_base: float, verbose: bool = False) -> dict:
    """Generate comprehensive definitions.json using Gemini."""
    prompt = f"""You are a creative writing assistant helping to create detailed character, setting, extra, and style definitions for a story.

Story Concept: {story_concept}

Eras/Time Periods: {', '.join(eras)}

Characters Information: {characters_info}

Settings Information: {settings_info}

Extras Information: {extras_info}

Style Information: {style_info}

Create a comprehensive definitions.json structure with:

1. **Characters**: For each character mentioned, provide:
   - name: Character's primary name
   - aliases: Array of alternative names
   - description: Character's role, personality, motivations (2-3 sentences)
   - appearance: EXTREMELY detailed physical description including:
     * Height and build
     * Skin tone with RGB color codes
     * Hair style and color with RGB codes
     * Eye color with RGB codes
     * Facial features
     * Distinctive features (scars, tattoos, etc.)
     * Clothing with detailed descriptions and RGB color codes
     * Accessories
   - role: Character's function in the story
   - era: The era/time period this character belongs to

2. **Settings**: For each setting mentioned, provide:
   - name: Setting's primary name
   - aliases: Array of alternative names
   - description: Setting's atmosphere, purpose, significance (2-3 sentences)
   - visual_details: EXTREMELY detailed visual description including:
     * Architecture/landscape features
     * Colors with RGB codes
     * Lighting conditions
     * Textures and materials
     * Atmospheric elements
     * Time of day/weather
   - era: The era/time period this setting belongs to

3. **Extras**: For each extra (non-character entity) mentioned, provide:
   - name: Extra's primary name
   - aliases: Array of alternative names
   - description: What the extra is and its role (1-2 sentences)
   - appearance: Detailed visual description including colors with RGB codes, dimensions, distinctive features

4. **Style**: Provide a comprehensive style definition:
   - description: Overall visual style description
   - typeface: Font/lettering style
   - inking: Inking technique description
   - coloring: Coloring approach
   - line_width: Line width specification
   - palette: Color palette description
   - shading: Shading technique
   - texture: Texture treatment

Return your response as a JSON object with this exact structure:
{{
  "characters": {{...}},
  "settings": {{...}},
  "extras": {{...}},
  "style": {{...}}
}}

Return ONLY valid JSON, no explanations or markdown formatting."""
    
    try:
        response = call_gemini(api_key, model, prompt, max_retries, retry_base, verbose)
        text = extract_text(response)
        
        # Clean up the response
        text = text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
        
        definitions = json.loads(text)
        
        # Ensure all required sections exist
        if "characters" not in definitions:
            definitions["characters"] = {}
        if "settings" not in definitions:
            definitions["settings"] = {}
        if "extras" not in definitions:
            definitions["extras"] = {}
        if "style" not in definitions:
            definitions["style"] = {}
        
        return definitions
    except json.JSONDecodeError as exc:
        if verbose:
            print(f"  Warning: Could not parse definitions: {exc}", file=sys.stderr, flush=True)
            print(f"  Response was: {text[:500]}", file=sys.stderr, flush=True)
        # Return minimal structure
        return {
            "characters": {},
            "settings": {},
            "extras": {},
            "style": {}
        }
    except Exception as exc:
        if verbose:
            print(f"  Warning: Could not generate definitions: {exc}", file=sys.stderr, flush=True)
        return {
            "characters": {},
            "settings": {},
            "extras": {},
            "style": {}
        }


def ensure_dir(path: str) -> None:
    """Ensure directory exists."""
    os.makedirs(path, exist_ok=True)


def main() -> int:
    script_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    load_env_file(os.path.join(script_root, ".env"))
    load_env_file(os.path.join(os.getcwd(), ".env"))

    parser = argparse.ArgumentParser(
        description="Interactive narrative scaffolding based on Borges' Four Cycles framework."
    )
    parser.add_argument("--api-key", default=os.environ.get("GEMINI_API_KEY"))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--output-dir", default=None, help="Output directory for the new story (default: prompt user)")
    parser.add_argument("--max-retries", type=int, default=5)
    parser.add_argument("--retry-base", type=float, default=5.0)
    parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed progress")
    parser.add_argument("--use-gemini", action="store_true", default=True, help="Use Gemini API to expand details")
    parser.add_argument("--acts", type=int, choices=[3, 5], default=None, help="Number of acts (3 or 5). Default: prompt user")
    args = parser.parse_args()

    print("=" * 70)
    print("Narrative Scaffolding Tool")
    print("Based on Jorge Luis Borges' 'Los Cuatro Ciclos' (The Four Cycles)")
    print("=" * 70)
    print()

    if args.use_gemini and not args.api_key:
        print("Missing API key. Set GEMINI_API_KEY or pass --api-key.", file=sys.stderr)
        print("Continuing without Gemini expansion...", file=sys.stderr)
        args.use_gemini = False

    # Get story folder name
    if args.output_dir:
        story_dir = args.output_dir
    else:
        story_dir = prompt_user("Enter the name for your story folder", required=True)
        story_dir = story_dir.lower().replace(" ", "-").replace("_", "-")
    
    story_path = os.path.join(script_root, story_dir)
    
    if os.path.exists(story_path):
        if not prompt_yes_no(f"Directory '{story_dir}' already exists. Continue and overwrite?", default=False):
            print("Aborted.", file=sys.stderr)
            return 1
    else:
        ensure_dir(story_path)
        ensure_dir(os.path.join(story_path, "boards"))

    print(f"\n📁 Story directory: {story_path}")
    print()

    # Core story concept
    print("=" * 70)
    print("STORY CONCEPT")
    print("=" * 70)
    story_concept = prompt_user(
        "Describe your story concept (can be brief or detailed)",
        required=True
    )
    
    if args.use_gemini:
        print("\n  Expanding story concept with Gemini...", flush=True)
        story_concept = expand_with_gemini(
            args.api_key, args.model, story_concept,
            "Expanding a story concept for a narrative structure",
            args.max_retries, args.retry_base, args.verbose
        )
        print(f"  Expanded concept: {story_concept[:200]}...")

    # Eras and time periods
    print("\n" + "=" * 70)
    print("ERAS AND TIME PERIODS")
    print("=" * 70)
    eras_input = prompt_user(
        "Enter era/time period(s) (e.g., 'Rural Texas, 1985' or 'Modern day, New York City'). Leave blank to auto-generate.",
        required=False
    )
    if eras_input:
        # Parse multiple eras if comma-separated
        eras = [e.strip() for e in eras_input.split(",") if e.strip()]
    else:
        eras = []

    # Determine number of acts
    if args.acts:
        num_acts = args.acts
    else:
        print("\n" + "=" * 70)
        print("NARRATIVE STRUCTURE")
        print("=" * 70)
        print("\nChoose your narrative structure:")
        print("  1. 3-Act Structure (Classic: Conflict, Journey, Resolution)")
        print("  2. 5-Act Structure (Epic: Conflict, Quest, Transformation, Return, Resolution)")
        choice = prompt_user("Enter choice (1 or 2)", default="1", required=True)
        num_acts = 3 if choice == "1" else 5
    
    # Automatically select cycles based on act structure
    if num_acts == 3:
        # 3-act: Troy (conflict), Search (journey), Return (resolution)
        cycles = [1, 2, 3]
        print(f"\n✓ Using 3-act structure with cycles: {', '.join([FOUR_CYCLES[c]['name'] for c in cycles])}")
    else:  # 5 acts
        # 5-act: Troy, Search, Sacrifice, Return, and back to Troy for resolution/rebuilding
        cycles = [1, 2, 4, 3, 1]
        print(f"\n✓ Using 5-act structure with cycles: {', '.join([FOUR_CYCLES[c]['name'] for c in cycles])}")

    # Characters, Settings, Extras, Style - all optional, will be auto-generated if not provided
    print("\n" + "=" * 70)
    print("ADDITIONAL DETAILS (Optional - leave blank to auto-generate)")
    print("=" * 70)
    
    characters_info = prompt_user(
        "Main characters (names, roles, descriptions). Leave blank to auto-generate:",
        required=False
    )
    if args.use_gemini and characters_info:
        print("  Expanding characters information with Gemini...", flush=True)
        characters_info = expand_with_gemini(
            args.api_key, args.model, characters_info,
            f"Expanding character information for story: {story_concept}",
            args.max_retries, args.retry_base, args.verbose
        )

    settings_info = prompt_user(
        "Main settings/locations. Leave blank to auto-generate:",
        required=False
    )
    if args.use_gemini and settings_info:
        print("  Expanding settings information with Gemini...", flush=True)
        settings_info = expand_with_gemini(
            args.api_key, args.model, settings_info,
            f"Expanding setting information for story: {story_concept}",
            args.max_retries, args.retry_base, args.verbose
        )

    extras_info = prompt_user(
        "Important objects, vehicles, props. Leave blank to auto-generate:",
        required=False
    )
    if args.use_gemini and extras_info:
        print("  Expanding extras information with Gemini...", flush=True)
        extras_info = expand_with_gemini(
            args.api_key, args.model, extras_info,
            f"Expanding extras information for story: {story_concept}",
            args.max_retries, args.retry_base, args.verbose
        )

    style_info = prompt_user(
        "Visual style (typeface, coloring, inking). Leave blank to auto-generate:",
        required=False
    )
    if args.use_gemini and style_info:
        print("  Expanding style information with Gemini...", flush=True)
        style_info = expand_with_gemini(
            args.api_key, args.model, style_info,
            f"Expanding visual style information for story: {story_concept}",
            args.max_retries, args.retry_base, args.verbose
        )

    # Generate acts structure
    print("\n" + "=" * 70)
    print("GENERATING ACTS STRUCTURE")
    print("=" * 70)
    if args.use_gemini:
        print("\n  Generating acts based on selected cycles with Gemini...", flush=True)
        acts = generate_acts_structure(
            args.api_key, args.model, story_concept, cycles,
            args.max_retries, args.retry_base, args.verbose
        )
    else:
        # Manual structure
        acts = []
        scene_num = 1
        for cycle_num in cycles:
            cycle = FOUR_CYCLES[cycle_num]
            act_title = prompt_user(
                f"Enter title for Act {len(acts) + 1} ({cycle['name']})",
                default=cycle['name'],
                required=True
            )
            act_desc = prompt_user(
                f"Enter description for Act {len(acts) + 1}",
                default=cycle['description'],
                required=True
            )
            
            num_scenes = int(prompt_user(
                f"How many scenes in Act {len(acts) + 1}?",
                default="3",
                required=True
            ))
            
            scenes = []
            for i in range(num_scenes):
                scene_purpose = prompt_user(
                    f"  Scene {i + 1} purpose",
                    required=True
                )
                scenes.append({"number": scene_num, "purpose": scene_purpose})
                scene_num += 1
            
            acts.append({
                "number": len(acts) + 1,
                "title": act_title,
                "description": act_desc,
                "scenes": scenes
            })

    # Generate definitions (always use Gemini if available, or create minimal structure)
    print("\n" + "=" * 70)
    print("GENERATING DEFINITIONS")
    print("=" * 70)
    if args.use_gemini:
        print("\n  Generating comprehensive definitions with Gemini...", flush=True)
        # Auto-generate missing info if not provided
        if not eras:
            eras = ["Contemporary, unspecified location"]
        definitions = generate_definitions(
            args.api_key, args.model, story_concept,
            characters_info or "Generate compelling main characters based on the story concept",
            settings_info or "Generate evocative settings based on the story concept",
            extras_info or "Generate relevant objects and props based on the story concept",
            style_info or "Generate a distinctive visual style appropriate for the story",
            eras,
            args.max_retries, args.retry_base, args.verbose
        )
    else:
        # Minimal structure
        if not eras:
            eras = ["Contemporary, unspecified location"]
        definitions = {
            "characters": {},
            "settings": {},
            "extras": {},
            "style": {}
        }

    # Save files
    print("\n" + "=" * 70)
    print("SAVING FILES")
    print("=" * 70)
    
    acts_path = os.path.join(story_path, "acts.json")
    with open(acts_path, "w", encoding="utf-8") as handle:
        json.dump({"acts": acts}, handle, indent=2, ensure_ascii=False)
    print(f"  ✓ Created {acts_path}")

    definitions_path = os.path.join(story_path, "definitions.json")
    with open(definitions_path, "w", encoding="utf-8") as handle:
        json.dump(definitions, handle, indent=2, ensure_ascii=False)
    print(f"  ✓ Created {definitions_path}")

    # Create README
    readme_path = os.path.join(story_path, "README.md")
    with open(readme_path, "w", encoding="utf-8") as handle:
        handle.write(f"# {story_dir.replace('-', ' ').title()}\n\n")
        handle.write(f"## Story Concept\n\n{story_concept}\n\n")
        handle.write(f"## Eras/Time Periods\n\n")
        for era in eras:
            handle.write(f"- {era}\n")
        handle.write(f"\n## Structure\n\n")
        handle.write(f"This story is structured using Borges' Four Cycles framework:\n\n")
        for cycle_num in cycles:
            cycle = FOUR_CYCLES[cycle_num]
            handle.write(f"- **{cycle['name']}**: {cycle['description']}\n")
        handle.write(f"\n## Acts\n\n")
        for act in acts:
            handle.write(f"### Act {act['number']}: {act['title']}\n\n")
            handle.write(f"{act['description']}\n\n")
            handle.write(f"Scenes: {len(act.get('scenes', []))}\n\n")
    print(f"  ✓ Created {readme_path}")

    print("\n" + "=" * 70)
    print("✓ NARRATIVE SCAFFOLDING COMPLETE")
    print("=" * 70)
    print(f"\nStory structure created in: {story_path}")
    print(f"\nNext steps:")
    print(f"  1. Review and edit {acts_path}")
    print(f"  2. Review and edit {definitions_path}")
    print(f"  3. Generate scenes: python scripts/generate_scenes.py --acts-file {story_dir}/acts.json")
    print(f"  4. Generate storyboards: python scripts/generate_storyboards.py --scene-glob {story_dir}/scene-*.md --output-dir {story_dir}/boards")
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
