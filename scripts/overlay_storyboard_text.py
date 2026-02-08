#!/usr/bin/env python3
"""
Overlay scene text onto generated storyboard images.

Uses the actual prose and dialogue from the scene markdown (not the generator's
panel instructions). The generator (generate_storyboards.py) is told not to draw
any lettering; if the model still outputs text, OCR (pytesseract + Tesseract)
detects and covers it before we draw. Requires: pip install Pillow. Optional: pytesseract + Tesseract to strip
model-generated text (--no-ocr to skip); pyphen for syllabic word breaks
(e.g. mani-folds) so text wraps tighter in boxes; opencv-python-headless for
--avoid-faces (snap boxes to bottom when faces detected in top of panel).
"""
import argparse
import glob
import json
import os
import re
import sys
from typing import Optional

# Optional OCR
try:
    import pytesseract
    _OCR_AVAILABLE = True
except ImportError:
    _OCR_AVAILABLE = False

# Optional syllabic hyphenation (e.g. manifolds -> mani-folds) for tighter wrapping
_hyphenator = None
try:
    import pyphen
    for _lang in ("en_US", "en_GB", "en"):
        try:
            _hyphenator = pyphen.Pyphen(lang=_lang)
            break
        except Exception:
            continue
except ImportError:
    pass

# Optional face detection for --avoid-faces (requires opencv-python-headless)
_CV2_AVAILABLE = False
try:
    import cv2
    _CV2_AVAILABLE = True
except ImportError:
    pass

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
    # When chunk has no body (e.g. chunk 1 is only "## Location\n\n## Time"), use a ## line as narrative
    # only when there are 2+ headers (use the second, e.g. "03:22 AM") so we don't duplicate the setting box
    if not body:
        headers = [line[3:].strip() for line in chunk_text.splitlines() if line.strip().startswith("## ")]
        if len(headers) >= 2 and headers[1] and len(headers[1]) >= 2:
            return [{"text": headers[1], "is_dialogue": False}]
        return []
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


def _lettering_json_path_for_image(image_path: str, lettering_dir: str) -> str:
    """Return path to lettering JSON for an image. Strips -lettered from base name.
    E.g. .../scene-0001-1-lettered.jpg -> lettering_dir/scene-0001-1.json
    """
    base = os.path.basename(image_path)
    name, _ = os.path.splitext(base)
    # Remove -lettered suffix so lettered and unlettered images use same JSON
    if name.endswith("-lettered"):
        name = name[: -len("-lettered")]
    return os.path.join(lettering_dir, f"{name}.json")


def _load_lettering_json(lettering_path: str) -> Optional[dict]:
    """Load lettering data from JSON file. Returns None if file missing or invalid.
    Expected keys: setting_label (optional), setting_rect (optional), panels (array of 4).
    """
    if not os.path.isfile(lettering_path):
        return None
    try:
        with open(lettering_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return None
    if not isinstance(data.get("panels"), list) or len(data["panels"]) < 4:
        return None
    return data


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


def _setting_label_from_chunk_title(chunk_title: str) -> str:
    """Return a clean location/setting label for overlay (strip ' (Part N)' suffix).
    Returns empty when the title is generic (e.g. 'Part 1' when scene has no ## sections).
    """
    if not chunk_title or not chunk_title.strip():
        return ""
    label = re.sub(r"\s*\(Part\s+\d+\)\s*$", "", chunk_title.strip(), flags=re.IGNORECASE).strip()
    if re.match(r"^Part\s*\d*\s*$", label, re.IGNORECASE):
        return ""
    return label


def _draw_setting_label(image, quadrant_bounds: tuple, label: str, font_size: int, style: dict = None, setting_rect: Optional[list] = None) -> int:
    """Draw setting/location in a caption-style box with bold text at the top of the panel.
    setting_rect: optional [left, top, right, bottom] as fractions 0-1 of quadrant; when present, box is drawn in that rect.
    Returns the height in pixels used (so caller can offset content below). Returns 0 if no label.
    """
    if not label or not label.strip():
        return 0
    try:
        from PIL import ImageDraw, ImageFont
    except ImportError:
        return 0
    x0, y0, x1, y1 = quadrant_bounds
    w = x1 - x0
    h_panel = y1 - y0
    pad = max(3, min(w, h_panel) // 40)
    size = max(11, min(15, font_size - 2))
    # Prefer bold font for setting label (consistent "header" look)
    font = None
    if os.path.isfile("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
        try:
            font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size)
        except (OSError, IOError):
            pass
    if font is None and os.path.isfile("/System/Library/Fonts/Helvetica.ttc"):
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size, index=1)
        except (TypeError, OSError, IOError):
            try:
                font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size)
            except (OSError, IOError):
                pass
    if font is None:
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size)
        except (OSError, IOError):
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
            except (OSError, IOError):
                font = ImageFont.load_default()
    draw = ImageDraw.Draw(image)
    box_fill = (style.get("box_fill", (30, 30, 30))) if style else (30, 30, 30)
    text_color = (style.get("text_color", (245, 245, 240))) if style else (245, 245, 240)
    outline_color = (style.get("outline_color", (200, 200, 200))) if style else (200, 200, 200)
    box_pad = max(2, pad // 2)
    if setting_rect and len(setting_rect) >= 4:
        rl, rt, rr, rb = setting_rect[:4]
        rect_left = x0 + int(rl * w)
        rect_top = y0 + int(rt * h_panel)
        rect_right = x0 + int(rr * w)
        rect_bottom = y0 + int(rb * h_panel)
    else:
        rect_left = x0 + pad
        rect_right = x1 - pad
        rect_top = y0 + max(2, pad - 2)
        rect_bottom = None  # computed after we know text height
    max_text_width = max(80, (rect_right - rect_left) - 2 * box_pad)
    words = label.strip().split()
    lines = []
    current = []
    for word in words:
        candidate = " ".join(current + [word]) if current else word
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if bbox[2] - bbox[0] <= max_text_width:
            current.append(word)
        else:
            if current:
                lines.append(" ".join(current))
            current = [word]
            if len(lines) >= 2:
                remainder = " ".join(current)
                if len(remainder) > 12:
                    remainder = remainder[:10].rsplit(" ", 1)[0] + "…"
                current = [remainder] if remainder else []
                break
    if current:
        lines.append(" ".join(current))
    if not lines:
        return 0
    line_height = draw.textbbox((0, 0), "Ay", font=font)[3] - draw.textbbox((0, 0), "A", font=font)[1]
    th = len(lines) * line_height
    if rect_bottom is None:
        rect_bottom = rect_top + th + 2 * box_pad
    draw.rounded_rectangle(
        [rect_left, rect_top, rect_right, rect_bottom],
        radius=max(2, pad // 2),
        fill=box_fill,
        outline=outline_color,
        width=1,
    )
    tx = rect_left + box_pad
    box_h = rect_bottom - rect_top
    ty = rect_top + (box_h - th) // 2
    for i, line in enumerate(lines):
        draw.text((tx, ty + i * line_height), line, font=font, fill=text_color)
    return int(rect_bottom - y0)


def _faces_in_quadrant(image, quadrant_bounds: tuple):
    """Return list of face bboxes (x0, y0, x1, y1) in image coords within the quadrant.
    Requires OpenCV; returns [] if cv2 unavailable or no faces detected.
    """
    if not _CV2_AVAILABLE:
        return []
    try:
        import numpy as np
        x0, y0, x1, y1 = quadrant_bounds
        crop = image.crop((x0, y0, x1, y1))
        arr = np.array(crop)
        gray = cv2.cvtColor(arr, cv2.COLOR_RGB2GRAY) if len(arr.shape) == 3 else arr
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        face_cascade = cv2.CascadeClassifier(cascade_path)
        if face_cascade.empty():
            return []
        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30))
        return [(x0 + int(fx), y0 + int(fy), x0 + int(fx) + int(fw), y0 + int(fy) + int(fh)) for (fx, fy, fw, fh) in faces]
    except Exception:
        return []


