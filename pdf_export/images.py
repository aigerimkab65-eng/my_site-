"""Prepare product images for ReportLab (resize, convert, fail soft)."""

from __future__ import annotations

import io
from typing import Optional, Tuple

from pdf_export.config import IMAGE_MAX_SIDE

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None  # type: ignore


def prepare_image_for_pdf(
    data: bytes, mime: str = ""
) -> Optional[Tuple[bytes, str]]:
    """
    Return (jpeg_or_png_bytes, 'JPEG'|'PNG') suitable for ReportLab ImageReader,
    or None if the image cannot be decoded.
    """
    if not data or Image is None:
        return None
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except Exception:
        return None

    try:
        if img.mode in ("RGBA", "LA") or (
            img.mode == "P" and "transparency" in img.info
        ):
            rgba = img.convert("RGBA")
            background = Image.new("RGB", rgba.size, (245, 241, 234))  # milky
            background.paste(rgba, mask=rgba.split()[-1])
            img = background
            out_fmt = "JPEG"
        elif img.mode != "RGB":
            img = img.convert("RGB")
            out_fmt = "JPEG"
        else:
            out_fmt = "JPEG"

        w, h = img.size
        longest = max(w, h)
        if longest > IMAGE_MAX_SIDE:
            scale = IMAGE_MAX_SIDE / float(longest)
            img = img.resize(
                (max(1, int(w * scale)), max(1, int(h * scale))),
                Image.Resampling.LANCZOS,
            )

        buf = io.BytesIO()
        if out_fmt == "PNG":
            img.save(buf, format="PNG", optimize=True)
            return buf.getvalue(), "PNG"
        img.save(buf, format="JPEG", quality=82, optimize=True)
        return buf.getvalue(), "JPEG"
    except Exception:
        return None
