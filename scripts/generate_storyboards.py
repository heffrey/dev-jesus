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
    """Load character and setting definitions from JSON file."""
    if not os.path.isfile(path):
        return {"characters": {}, "settings": {}}
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def detect_entities(scene_text: str, definitions: dict) -> tuple[list[dict], list[dict]]:
    """Detect which characters and settings appear in the scene text."""
    scene_lower = scene_text.lower()
    found_characters = []
    found_settings = []

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

    return found_characters, found_settings


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
            char_lines = [f"- {char.get('name', 'Unknown')}:"]
            if "description" in char:
                char_lines.append(f"  Description: {char['description']}")
            if "appearance" in char:
                char_lines.append(f"  Appearance: {char['appearance']}")
            lines.extend(char_lines)
        lines.append("")

    # Add setting definitions
    if settings:
        lines.append("Setting Definitions (MUST be drawn consistently):")
        for setting in settings:
            setting_lines = [f"- {setting.get('name', 'Unknown')}:"]
            if "description" in setting:
                setting_lines.append(f"  Description: {setting['description']}")
            if "visual_details" in setting:
                setting_lines.append(f"  Visual details: {setting['visual_details']}")
            lines.extend(setting_lines)
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
            "CRITICAL: Character and setting consistency:",
            "- Draw all characters EXACTLY as described in their definitions above",
            "- Maintain consistent appearance, clothing, and physical features for each character across all panels",
            "- Draw all settings EXACTLY as described in their definitions above",
            "- Maintain consistent visual details, architecture, and atmosphere for each setting",
            "- If a character or setting appears in multiple panels, they must look identical",
            "",
            "Negative prompts:",
            f"- {negative_prompt}",
            "- inconsistent fonts, mismatched lettering, varying text styles",
            "- inconsistent character appearance, changing facial features, different clothing",
            "- inconsistent setting details, changing architecture, varying visual style",
        ]
    )

    return "\n".join(lines).strip() + "\n"


def call_gemini(api_key: str, model: str, prompt: str, max_retries: int, retry_base: float, verbose: bool = False) -> dict:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
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
    parser.add_argument("--definitions-file", default="story/definitions.json", help="Path to character and setting definitions JSON file")
    args = parser.parse_args()

    if not args.api_key:
        print("Missing API key. Set GEMINI_API_KEY or pass --api-key.", file=sys.stderr)
        return 2

    # Load character and setting definitions
    definitions = load_definitions(args.definitions_file)
    if args.verbose and definitions.get("characters") or definitions.get("settings"):
        char_count = len(definitions.get("characters", {}))
        setting_count = len(definitions.get("settings", {}))
        print(f"Loaded {char_count} character(s) and {setting_count} setting(s) from definitions", flush=True)

    scene_paths = sorted(glob.glob(args.scene_glob))
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
        
        # Detect characters and settings in this scene (for all storyboards)
        characters, settings = detect_entities(scene_text, definitions)
        if args.verbose and (characters or settings):
            if characters:
                char_names = [c.get("name", "Unknown") for c in characters]
                print(f"  Detected characters: {', '.join(char_names)}", flush=True)
            if settings:
                setting_names = [s.get("name", "Unknown") for s in settings]
                print(f"  Detected settings: {', '.join(setting_names)}", flush=True)
        
        # Divide scene into multiple storyboards
        min_sb = 3
        max_sb = 5
        if args.storyboards_per_scene:
            min_sb = max_sb = args.storyboards_per_scene
        
        storyboard_chunks = divide_scene_into_storyboards(scene_text, min_sb, max_sb)
        total_storyboards = len(storyboard_chunks)
        
        if args.verbose:
            print(f"  Dividing scene into {total_storyboards} storyboard(s)...", flush=True)
        
        # Generate a storyboard for each chunk
        for sb_idx, (chunk_title, chunk_text) in enumerate(storyboard_chunks, start=1):
            if args.verbose:
                print(f"  Storyboard {sb_idx}/{total_storyboards}: {chunk_title}", flush=True)
            
            panel_instructions = derive_panel_instructions(chunk_text, args.panel_count)
            if args.verbose:
                print(f"    Generating {len(panel_instructions)} panel(s)...", flush=True)
            
            prompt = build_prompt(
                scene_id=f"{scene_id}-{sb_idx}",
                scene_title=f"{scene_title} - {chunk_title}",
                scene_text=chunk_text,
                panel_instructions=panel_instructions,
                mood=args.mood,
                camera=args.camera,
                negative_prompt=args.negative_prompt,
                characters=characters,
                settings=settings,
            )

            try:
                response = call_gemini(args.api_key, args.model, prompt, args.max_retries, args.retry_base, args.verbose)
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
