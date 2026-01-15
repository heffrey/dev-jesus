# dev-jesus

Dev-Jesus is a text-first art and software concept built around an AI-driven story. The story lives in markdown files and evolves through user-assisted inputs. A procedural engine uses those inputs to generate a cohesive story arc, and as the narrative develops we invoke Gemini to produce storyboard imagery for the current state of the story.

## How it works

- Story concepts and scenes are stored as markdown documents.
- User inputs guide the procedural generation of the story arc.
- The evolving story triggers Gemini to generate storyboards.

## Goals

- Keep narrative development transparent and versioned in text.
- Enable collaborative story shaping through guided inputs.
- Translate story progress into visual boards via AI.

## Scripts

The `scripts/` directory contains Python utilities for generating story content:

### `generate_scenes.py`

Generates scene markdown files from an acts structure using Gemini AI. The script:
- Reads act and scene definitions from `story/acts.json`
- Uses the core premise from `story/core-premise.md` (or a default)
- Generates each scene as a markdown file in the story directory
- Maintains context by referencing previous scenes
- Handles rate limiting and retries automatically

**Usage:**
```bash
python scripts/generate_scenes.py [--api-key KEY] [--start-scene N] [--end-scene M]
```

### `generate_storyboards.py`

Generates comic book-style storyboard images from scene markdown files using Gemini's image generation. The script:
- Processes scene markdown files matching `story/scene-*.md`
- Divides each scene into 3-5 storyboard chunks
- Detects characters and settings from `story/definitions.json` to maintain visual consistency
- Generates multi-panel comic images with consistent character and setting appearances
- Saves images to `story/boards/` directory

**Usage:**
```bash
python scripts/generate_storyboards.py [--api-key KEY] [--scene-glob PATTERN]
```

## File Formats

### `story/acts.json.example`

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

Copy `acts.json.example` to `acts.json` and customize it for your story structure.

### `story/definitions.json`

Defines characters and settings with detailed appearance and description information to ensure visual consistency across generated storyboards. The file contains two main sections:

**Characters:**
Each character entry includes:
- `name`: Character's primary name (string)
- `aliases`: Optional array of alternative names (array of strings)
- `description`: Character's role and personality (string)
- `appearance`: Detailed physical description including height, build, skin tone, hair, eyes, clothing with RGB color codes (string)
- `role`: Character's function in the story (string)
- `era`: Time period ("biblical" or "present-day")

**Settings:**
Each setting entry includes:
- `name`: Setting's primary name (string)
- `aliases`: Optional array of alternative names (array of strings)
- `description`: Setting's atmosphere and purpose (string)
- `visual_details`: Key visual elements for consistent rendering (string)
- `era`: Time period ("biblical" or "present-day")

The storyboard generator uses these definitions to maintain consistent character appearances and setting details across all generated images.
