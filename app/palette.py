"""Programmatic palette extraction: hex + % coverage across all input images.

Pure code (Pillow quantization) — no LLM involved. The visual specialist
receives this as data and interprets it; palette is one signal among many.
"""

import base64
import io
import logging
from collections import defaultdict

from PIL import Image

from app.schemas import ImagePayload, PaletteColor

logger = logging.getLogger("trend_agent")

_THUMB = 200  # quantize on a thumbnail; palette accuracy doesn't need full res


def extract_palette(images: list[ImagePayload], colors: int = 6) -> list[PaletteColor]:
    """Aggregate dominant colors across images, weighted by pixel coverage."""
    counts: dict[str, int] = defaultdict(int)
    total = 0
    for img in images:
        try:
            pil = Image.open(io.BytesIO(base64.b64decode(img.data)))
            pil = pil.convert("RGB")
            pil.thumbnail((_THUMB, _THUMB))
            quantized = pil.quantize(colors=colors, method=Image.Quantize.FASTOCTREE)
            palette = quantized.getpalette()
            for count, index in quantized.getcolors(maxcolors=colors * 2) or []:
                r, g, b = palette[index * 3 : index * 3 + 3]
                counts[f"#{r:02x}{g:02x}{b:02x}"] += count
                total += count
        except Exception:
            logger.warning("palette extraction skipped an undecodable image", exc_info=True)
    if not total:
        return []
    top = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:colors]
    return [PaletteColor(hex=h, coverage_pct=round(100 * c / total, 1)) for h, c in top]


def palette_family(palette: list[PaletteColor]) -> str:
    """Coarse family of the dominant color — memory metadata, not analysis."""
    if not palette:
        return "unknown"
    h = palette[0].hex.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    mx, mn = max(r, g, b), min(r, g, b)
    if mx - mn < 24:
        return "neutral"
    import colorsys

    hue = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)[0] * 360
    for family, upper in (("red", 20), ("orange", 45), ("yellow", 70), ("green", 165), ("cyan", 200), ("blue", 255), ("purple", 290), ("pink", 335)):
        if hue <= upper:
            return family
    return "red"
