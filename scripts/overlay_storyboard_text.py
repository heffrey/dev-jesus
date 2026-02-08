#!/usr/bin/env python3
"""
Overlay scene text onto generated storyboard images.

Uses the actual prose and dialogue from the scene markdown (not the generator's
panel instructions). The generator (generate_storyboards.py) is told not to draw
any lettering; if the model still outputs text, OCR (pytesseract + Tesseract)
detects and covers it before we draw. Requires: pip install Pillow. Optional:
pip install pytesseract and system Tesseract (e.g. brew install tesseract) to
strip any remaining model-generated text. Use --no-ocr to skip OCR.
"""
import argparse
import glob
import os
import re
import sys

# Optional OCR
try:
    import pytesseract
    _OCR_AVAILABLE = True
except ImportError:
    _OCR_AVAILABLE = False

# Import generator logic so chunking and panel instructions match exactly
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)
import generate_storyboards as gen

def _extract_scene_content_for_panels(chunk_text: str, max_panels: int = 4) -> list[dict]:
    """Extract dialogue and narrative from chunk text for overlay.

    Returns all extracted items (up to 24) in reading order, each {"text": str, "is_dialogue": bool}.
    Caller should use _merge_content_to_panels() to distribute across 4 panels.
    """
    # Strip section headers (## Title) so we don't treat them as content
    body = re.sub(r"^## .+$", "", chunk_text, flags=re.MULTILINE).strip()
    # Split on double-quoted strings to get alternating [narrative, dialogue, narrative, ...]
    parts = re.split(r'"([^"]*)"', body)
    content = []  # list of (text, is_dialogue)
    min_dialogue_len = 15
    min_narrative_len = 20

    for i, part in enumerate(parts):
        part = part.strip()
        if not part:
            continue
        if i % 2 == 1:
            # This is the content inside quotes (dialogue) — skip inline terms like "hallucination anchors,"
            stripped = part.strip()
            if stripped.endswith(",") and stripped.count(",") == 1:
                continue  # skip "Word Word," style inline phrases
            if (
                len(stripped) >= min_dialogue_len
                and not stripped.startswith(":")
                and " " in stripped
            ):
                content.append((stripped, True))
        else:
            # Narrative: split into sentences (complete ones, start with capital)
            # Skip speech-attribution-only sentences (e.g. "Jed whispered, though Sarah was already behind him.")
            attribution_pattern = re.compile(
                r"^[A-Z][a-z]*(?:\s+[A-Z][a-z]*)*\s+"
                r"(whispered|said|murmured|replied|answered|continued|asked)\s*[,.]",
                re.IGNORECASE,
            )
            for sent in re.split(r"(?<=[.!?])\s+", part):
                sent = sent.strip()
                if (
                    len(sent) >= min_narrative_len
                    and sent
                    and re.search(r"[.!?]$", sent)
                    and sent[0].isupper()
                ):
                    if attribution_pattern.match(sent) and len(sent) < 180:
                        continue  # skip attribution-only narrative
                    content.append((sent, False))

    max_items = min(len(content), 24)  # cap so we don't explode; merge will distribute across 4 panels
    content = content[:max_items]

    # Truncate very long items; return ALL items (caller will merge into 4 panels)
    result = []
    max_chars = 220
    for text, is_dialogue in content:
        if len(text) > max_chars:
            text = text[: max_chars - 3].rsplit(" ", 1)[0] + "…"
        result.append({"text": text, "is_dialogue": is_dialogue})
    return result


def _merge_content_to_panels(content: list[dict], num_panels: int = 4) -> list[dict]:
    """Distribute content across num_panels. Each panel gets {"narrative": str, "dialogue": str}
    so dialogue can be drawn in bubbles and narrative in captions (both when present)."""
    if not content:
        return [{"narrative": "", "dialogue": ""}] * num_panels
    n = len(content)
    per_panel = (n + num_panels - 1) // num_panels
    panels = []
    for p in range(num_panels):
        start = p * per_panel
        end = min(start + per_panel, n)
        if start >= n:
            panels.append({"narrative": "", "dialogue": ""})
            continue
        items = content[start:end]
        narrative_parts = [it["text"].strip() for it in items if it.get("text") and not it.get("is_dialogue")]
        dialogue_parts = [it["text"].strip() for it in items if it.get("text") and it.get("is_dialogue")]
        panels.append({
            "narrative": " ".join(narrative_parts) if narrative_parts else "",
            "dialogue": " ".join(dialogue_parts) if dialogue_parts else "",
        })
    return panels


