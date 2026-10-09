from __future__ import annotations

import re

from ai.core.registry import ToolRegistry
from ai.core.types import ToolSpec

CONTACT_TG = "https://t.me/aigerim_aicreator"
CONTACT_WA = "https://wa.me/77007002132"
PORTFOLIO_TG = "https://t.me/portfolioaigerimkabayeva"

# Canonical ids — must match src/lib/prices.js and Services.jsx.
SERVICE_CATALOG = [
    {
        "id": "ai.photo",
        "name": {"ru": "AI-фотосессия", "kz": "AI-фотосессия", "en": "AI photoshoot"},
        "price_kzt": 25000,
        "keys": ("фотосесс", "фотосет", "photoshoot", "ai photo", "ai-фото", "ai фото"),
        "soft": ("фото", "photo", "съём", "съем"),
    },
    {
        "id": "ai.video",
        "name": {
            "ru": "Рекламный / трендовый AI-ролик",
            "kz": "Жарнамалық / трендті AI-ролик",
            "en": "Promotional / trend AI video",
        },
        "price_kzt": 45000,
        "keys": ("ролик", "видео", "video", "reels", "рекламн", "tiktok", "тикток"),
        "soft": (),
    },
    {
        "id": "ai.viz3d",
        "name": {"ru": "3D-визуализация", "kz": "3D-визуализация", "en": "3D visualization"},
        "price_kzt": 30000,
        "keys": ("3d", "3д", "рендер", "render", "3d-визуал", "3d визуал"),
        "soft": (),
    },
    {
        "id": "ai.anim",
        "name": {
            "ru": "AI-анимация / оживление фото",
            "kz": "AI-анимация / фотоны жандандыру",
            "en": "AI animation / photo liveliness",
        },
        "price_kzt": 15000,
        "keys": ("анимац", "ожив", "animat", "оживление"),
        "soft": (),
    },
    {
        "id": "ai.character",
        "name": {
            "ru": "AI-персонаж и креативная концепция",
            "kz": "AI-персонаж және креативті тұжырымдама",
            "en": "AI character and creative concept",
        },
        "price_kzt": 30000,
        "keys": ("персонаж", "character", "маскот", "mascot"),
        "soft": ("концепц", "concept"),
    },
    {
        "id": "design.carousel",
        "name": {
            "ru": "Карусель для социальных сетей",
            "kz": "Әлеуметтік желіге карусель",
            "en": "Social media carousel",
        },
        "price_kzt": 25000,
        "keys": ("карусел", "carousel"),
        "soft": (),
    },
    {
        "id": "design.card",
        "name": {"ru": "Карточка товара", "kz": "Тауар карточкасы", "en": "Product card"},
        "price_kzt": 10000,
        "keys": ("карточк товара", "карточка товара", "product card", "карточки товара"),
        "soft": ("карточк",),
    },
    {
        "id": "design.info",
        "name": {
            "ru": "Инфографика для товара",
            "kz": "Тауарға инфографика",
            "en": "Product infographic",
        },
        "price_kzt": 10000,
        "keys": ("инфограф", "infograph"),
        "soft": (),
    },
    {
        "id": "design.pack",
        "name": {
            "ru": "Комплект карточек товара",
            "kz": "Тауар карточкаларының жиынтығы",
            "en": "Product card set",
        },
        "price_kzt": 35000,
        "keys": ("комплект карточек", "набор карточек", "pack of cards", "product pack"),
        "soft": ("комплект", "набор"),
    },
]

# Old short ids from earlier AI catalog → canonical.
LEGACY_SERVICE_IDS = {
    "photo": "ai.photo",
    "video": "ai.video",
    "viz3d": "ai.viz3d",
    "anim": "ai.anim",
    "character": "ai.character",
    "carousel": "design.carousel",
    "card": "design.card",
    "info": "design.info",
    "pack": "design.pack",
}

SERVICE_PRICES_KZT = {item["id"]: item["price_kzt"] for item in SERVICE_CATALOG}


