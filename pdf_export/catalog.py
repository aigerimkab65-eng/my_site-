"""Build a branded PDF product catalog with ReportLab."""

from __future__ import annotations

import io
import math
from contextvars import ContextVar
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from reportlab.lib.colors import Color, HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

from pdf_export import config
from pdf_export.fonts import (
    FONT_BODY,
    FONT_BODY_BOLD,
    FONT_BODY_MED,
    FONT_DISPLAY,
    ensure_fonts,
)
from pdf_export.images import prepare_image_for_pdf

# Per-request image loader (safe under ThreadingHTTPServer).
_GetImage: ContextVar[Optional[Callable]] = ContextVar("pdf_get_image", default=None)

STRINGS = {
    "ru": {
        "catalog": "Каталог",
        "products": "Товары",
        "services": "Услуги",
        "on_request": "Цена по запросу",
        "empty": "Нет товаров",
        "page": "стр. {n} из {m}",
        "date_prefix": "от {date}",
        "contacts_line": "{tg}  ·  WhatsApp {wa}  ·  {site}",
    },
    "kz": {
        "catalog": "Каталог",
        "products": "Тауарлар",
        "services": "Қызметтер",
        "on_request": "Бағасы сұраныс бойынша",
        "empty": "Тауар жоқ",
        "page": "б. {n} / {m}",
        "date_prefix": "{date}",
        "contacts_line": "{tg}  ·  WhatsApp {wa}  ·  {site}",
    },
    "en": {
        "catalog": "Catalog",
        "products": "Products",
        "services": "Services",
        "on_request": "Price on request",
        "empty": "No products",
        "page": "p. {n} of {m}",
        "date_prefix": "{date}",
        "contacts_line": "{tg}  ·  WhatsApp {wa}  ·  {site}",
    },
}


def _t(lang: str) -> dict:
    return STRINGS[lang if lang in STRINGS else "ru"]


def _hex(c: str) -> Color:
    return HexColor(c)


def format_money(value, currency: str = "kzt") -> Optional[str]:
    if value == "" or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    if number.is_integer():
        int_part = f"{int(number):,}".replace(",", " ")
        frac = ""
    else:
        fixed = f"{number:.2f}"
        whole, dec = fixed.split(".")
        int_part = f"{int(whole):,}".replace(",", " ")
        frac = "," + dec
    code = (currency or "kzt").lower()
    if code == "usd":
        return f"$ {int_part}{frac}"
    if code == "rub":
        return f"{int_part}{frac} ₽"
    return f"{int_part}{frac} ₸"


def _ellipsis_fit(c: canvas.Canvas, text: str, font: str, size: float, max_w: float) -> str:
    ell = "…"
    if c.stringWidth(text, font, size) <= max_w:
        return text
    while text and c.stringWidth(text + ell, font, size) > max_w:
        text = text[:-1]
    return (text.rstrip(" .,;:") + ell) if text else ell


def _wrap_lines(
    c: canvas.Canvas, text: str, font: str, size: float, max_w: float, max_lines: int
) -> List[str]:
    text = (text or "").strip()
    if not text or max_lines <= 0:
        return []
    words = text.split()
    lines: List[str] = []
    current = ""
    for word in words:
        trial = (current + " " + word).strip()
        if c.stringWidth(trial, font, size) <= max_w:
            current = trial
            continue
        if current:
            lines.append(current)
            current = ""
            if len(lines) >= max_lines:
                # Remaining content → ellipsis on last line
                lines[-1] = _ellipsis_fit(c, lines[-1], font, size, max_w)
                return lines
        # Single word wider than column
        if c.stringWidth(word, font, size) > max_w:
            lines.append(_ellipsis_fit(c, word, font, size, max_w))
            current = ""
            if len(lines) >= max_lines:
                return lines
        else:
            current = word
    if current and len(lines) < max_lines:
        lines.append(current)
    elif current and lines:
        lines[-1] = _ellipsis_fit(c, lines[-1], font, size, max_w)
    return lines