def _top_region_overlaps_faces(quadrant_bounds: tuple, face_bboxes: list, top_fraction: float = 0.45) -> bool:
    """Return True if any face bbox overlaps the top region (y0 to y0 + top_fraction * height)."""
    if not face_bboxes:
        return False
    x0, y0, x1, y1 = quadrant_bounds
    h = y1 - y0
    top_y1 = y0 + int(h * top_fraction)
    for (fx0, fy0, fx1, fy1) in face_bboxes:
        face_center_y = (fy0 + fy1) / 2
        if face_center_y < top_y1:
            return True
        if fy1 > y0 and fy0 < top_y1:
            return True
    return False


def _bottom_region_overlaps_faces(quadrant_bounds: tuple, face_bboxes: list, bottom_fraction: float = 0.40) -> bool:
    """Return True if any face bbox overlaps the bottom region (y1 - bottom_fraction * height to y1)."""
    if not face_bboxes:
        return False
    x0, y0, x1, y1 = quadrant_bounds
    h = y1 - y0
    bottom_y0 = y1 - int(h * bottom_fraction)
    for (fx0, fy0, fx1, fy1) in face_bboxes:
        face_center_y = (fy0 + fy1) / 2
        if face_center_y > bottom_y0:
            return True
        if fy0 < y1 and fy1 > bottom_y0:
            return True
    return False


def _hyphenate_word(word: str) -> list[str]:
    """Return syllable segments for word, e.g. 'manifolds' -> ['mani', 'folds']. Empty list if no hyphenation."""
    if not _hyphenator or len(word) < 4 or "-" in word:
        return []
    try:
        inserted = _hyphenator.inserted(word, hyphen="-")
        if "-" in inserted:
            return inserted.split("-")
    except Exception:
        pass
    return []


def _measure(draw, s: str, font) -> int:
    bbox = draw.textbbox((0, 0), s, font=font)
    return bbox[2] - bbox[0]


# Markdown for dialogue/narrative: **bold**, *italic*, __underline__
_MD_BOLD = "**"
_MD_UNDERLINE = "__"
_MD_ITALIC = "*"


def _strip_markdown(s: str) -> str:
    """Return plain text with **, __, *, _ delimiters removed (for width measurement)."""
    out = []
    i = 0
    while i < len(s):
        if s[i : i + 2] == _MD_BOLD:
            i += 2
            j = s.find(_MD_BOLD, i)
            if j == -1:
                out.append(s[i:])
                break
            out.append(s[i:j])
            i = j + 2
        elif s[i : i + 2] == _MD_UNDERLINE:
            i += 2
            j = s.find(_MD_UNDERLINE, i)
            if j == -1:
                out.append(s[i:])
                break
            out.append(s[i:j])
            i = j + 2
        elif s[i] == _MD_ITALIC:
            i += 1
            j = s.find(_MD_ITALIC, i)
            if j == -1:
                out.append(s[i:])
                break
            out.append(s[i:j])
            i = j + 1
        elif s[i] == "_" and (i + 1 >= len(s) or s[i + 1] != "_"):
            i += 1
            j = s.find("_", i)
            if j == -1:
                out.append(s[i:])
                break
            out.append(s[i:j])
            i = j + 1
        else:
            out.append(s[i])
            i += 1
    return "".join(out)