def _find_storyboard_images(boards_dir: str, scene_id: str) -> list[tuple[int, str]]:
    """Return list of (sb_idx_1based, absolute_path) sorted by sb_idx."""
    found = []
    for ext in ("jpg", "jpeg", "png"):
        pattern = os.path.join(boards_dir, f"{scene_id}-*.{ext}")
        for path in glob.glob(pattern):
            base = os.path.basename(path)
            # Match scene_id-<digit>.ext only (exclude -lettered, -1-2 multi-panel, etc.)
            m = re.match(r"^" + re.escape(scene_id) + r"-(\d+)\.([a-z]+)$", base, re.I)
            if m:
                sb_idx = int(m.group(1))
                found.append((sb_idx, os.path.abspath(path)))
    found.sort(key=lambda x: x[0])
    return found


def _parse_style_from_definitions(definitions: dict) -> dict:
    """Extract lettering/box colors from definitions.style and definitions.style.palette.
    Returns dict with box_fill (R,G,B), text_color (R,G,B), outline_color (R,G,B), or empty dict.
    """
    style = definitions.get("style") or {}
    palette_str = style.get("palette", "") or ""
    # Parse "Obsidian (RGB: 10,10,12), Bone White (RGB: 245,245,240), ..."
    rgb_by_name = {}
    for m in re.finditer(r"(\w+(?:\s+\w+)?)\s*\(\s*RGB:\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", palette_str, re.IGNORECASE):
        name = m.group(1).strip().lower()
        rgb = (int(m.group(2)), int(m.group(3)), int(m.group(4)))
        rgb_by_name[name] = rgb
    # Obsidian = box/caption background; Bone White = text
    box_fill = rgb_by_name.get("obsidian", (10, 10, 12))
    text_color = rgb_by_name.get("bone white", (245, 245, 240))
    outline_color = text_color  # thin outline in bone white per "ultra-fine" line
    return {
        "box_fill": box_fill,
        "text_color": text_color,
        "outline_color": outline_color,
    }


def _ocr_text_bboxes_in_region(img, region: tuple, min_confidence: int = 30) -> list[tuple[int, int, int, int]]:
    """Return list of (x0, y0, x1, y1) in full-image coords for text detected in region.
    Requires pytesseract and Tesseract. Returns [] if OCR unavailable or fails.
    """
    if not _OCR_AVAILABLE:
        return []
    x0, y0, x1, y1 = region
    crop = img.crop((x0, y0, x1, y1))
    try:
        data = pytesseract.image_to_data(crop, output_type=pytesseract.Output.DICT)
    except (pytesseract.TesseractNotFoundError, Exception):
        return []
    bboxes = []
    n = len(data.get("left", []))
    for i in range(n):
        conf = int(data.get("conf", [0] * n)[i])
        if conf < min_confidence:
            continue
        left = data["left"][i] + x0
        top = data["top"][i] + y0
        w = data["width"][i]
        h = data["height"][i]
        if w > 0 and h > 0:
            bboxes.append((left, top, left + w, top + h))
    return bboxes


def _cover_text_bboxes(image, bboxes: list, pad: int = 3, fill_color: tuple = None):
    """Draw filled rectangles over bboxes to hide existing text."""
    try:
        from PIL import ImageDraw
    except ImportError:
        return
    if fill_color is None:
        fill_color = (40, 40, 40)
    draw = ImageDraw.Draw(image)
    for (left, top, right, bottom) in bboxes:
        left = max(0, left - pad)
        top = max(0, top - pad)
        right = min(image.width, right + pad)
        bottom = min(image.height, bottom + pad)
        draw.rectangle([left, top, right, bottom], fill=fill_color, outline=fill_color)


def _merge_overlapping_bboxes(bboxes: list, margin: int = 5) -> list[tuple[int, int, int, int]]:
    """Merge bboxes that overlap or are close (within margin) to reduce draw calls and avoid gaps."""
    if not bboxes:
        return []
    merged = []
    for (a0, a1, a2, a3) in sorted(bboxes, key=lambda b: (b[1], b[0])):
        found = False
        for i, (b0, b1, b2, b3) in enumerate(merged):
            if a0 <= b2 + margin and a2 >= b0 - margin and a1 <= b3 + margin and a3 >= b1 - margin:
                merged[i] = (
                    min(a0, b0), min(a1, b1),
                    max(a2, b2), max(a3, b3),
                )
                found = True
                break
        if not found:
            merged.append((a0, a1, a2, a3))
    return merged


