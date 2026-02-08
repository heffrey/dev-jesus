# Lettering JSON schema

Per-image lettering files used by the overlay script and the lettering editor. Stored under `stories/<story>/lettering/` with filenames matching the unlettered board image: `scene-0001-1.json` for `scene-0001-1.jpg`.

## Root object

| Field           | Type   | Required | Description |
|----------------|--------|----------|-------------|
| `setting_label`| string | no       | Location/setting text for the first panel (e.g. from scene `##` header). |
| `setting_rect` | array  | no       | `[left, top, right, bottom]` as fractions 0–1 **of the first quadrant**. When present, the overlay draws the setting box in this rect instead of default top placement. |
| `panels`       | array  | yes      | Exactly 4 panel objects (one per quadrant in 2x2 order: top-left, top-right, bottom-left, bottom-right). |

## Panel object

| Field           | Type   | Required | Description |
|----------------|--------|----------|-------------|
| `narrative`    | string | no       | Caption/narrative text (drawn in dark box, light text). |
| `dialogue`     | string | no       | Dialogue text (drawn in speech bubble: light fill, dark text). |
| `narrative_rect` | array | no       | `[left, top, right, bottom]` as fractions 0–1 **of that quadrant**. When present, overlay draws the narrative box in this rect instead of rule-based placement. |
| `dialogue_rect`  | array | no       | `[left, top, right, bottom]` as fractions 0–1 **of that quadrant**. When present, overlay draws the dialogue box in this rect. |

## Rect format

- Each rect is `[left, top, right, bottom]` in the range 0–1.
- Coordinates are relative to the quadrant (for panels) or the first quadrant (for `setting_rect`).
- Example: `[0.05, 0.7, 0.95, 0.95]` = box in the lower 25% of the panel, with 5% horizontal margin on each side.

## Example

```json
{
  "setting_label": "Anthropic Headquarters – The Corridor",
  "setting_rect": [0.05, 0.02, 0.95, 0.12],
  "panels": [
    {
      "narrative": "Jed and Sarah walk past the alignment diagrams.",
      "dialogue": "Do you see it too?",
      "narrative_rect": [0.05, 0.72, 0.95, 0.95],
      "dialogue_rect": [0.05, 0.45, 0.95, 0.65]
    },
    {
      "narrative": "",
      "dialogue": ""
    },
    { "narrative": "", "dialogue": "" },
    { "narrative": "", "dialogue": "" }
  ]
}
```

## Fallback behavior

- If a rect is omitted for a box that has text, the overlay uses its built-in rule-based placement (top/bottom/middle, h_align, avoid_faces, etc.).
- If no lettering file exists for an image, the overlay derives content from the scene markdown (when `--scene` is provided).