def _segment_to_raw(text: str, style: Optional[str]) -> str:
    """Reconstruct raw markdown string from a segment (for wrap output)."""
    if style == "bold":
        return _MD_BOLD + text + _MD_BOLD
    if style == "underline":
        return _MD_UNDERLINE + text + _MD_UNDERLINE
    if style == "italic":
        return "_" + text + "_"
    return text


def _parse_markdown_line(line: str) -> list[tuple[str, Optional[str]]]:
    """Parse a line into segments (text, style). style is None, 'bold', 'italic', or 'underline'."""
    segments = []
    i = 0
    while i < len(line):
        if line[i : i + 2] == _MD_BOLD:
            i += 2
            j = line.find(_MD_BOLD, i)
            if j == -1:
                segments.append((line[i:], "bold"))
                break
            segments.append((line[i:j], "bold"))
            i = j + 2
        elif line[i : i + 2] == _MD_UNDERLINE:
            i += 2
            j = line.find(_MD_UNDERLINE, i)
            if j == -1:
                segments.append((line[i:], "underline"))
                break
            segments.append((line[i:j], "underline"))
            i = j + 2
        elif line[i] == _MD_ITALIC:
            i += 1
            j = line.find(_MD_ITALIC, i)
            if j == -1:
                segments.append((line[i:], "italic"))
                break
            segments.append((line[i:j], "italic"))
            i = j + 1
        elif line[i] == "_" and (i + 1 >= len(line) or line[i + 1] != "_"):
            i += 1
            j = line.find("_", i)
            if j == -1:
                segments.append((line[i:], "italic"))
                break
            segments.append((line[i:j], "italic"))
            i = j + 1
        else:
            start = i
            while i < len(line):
                if line[i : i + 2] == _MD_BOLD or line[i : i + 2] == _MD_UNDERLINE or line[i] == _MD_ITALIC:
                    break
                if line[i] == "_" and (i + 1 >= len(line) or line[i + 1] != "_"):
                    break
                i += 1
            if start < i:
                segments.append((line[start:i], None))
    return segments


def _wrap_text_segment_markdown(draw, segment: str, font, max_width: int) -> list[str]:
    """Wrap a segment without breaking inside markdown spans. Each **, __, *, _ span is atomic. Plain (non-markdown) runs are word-wrapped."""
    segments = _parse_markdown_line(segment)
    if not segments:
        return [""]
    expanded = []
    for text, seg_style in segments:
        if seg_style is None and _measure(draw, text, font) > max_width:
            for line in _wrap_text_segment(draw, text, font, max_width, strip_markdown_for_wrap=False):
                expanded.append((line, None))
        else:
            expanded.append((text, seg_style))
    line_segments = []
    current_width = 0
    lines_out = []
    for text, seg_style in expanded:
        w = _measure(draw, text, font)
        if line_segments and current_width + w > max_width:
            lines_out.append("".join(_segment_to_raw(t, s) for t, s in line_segments))
            line_segments = []
            current_width = 0
        line_segments.append((text, seg_style))
        current_width += w
    if line_segments:
        lines_out.append("".join(_segment_to_raw(t, s) for t, s in line_segments))
    return lines_out


def _load_panel_font(font_size: int, style: Optional[str]) -> "ImageFont.FreeTypeFont":
    """Load panel font at size; style is None (regular), 'bold', or 'italic'. Underline uses regular + line."""
    import os
    from PIL import ImageFont

    font = None
    if style == "bold":
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size, index=1)
        except (TypeError, OSError, IOError):
            pass
        if font is None and os.path.isfile("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"):
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
            except (OSError, IOError):
                pass
    elif style == "italic":
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size, index=2)
        except (TypeError, OSError, IOError):
            pass
        if font is None and os.path.isfile("/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"):
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf", font_size)
            except (OSError, IOError):
                pass
    if font is None:
        try:
            font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", font_size)
        except (OSError, IOError):
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", font_size)
            except (OSError, IOError):
                fonts_dir = os.path.join(_SCRIPT_DIR, "fonts")
                if os.path.isdir(fonts_dir):
                    for name in sorted(os.listdir(fonts_dir)):
                        if name.lower().endswith((".ttf", ".otf")):
                            try:
                                font = ImageFont.truetype(os.path.join(fonts_dir, name), font_size)
                                break
                            except (OSError, IOError):
                                continue
                font = font or ImageFont.load_default()
    return font


def _count_lines_no_hyphen(draw, words: list, font, max_width: int, initial_width: int = 0) -> int:
    """Simulate word-only wrap; return number of lines. Used to choose hyphen break that minimizes lines."""
    if not words:
        return 0
    space_w = _measure(draw, " ", font)
    current_width = initial_width
    count = 1
    for w in words:
        wd = _measure(draw, w, font)
        gap = space_w if current_width > 0 else 0
        if current_width + gap + wd <= max_width:
            current_width += gap + wd
        else:
            count += 1
            current_width = wd
    return count


