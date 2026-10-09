"""Register TTF fonts for ReportLab. Prefer brand fonts; fall back to Noto for Kazakh."""

from __future__ import annotations

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from pdf_export.config import FONTS_DIR

# Registered family names used in layouts
FONT_BODY = "AKBody"
FONT_BODY_MED = "AKBodyMed"
FONT_BODY_BOLD = "AKBodyBold"
FONT_DISPLAY = "AKDisplay"

_KZ_PROBE = "әғқңөұүһіӘҒҚҢӨҰҮҺІ"
_registered = False


def _font_has_chars(path, chars: str) -> bool:
    try:
        from fontTools.ttLib import TTFont as FTFont

        font = FTFont(str(path))
        cmap = {}
        for table in font["cmap"].tables:
            cmap.update(table.cmap)
        return all(ord(ch) in cmap for ch in chars)
    except Exception:
        # If fontTools is missing, assume brand fonts are complete (we ship verified TTFs).
        return True


def _register(name: str, path) -> bool:
    if not path.is_file() or path.stat().st_size < 1000:
        return False
    pdfmetrics.registerFont(TTFont(name, str(path)))
    return True


def ensure_fonts() -> None:
    """Idempotent font registration for PDF generation."""
    global _registered
    if _registered:
        return

    mont_r = FONTS_DIR / "Montserrat-Regular.ttf"
    mont_m = FONTS_DIR / "Montserrat-Medium.ttf"
    mont_b = FONTS_DIR / "Montserrat-Bold.ttf"
    display = FONTS_DIR / "CormorantGaramond-Bold.ttf"
    noto_r = FONTS_DIR / "NotoSans-Regular.ttf"
    noto_b = FONTS_DIR / "NotoSans-Bold.ttf"
    noto_serif = FONTS_DIR / "NotoSerif-Bold.ttf"

    use_noto_body = not (
        mont_r.is_file() and _font_has_chars(mont_r, _KZ_PROBE)
    )
    use_noto_display = not (
        display.is_file() and _font_has_chars(display, _KZ_PROBE)
    )

    if use_noto_body:
        if not _register(FONT_BODY, noto_r):
            raise RuntimeError("PDF fonts missing: NotoSans-Regular.ttf")
        _register(FONT_BODY_MED, noto_b) or _register(FONT_BODY_MED, noto_r)
        _register(FONT_BODY_BOLD, noto_b) or _register(FONT_BODY_BOLD, noto_r)
    else:
        if not _register(FONT_BODY, mont_r):
            raise RuntimeError("PDF fonts missing: Montserrat-Regular.ttf")
        _register(FONT_BODY_MED, mont_m) or _register(FONT_BODY_MED, mont_r)
        _register(FONT_BODY_BOLD, mont_b) or _register(FONT_BODY_BOLD, mont_r)

    if use_noto_display:
        if not _register(FONT_DISPLAY, noto_serif):
            if not _register(FONT_DISPLAY, noto_b):
                raise RuntimeError("PDF fonts missing: NotoSerif-Bold.ttf")
    else:
        if not _register(FONT_DISPLAY, display):
            raise RuntimeError("PDF fonts missing: CormorantGaramond-Bold.ttf")

    _registered = True