def _product_image_reader(product: dict) -> Optional[ImageReader]:
    product_id = product.get("id") or ""
    getter = _GetImage.get()
    if not getter or not product_id:
        return None
    try:
        stored = getter(product_id)
    except Exception:
        return None
    if not stored:
        return None
    raw, mime = stored
    prepared = prepare_image_for_pdf(raw, mime or "")
    if not prepared:
        return None
    data, _fmt = prepared
    try:
        return ImageReader(io.BytesIO(data))
    except Exception:
        return None


def _draw_contain_image(
    c: canvas.Canvas,
    reader: ImageReader,
    x: float,
    y: float,
    box_w: float,
    box_h: float,
    bg: Color,
) -> None:
    """Draw image inside box preserving aspect ratio (letterbox on milky)."""
    c.setFillColor(bg)
    c.rect(x, y, box_w, box_h, fill=1, stroke=0)
    try:
        iw, ih = reader.getSize()
    except Exception:
        return
    if iw <= 0 or ih <= 0:
        return
    scale = min(box_w / iw, box_h / ih)
    dw, dh = iw * scale, ih * scale
    dx = x + (box_w - dw) / 2
    dy = y + (box_h - dh) / 2
    try:
        c.drawImage(reader, dx, dy, width=dw, height=dh, mask="auto")
    except Exception:
        pass


def _draw_placeholder(
    c: canvas.Canvas,
    x: float,
    y: float,
    box_w: float,
    box_h: float,
    letter: str,
) -> None:
    c.setFillColor(_hex(config.MILKY))
    c.rect(x, y, box_w, box_h, fill=1, stroke=0)
    c.setStrokeColor(_hex(config.SANDY))
    c.setLineWidth(0.6)
    c.rect(x + 1, y + 1, box_w - 2, box_h - 2, fill=0, stroke=1)
    ch = (letter or "?").strip()[:1].upper() or "?"
    c.setFillColor(_hex(config.GOLD))
    c.setFont(FONT_DISPLAY, 36)
    c.drawCentredString(x + box_w / 2, y + box_h / 2 - 12, ch)


def _footer(c: canvas.Canvas, page_w, page_h, page_no: int, page_total: int, lang: str) -> None:
    s = _t(lang)
    margin = config.PAGE_MARGIN
    y = margin / 2 + 4
    c.setStrokeColor(_hex(config.SANDY))
    c.setLineWidth(0.4)
    c.line(margin, margin - 2, page_w - margin, margin - 2)
    contact = s["contacts_line"].format(
        tg=config.TELEGRAM_HANDLE,
        wa=config.WHATSAPP_DISPLAY,
        site=config.SITE_URL.replace("https://", ""),
    )
    c.setFillColor(_hex(config.GRAY))
    c.setFont(FONT_BODY, 7.5)
    c.drawString(margin, y, contact)
    page_label = s["page"].format(n=page_no, m=page_total)
    c.drawRightString(page_w - margin, y, page_label)


