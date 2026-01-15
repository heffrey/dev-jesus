# Gemini image query (Nano Banana 3)

Use this as a standard request template for generating comic panels per scene.
Replace placeholders wrapped in <> for each scene file.

## Request payload (JSON)

```json
{
  "model": "gemini-3-pro-image-preview",
  "contents": [
    {
      "role": "user",
      "parts": [
        {
          "text": "Create a <panel-count>-panel comic.\n\nScene ID: <scene-id>\nScene title: <scene-title>\n\nScene text:\n<full-scene-text>\n\nPanel instructions:\n1) <panel-1-instruction>\n2) <panel-2-instruction>\n3) <panel-3-instruction>\n\nStyle:\n- format: comic\n- color: limited-palette\n- linework: inked\n- era: biblical-meets-sci-fi\n- mood: <mood>\n- camera: <camera-guidance>\n\nNegative prompts:\n- <things-to-avoid>\n"
        }
      ]
    }
  ],
  "generationConfig": {
    "responseModalities": ["IMAGE"],
    "imageConfig": {
      "aspectRatio": "16:9",
      "imageSize": "2K"
    }
  }
}
```

## Example per-scene mapping

- `scene-id`: `scene-1`
- `scene-title`: `That night -- in Joel's house / Morning -- outskirts of Capernaum`
- `full-scene-text`: full contents of the scene file
- `panel-count`: 3 to 6
- `panel-instructions`: one short visual description per panel
- `negative prompts`: modern clothing, cars, guns, neon signage
