"""Attachment parsing for the AI core (stdlib only).

Turns raw uploaded bytes into structured text/vision parts that features
can pass to the LLM or local fallback.
"""

from __future__ import annotations

import base64
import html
import json
import re
import zipfile
import zlib
from dataclasses import dataclass, field
from io import BytesIO
from xml.etree import ElementTree as ET

VISION_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}
TEXT_MIME_TYPES = {
    "text/plain",
    "text/markdown",
    "text/csv",
    "text/html",
    "text/css",
    "text/javascript",
    "application/json",
    "application/xml",
    "text/xml",
    "application/javascript",
    "application/x-javascript",
    "application/rtf",
    "text/rtf",
}

MAX_EXTRACT_CHARS = 8000
MAX_NOTE_CHARS = 7000


@dataclass
class ParsedAttachment:
    name: str
    mime: str
    size: int
    kind: str  # image | text | document | archive | binary
    text: str = ""
    vision_mime: str = ""
    vision_data: bytes = field(default_factory=bytes, repr=False)
    meta: dict = field(default_factory=dict)

    @property
    def has_vision(self) -> bool:
        return bool(self.vision_mime and self.vision_data)

    @property
    def has_text(self) -> bool:
        return bool((self.text or "").strip())


def _clean_text(value: str, limit: int = MAX_EXTRACT_CHARS) -> str:
    text = html.unescape(value or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit]


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8", "utf-16", "utf-16-le", "cp1251", "latin-1"):
        try:
            return _clean_text(data.decode(encoding))
        except UnicodeDecodeError:
            continue
    return _clean_text(data.decode("utf-8", errors="ignore"))