def _best_single_break(segments: list, draw, font, max_width: int, space_width: int, current_width: int, words_queue: list, prefix_on_current: bool) -> tuple:
    """Return (prefix, suffix) for the single break that minimizes total lines, or (None, None) if len(segments)<2.
    words_queue is list of (word, is_suffix); we use word part only for line-count simulation.
    When line counts tie, prefer the break that avoids a very short fragment (maximize min(prefix_len, suffix_len))."""
    if len(segments) < 2:
        return (None, None)
    rest_words = [item[0] for item in words_queue]
    best_k = None
    best_lines = float("inf")
    best_min_part = -1
    best_suffix_len = -1
    for k in range(1, len(segments)):
        prefix = "".join(segments[:k]) + "-"
        suffix = "".join(segments[k:])
        rest = [suffix] + rest_words
        prefix_fits = current_width + (space_width if prefix_on_current else 0) + _measure(draw, prefix, font) <= max_width
        if prefix_fits and prefix_on_current:
            total = 1 + _count_lines_no_hyphen(draw, rest, font, max_width, 0)
        else:
            total = (2 if prefix_on_current else 1) + _count_lines_no_hyphen(draw, rest, font, max_width, 0)
        min_part = min(len(prefix) - 1, len(suffix))
        if total < best_lines:
            best_lines = total
            best_k = k
            best_min_part = min_part
            best_suffix_len = len(suffix)
        elif total == best_lines:
            if min_part > best_min_part:
                best_k = k
                best_min_part = min_part
                best_suffix_len = len(suffix)
            elif min_part == best_min_part and len(suffix) > best_suffix_len:
                best_k = k
                best_suffix_len = len(suffix)
    if best_k is None:
        return (None, None)
    prefix = "".join(segments[:best_k]) + "-"
    suffix = "".join(segments[best_k:])
    return (prefix, suffix)


def _wrap_text(draw, text: str, font, max_width: int, strip_markdown_for_wrap: bool = False) -> list[str]:
    """Wrap text to fit within max_width pixels. Newline characters in the source force line breaks. At most one hyphen per word.
    If strip_markdown_for_wrap is True, use markdown-aware wrap so we never break inside **, __, *, _ spans."""
    all_lines = []
    for segment in text.split("\n"):
        segment = segment.strip()
        if not segment:
            all_lines.append("")
            continue
        if strip_markdown_for_wrap:
            all_lines.extend(_wrap_text_segment_markdown(draw, segment, font, max_width))
        else:
            all_lines.extend(_wrap_text_segment(draw, segment, font, max_width, strip_markdown_for_wrap=False))
    return all_lines


def _wrap_text_segment(draw, text: str, font, max_width: int, strip_markdown_for_wrap: bool = False) -> list[str]:
    """Wrap a single segment (no newlines) to fit max_width. At most one hyphen per word; break point chosen to minimize line count."""
    words_queue = [(w, False) for w in text.split()]
    lines = []
    current = []
    current_width = 0
    space_width = _measure(draw, " ", font) if words_queue else 0

    def measure_word(w: str) -> int:
        s = _strip_markdown(w) if strip_markdown_for_wrap else w
        return _measure(draw, s, font)

    def flush():
        nonlocal current, current_width
        if current:
            lines.append(" ".join(current))
            current = []
            current_width = 0

    def add_word(w, add_space_before=True):
        nonlocal current, current_width
        wd = measure_word(w)
        gap = (space_width if add_space_before and current else 0)
        if current_width + gap + wd <= max_width:
            current.append(w)
            current_width += gap + wd
            return True
        return False

    while words_queue:
        w, is_suffix = words_queue.pop(0)
        if add_word(w):
            continue
        segments = _hyphenate_word(w) if not is_suffix else []
        # At most one hyphen per word; choose break that minimizes number of lines
        if len(segments) >= 2 and current:
            prefix, suffix = _best_single_break(segments, draw, font, max_width, space_width, current_width, words_queue, prefix_on_current=True)
            if prefix is not None:
                current.append(prefix)
                flush()
                if suffix:
                    words_queue.insert(0, (suffix, True))
                continue
        flush()
        if add_word(w, add_space_before=False):
            continue
        if len(segments) >= 2:
            prefix, suffix = _best_single_break(segments, draw, font, max_width, space_width, 0, words_queue, prefix_on_current=False)
            if prefix is not None:
                lines.append(prefix)
                if suffix:
                    words_queue.insert(0, (suffix, True))
                continue
        # No hyphenation or single segment: one line or character-level break
        if not segments or len(segments) == 1:
            def measure_str(s: str) -> int:
                return _measure(draw, _strip_markdown(s) if strip_markdown_for_wrap else s, font)

            if measure_str(w) <= max_width:
                current = [w]
                current_width = measure_str(w)
            else:
                for i in range(len(w) - 1, 0, -1):
                    chunk = w[:i] + "-"
                    if measure_str(chunk) <= max_width:
                        lines.append(chunk)
                        current = [w[i:]]
                        current_width = measure_str(current[0])
                        break
                else:
                    current = [w]
                    current_width = measure_str(w)
    flush()
    return lines