def normalize_service_id(service_id: str) -> str:
    sid = (service_id or "").strip().lower()
    if not sid:
        return ""
    return LEGACY_SERVICE_IDS.get(sid, sid)


def format_price_label(amount_kzt: int) -> str:
    return f"{amount_kzt:,}".replace(",", " ") + " ₸"


def contains_any(text, words):
    return any(word in text for word in words)


def contains_word(text, word):
    return re.search(r"(?<!\w)" + re.escape(word) + r"(?!\w)", text, flags=re.IGNORECASE) is not None


def contains_any_word(text, words):
    return any(contains_word(text, word) for word in words)


def score_service(text, service):
    score = 0
    for key in service["keys"]:
        if key in text:
            score += 3
    for key in service["soft"]:
        if key in text:
            score += 1
    sid = service["id"]
    if sid == "ai.photo" and contains_any(text, ("анимац", "ожив", "animat")):
        score -= 2
    if sid == "design.card" and contains_any(text, ("комплект", "набор", "инфограф", "pack")):
        score -= 2
    if sid == "design.pack" and "карточ" not in text and "product" not in text:
        score -= 1
    return score


def detect_service(text):
    best = None
    best_score = 0
    for service in SERVICE_CATALOG:
        score = score_service(text, service)
        if score > best_score:
            best = service
            best_score = score
    if best_score < 2:
        return None
    return best


def service_by_id(service_id: str):
    sid = normalize_service_id(service_id)
    if not sid:
        return None
    for service in SERVICE_CATALOG:
        if service["id"] == sid:
            return service
    return None


def format_service(service, lang: str = "ru") -> dict:
    lang = lang if lang in {"ru", "kz", "en"} else "ru"
    price_kzt = int(service["price_kzt"])
    return {
        "id": service["id"],
        "name": service["name"].get(lang) or service["name"]["ru"],
        "price_from": format_price_label(price_kzt),
        "price_kzt": price_kzt,
        "currency": "kzt",
        "names": service["name"],
    }


def list_services(lang: str = "ru") -> list[dict]:
    return [format_service(item, lang) for item in SERVICE_CATALOG]


def _handle_get_service_info(args: dict, context: dict):
    lang = (context.get("lang") or "ru").strip().lower()
    if lang not in {"ru", "kz", "en"}:
        lang = "ru"
    service_id = str(args.get("service_id") or args.get("serviceId") or "").strip()
    query = str(args.get("query") or "").strip()
    list_all = bool(args.get("list_all") or args.get("listAll"))

    if list_all and not service_id and not query:
        return {"ok": True, "services": list_services(lang)}

    matched = service_by_id(service_id) if service_id else None
    if matched is None and query:
        matched = detect_service(query.lower())
        if matched is None:
            for service in SERVICE_CATALOG:
                for label in service["name"].values():
                    if label.lower() in query.lower():
                        matched = service
                        break
                if matched:
                    break

    if matched is None:
        return {
            "ok": False,
            "error": "Service not found in public price list",
            "services": list_services(lang),
        }
    return {"ok": True, "service": format_service(matched, lang)}


def register_catalog_tools(registry: ToolRegistry):
    registry.register(
        ToolSpec(
            name="get_service_info",
            description=(
                "Look up Aigerim's public starting prices and service names. "
                "Use for any price/service question. "
                "Pass service_id, free-text query, or list_all=true for the full catalog."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "service_id": {
                        "type": "string",
                        "description": (
                            "Service id: ai.photo, ai.video, ai.viz3d, ai.anim, "
                            "ai.character, design.carousel, design.card, design.info, "
                            "design.pack (legacy short ids like photo/card also accepted)"
                        ),
                    },
                    "query": {
                        "type": "string",
                        "description": "Free-text description of the service the user asked about",
                    },
                    "list_all": {
                        "type": "boolean",
                        "description": "If true, return the full public catalog",
                    },
                },
            },
            handler=_handle_get_service_info,
        )
    )
