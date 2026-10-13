"""Build invoice (счёт-фактура) PDF from a CRM order."""

from __future__ import annotations

import io
import math
from datetime import datetime
from typing import Any, Dict
from xml.sax.saxutils import escape

from reportlab.lib.colors import HexColor
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Table, TableStyle

from pdf_export import config
from pdf_export.fonts import (
    FONT_BODY,
    FONT_BODY_BOLD,
    FONT_BODY_MED,
    FONT_DISPLAY,
    ensure_fonts,
)
from pdf_export.i18n import t_invoice
from pdf_export.money_words import amount_in_words, split_vat_from_gross


def invoice_number(order_id: str) -> str:
    return str(order_id or "")[:8].upper()


def format_order_date(ts, lang: str = "ru") -> str:
    try:
        value = float(ts)
    except (TypeError, ValueError):
        return "—"
    dt = datetime.fromtimestamp(value)
    return dt.strftime("%d.%m.%Y")


def format_money_cell(value, currency: str = "kzt") -> str:
    if value is None or value == "":
        return ""
    number = float(value)
    if number.is_integer():
        text = f"{int(number):,}".replace(",", " ")
    else:
        whole, frac = f"{number:.2f}".split(".")
        text = f"{int(whole):,}".replace(",", " ") + "," + frac
    code = (currency or "kzt").lower()
    if code == "usd":
        return f"$ {text}"
    if code == "rub":
        return f"{text} ₽"
    return f"{text} ₸"


def _hex(c: str):
    return HexColor(c)


def _wrap(c, text, font, size, max_w, max_lines=4):
    """Word-wrap a single line so drawString stays inside max_w."""
    text = " ".join(str(text or "").split())
    if not text or max_w <= 0 or max_lines <= 0:
        return []
    words = text.split(" ")
    lines = []
    current = ""

    def width(value):
        return c.stringWidth(value, font, size)

    def push(line):
        if len(lines) < max_lines:
            lines.append(line)
        return len(lines) >= max_lines

    for word in words:
        trial = (current + " " + word).strip()
        if current and width(trial) <= max_w:
            current = trial
            continue
        if current:
            if push(current):
                return lines
            current = ""
        if width(word) <= max_w:
            current = word
            continue
        chunk = ""
        for ch in word:
            if chunk and width(chunk + ch) > max_w:
                if push(chunk):
                    return lines
                chunk = ch
            else:
                chunk += ch
        current = chunk
    if current:
        push(current)
    return lines


def _para(text, font, size, align="LEFT"):
    align_map = {"LEFT": TA_LEFT, "CENTER": TA_CENTER, "RIGHT": TA_RIGHT}
    style = ParagraphStyle(
        "invCell",
        fontName=font,
        fontSize=size,
        leading=size + 1.8,
        alignment=align_map.get(align, TA_LEFT),
        textColor=_hex(config.GRAPHITE),
    )
    return Paragraph(escape(str(text or "")), style)


