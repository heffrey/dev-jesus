# Lettering Editor

WYSIWYG desktop app for editing narrative and dialogue boxes on storyboard images (2x2 panels). Uses the same lettering JSON format as `scripts/overlay_storyboard_text.py`.

## Run

From this directory:

```bash
npm install
npm start
```

On first run, choose the dev-jesus project root (the folder that contains `stories/` and `scripts/`). If the app was started from inside the repo, the root may be detected automatically.

## Usage

1. Select a **Story** (e.g. claude).
2. Select an **Image** (unlettered board, e.g. `scene-0001-1.jpg`).
3. Edit the setting label (first panel only), dialogue, and narrative in each quadrant. Drag boxes to move, use corner/edge handles to resize.
4. **Save lettering** writes `stories/<story>/lettering/scene-XXXX-Y.json`.
5. **Run overlay** runs `scripts/overlay_storyboard_text.py` with `--lettering-dir` for the current story to generate lettered images.

See [../docs/lettering-json-schema.md](../docs/lettering-json-schema.md) for the JSON format.
