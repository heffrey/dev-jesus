# dev-jesus

**[View Live Demo](https://heffrey.github.io/dev-jesus/)**

Dev-Jesus is a pipeline for generating graphic novels. The story lives in markdown and evolves through user-assisted inputs. A procedural engine uses those inputs to build a cohesive story arc; we then use Gemini to produce panel art and overlay lettering from the scene text, yielding full pages ready for print or digital reading.

## How it works

- Story concepts and scenes are stored as markdown documents.
- User inputs guide the procedural generation of the story arc.
- The evolving story triggers Gemini to generate storyboards (art only; no lettering in the image).
- A separate overlay script adds dialogue and narrative from the scene markdown to the panels.

## Goals

- Keep narrative development transparent and versioned in text.
- Enable collaborative story shaping through guided inputs.
- Translate story progress into visual boards via AI.
- Keep lettering (dialogue and captions) sourced from markdown so it stays editable and consistent.

## Project Structure

```
dev-jesus/
├── stories/                    # All story projects
│   └── {story-name}/           # Individual story folder
│       ├── acts.json           # Story structure (acts and scenes)
│       ├── definitions.json    # Characters, settings, extras, style
│       ├── core-premise.md     # Story premise (optional)
│       ├── README.md           # Story-specific readme
│       ├── character_references.json   # Character visual tracking
│       ├── setting_references.json     # Setting visual tracking
│       ├── extra_references.json       # Extra visual tracking
│       ├── scenes/             # Scene markdown files
│       │   ├── scene-0001.md
│       │   ├── scene-0001.continuity.md
│       │   └── ...
│       └── boards/             # Generated storyboard images
│           ├── refs/           # Reference images
│           │   ├── ref-{character}.jpg
│           │   ├── ref-setting-{name}-indoor.jpg
│           │   ├── ref-setting-{name}-outdoor.jpg
│           │   ├── ref-extra-{name}.jpg
│           │   └── ref-style.jpg
│           ├── lettered/       # Post-processed boards with overlay lettering
│           │   ├── scene-0001-1-lettered.jpg
│           │   └── ...
│           ├── scene-0001-1.jpg
│           └── ...
│       └── lettering/         # Per-image lettering JSON (optional; used by overlay and editor)
│           ├── scene-0001-1.json
│           └── ...
├── lettering-editor/          # Electron app for editing lettering boxes (WYSIWYG)
├── scripts/                    # Python generation scripts
│   ├── generate_narrative.py
│   ├── generate_scenes.py
│   ├── generate_storyboards.py
│   ├── overlay_storyboard_text.py
│   └── tag_storyboards.py
└── README.md
```

## Scripts

The `scripts/` directory contains Python utilities for generating story content:

### `generate_narrative.py`

Interactive narrative scaffolding tool that creates a new story structure based on Jorge Luis Borges' 1972 essay "Los Cuatro Ciclos" (The Four Cycles). The script:

- Interviews the user interactively to gather story details
- Supports multiple dimensions, time periods, eras, settings, and spaces
- Uses Gemini API to expand on user input and fill in missing details
- Structures acts according to Borges' Four Cycles framework:
  1. **The Troy Cycle**: War, destruction, and rebuilding
  2. **The Search Cycle**: Quest, journey, and discovery
  3. **The Return Cycle**: Homecoming, recognition, and restoration
  4. **The Sacrifice Cycle**: Ritual, transformation, and transcendence
- Generates comprehensive `acts.json` and `definitions.json` files
- Creates a new story folder in `stories/` with all necessary scaffolding

**Usage:**
```bash
python scripts/generate_narrative.py [--api-key KEY] [--output-dir STORY_NAME]
```

**Interactive Process:**

The script guides you through:
1. **Story Concept**: Core idea (can be brief or detailed)
2. **Eras and Time Periods**: Multiple time periods/eras the story spans
3. **Dimensions and Spaces**: Special realities, parallel worlds, dream spaces
4. **Cycle Selection**: Choose which of the Four Cycles to use (all 4 or subset)
5. **Characters**: Main characters (names, roles, descriptions)
6. **Settings**: Main locations and environments
7. **Extras**: Important objects, vehicles, props
8. **Visual Style**: Comic book style preferences

The script uses Gemini API to:
- Expand brief concepts into detailed descriptions
- Generate comprehensive character, setting, and style definitions
- Create act structures that embody the selected cycles
- Fill in missing details while staying true to your vision

**Example:**
```bash
python scripts/generate_narrative.py
# Follow the interactive prompts
# Script creates: stories/{story-name}/acts.json, definitions.json, scenes/, boards/, boards/refs/
```

### `generate_scenes.py`

Generates scene markdown files from an acts structure using Gemini AI. The script:
- Reads act and scene definitions from `stories/{story}/acts.json`
- Uses the core premise from `stories/{story}/core-premise.md` (optional)
- Generates each scene as a markdown file in `stories/{story}/scenes/`
- Maintains context by referencing previous scenes
- Handles rate limiting and retries automatically

**Usage:**
```bash
python scripts/generate_scenes.py --acts-file stories/{story}/acts.json --output-dir stories/{story} [--api-key KEY] [--start-scene N] [--end-scene M]
```

### `generate_storyboards.py`

Generates comic book-style storyboard images from scene markdown files using Gemini's image generation. The script:
- Processes scene markdown files matching `stories/{story}/scenes/scene-*.md`
- Divides each scene into 4–6 storyboard chunks (4 panels per chunk in a 2×2 grid)
- Detects characters, settings, and extras from `stories/{story}/definitions.json` to maintain visual consistency
- **Uses visual references** (character, setting, style refs plus the previous chunk’s image for continuity) so the model draws consistent art
- Sends an explicit **INPUT IMAGES** section in the prompt so the model knows what each reference is for
- Generates **art-only** panels (no lettering, bubbles, or captions); lettering is added later by `overlay_storyboard_text.py`
- Saves storyboard images to `stories/{story}/boards/` and reference images to `stories/{story}/boards/refs/`
- Tracks character, extra, and setting references in JSON for continuity

**Usage:**
```bash
python scripts/generate_storyboards.py --scene-glob "stories/{story}/scenes/scene-*.md" --output-dir stories/{story}/boards --definitions-file stories/{story}/definitions.json [--api-key KEY]
```

To regenerate only specific chunks:
```bash
python scripts/generate_storyboards.py ... --chunks 2,4
```

### `overlay_storyboard_text.py`

Adds lettering to generated storyboard images. When **lettering JSON** is provided (`--lettering-dir`), the script uses that for text and box positions (WYSIWYG from the lettering editor); otherwise it uses **scene markdown** and rule-based placement. The script:
- With lettering JSON: per-image JSON supplies rects and text; font scales to fill boxes; newlines force line breaks. With scene markdown: reads the same scene chunks as the generator (via `divide_scene_into_storyboards`)
- Extracts narrative and dialogue from each chunk (splits on quoted dialogue; strips speech-attribution sentences like “Jed whispered…”)
- Draws **dialogue** in speech bubbles (light fill, dark text) and **narrative** in caption boxes (dark fill, light text)
- Distributes all extracted content across the 4 panels per image (merge), so more of the scene text appears
- Optionally uses OCR (pytesseract) to detect and cover any model-drawn text before overlaying
- Uses palette and style from `definitions.json` (e.g. Obsidian, Bone White) for box and text colors
- Writes lettered images to `--output-dir` (e.g. `stories/{story}/boards/lettered/`) as `scene-XXXX-N-lettered.jpg`

**Requirements:** Pillow. Optional: `pytesseract` and Tesseract (e.g. `brew install tesseract`) for covering existing text.

**Usage:**
```bash
# With lettering editor JSON (WYSIWYG)
python scripts/overlay_storyboard_text.py --scene "stories/{story}/scenes/scene-0001.md" --boards-dir stories/{story}/boards --lettering-dir stories/{story}/lettering [--output-dir stories/{story}/boards/lettered] [--verbose]

# Scene-only (rule-based placement)
python scripts/overlay_storyboard_text.py --scene "stories/{story}/scenes/scene-0001.md" --boards-dir stories/{story}/boards [--definitions-file stories/{story}/definitions.json] [--output-dir stories/{story}/boards/lettered] [--verbose]
```

**Typical workflow:** Generate boards with `generate_storyboards.py`. Optionally edit boxes in the **Lettering Editor**, then run the overlay with `--lettering-dir stories/{story}/lettering`.

### Lettering Editor (Electron)

The `lettering-editor/` app positions and edits narrative/dialogue boxes per image (WYSIWYG). Set project root, pick story and image; drag/resize boxes; text is saved to `stories/{story}/lettering/scene-XXXX-N.json`. **Space** toggles Show lettered (view updates when `boards/lettered/` files change). **Run overlay** runs the overlay script for the current story. Boxes auto-expand to fit content. Run: `cd lettering-editor && npm install && npm start`. See `lettering-editor/README.md`.

**Visual Continuity System:**

The script maintains visual continuity through multiple reference systems:

1. **Character References:**
   - Tracks which storyboard images contain which characters in `character_references.json`
   - Generates canonical reference images (`ref-{character-name}.{ext}`) on first appearance
   - Includes up to 2 reference images per character when generating new storyboards
   - Sends these reference images to the AI model to ensure consistent character appearance
   - Automatically updates the reference database as new storyboards are generated

2. **Extra References (Non-Character Entities):**
   - Tracks vehicles, props, clothing items, and other non-character entities in `extra_references.json`
   - Generates canonical reference images (`ref-extra-{extra-name}.{ext}`) on first appearance
   - Ensures consistent appearance of important objects, vehicles, and props across scenes
   - Examples: vehicles, weapons, important props, distinctive clothing items

3. **Setting References (Indoor/Outdoor Continuity):**
   - Tracks setting reference images in `setting_references.json`
   - Generates separate indoor and outdoor reference images for each setting
   - Files named `ref-setting-{setting-name}-indoor.{ext}` and `ref-setting-{setting-name}-outdoor.{ext}`
   - Ensures architectural and environmental consistency between scenes
   - Automatically generates both views when a setting is first encountered

4. **Master Style Reference:**
   - Generates a single master style reference image (`ref-style.{ext}`) that defines the visual style for the entire comic series
   - Includes typeface, inking technique, coloring approach, line width, palette, shading, and texture
   - Takes precedence over all other style instructions in prompts
   - Generated once at the start if a `style` section exists in `definitions.json`
   - Ensures consistent typography, lettering, speech bubbles, and overall visual style across all storyboards

### `tag_storyboards.py`

Utility script to manually tag existing storyboard images with character appearances. This is useful for:
- Building the character reference database retroactively for existing storyboards
- Correcting or updating character tags
- Manually curating which images serve as visual references

**Usage:**
```bash
# Auto-tag based on scene files (recommended for existing storyboards)
python scripts/tag_storyboards.py --boards-dir stories/{story}/boards --auto-tag

# Tag a specific image
python scripts/tag_storyboards.py --boards-dir stories/{story}/boards --image scene-0001-1.jpg --characters Annie Sarah

# Interactive mode (tag all images one by one)
python scripts/tag_storyboards.py --boards-dir stories/{story}/boards
```

## File Formats

### `stories/{story}/acts.json`

Defines the story structure as a JSON file with acts and scenes. Each act contains:
- `number`: Act number (integer)
- `title`: Act title (string)
- `description`: Brief description of the act's purpose (string)
- `scenes`: Array of scene objects, each containing:
  - `number`: Scene number (integer)
  - `purpose`: Description of what the scene should accomplish (string)

**Example structure:**
```json
{
  "acts": [
    {
      "number": 1,
      "title": "The Signal",
      "description": "Introduction of Jesus as the developer avatar...",
      "scenes": [
        {
          "number": 1,
          "purpose": "Introduce Joel and his first dream vision..."
        }
      ]
    }
  ]
}
```

### `stories/{story}/definitions.json`

Defines characters, settings, extras, and style with detailed appearance and description information to ensure visual consistency across generated storyboards. The file contains four main sections:

**Characters:**
Each character entry includes:
- `name`: Character's primary name (string)
- `aliases`: Optional array of alternative names (array of strings)
- `description`: Character's role and personality (string)
- `appearance`: Detailed physical description including height, build, skin tone, hair, eyes, clothing with RGB color codes (string)
- `role`: Character's function in the story (string)
- `era`: Time period (string, e.g., "Rural Texas, 1985")

**Settings:**
Each setting entry includes:
- `name`: Setting's primary name (string)
- `aliases`: Optional array of alternative names (array of strings)
- `description`: Setting's atmosphere and purpose (string)
- `visual_details`: Key visual elements for consistent rendering, including colors, architecture, lighting (string)
- `era`: Time period (string, e.g., "Rural Texas, 1985")

**Extras (Non-Character Entities):**
Each extra entry includes:
- `name`: Extra's primary name (string)
- `aliases`: Optional array of alternative names (array of strings)
- `description`: What the extra is and its role in the story (string)
- `appearance`: Detailed visual description including colors, dimensions, distinctive features with RGB color codes (string)

Examples of extras: vehicles (cars, trucks), weapons, important props, distinctive clothing items, tools, or any non-character entity that needs visual consistency.

**Style (Master Style Reference):**
The style section defines the visual style for the entire comic series:
- `description`: Overall style description (string)
- `typeface`: Font/lettering style (string, e.g., "Comic Sans-style lettering")
- `inking`: Inking technique description (string, e.g., "Bold, consistent line work")
- `coloring`: Coloring approach (string, e.g., "Limited palette with muted tones")
- `line_width`: Line width specification (string, e.g., "Medium, consistent")
- `palette`: Color palette description (string, e.g., "Earth tones, muted colors")
- `shading`: Shading technique (string, e.g., "Cross-hatching and stippling")
- `texture`: Texture treatment (string, e.g., "Minimal, clean")

The storyboard generator uses these definitions to:
- Maintain consistent character appearances across all generated images
- Ensure setting details remain consistent (indoor/outdoor views)
- Keep extras (vehicles, props, etc.) visually consistent
- Apply a unified visual style across the entire comic series

### Reference Tracking Files

The storyboard generator automatically creates and maintains several JSON files to track visual references:

#### `stories/{story}/character_references.json`

Tracks which storyboard images contain which characters. Used to maintain visual continuity by referencing previous character appearances when generating new storyboards.

**Format:**
```json
{
  "Annie": [
    "stories/{story}/boards/refs/ref-annie.jpg",
    "stories/{story}/boards/scene-0001-1.jpg",
    "stories/{story}/boards/scene-0001-2.jpg"
  ],
  "Sarah": [
    "stories/{story}/boards/refs/ref-sarah.jpg",
    "stories/{story}/boards/scene-0001-1.jpg",
    "stories/{story}/boards/scene-0002-1.jpg"
  ]
}
```

Canonical reference images (in `boards/refs/`, prefixed with `ref-`) are prioritized over storyboard images. The file is automatically maintained by `generate_storyboards.py`, but can be manually edited.

#### `stories/{story}/extra_references.json`

Tracks which storyboard images contain which extras (non-character entities). Used to maintain visual consistency for vehicles, props, clothing items, and other important objects.

**Format:**
```json
{
  "1985 Camaro": [
    "stories/{story}/boards/refs/ref-extra-1985-camaro.jpg",
    "stories/{story}/boards/scene-0001-1.jpg"
  ],
  "Folding Knife": [
    "stories/{story}/boards/refs/ref-extra-folding-knife.jpg",
    "stories/{story}/boards/scene-0002-3.jpg"
  ]
}
```

Canonical reference images (in `boards/refs/`, prefixed with `ref-extra-`) are generated on first appearance and prioritized for consistency.

#### `stories/{story}/setting_references.json`

Tracks indoor and outdoor reference images for each setting. Used to maintain architectural and environmental consistency between scenes.

**Format:**
```json
{
  "The Farmhouse": {
    "indoor": [
      "stories/{story}/boards/refs/ref-setting-the-farmhouse-indoor.jpg"
    ],
    "outdoor": [
      "stories/{story}/boards/refs/ref-setting-the-farmhouse-outdoor.jpg"
    ]
  },
  "The Gas Station": {
    "indoor": [
      "stories/{story}/boards/refs/ref-setting-the-gas-station-indoor.jpg"
    ],
    "outdoor": [
      "stories/{story}/boards/refs/ref-setting-the-gas-station-outdoor.jpg"
    ]
  }
}
```

Both indoor and outdoor references are automatically generated when a setting is first encountered in a scene.

#### Master Style Reference

The master style reference image (`boards/refs/ref-style.{ext}`) is generated once and defines the visual style for the entire comic series. This single image takes precedence over all other style instructions and ensures consistent:
- Typography and lettering
- Inking technique and line work
- Coloring approach and palette
- Shading and texture treatments
- Speech bubble and caption styling

All reference files are automatically maintained by `generate_storyboards.py` and should generally not need manual editing.
