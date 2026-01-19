#!/usr/bin/env python3
"""Utility script to tag existing storyboard images with character appearances.

This helps build the character_references.json database retroactively
for storyboards that were generated before the reference system was added.
"""
import argparse
import json
import os
import sys
import glob


def load_character_references(path: str) -> dict:
    """Load character visual references from JSON file."""
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (json.JSONDecodeError, IOError):
        return {}


def save_character_references(path: str, references: dict) -> None:
    """Save character visual references to JSON file."""
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(references, handle, indent=2, sort_keys=True)


def load_definitions(path: str) -> dict:
    """Load character definitions to get character names."""
    if not os.path.isfile(path):
        return {"characters": {}}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (json.JSONDecodeError, IOError):
        return {"characters": {}}


def tag_storyboard(
    image_path: str,
    character_names: list[str],
    character_references: dict,
    output_dir: str,
) -> None:
    """Tag a storyboard image with character appearances."""
    for char_name in character_names:
        if char_name not in character_references:
            character_references[char_name] = []
        
        # Store path relative to output_dir
        if os.path.isabs(image_path):
            rel_path = os.path.relpath(image_path, output_dir)
        else:
            rel_path = image_path
        
        # Add to front if not already present
        if rel_path not in character_references[char_name]:
            character_references[char_name].insert(0, rel_path)
            # Keep only last 10 references per character
            character_references[char_name] = character_references[char_name][:10]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Tag existing storyboard images with character appearances for visual continuity."
    )
    parser.add_argument(
        "--boards-dir",
        default="stories/story/boards",
        help="Directory containing storyboard images (default: stories/story/boards)",
    )
    parser.add_argument(
        "--definitions-file",
        default=None,
        help="Path to definitions.json (defaults to {boards-dir parent}/definitions.json)",
    )
    parser.add_argument(
        "--references-file",
        default=None,
        help="Path to character_references.json (defaults to {boards-dir parent}/character_references.json)",
    )
    parser.add_argument(
        "--image",
        help="Specific image file to tag (if not provided, will prompt for all images)",
    )
    parser.add_argument(
        "--characters",
        nargs="+",
        help="Character names to tag (if not provided, will prompt interactively)",
    )
    parser.add_argument(
        "--auto-tag",
        action="store_true",
        help="Automatically tag all images based on scene files (requires scene files to exist)",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Show detailed progress"
    )
    args = parser.parse_args()

    # Determine paths
    boards_dir = os.path.abspath(args.boards_dir)
    parent_dir = os.path.dirname(boards_dir) if os.path.dirname(boards_dir) else "."
    
    if args.definitions_file is None:
        args.definitions_file = os.path.join(parent_dir, "definitions.json")
    
    if args.references_file is None:
        args.references_file = os.path.join(parent_dir, "character_references.json")

    # Load definitions
    definitions = load_definitions(args.definitions_file)
    character_names = list(definitions.get("characters", {}).keys())
    
    if args.verbose:
        print(f"Found {len(character_names)} character(s) in definitions", flush=True)
        if character_names:
            print(f"  Characters: {', '.join(character_names)}", flush=True)

    # Load existing references
    character_references = load_character_references(args.references_file)
    if args.verbose and character_references:
        total_refs = sum(len(refs) for refs in character_references.values())
        print(f"Loaded {len(character_references)} existing character reference(s) ({total_refs} total)", flush=True)

    if args.auto_tag:
        # Auto-tag based on scene files
        # New structure: scenes are in {story}/scenes/
        scene_dir = os.path.join(parent_dir, "scenes")
        if not os.path.isdir(scene_dir):
            # Fall back to parent_dir for legacy structure
            scene_dir = parent_dir
        scene_files = sorted(glob.glob(os.path.join(scene_dir, "scene-*.md")))
        
        if not scene_files:
            print(f"No scene files found in {scene_dir}", file=sys.stderr)
            return 1
        
        print(f"Auto-tagging based on {len(scene_files)} scene file(s)...", flush=True)
        
        # Map scene IDs to characters
        scene_character_map = {}
        for scene_file in scene_files:
            scene_id = os.path.splitext(os.path.basename(scene_file))[0]
            with open(scene_file, "r", encoding="utf-8") as handle:
                scene_text = handle.read().lower()
            
            scene_chars = []
            for char_key, char_data in definitions.get("characters", {}).items():
                names_to_check = [char_key, char_data.get("name", "")]
                if "aliases" in char_data:
                    names_to_check.extend(char_data["aliases"])
                
                for name in names_to_check:
                    if name and name.lower() in scene_text:
                        scene_chars.append(char_data.get("name", char_key))
                        break
            
            if scene_chars:
                scene_character_map[scene_id] = scene_chars
        
        # Find matching storyboard images
        image_files = sorted(glob.glob(os.path.join(boards_dir, "*.jpg")) + glob.glob(os.path.join(boards_dir, "*.png")))
        tagged_count = 0
        
        for image_file in image_files:
            image_basename = os.path.splitext(os.path.basename(image_file))[0]
            # Extract scene ID (e.g., "scene-0001-1" -> "scene-0001")
            scene_id = "-".join(image_basename.split("-")[:-1]) if "-" in image_basename else image_basename
            
            if scene_id in scene_character_map:
                tag_storyboard(
                    image_file,
                    scene_character_map[scene_id],
                    character_references,
                    boards_dir,
                )
                tagged_count += 1
                if args.verbose:
                    chars = ", ".join(scene_character_map[scene_id])
                    print(f"  Tagged {os.path.basename(image_file)} with: {chars}", flush=True)
        
        print(f"Auto-tagged {tagged_count} image(s)", flush=True)
    
    elif args.image:
        # Tag a specific image
        image_path = args.image
        if not os.path.isabs(image_path):
            image_path = os.path.join(boards_dir, image_path)
        
        if not os.path.isfile(image_path):
            print(f"Image not found: {image_path}", file=sys.stderr)
            return 1
        
        chars_to_tag = args.characters
        if not chars_to_tag:
            print(f"\nTagging: {os.path.basename(image_path)}")
            print(f"Available characters: {', '.join(character_names)}")
            chars_to_tag = input("Enter character names (space-separated): ").strip().split()
        
        if chars_to_tag:
            tag_storyboard(image_path, chars_to_tag, character_references, boards_dir)
            print(f"Tagged {os.path.basename(image_path)} with: {', '.join(chars_to_tag)}", flush=True)
        else:
            print("No characters specified", file=sys.stderr)
            return 1
    
    else:
        # Interactive mode: tag all images
        image_files = sorted(glob.glob(os.path.join(boards_dir, "*.jpg")) + glob.glob(os.path.join(boards_dir, "*.png")))
        
        if not image_files:
            print(f"No images found in {boards_dir}", file=sys.stderr)
            return 1
        
        print(f"Found {len(image_files)} image(s) to tag", flush=True)
        print(f"Available characters: {', '.join(character_names)}", flush=True)
        print("(Press Enter to skip an image, 'q' to quit)\n", flush=True)
        
        for image_file in image_files:
            image_name = os.path.basename(image_file)
            response = input(f"Tag {image_name}? (characters or Enter to skip, 'q' to quit): ").strip()
            
            if response.lower() == "q":
                break
            
            if response:
                chars_to_tag = response.split()
                tag_storyboard(image_file, chars_to_tag, character_references, boards_dir)
                print(f"  ✓ Tagged with: {', '.join(chars_to_tag)}", flush=True)

    # Save updated references
    save_character_references(args.references_file, character_references)
    print(f"\n✓ Saved character references to {args.references_file}", flush=True)
    
    # Show summary
    if character_references:
        print("\nCharacter reference summary:", flush=True)
        for char_name, refs in sorted(character_references.items()):
            print(f"  {char_name}: {len(refs)} reference(s)", flush=True)
    
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