def _cover(c: canvas.Canvas, page_w, page_h, lang: str, formed_at: datetime) -> None:
    s = _t(lang)
    c.setFillColor(_hex(config.MILKY))
    c.rect(0, 0, page_w, page_h, fill=1, stroke=0)

    c.setStrokeColor(_hex(config.GOLD))
    c.setLineWidth(1.2)
    mid_y = page_h * 0.52
    c.line(page_w * 0.25, mid_y, page_w * 0.75, mid_y)

    logo = config.LOGO_PATH
    if logo.is_file():
        try:
            reader = ImageReader(str(logo))
            iw, ih = reader.getSize()
            max_w, max_h = 90, 80
            scale = min(max_w / iw, max_h / ih)
            lw, lh = iw * scale, ih * scale
            c.drawImage(
                reader,
                page_w / 2 - lw / 2,
                page_h * 0.68 - lh / 2,
                width=lw,
                height=lh,
                mask="auto",
            )
        except Exception:
            pass

    c.setFillColor(_hex(config.GRAPHITE))
    c.setFont(FONT_DISPLAY, 42)
    c.drawCentredString(page_w / 2, page_h * 0.58, s["catalog"])

    c.setFont(FONT_BODY_MED, 11)
    c.setFillColor(_hex(config.GOLD))
    c.drawCentredString(page_w / 2, page_h * 0.48, config.BRAND_NAME)

    c.setFillColor(_hex(config.GRAY))
    c.setFont(FONT_BODY, 9)
    c.drawCentredString(page_w / 2, page_h * 0.44, config.BRAND_ROLE)

    date_str = formed_at.strftime("%d.%m.%Y")
    c.setFont(FONT_BODY, 9)
    c.drawCentredString(
        page_w / 2, page_h * 0.38, s["date_prefix"].format(date=date_str)
    )

    c.setFont(FONT_BODY, 8.5)
    lines = [
        f"Telegram {config.TELEGRAM_HANDLE}",
        f"WhatsApp {config.WHATSAPP_DISPLAY}",
        config.SITE_URL.replace("https://", ""),
    ]
    y = page_h * 0.22
    for line in lines:
        c.drawCentredString(page_w / 2, y, line)
        y -= 14


def _section_banner(c: canvas.Canvas, title: str, page_w, top: float) -> float:
    margin = config.PAGE_MARGIN
    c.setFillColor(_hex(config.GRAPHITE))
    c.setFont(FONT_DISPLAY, 18)
    c.drawString(margin, top - 6, title)
    c.setStrokeColor(_hex(config.GOLD))
    c.setLineWidth(0.8)
    c.line(margin, top - 14, page_w - margin, top - 14)
    return top - 28


