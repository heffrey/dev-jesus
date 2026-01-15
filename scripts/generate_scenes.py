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


def call_gemini(api_key: str, model: str, prompt: str, max_retries: int, retry_base: float, verbose: bool = False) -> dict:
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
    candidates = response.get("candidates") or []
    for candidate in candidates:
        content = candidate.get("content") or {}
        for part in content.get("parts") or []:
            text = part.get("text")
            if text:
                return text.strip()
    return ""


def build_scene_prompt(
    act_number: int,
    act_title: str,
    act_description: str,
    scene_number: int,
    scene_purpose: str,
    previous_scenes: list[str],
    core_premise: str,
) -> str:
    previous_context = ""
    if previous_scenes:
        previous_context = "\n\nPrevious scenes summary:\n" + "\n".join(f"- {s}" for s in previous_scenes[-3:])

    prompt = f"""Generate a scene for a story called "dev-jesus". Write in the same style and format as the existing scenes.

Core premise: {core_premise}

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
- The story alternates between biblical-era scenes (Galilee) and present-day scenes (The Company operations floor)
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
    parser.add_argument("--acts-file", default="story/acts.json", help="JSON file defining acts and scenes")
    parser.add_argument("--core-premise-file", default="story/core-premise.md", help="File with core premise")
    parser.add_argument("--output-dir", default="story", help="Directory to save generated scenes")
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
        core_premise = read_text(args.core_premise_file)
    else:
        core_premise = "Human reality is a simulation. Jesus is a systems engineer from the originating civilization who entered as a constrained instance to deliver a corrective signal."

    with open(args.acts_file, "r", encoding="utf-8") as handle:
        acts_data = json.load(handle)

    ensure_dir(args.output_dir)

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

        prompt = build_scene_prompt(
            act_number=scene_def["act_number"],
            act_title=scene_def["act_title"],
            act_description=scene_def["act_description"],
            scene_number=scene_num,
            scene_purpose=scene_def["scene_purpose"],
            previous_scenes=previous_scenes,
            core_premise=core_premise,
        )

        try:
            response = call_gemini(args.api_key, args.model, prompt, args.max_retries, args.retry_base, args.verbose)
            scene_text = extract_text(response)
            
            if not scene_text:
                print(f"  ✗ No text returned for Scene {scene_num}", file=sys.stderr, flush=True)
                continue

            output_path = os.path.join(args.output_dir, f"scene-{scene_num:04d}.md")
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