def build_invoice_pdf(order: Dict[str, Any], lang: str = "ru") -> bytes:
    ensure_fonts()
    lang = lang if lang in {"ru", "kz", "en"} else "ru"
    s = t_invoice(lang)
    # Raises SellerConfigError if required .env requisites are missing.
    seller = config.get_seller(require_complete=True)
    vat_rate = float(seller.get("vat_rate") or 0)
    number = invoice_number(order.get("id") or "")
    order_date = format_order_date(order.get("createdAt"), lang)
    currency = (order.get("currency") or "kzt").lower()
    if currency not in {"kzt", "usd", "rub"}:
        currency = "kzt"
    price = order.get("priceFrom")
    has_price = price is not None and price != ""
    if has_price:
        try:
            price = float(price)
        except (TypeError, ValueError):
            price = None
        if price is None or not math.isfinite(price) or price < 0:
            has_price = False
            price = None

    buf = io.BytesIO()
    page_w, page_h = A4
    c = canvas.Canvas(buf, pagesize=A4)
    c.setTitle(s["title"].format(number=number, date=order_date))
    c.setAuthor(seller.get("name") or config.BRAND_NAME)

    margin = config.PAGE_MARGIN
    y = page_h - margin

    # Background wash
    c.setFillColor(_hex(config.MILKY))
    c.rect(0, page_h - 90, page_w, 90, fill=1, stroke=0)

    # Logo
    logo = config.LOGO_PATH
    if logo.is_file():
        try:
            reader = ImageReader(str(logo))
            iw, ih = reader.getSize()
            scale = min(48 / iw, 42 / ih)
            lw, lh = iw * scale, ih * scale
            c.drawImage(reader, margin, y - lh, width=lw, height=lh, mask="auto")
        except Exception:
            pass

    c.setFillColor(_hex(config.GRAPHITE))
    c.setFont(FONT_DISPLAY, 18)
    title = s["title"].format(number=number, date=order_date)
    c.drawString(margin + 60, y - 22, title)
    y -= 56

    c.setStrokeColor(_hex(config.GOLD))
    c.setLineWidth(1)
    c.line(margin, y, page_w - margin, y)
    y -= 18

    c.setFont(FONT_BODY, 9)
    c.setFillColor(_hex(config.GRAY))
    c.drawString(margin, y, f"{s['turnover_date']}: {order_date}")
    y -= 22

    # Supplier / buyer blocks
    left_x = margin
    right_x = page_w / 2 + 8
    block_top = y

    half = page_w / 2 - margin - 16

    def draw_party(x, top, heading, lines):
        c.setFillColor(_hex(config.GOLD))
        c.setFont(FONT_BODY_BOLD, 10)
        c.drawString(x, top, heading)
        c.setFillColor(_hex(config.GRAPHITE))
        c.setFont(FONT_BODY, 8.5)
        yy = top - 14
        for line in lines:
            if not line:
                continue
            for part in _wrap(c, line, FONT_BODY, 8.5, half, 3):
                c.drawString(x, yy, part)
                yy -= 11
        return yy

    supplier_lines = [
        seller.get("name") or "",
        f"{s['bin']}: {seller.get('bin') or '—'}",
        f"{s['address']}: {seller.get('address') or '—'}",
        f"{s['bank']}: {seller.get('bank') or '—'}",
        f"{s['iik']}: {seller.get('iik') or '—'}",
        f"{s['bik']}: {seller.get('bik') or '—'}  ·  {s['kbe']}: {seller.get('kbe') or '—'}",
        f"{s['phone']}: {seller.get('phone') or '—'}",
        f"{s['telegram']}: {seller.get('telegram') or '—'}",
    ]
    buyer_name = (order.get("clientName") or "").strip() or "—"
    buyer_phone = (order.get("clientPhone") or "").strip() or "—"
    buyer_lines = [buyer_name, buyer_phone]

    y_left = draw_party(left_x, block_top, s["supplier"], supplier_lines)
    y_right = draw_party(right_x, block_top, s["buyer"], buyer_lines)
    y = min(y_left, y_right) - 16

    c.setFillColor(_hex(config.GRAPHITE))
    c.setFont(FONT_BODY, 9)
    c.drawString(margin, y, f"{s['payment_terms']}: {s['payment_cashless']}")
    y -= 18

    # Table
    service = (order.get("serviceName") or "").strip() or "—"
    qty = 1
    if has_price:
        net, vat, gross = split_vat_from_gross(price, vat_rate)
        if vat_rate <= 0:
            rate_label = s["no_vat"]
            vat_label = s["no_vat"]
            net_label = format_money_cell(gross, currency)
            gross_label = format_money_cell(gross, currency)
            price_label = format_money_cell(gross, currency)
        else:
            rate_label = f"{int(vat_rate) if float(vat_rate).is_integer() else vat_rate}%"
            vat_label = format_money_cell(vat, currency)
            net_label = format_money_cell(net, currency)
            gross_label = format_money_cell(gross, currency)
            # Unit price is excl. VAT, so price × qty matches "стоимость без НДС".
            price_label = format_money_cell(net, currency)
        total_net, total_vat, total_gross = net, vat, gross
    else:
        rate_label = s["no_vat"] if vat_rate <= 0 else f"{int(vat_rate)}%"
        vat_label = s["on_agreement"]
        net_label = s["on_agreement"]
        gross_label = s["on_agreement"]
        price_label = s["on_agreement"]
        total_net = total_vat = total_gross = None

    header = [
        s["col_n"],
        s["col_name"],
        s["col_unit"],
        s["col_qty"],
        s["col_price"],
        s["col_net"],
        s["col_vat_rate"],
        s["col_vat"],
        s["col_gross"],
    ]
    row = [
        "1",
        service,
        s["unit_service"],
        str(qty),
        price_label,
        net_label,
        rate_label,
        vat_label,
        gross_label,
    ]
    if has_price:
        total_row = [
            "",
            s["total"],
            "",
            "",
            "",
            format_money_cell(total_net, currency) if vat_rate > 0 else format_money_cell(total_gross, currency),
            "",
            s["no_vat"] if vat_rate <= 0 else format_money_cell(total_vat, currency),
            format_money_cell(total_gross, currency),
        ]
    else:
        total_row = ["", s["total"], "", "", "", s["on_agreement"], "", s["on_agreement"], s["on_agreement"]]

    def _cells(values, kind):
        out = []
        for index, value in enumerate(values):
            if kind == "header":
                font, size, align = FONT_BODY_BOLD, 6.5, "CENTER"
            elif kind == "total" and index == 1:
                font, size, align = FONT_BODY_BOLD, 8, "LEFT"
            elif index == 1:
                font, size, align = FONT_BODY, 7.5, "LEFT"
            else:
                font, size, align = FONT_BODY, 7, "CENTER"
            out.append(_para(value, font, size, align))
        return out

    # Widths sum to 522 pt; usable A4 width at 36 pt margins is ~523 pt.
    col_widths = [22, 120, 36, 32, 56, 68, 54, 60, 74]
    data = [
        _cells(header, "header"),
        _cells(row, "body"),
        _cells(total_row, "total"),
    ]
    table = Table(data, colWidths=col_widths, repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _hex(config.MILKY)),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("GRID", (0, 0), (-1, -1), 0.4, _hex(config.SANDY)),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 3),
                ("RIGHTPADDING", (0, 0), (-1, -1), 3),
                ("BACKGROUND", (0, -1), (-1, -1), HexColor("#faf7f2")),
            ]
        )
    )
    tw, th = table.wrap(page_w - 2 * margin, y - margin - 160)
    table.drawOn(c, margin, y - th)
    y = y - th - 18

    if has_price and total_gross is not None:
        try:
            words = amount_in_words(total_gross, lang, currency)
        except ValueError:
            words = format_money_cell(total_gross, currency)
        c.setFillColor(_hex(config.GRAPHITE))
        c.setFont(FONT_BODY_MED, 9)
        prefix = s["amount_words"].split("{words}")[0].rstrip()
        max_w = page_w - 2 * margin
        for line in _wrap(c, f"{prefix} {words}".strip(), FONT_BODY_MED, 9, max_w, 4):
            c.drawString(margin, y, line)
            y -= 12

    y -= 10
    c.setStrokeColor(_hex(config.GOLD))
    c.setLineWidth(0.6)
    c.line(margin, y, page_w - margin, y)
    y -= 28

    # Signatures
    c.setFillColor(_hex(config.GRAPHITE))
    c.setFont(FONT_BODY, 9)
    director = seller.get("director_fio") or "—"
    sig_w = (page_w - 2 * margin - 20) / 2
    left_sig = _wrap(c, f"{s['director']} ________ / {director}", FONT_BODY, 9, sig_w, 2)
    right_sig = _wrap(
        c, f"{s['accountant']} ________ / {s['accountant_na']}", FONT_BODY, 9, sig_w, 2
    )
    for index in range(max(len(left_sig), len(right_sig), 1)):
        if index < len(left_sig):
            c.drawString(margin, y, left_sig[index])
        if index < len(right_sig):
            c.drawString(margin + sig_w + 20, y, right_sig[index])
        y -= 13
    c.setFont(FONT_BODY_BOLD, 9)
    c.drawString(margin, y, s["stamp"])
    y -= 30

    # Footer note
    formed = datetime.now().strftime("%d.%m.%Y %H:%M")
    c.setFillColor(_hex(config.GRAY))
    c.setFont(FONT_BODY, 7.5)
    c.drawString(margin, margin / 2 + 4, s["generated"].format(date=formed))

    c.save()
    return buf.getvalue()