def _draw_card(
    c: canvas.Canvas,
    product: dict,
    x: float,
    y: float,
    w: float,
    h: float,
    lang: str,
) -> None:
    s = _t(lang)
    pad = 8
    price_h = 18

    c.setFillColor(_hex(config.WHITE))
    c.setStrokeColor(Color(34 / 255, 34 / 255, 34 / 255, alpha=0.18))
    c.setLineWidth(0.7)
    c.roundRect(x, y, w, h, 8, fill=1, stroke=1)

    img_h = h * 0.48
    img_x, img_y = x + pad, y + h - pad - img_h
    img_w = w - 2 * pad

    reader = _product_image_reader(product)
    if reader:
        _draw_contain_image(c, reader, img_x, img_y, img_w, img_h, _hex(config.MILKY))
    else:
        name = product.get("name") or "?"
        _draw_placeholder(c, img_x, img_y, img_w, img_h, name)

    text_top = img_y - 10
    text_bottom = y + pad + price_h
    text_w = w - 2 * pad

    name = (product.get("name") or "").strip() or "—"
    name_lines = _wrap_lines(c, name, FONT_BODY_BOLD, 9.5, text_w, 2)
    c.setFillColor(_hex(config.GRAPHITE))
    c.setFont(FONT_BODY_BOLD, 9.5)
    ty = text_top
    for line in name_lines:
        if ty < text_bottom + 10:
            break
        c.drawString(x + pad, ty, line)
        ty -= 12

    desc = (product.get("description") or "").strip()
    if desc:
        # How many desc lines fit above the price
        avail = ty - text_bottom - 4
        max_desc = max(0, min(4, int(avail // 9.5)))
        if max_desc:
            desc_lines = _wrap_lines(c, desc, FONT_BODY, 7.5, text_w, max_desc)
            c.setFillColor(_hex(config.GRAY))
            c.setFont(FONT_BODY, 7.5)
            ty -= 2
            for line in desc_lines:
                if ty < text_bottom + 8:
                    break
                c.drawString(x + pad, ty, line)
                ty -= 9.5

    price = format_money(product.get("price"), product.get("currency") or "kzt")
    price_label = price if price else s["on_request"]
    c.setFillColor(_hex(config.GOLD))
    c.setFont(FONT_BODY_BOLD, 11 if price else 8.5)
    c.drawString(x + pad, y + pad + 4, _ellipsis_fit(c, price_label, FONT_BODY_BOLD, 11 if price else 8.5, text_w))


def _paginated_grids(
    items: Sequence[dict],
) -> List[Tuple[Optional[str], List[dict]]]:
    """
    Return list of (section_title_key or None, chunk_of_up_to_6).
    section_title_key is 'products' / 'services' when both kinds present,
    else None for unsectioned pages.
    """
    kinds = {(p.get("kind") or "product").lower() for p in items}
    split = "product" in kinds and "service" in kinds
    pages: List[Tuple[Optional[str], List[dict]]] = []
    if not split:
        for i in range(0, len(items), config.CARDS_PER_PAGE):
            pages.append((None, list(items[i : i + config.CARDS_PER_PAGE])))
        return pages

    products = [p for p in items if (p.get("kind") or "product").lower() == "product"]
    services = [p for p in items if (p.get("kind") or "product").lower() == "service"]
    for group, key in ((products, "products"), (services, "services")):
        if not group:
            continue
        for i in range(0, len(group), config.CARDS_PER_PAGE):
            pages.append((key, list(group[i : i + config.CARDS_PER_PAGE])))
    return pages


def build_catalog_pdf(
    products: Sequence[Dict[str, Any]],
    lang: str = "ru",
    *,
    get_image=None,
) -> bytes:
    """
    Render catalog PDF and return bytes.

    get_image: callable(product_id) -> (bytes, mime) | None
    """
    ensure_fonts()
    lang = lang if lang in STRINGS else "ru"
    formed_at = datetime.now()
    token = _GetImage.set(get_image)

    try:
        buf = io.BytesIO()
        page_w, page_h = A4
        c = canvas.Canvas(buf, pagesize=A4)
        c.setTitle(f"{_t(lang)['catalog']} — {config.BRAND_NAME}")
        c.setAuthor(config.BRAND_NAME)

        _cover(c, page_w, page_h, lang, formed_at)

        items = list(products)
        if not items:
            c.showPage()
            c.setFillColor(_hex(config.MILKY))
            c.rect(0, 0, page_w, page_h, fill=1, stroke=0)
            c.setFillColor(_hex(config.GRAPHITE))
            c.setFont(FONT_DISPLAY, 22)
            c.drawCentredString(page_w / 2, page_h / 2, _t(lang)["empty"])
            _footer(c, page_w, page_h, 1, 1, lang)
            c.save()
            return buf.getvalue()

        grids = _paginated_grids(items)
        content_pages = len(grids)
        for page_idx, (section_key, chunk) in enumerate(grids):
            c.showPage()
            c.setFillColor(_hex(config.WHITE))
            c.rect(0, 0, page_w, page_h, fill=1, stroke=0)

            margin = config.PAGE_MARGIN
            footer_space = 28
            top = page_h - margin
            if section_key:
                top = _section_banner(c, _t(lang)[section_key], page_w, top)

            gap_x, gap_y = 12, 12
            usable_w = page_w - 2 * margin
            usable_h = top - margin - footer_space
            card_w = (usable_w - gap_x) / config.COLS
            card_h = (usable_h - gap_y * (config.ROWS - 1)) / config.ROWS

            for i, product in enumerate(chunk):
                col = i % config.COLS
                row = i // config.COLS
                px = margin + col * (card_w + gap_x)
                py = top - (row + 1) * card_h - row * gap_y
                _draw_card(c, product, px, py, card_w, card_h, lang)

            _footer(c, page_w, page_h, page_idx + 1, content_pages, lang)

        c.save()
        return buf.getvalue()
    finally:
        _GetImage.reset(token)