def _draw_panel_text(image, quadrant_bounds: tuple, panel_content: dict, font, font_size: int, verbose: bool, style: dict = None, position: str = "bottom", h_align: str = "full", v_offset: int = 0, bottom_slot: int = 0, quadrant_rect: Optional[list] = None):
    """Draw text in one panel. panel_content: {text, is_dialogue}.
    quadrant_rect: optional [left, top, right, bottom] as fractions 0-1 of quadrant; when present, box is drawn in that rect.
    position/h_align/v_offset/bottom_slot: used only when quadrant_rect is not provided.
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
    box_inset = max(2, min(w, h) // 50)
    if len(text) > 180:
        font_size = max(9, int(font_size * 0.85))

    if quadrant_rect and len(quadrant_rect) >= 4:
        rl, rt, rr, rb = quadrant_rect[:4]
        box_x0 = x0 + int(rl * w)
        box_y0 = y0 + int(rt * h)
        box_x1 = x0 + int(rr * w)
        box_y1 = y0 + int(rb * h)
    else:
        # Text area: box wider (smaller inset), padding slightly larger inside
        if h_align == "left":
            box_x0 = x0 + box_inset
            box_x1 = x0 + int(w * 0.92)
        elif h_align == "right":
            box_x0 = x1 - int(w * 0.92)
            box_x1 = x1 - box_inset
        else:  # "full"
            box_x0 = x0 + box_inset
            box_x1 = x1 - box_inset
        box_w = box_x1 - box_x0
        padding_rect = max(3, pad // 2)
        text_inset = max(4, padding_rect)
        right_inset = text_inset + 18
        max_text_width = max(50, int((box_w - text_inset - right_inset) * 0.88))
        top_margin = 0 if (position == "top" and v_offset > 0) else pad
        if position == "top":
            box_y0 = y0 + top_margin + v_offset
            box_y1 = y0 + int(h * 0.40) + v_offset
        elif position == "middle":
            if bottom_slot == 1:
                box_y0 = y0 + int(h * 0.35) + v_offset
                box_y1 = y0 + int(h * 0.50) + v_offset
            elif bottom_slot == 2:
                box_y0 = y0 + int(h * 0.50) + v_offset
                box_y1 = y0 + int(h * 0.65) + v_offset
            else:
                box_y0 = y0 + int(h * 0.35) + v_offset
                box_y1 = y0 + int(h * 0.65) + v_offset
        else:
            bottom_edge_margin = max(pad, int(h * 0.07))
            bottom_limit = y1 - pad - bottom_edge_margin
            if bottom_slot == 1:
                box_y0 = y1 - int(h * 0.60) + v_offset
                box_y1 = min(y1 - int(h * 0.40) + v_offset, bottom_limit)
            elif bottom_slot == 2:
                box_y0 = y1 - int(h * 0.40) + v_offset
                box_y1 = min(y1 - pad + v_offset, bottom_limit)
            else:
                box_y0 = y1 - int(h * 0.40) + v_offset
                box_y1 = min(y1 - pad + v_offset, bottom_limit)

    box_w = box_x1 - box_x0
    box_h = box_y1 - box_y0
    padding_rect = max(3, pad // 2)
    text_inset = max(4, padding_rect)
    right_inset = text_inset + 18
    # For lettering rects use actual box width (lower minimum) so narrow dialogue boxes wrap correctly
    _min_wrap = 20 if (quadrant_rect and len(quadrant_rect) >= 4) else 50
    max_text_width = max(_min_wrap, int((box_w - text_inset - right_inset) * 0.88))

    if not text or not text.strip():
        return

    # When drawing in a specific rect, scale font to box height so text fits (match WYSIWYG editor, +20%)
    if quadrant_rect and len(quadrant_rect) >= 4:
        available_h = box_h - 2 * padding_rect
        # Use a readable minimum (12) and a less aggressive cap (//6) so narrative boxes don't look too small
        font_size = max(12, min(font_size, int((available_h // 6) * 1.2 * 1.1)))

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
    strip_md = (_MD_BOLD in text or _MD_UNDERLINE in text or _MD_ITALIC in text or "_" in text)
    lines = _wrap_text(draw, text, pil_font, int(max_text_width), strip_markdown_for_wrap=strip_md)
    max_lines = 8 if len(text) > 300 else 6
    if quadrant_rect and len(quadrant_rect) >= 4:
        max_lines = max(max_lines, 25)
    # If text still overflows, try a smaller font to fit more
    if len(lines) > max_lines:
        smaller_size = max(9, int(font_size * 0.80))
        try:
            smaller_font = ImageFont.truetype(pil_font.path, smaller_size)
        except Exception:
            smaller_font = pil_font
            smaller_size = font_size
        lines = _wrap_text(draw, text, smaller_font, int(max_text_width), strip_markdown_for_wrap=strip_md)
        if len(lines) <= max_lines + 2:
            pil_font = smaller_font
            font_size = smaller_size
        else:
            lines = _wrap_text(draw, text, pil_font, int(max_text_width), strip_markdown_for_wrap=strip_md)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1].rstrip()
        if len(lines[-1]) > 15:
            lines[-1] = lines[-1][: len(lines[-1]) - 3].rsplit(" ", 1)[0] + "…"

    # Line height from font (tight)
    line_height = int(font_size * 1.15)
    total_h = len(lines) * line_height
    if quadrant_rect and len(quadrant_rect) >= 4:
        # Fixed rect: anchor at top
        start_y = box_y0 + padding_rect
        available_h = box_y1 - start_y - padding_rect
        max_fit_lines = max(1, available_h // line_height)
        if len(lines) > max_fit_lines:
            # Try smaller font so all lines fit in the box instead of truncating
            def _load_font(size):
                try:
                    return ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", size)
                except (OSError, IOError):
                    try:
                        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size)
                    except (OSError, IOError):
                        return None
            fit_font = pil_font
            fit_size = font_size
            fit_lines = lines
            for try_size in range(font_size - 1, 7, -1):
                if try_size < 8:
                    break
                try_font = _load_font(try_size)
                if try_font is None:
                    continue
                try_lines = _wrap_text(draw, text, try_font, int(max_text_width), strip_markdown_for_wrap=strip_md)
                if len(try_lines) > max_lines:
                    try_lines = try_lines[:max_lines]
                    if try_lines and len(try_lines[-1]) > 15:
                        try_lines[-1] = try_lines[-1][: len(try_lines[-1]) - 3].rsplit(" ", 1)[0] + "…"
                try_lh = int(try_size * 1.15)
                try_fit = max(1, available_h // try_lh)
                if len(try_lines) <= try_fit:
                    fit_font = try_font
                    fit_size = try_size
                    fit_lines = try_lines
                    break
            pil_font = fit_font
            font_size = fit_size
            lines = fit_lines
            line_height = int(font_size * 1.15)
            max_fit_lines = max(1, available_h // line_height)
            if len(lines) > max_fit_lines:
                lines = lines[:max_fit_lines]
                if lines and len(lines[-1]) > 15:
                    lines[-1] = lines[-1][: len(lines[-1]) - 3].rsplit(" ", 1)[0] + "…"
        total_h = len(lines) * line_height
        # Pixel-aware fill: pick largest font such that n * natural_line_height <= available_h, then use that line height for spacing (consistent)
        n = len(lines)
        if n >= 1:
            fill_font_size = max(8, min(60 if not is_dialogue else 48, int((available_h / n) / 1.15)))
            available_w = max(1, box_w - text_inset - right_inset)
            fill_font = None
            try:
                fill_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", fill_font_size)
            except (OSError, IOError):
                try:
                    fill_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", fill_font_size)
                except (OSError, IOError):
                    pass
            if fill_font is not None:
                max_line_w = max(_measure(draw, line, fill_font) for line in lines)
                if max_line_w > available_w:
                    fill_font_size = max(font_size, min(fill_font_size, int(fill_font_size * available_w / max_line_w)))
                    try:
                        fill_font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", fill_font_size)
                    except (OSError, IOError):
                        try:
                            fill_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", fill_font_size)
                        except (OSError, IOError):
                            fill_font = None
                if fill_font is not None and fill_font_size >= font_size:
                    pil_font = fill_font
                    font_size = fill_font_size
                    line_height = int(font_size * 1.15)
                    total_h = n * line_height
        # #region agent log
        try:
            import time
            _unused = available_h - total_h
            _log = {"location": "overlay_storyboard_text.py:_draw_panel_text", "message": "lettering rect text fill", "data": {"box_h": box_h, "padding_rect": padding_rect, "available_h": available_h, "font_size": font_size, "line_height": line_height, "max_fit_lines": max_fit_lines, "num_lines": len(lines), "total_h": total_h, "unused_h": _unused, "is_dialogue": is_dialogue}, "timestamp": int(time.time() * 1000), "hypothesisId": "H1", "runId": "post-fix"}
            _f = open("/Users/heffrey/src/dev-jesus/.cursor/debug.log", "a")
            _f.write(__import__("json").dumps(_log) + "\n")
            _f.close()
        except Exception:
            pass
        # #endregion
    elif position == "top" or position == "middle":
        start_y = box_y0 + max(1, top_margin if position == "top" else padding_rect)
    else:
        start_y = box_y1 - total_h

    # Dialogue = speech bubble (light fill, dark text); narrative = caption box (dark fill, light text)
    if quadrant_rect and len(quadrant_rect) >= 4:
        # Respect exact rect from WYSIWYG editor (all four corners, including bottom)
        rect_left = box_x0
        rect_top = box_y0
        rect_right = box_x1
        rect_bottom = box_y1
    else:
        rect_top = max(box_y0, start_y - padding_rect)
        rect_bottom = min(box_y1, start_y + total_h + padding_rect)
        rect_left = box_x0
        rect_right = box_x1
    content_w = max(_measure(draw, line, pil_font) for line in lines) if lines else 0
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
    # Font cache for markdown (bold/italic); regular and underline use pil_font
    _font_cache = {None: pil_font, "underline": pil_font}

    for i, line in enumerate(lines):
        y = start_y + i * line_height
        tx = box_x0 + text_inset
        if not strip_md:
            draw.text((tx, y), line, font=pil_font, fill=text_color)
            continue
        segments = _parse_markdown_line(line)
        for seg_text, seg_style in segments:
            if not seg_text:
                continue
            seg_font = _font_cache.get(seg_style)
            if seg_font is None:
                seg_font = _load_panel_font(font_size, seg_style)
                _font_cache[seg_style] = seg_font
            draw.text((tx, y), seg_text, font=seg_font, fill=text_color)
            seg_w = _measure(draw, seg_text, seg_font)
            if seg_style == "underline":
                bbox = draw.textbbox((tx, y), seg_text, font=seg_font)
                ul_y = bbox[3] + 1
                draw.line([(tx, ul_y), (tx + seg_w, ul_y)], fill=text_color, width=max(1, font_size // 16))
            tx += seg_w


def _overlay_one_image(
    image_path: str,
    panel_contents: list[dict],
    output_path: str,
    verbose: bool,
    use_ocr: bool = True,
    style: dict = None,
    setting_label: str = None,
    avoid_faces: bool = False,
    lettering_rects: Optional[dict] = None,
) -> None:
    """Overlay up to 4 panel contents onto one storyboard image (2x2 grid).
    Each panel in panel_contents is {narrative, dialogue}.
    setting_label: optional location/setting text drawn at top of first panel.
    lettering_rects: optional {setting_rect: [l,t,r,b], panels: [{narrative_rect, dialogue_rect}, ...]} (0-1 fractions).
    When lettering_rects is provided, boxes are drawn at those positions instead of rule-based placement.
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

    # Face-aware placement: when avoid_faces and OpenCV available, detect faces and avoid top if overlap
    avoid_top = [False] * 4
    face_bboxes_per_panel = [[] for _ in range(4)]
    if avoid_faces and _CV2_AVAILABLE:
        for i, bounds in enumerate(quadrants):
            face_bboxes = _faces_in_quadrant(img, bounds)
            face_bboxes_per_panel[i] = face_bboxes
            avoid_top[i] = _top_region_overlaps_faces(bounds, face_bboxes, top_fraction=0.45)

    # Font size: scale down to match WYSIWYG editor scale and avoid truncated text in lettered images (+20%)
    font_size = max(9, min(14, half_h // 36))
    font_size = max(9, min(19, int(font_size * 1.2 * 1.1)))

    # Lettering rects from editor (0-1 fractions per quadrant)
    lrects = lettering_rects or {}
    setting_rect = lrects.get("setting_rect")
    panel_rects = (lrects.get("panels") or [{}] * 4)[:4]

    # Draw setting label first in its own caption-style box (bold) at top of first panel; reserve space below it
    setting_height = 0
    if setting_label and setting_label.strip():
        setting_height = _draw_setting_label(
            img, quadrants[0], setting_label.strip(), font_size, style=style, setting_rect=setting_rect
        )
        if verbose:
            print(f"      Setting: {setting_label.strip()[:50]}{'…' if len(setting_label) > 50 else ''}")

    empty = {"narrative": "", "dialogue": ""}
    contents = (panel_contents[:4] + [empty] * 4)[:4]
    for i, (bounds, content) in enumerate(zip(quadrants, contents)):
        prect = panel_rects[i] if i < len(panel_rects) else {}
        narrative = content.get("narrative", "")
        dialogue = content.get("dialogue", "")
        if verbose and (narrative or dialogue):
            for label, t in [("narrative", narrative), ("dialogue", dialogue)]:
                if t:
                    print(f"      Panel {i + 1} ({label}): {t[:50]}{'…' if len(t) > 50 else ''}")
        dialogue_rect = prect.get("dialogue_rect") if isinstance(prect.get("dialogue_rect"), (list, tuple)) and len(prect.get("dialogue_rect")) >= 4 else None
        narrative_rect = prect.get("narrative_rect") if isinstance(prect.get("narrative_rect"), (list, tuple)) and len(prect.get("narrative_rect")) >= 4 else None
        pos = "top" if i == 0 else "bottom"
        h_align = "left" if i == 1 else "full"
        v_off = 150 if i == 1 else 0
        panel0_offset = setting_height if i == 0 else 0
        narrative_pos = "bottom" if dialogue else ("bottom" if (i == 1 and narrative and avoid_faces) else ("top" if (i == 1 and narrative) else pos))
        narrative_v_off = v_off if (not dialogue and narrative_pos == "bottom" and i == 1) else 0
        if avoid_top[i]:
            dialogue_pos = "bottom"
            narrative_pos = "bottom"
            both_bottom = bool(dialogue and narrative)
        else:
            dialogue_pos = "top"
            both_bottom = False
        if dialogue:
            _draw_panel_text(
                img, bounds, {"text": dialogue, "is_dialogue": True}, None, font_size, verbose, style=style,
                position=dialogue_pos, h_align=h_align, v_offset=panel0_offset if dialogue_pos == "top" else 0,
                bottom_slot=1 if both_bottom else 0, quadrant_rect=dialogue_rect,
            )
        if narrative:
            first_panel_top_offset = panel0_offset if (i == 0 and narrative_pos == "top") else 0
            _draw_panel_text(
                img, bounds, {"text": narrative, "is_dialogue": False}, None, font_size, verbose, style=style,
                position=narrative_pos, h_align=h_align, v_offset=narrative_v_off + first_panel_top_offset,
                bottom_slot=2 if both_bottom else 0, quadrant_rect=narrative_rect,
            )

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
    parser.add_argument("--lettering-dir", default=None, help="Directory of per-image lettering JSON (e.g. stories/claude/lettering). When a scene-XXXX-Y.json exists for an image, use it instead of scene-derived content and optional rects for box positions.")
    parser.add_argument("--definitions-file", default=None, help="Path to definitions.json (optional; used for style.palette: box/text colors and lettering)")
    parser.add_argument("--output-dir", default=None, help="Where to write lettered images (default: same as --boards-dir)")
    parser.add_argument("--in-place", action="store_true", help="Overwrite original images instead of writing -lettered files")
    parser.add_argument("--no-ocr", action="store_true", help="Do not use OCR to cover existing text (default: use if pytesseract and Tesseract available)")
    parser.add_argument("--avoid-faces", action="store_true", help="Snap narrative/dialogue boxes to bottom when face detection finds faces in top of panel (requires opencv-python-headless)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print progress and panel text")
    parser.add_argument("--print-lettering", action="store_true", help="Print lettering JSON to stdout for one image (use with --for-image); no drawing.")
    parser.add_argument("--for-image", default=None, metavar="BASENAME", help="With --print-lettering: image basename (e.g. scene-0001-1.jpg) to output lettering for.")
    args = parser.parse_args()

    boards_dir = os.path.abspath(args.boards_dir)
    output_dir = os.path.abspath(args.output_dir or boards_dir)
    if args.in_place:
        output_dir = boards_dir
    lettering_dir = os.path.abspath(args.lettering_dir) if args.lettering_dir else None
    if lettering_dir and not os.path.isdir(lettering_dir):
        os.makedirs(lettering_dir, exist_ok=True)

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

    if args.print_lettering and args.for_image:
        want_base = os.path.basename(args.for_image).replace("-lettered", "")
        for sb_idx, img_path in image_list:
            base = os.path.basename(img_path)
            name = base.replace("-lettered", "") if "-lettered" in base else base
            name_no_ext, _ = os.path.splitext(name)
            want_no_ext, _ = os.path.splitext(want_base)
            if name_no_ext != want_no_ext:
                continue
            if sb_idx > len(storyboard_chunks):
                break
            chunk_title, chunk_text = storyboard_chunks[sb_idx - 1]
            all_items = _extract_scene_content_for_panels(chunk_text, max_panels=4)
            panel_texts = _merge_content_to_panels(all_items, num_panels=4)
            setting_label = _setting_label_from_chunk_title(chunk_title)
            default_setting_rect = [0.05, 0.025, 0.95, 0.075]
            default_dialogue_rect = [0.05, 0.1, 0.95, 0.4]
            default_narrative_rect = [0.05, 0.65, 0.95, 0.95]
            lettering_out = {
                "setting_label": setting_label or "",
                "setting_rect": default_setting_rect,
                "panels": [
                    {
                        "narrative": p.get("narrative", ""),
                        "dialogue": p.get("dialogue", ""),
                        "narrative_rect": default_narrative_rect,
                        "dialogue_rect": default_dialogue_rect,
                    }
                    for p in (panel_texts[:4] + [{"narrative": "", "dialogue": ""}] * 4)[:4]
                ],
            }
            print(json.dumps(lettering_out, indent=2))
            return 0
        print("{}")
        return 0

    for sb_idx, img_path in image_list:
        if sb_idx > len(storyboard_chunks):
            if args.verbose:
                print(f"  Skip {os.path.basename(img_path)} (no chunk for index {sb_idx})")
            continue
        chunk_title, chunk_text = storyboard_chunks[sb_idx - 1]
        all_items = _extract_scene_content_for_panels(chunk_text, max_panels=4)
        panel_texts = _merge_content_to_panels(all_items, num_panels=4)
        setting_label = _setting_label_from_chunk_title(chunk_title)
        lettering_rects = None

        default_setting_rect = [0.05, 0.025, 0.95, 0.075]
        default_dialogue_rect = [0.05, 0.1, 0.95, 0.4]
        default_narrative_rect = [0.05, 0.65, 0.95, 0.95]

        if lettering_dir:
            lettering_path = _lettering_json_path_for_image(img_path, lettering_dir)
            lettering_data = _load_lettering_json(lettering_path)
            if lettering_data:
                panel_texts = (lettering_data.get("panels", [])[:4] + [{"narrative": "", "dialogue": ""}] * 4)[:4]
                setting_label = (lettering_data.get("setting_label") or "").strip() or setting_label
                lettering_rects = {
                    "setting_rect": lettering_data.get("setting_rect"),
                    "panels": [
                        {"narrative_rect": p.get("narrative_rect"), "dialogue_rect": p.get("dialogue_rect")}
                        for p in lettering_data.get("panels", [])[:4]
                    ],
                }
            else:
                # Missing lettering file: write one from scene-derived content so the lettering folder is backfilled
                lettering_out = {
                    "setting_label": setting_label or "",
                    "setting_rect": default_setting_rect,
                    "panels": [
                        {
                            "narrative": p.get("narrative", ""),
                            "dialogue": p.get("dialogue", ""),
                            "narrative_rect": default_narrative_rect,
                            "dialogue_rect": default_dialogue_rect,
                        }
                        for p in (panel_texts[:4] + [{"narrative": "", "dialogue": ""}] * 4)[:4]
                    ],
                }
                os.makedirs(os.path.dirname(lettering_path) or ".", exist_ok=True)
                with open(lettering_path, "w", encoding="utf-8") as f:
                    json.dump(lettering_out, f, indent=2)
                if args.verbose:
                    print(f"      Wrote lettering {os.path.basename(lettering_path)}")

        if args.verbose:
            print(f"  {os.path.basename(img_path)} -> chunk {sb_idx}: {chunk_title}")

        base = os.path.basename(img_path)
        name, ext = os.path.splitext(base)
        if name.endswith("-lettered"):
            name = name[: -len("-lettered")]
        if args.in_place:
            out_path = os.path.join(output_dir, base)
        else:
            out_path = os.path.join(output_dir, f"{name}-lettered.jpg")
        _overlay_one_image(img_path, panel_texts, out_path, args.verbose, use_ocr=not args.no_ocr, style=style, setting_label=setting_label, avoid_faces=args.avoid_faces, lettering_rects=lettering_rects)

    if args.verbose:
        print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