def _strip_html(data: bytes) -> str:
    text = _decode_text(data)
    text = re.sub(r"(?is)<script[^>]*>.*?</script>", " ", text)
    text = re.sub(r"(?is)<style[^>]*>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return _clean_text(text)


def _strip_rtf(data: bytes) -> str:
    text = _decode_text(data)
    text = re.sub(r"\\'[0-9a-fA-F]{2}", " ", text)
    text = re.sub(r"\\[a-zA-Z]+-?\d* ?", " ", text)
    text = text.replace("{", " ").replace("}", " ")
    return _clean_text(text)


def _sniff_kind(name: str, mime: str, data: bytes) -> tuple[str, str]:
    """Return (kind_hint, normalized_mime) from magic bytes + extension."""
    lower = (name or "").lower()
    mime = (mime or "").lower().strip() or "application/octet-stream"
    head = data[:16]

    if head.startswith(b"%PDF"):
        return "document", "application/pdf"
    if head.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image", "image/png"
    if head.startswith(b"\xff\xd8\xff"):
        return "image", "image/jpeg"
    if head.startswith(b"GIF87a") or head.startswith(b"GIF89a"):
        return "image", "image/gif"
    if len(data) >= 12 and head.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image", "image/webp"
    if head.startswith(b"PK\x03\x04") or head.startswith(b"PK\x05\x06"):
        if lower.endswith(".docx"):
            return (
                "document",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        if lower.endswith(".xlsx"):
            return (
                "document",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        if lower.endswith(".pptx"):
            return (
                "document",
                "application/vnd.openxmlformats-officedocument.presentationml.presentation",
            )
        return "archive", "application/zip"

    if mime in VISION_IMAGE_TYPES or mime.startswith("image/"):
        return "image", mime
    if mime in TEXT_MIME_TYPES or lower.endswith(
        (".txt", ".md", ".csv", ".json", ".html", ".htm", ".xml", ".log", ".rtf", ".css", ".js")
    ):
        return "text", mime
    if mime == "application/pdf" or lower.endswith(".pdf"):
        return "document", "application/pdf"
    if lower.endswith((".docx", ".xlsx", ".pptx")):
        return "document", mime
    if mime in {"application/zip", "application/x-zip-compressed"} or lower.endswith(".zip"):
        return "archive", "application/zip"
    return "binary", mime


def _extract_pdf_text(data: bytes) -> str:
    chunks: list[str] = []

    def absorb_bytes(raw: bytes):
        for match in re.finditer(rb"\((?:\\.|[^\\()])*\)\s*Tj", raw):
            literal = match.group(0)
            literal = re.sub(rb"\s*Tj$", b"", literal)
            if literal.startswith(b"(") and literal.endswith(b")"):
                literal = literal[1:-1]
            try:
                text = literal.decode("latin-1", errors="ignore")
            except Exception:
                continue
            text = text.replace("\\n", " ").replace("\\r", " ").replace("\\t", " ")
            text = re.sub(r"\\([\\()])", r"\1", text)
            text = re.sub(r"\\[0-7]{1,3}", " ", text)
            if text.strip():
                chunks.append(text)
        for match in re.finditer(rb"\[(.*?)\]\s*TJ", raw, re.S):
            part = match.group(1)
            for lit in re.findall(rb"\((?:\\.|[^\\()])*\)", part):
                try:
                    text = lit[1:-1].decode("latin-1", errors="ignore")
                except Exception:
                    continue
                text = re.sub(r"\\([\\()])", r"\1", text)
                if text.strip():
                    chunks.append(text)
        ascii_parts = re.findall(rb"[\x20-\x7E\xC0-\xFF]{5,}", raw)
        if ascii_parts and len(chunks) < 3:
            joined = b" ".join(ascii_parts[:120]).decode("latin-1", errors="ignore")
            chunks.append(joined)

    absorb_bytes(data)

    for match in re.finditer(rb"stream\r?\n(.+?)\r?\nendstream", data, re.S):
        stream = match.group(1)
        if stream.startswith(b"\r\n"):
            stream = stream[2:]
        elif stream.startswith(b"\n"):
            stream = stream[1:]
        decoded = None
        for wbits in (zlib.MAX_WBITS, -zlib.MAX_WBITS):
            try:
                decoded = zlib.decompress(stream, wbits)
                break
            except Exception:
                continue
        if decoded:
            absorb_bytes(decoded)

    return _clean_text(" ".join(chunks))


def _xml_texts(xml_bytes: bytes, local_names: set[str]) -> str:
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError:
        return _clean_text(re.sub(rb"<[^>]+>", b" ", xml_bytes).decode("utf-8", errors="ignore"))
    parts: list[str] = []
    for node in root.iter():
        tag = node.tag.rsplit("}", 1)[-1]
        if tag in local_names and node.text:
            parts.append(node.text)
    return _clean_text(" ".join(parts))


def _extract_docx_text(data: bytes) -> str:
    try:
        with zipfile.ZipFile(BytesIO(data)) as zf:
            names = set(zf.namelist())
            pieces = []
            if "word/document.xml" in names:
                pieces.append(_xml_texts(zf.read("word/document.xml"), {"t"}))
            for extra in ("word/header1.xml", "word/footer1.xml"):
                if extra in names:
                    pieces.append(_xml_texts(zf.read(extra), {"t"}))
            return _clean_text(" ".join(p for p in pieces if p))
    except (zipfile.BadZipFile, KeyError, OSError):
        return ""


def _extract_xlsx_text(data: bytes) -> str:
    try:
        with zipfile.ZipFile(BytesIO(data)) as zf:
            shared = ""
            if "xl/sharedStrings.xml" in zf.namelist():
                shared = _xml_texts(zf.read("xl/sharedStrings.xml"), {"t"})
            sheet_bits = []
            for name in zf.namelist():
                if name.startswith("xl/worksheets/sheet") and name.endswith(".xml"):
                    sheet_bits.append(_xml_texts(zf.read(name), {"v", "t"}))
            return _clean_text(" ".join([shared] + sheet_bits))
    except (zipfile.BadZipFile, KeyError, OSError):
        return ""


def _extract_pptx_text(data: bytes) -> str:
    try:
        with zipfile.ZipFile(BytesIO(data)) as zf:
            pieces = []
            for name in sorted(zf.namelist()):
                if name.startswith("ppt/slides/slide") and name.endswith(".xml"):
                    pieces.append(_xml_texts(zf.read(name), {"t"}))
            return _clean_text(" ".join(pieces))
    except (zipfile.BadZipFile, KeyError, OSError):
        return ""


def _extract_zip_listing(data: bytes) -> str:
    try:
        with zipfile.ZipFile(BytesIO(data)) as zf:
            names = zf.namelist()[:40]
            listing = ", ".join(names)
            nested = []
            for name in names[:12]:
                lower = name.lower()
                if lower.endswith((".txt", ".md", ".csv", ".json", ".xml", ".html", ".log")):
                    try:
                        info = zf.getinfo(name)
                        if info.file_size > 400_000:
                            continue
                        nested.append(f"{name}: {_decode_text(zf.read(name))[:1200]}")
                    except Exception:
                        continue
            body = listing
            if nested:
                body += " | " + " || ".join(nested)
            return _clean_text(body, MAX_EXTRACT_CHARS)
    except (zipfile.BadZipFile, OSError):
        return ""


def _binary_snippets(data: bytes) -> str:
    ascii_parts = re.findall(rb"[\x20-\x7E]{6,}", data)
    chunks = [part.decode("ascii", errors="ignore") for part in ascii_parts[:250]]
    ascii_text = _clean_text(" ".join(chunks), 4000)
    utf_text = data.decode("utf-8", errors="ignore")
    utf_text = re.sub(r"\s+", " ", utf_text)
    utf_text = re.sub(
        r"[^\w\s.,:;!?\-–—()/«»\"'%№#@&+а-яА-ЯёЁәіңғүұқөһӘІҢҒҮҰҚӨҺ]", " ", utf_text
    )
    utf_text = _clean_text(utf_text, 4000)
    if len(utf_text) >= len(ascii_text):
        return utf_text if len(utf_text) > 40 else ""
    return ascii_text if len(ascii_text) > 40 else ""


def parse_attachment(name: str, mime: str, data: bytes) -> ParsedAttachment:
    data = data or b""
    kind, norm_mime = _sniff_kind(name, mime, data)
    parsed = ParsedAttachment(
        name=name or "file",
        mime=norm_mime,
        size=len(data),
        kind=kind,
    )
    lower = (name or "").lower()

    if kind == "image" and norm_mime in VISION_IMAGE_TYPES:
        parsed.vision_mime = norm_mime
        parsed.vision_data = data
        parsed.meta["vision"] = True
        return parsed

    if kind == "image":
        parsed.kind = "binary"
        parsed.text = _binary_snippets(data)
        parsed.meta["original_mime"] = mime
        return parsed

    if lower.endswith(".json") or norm_mime == "application/json":
        try:
            obj = json.loads(_decode_text(data))
            parsed.text = _clean_text(json.dumps(obj, ensure_ascii=False))
        except Exception:
            parsed.text = _decode_text(data)
        parsed.kind = "text"
        return parsed

    if lower.endswith((".html", ".htm")) or norm_mime == "text/html":
        parsed.text = _strip_html(data)
        parsed.kind = "text"
        return parsed

    if lower.endswith(".rtf") or norm_mime in {"application/rtf", "text/rtf"}:
        parsed.text = _strip_rtf(data)
        parsed.kind = "text"
        return parsed

    if kind == "text" or norm_mime in TEXT_MIME_TYPES or lower.endswith(
        (".txt", ".md", ".csv", ".log", ".xml", ".css", ".js")
    ):
        parsed.text = _decode_text(data)
        parsed.kind = "text"
        return parsed

    if norm_mime == "application/pdf" or lower.endswith(".pdf"):
        parsed.text = _extract_pdf_text(data)
        parsed.kind = "document"
        parsed.meta["format"] = "pdf"
        return parsed

    if lower.endswith(".docx") or "wordprocessingml" in norm_mime:
        parsed.text = _extract_docx_text(data)
        parsed.kind = "document"
        parsed.meta["format"] = "docx"
        return parsed

    if lower.endswith(".xlsx") or "spreadsheetml" in norm_mime:
        parsed.text = _extract_xlsx_text(data)
        parsed.kind = "document"
        parsed.meta["format"] = "xlsx"
        return parsed

    if lower.endswith(".pptx") or "presentationml" in norm_mime:
        parsed.text = _extract_pptx_text(data)
        parsed.kind = "document"
        parsed.meta["format"] = "pptx"
        return parsed

    if kind == "archive" or lower.endswith(".zip"):
        parsed.text = _extract_zip_listing(data)
        parsed.kind = "archive"
        parsed.meta["format"] = "zip"
        return parsed

    parsed.text = _binary_snippets(data)
    parsed.kind = "binary"
    return parsed


def parse_attachments(attachments: list[dict]) -> list[ParsedAttachment]:
    parsed = []
    for item in attachments or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "file")
        mime = str(item.get("type") or "application/octet-stream")
        data = item.get("data") or b""
        if isinstance(data, str):
            value = data
            if "," in value and value.lower().startswith("data:"):
                value = value.split(",", 1)[1]
            try:
                data = base64.b64decode(re.sub(r"\s+", "", value), validate=False)
            except Exception:
                data = b""
        if not isinstance(data, (bytes, bytearray)):
            data = b""
        parsed.append(parse_attachment(name, mime, bytes(data)))
    return parsed


def format_parsed_note(item: ParsedAttachment) -> str:
    size_kb = max(1, round(item.size / 1024)) if item.size else 0
    header = f"«{item.name}» ({item.mime}, ~{size_kb} КБ, тип: {item.kind})"
    if item.has_vision:
        return f"Изображение {header}. Содержимое передано модели как картинка."
    if item.has_text:
        return f"Файл {header}. Извлечённое содержимое:\n{item.text[:MAX_NOTE_CHARS]}"
    return (
        f"Файл {header} получен. Текст извлечь не удалось "
        "(бинарный/защищённый формат) — опирайся на имя файла и запрос пользователя."
    )


def build_multimodal_user_content(
    user_text: str,
    attachments: list[dict],
    *,
    include_image_data: bool = True,
):
    """Build OpenAI user content + parsed attachments for a feature."""
    parsed = parse_attachments(attachments)
    names = [item.name for item in parsed]
    notes = [format_parsed_note(item) for item in parsed]

    text = (user_text or "").strip()
    if notes:
        block = "\n\n".join(notes)
        text = (text + "\n\n" if text else "") + "Вложения пользователя:\n" + block
    if not text:
        text = "Пользователь прикрепил файл(ы). Изучи содержимое и ответь уверенно."

    image_parts = []
    if include_image_data:
        for item in parsed:
            if not item.has_vision:
                continue
            b64 = base64.b64encode(item.vision_data).decode("ascii")
            image_parts.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{item.vision_mime};base64,{b64}"},
                }
            )
    else:
        for item in parsed:
            if item.has_vision:
                image_parts.append({"type": "image_url", "image_url": {"url": ""}})

    if image_parts:
        content = [{"type": "text", "text": text[:MAX_NOTE_CHARS]}] + image_parts
    else:
        content = text[:MAX_NOTE_CHARS]
    return content, names, parsed
