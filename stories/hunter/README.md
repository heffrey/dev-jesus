# Hunter Story

This folder contains the "hunter" story, following the same structure as the `story/` folder.

## Structure

- `acts.json.example` - Template for defining the story structure (copy to `acts.json` to use)
- `definitions.json` - Character and setting definitions for visual consistency
- `boards/` - Directory for generated storyboard images
- `scene-*.md` - Scene markdown files (generated from acts.json)

## Usage

### 1. Set up the story structure

Copy the example acts file:
```bash
cp hunter/acts.json.example hunter/acts.json
```

Edit `hunter/acts.json` to define your story's acts and scenes.

### 2. Edit character and setting definitions

Edit `hunter/definitions.json` to define characters and settings for your story. This ensures visual consistency in generated storyboards.

### 3. Generate scenes

Generate scene markdown files from your acts structure:
```bash
python scripts/generate_scenes.py \
  --acts-file hunter/acts.json \
  --output-dir hunter
```

### 4. Generate storyboards

Generate storyboard images from your scenes:
```bash
python scripts/generate_storyboards.py \
  --scene-glob "hunter/scene-*.md" \
  --output-dir hunter/boards \
  --definitions-file hunter/definitions.json
```

## Notes

- Scene files should be named with zero-padded 4-digit format: `scene-0001.md`, `scene-0002.md`, etc.
- Storyboard images will be named: `scene-0001-1.jpg`, `scene-0001-2.jpg`, etc.
- The scripts support all the same options as documented in the main README.md