def _wrap_text(draw, text: str, font, max_width: int) -> list[str]:
    """Wrap text to fit within max_width pixels. Returns list of lines."""
    words = text.split()
    lines = []
    current = []
    current_width = 0
    for w in words:
        test = " ".join(current + [w]) if current else w
        bbox = draw.textbbox((0, 0), test, font=font)
        wd = bbox[2] - bbox[0]
        if wd <= max_width:
            current.append(w)
            current_width = wd
        else:
            if current:
                lines.append(" ".join(current))
            current = [w]
            bbox = draw.textbbox((0, 0), w, font=font)
            current_width = bbox[2] - bbox[0]
    if current:
        lines.append(" ".join(current))
    return lines


def _draw_panel_text(image, quadrant_bounds: tuple, panel_content: dict, font, font_size: int, verbose: bool, style: dict = None, position: str = "bottom", h_align: str = "full", v_offset: int = 0):
    """Draw text in one panel. panel_content: {text, is_dialogue}.
    position: "top" places box at the top of the panel, "bottom" (default) at the bottom.
    h_align: "full" (default) spans the panel width, "left" anchors a narrower box to the left side,
             "right" anchors it to the right side.
    v_offset: extra pixels to push the box down (positive) or up (negative) from its default position.
    Dialogue -> speech bubble (light fill, dark text); narrative -> caption box (dark fill, light text).
    """
    text = (panel_content or {}).get("text", "") or ""
    is_dialogue = (panel_content or {}).get("is_dialogue", False)
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        raise SystemExit("Pillow is required. Install with: pip install Pillow") from None

    x0, y0, x1, y1 = quadrant_bounds
    w = x1 - x0
    h = y1 - y0
    pad = max(4, min(w, h) // 30)
    # Use slightly smaller font for long text so more fits
    if len(text) > 180:
        font_size = max(9, int(font_size * 0.85))
    # Text area: small padding from panel edges
    if h_align == "left":
        box_x0 = x0 + pad
        box_x1 = x0 + int(w * 0.90)
    elif h_align == "right":
        box_x0 = x1 - int(w * 0.90)
        box_x1 = x1 - pad
    else:  # "full"
        box_x0 = x0 + pad
        box_x1 = x1 - pad
    box_w = box_x1 - box_x0
    if position == "top":
        box_y0 = y0 + pad + v_offset
        box_y1 = y0 + int(h * 0.40) + v_offset
    else:
        box_y0 = y1 - int(h * 0.40) + v_offset
        box_y1 = y1 - pad + v_offset

    if not text or not text.strip():
        return

    # Load font at size
    try:
        pil_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
    except (OSError, IOError):
        try:
            pil_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", font_size)
        except (OSError, IOError):
            fonts_dir = os.path.join(_SCRIPT_DIR, "fonts")
            if os.path.isdir(fonts_dir):
                for name in os.listdir(fonts_dir):
                    if name.lower().endswith((".ttf", ".otf")):
                        try:
                            pil_font = ImageFont.truetype(os.path.join(fonts_dir, name), font_size)
                            break
                        except (OSError, IOError):
                            continue
            pil_font = ImageFont.load_default()

    draw = ImageDraw.Draw(image)
    lines = _wrap_text(draw, text, pil_font, int(box_w * 0.95))
    max_lines = 8 if len(text) > 300 else 6
    # If text still overflows, try a smaller font to fit more
    if len(lines) > max_lines:
        smaller_size = max(9, int(font_size * 0.80))
        try:
            smaller_font = ImageFont.truetype(pil_font.path, smaller_size)
        except Exception:
            smaller_font = pil_font
            smaller_size = font_size
        lines = _wrap_text(draw, text, smaller_font, int(box_w * 0.95))
        if len(lines) <= max_lines + 2:
            pil_font = smaller_font
            font_size = smaller_size
        else:
            lines = _wrap_text(draw, text, pil_font, int(box_w * 0.95))
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip()
        if len(lines[-1]) > 15:
            lines[-1] = lines[-1][: len(lines[-1]) - 3].rsplit(" ", 1)[0] + "…"

    # Line height from font (tight)
    line_height = int(font_size * 1.15)
    total_h = len(lines) * line_height
    if position == "top":
        start_y = box_y0 + pad
    else:
        # Anchor text flush to bottom of panel (only small padding_rect gap below)
        start_y = box_y1 - total_h

    # Dialogue = speech bubble (light fill, dark text); narrative = caption box (dark fill, light text)
    padding_rect = max(2, pad // 3)
    rect_top = max(box_y0, start_y - padding_rect)
    rect_bottom = min(box_y1, start_y + total_h + padding_rect)
    rect_left = box_x0
    rect_right = box_x1
    if is_dialogue:
        # Speech bubble: Bone White fill, Obsidian text, thin dark outline
        box_fill = style.get("text_color", (245, 245, 240)) if style else (245, 245, 240)  # Bone White
        text_color = style.get("box_fill", (10, 10, 12)) if style else (10, 10, 12)  # Obsidian
        outline_color = (60, 60, 65)
    else:
        # Caption box: Obsidian fill, Bone White text
        box_fill = style.get("box_fill", (30, 30, 30)) if style else (30, 30, 30)
        outline_color = style.get("outline_color", (200, 200, 200)) if style else (200, 200, 200)
        text_color = style.get("text_color", (255, 255, 255)) if style else (255, 255, 255)
    draw.rounded_rectangle(
        [rect_left, rect_top, rect_right, rect_bottom],
        radius=max(2, pad // 2),
        fill=box_fill,
        outline=outline_color,
        width=1,
    )
    for i, line in enumerate(lines):
        y = start_y + i * line_height
        # Center horizontally in box
        bbox = draw.textbbox((0, 0), line, font=pil_font)
        tw = bbox[2] - bbox[0]
        tx = box_x0 + (box_w - tw) // 2
        draw.text((tx, y), line, font=pil_font, fill=text_color)


def _overlay_one_image(
    image_path: str,
    panel_contents: list[dict],
    output_path: str,
    verbose: bool,
    use_ocr: bool = True,
    style: dict = None,
) -> None:
    """Overlay up to 4 panel contents onto one storyboard image (2x2 grid).
    Each item is {text, is_dialogue}; dialogue drawn as speech bubble, narrative as caption.
    If use_ocr and pytesseract available, covers detected text in each quadrant before drawing.
    style: from _parse_style_from_definitions (box_fill, text_color, outline_color) for lettering/box colors.
    """
    try:
        from PIL import Image
    except ImportError:
        raise SystemExit("Pillow is required. Install with: pip install Pillow") from None

    img = Image.open(image_path).convert("RGB")
    w, h = img.size
    half_w = w // 2
    half_h = h // 2
    quadrants = [
        (0, 0, half_w, half_h),
        (half_w, 0, w, half_h),
        (0, half_h, half_w, h),
        (half_w, half_h, w, h),
    ]
    # Detect and cover any existing text in panels (model-generated or other) so only our lettering shows
    if use_ocr and _OCR_AVAILABLE:
        cover_color = (style.get("box_fill", (32, 32, 32))) if style else (32, 32, 32)
        for bounds in quadrants:
            bboxes = _ocr_text_bboxes_in_region(img, bounds, min_confidence=20)  # low threshold to catch faint text
            merged = _merge_overlapping_bboxes(bboxes, margin=12)  # merge nearby so we cover full text blocks
            _cover_text_bboxes(img, merged, pad=8, fill_color=cover_color)  # generous pad to fully hide text

    # Font size: readable but not overwhelming (between previous too-big and too-small)
    font_size = max(11, min(20, half_h // 22))

    empty = {"narrative": "", "dialogue": ""}
    contents = (panel_contents[:4] + [empty] * 4)[:4]
    for i, (bounds, content) in enumerate(zip(quadrants, contents)):
        narrative = content.get("narrative", "")
        dialogue = content.get("dialogue", "")
        if verbose and (narrative or dialogue):
            for label, t in [("narrative", narrative), ("dialogue", dialogue)]:
                if t:
                    print(f"      Panel {i + 1} ({label}): {t[:50]}{'…' if len(t) > 50 else ''}")
        # When both: dialogue as bubble at top, narrative as caption at bottom
        pos = "top" if i == 0 else "bottom"
        h_align = "left" if i == 1 else "full"
        v_off = 150 if i == 1 else 0
        # Panel 1 (top-right): narrative-only box at top so it doesn't overlap art in bottom-right
        narrative_pos = "bottom" if dialogue else ("top" if (i == 1 and narrative) else pos)
        narrative_v_off = v_off if (not dialogue and narrative_pos == "bottom" and i == 1) else 0
        if dialogue:
            _draw_panel_text(img, bounds, {"text": dialogue, "is_dialogue": True}, None, font_size, verbose, style=style, position="top", h_align=h_align, v_offset=0)
        if narrative:
            _draw_panel_text(img, bounds, {"text": narrative, "is_dialogue": False}, None, font_size, verbose, style=style, position=narrative_pos, h_align=h_align, v_offset=narrative_v_off)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    img.save(output_path, "JPEG", quality=92)
    if verbose:
        print(f"    Wrote {output_path}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Overlay scene text onto generated storyboard images (2x2 panels per image)."
    )
    parser.add_argument("--scene", required=True, help="Path to scene markdown (e.g. stories/claude/scenes/scene-0001.md)")
    parser.add_argument("--boards-dir", required=True, help="Directory containing storyboard images")
    parser.add_argument("--definitions-file", default=None, help="Path to definitions.json (optional; used for style.palette: box/text colors and lettering)")
    parser.add_argument("--output-dir", default=None, help="Where to write lettered images (default: same as --boards-dir)")
    parser.add_argument("--in-place", action="store_true", help="Overwrite original images instead of writing -lettered files")
    parser.add_argument("--no-ocr", action="store_true", help="Do not use OCR to cover existing text (default: use if pytesseract and Tesseract available)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print progress and panel text")
    args = parser.parse_args()

    boards_dir = os.path.abspath(args.boards_dir)
    output_dir = os.path.abspath(args.output_dir or boards_dir)
    if args.in_place:
        output_dir = boards_dir

    if not os.path.isfile(args.scene):
        print(f"Scene file not found: {args.scene}", file=sys.stderr)
        return 1
    if args.definitions_file and not os.path.isfile(args.definitions_file):
        print(f"Definitions file not found: {args.definitions_file}", file=sys.stderr)
        return 1
    if not os.path.isdir(boards_dir):
        print(f"Boards directory not found: {boards_dir}", file=sys.stderr)
        return 1

    scene_text = gen.read_text(args.scene)
    scene_id = gen.build_scene_id(args.scene)
    # Load style from definitions for lettering/box colors (Obsidian, Bone White, etc.)
    style = {}
    if args.definitions_file and os.path.isfile(args.definitions_file):
        definitions = gen.load_definitions(args.definitions_file)
        style = _parse_style_from_definitions(definitions)

    storyboard_chunks = gen.divide_scene_into_storyboards(scene_text, 4, 6)
    image_list = _find_storyboard_images(boards_dir, scene_id)
    if not image_list:
        print(f"No storyboard images found in {boards_dir} for scene {scene_id}", file=sys.stderr)
        return 1

    if args.verbose:
        print(f"Scene: {scene_id}, chunks: {len(storyboard_chunks)}, images: {len(image_list)}")

    for sb_idx, img_path in image_list:
        if sb_idx > len(storyboard_chunks):
            if args.verbose:
                print(f"  Skip {os.path.basename(img_path)} (no chunk for index {sb_idx})")
            continue
        chunk_title, chunk_text = storyboard_chunks[sb_idx - 1]
        all_items = _extract_scene_content_for_panels(chunk_text, max_panels=4)
        panel_texts = _merge_content_to_panels(all_items, num_panels=4)

        if args.verbose:
            print(f"  {os.path.basename(img_path)} -> chunk {sb_idx}: {chunk_title}")

        base = os.path.basename(img_path)
        name, ext = os.path.splitext(base)
        if args.in_place:
            out_path = os.path.join(output_dir, base)
        else:
            out_path = os.path.join(output_dir, f"{name}-lettered.jpg")
        _overlay_one_image(img_path, panel_texts, out_path, args.verbose, use_ocr=not args.no_ocr, style=style)

    if args.verbose:
        print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
