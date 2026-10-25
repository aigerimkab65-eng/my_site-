from __future__ import annotations

import hashlib
import re

from ai.core.registry import ToolRegistry
from ai.core.types import ToolSpec
from ai.tools.catalog import SERVICE_CATALOG, format_service, service_by_id


def _lead_idempotency_key(session_id: str, phone: str, service_id: str) -> str:
    """Stable key so repeated create_lead calls in one chat don't duplicate CRM rows."""
    digits = re.sub(r"\D+", "", phone or "")
    raw = f"{session_id}|{digits}|{service_id}".encode("utf-8")
    return "chat-" + hashlib.sha256(raw).hexdigest()[:32]


def _handle_create_lead(args: dict, context: dict):
    create_order = context.get("create_order")
    if create_order is None:
        return {"ok": False, "error": "Lead creation is unavailable"}

    client_name = str(args.get("client_name") or args.get("clientName") or "").strip()
    client_phone = str(args.get("client_phone") or args.get("clientPhone") or "").strip()
    message = str(args.get("message") or "").strip()
    service_name = str(args.get("service_name") or args.get("serviceName") or "").strip()
    service_id = str(args.get("service_id") or args.get("serviceId") or "").strip()
    lang = (context.get("lang") or "ru").strip().lower()
    if lang not in {"ru", "kz", "en"}:
        lang = "ru"

    if not client_name or not client_phone:
        return {
            "ok": False,
            "error": "client_name and client_phone are required to create a lead",
        }
    if not message and not service_name:
        message = "Заявка из AI-чата"

    matched = service_by_id(service_id) if service_id else None
    # If only a name was passed, try to resolve from catalog names.
    if matched is None and service_name:
        needle = service_name.lower()
        for service in SERVICE_CATALOG:
            labels = [str(v).lower() for v in service["name"].values()]
            if needle in labels or any(needle in label for label in labels):
                matched = service
                break

    session_id = str(context.get("session_id") or "")[:80]
    resolved_service_id = matched["id"] if matched else service_id
    payload = {
        "source": "chat",
        "clientName": client_name,
        "clientPhone": client_phone,
        "message": message,
        "serviceName": service_name or "Чат-консультант",
        "serviceId": service_id,
        "lang": lang,
        "visitorId": session_id,
        "pagePath": str(context.get("page_path") or "/"),
        "idempotencyKey": _lead_idempotency_key(
            session_id, client_phone, resolved_service_id
        ),
    }

    if matched:
        formatted = format_service(matched, lang)
        payload["serviceId"] = formatted["id"]
        payload["serviceName"] = service_name or formatted["name"]
        if formatted.get("price_kzt") is not None:
            payload["priceFrom"] = formatted["price_kzt"]
            payload["currency"] = "kzt"

    try:
        order = create_order(payload)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception:
        return {"ok": False, "error": "Failed to create lead"}

    return {
        "ok": True,
        "orderId": order.get("id") if isinstance(order, dict) else None,
        "message": "Lead created successfully",
    }


def register_lead_tools(registry: ToolRegistry, *, create_order=None):
    # create_order is also available via runtime context; kept for bootstrap wiring clarity.
    _ = create_order
    registry.register(
        ToolSpec(
            name="create_lead",
            description=(
                "Create a CRM lead when the user wants to leave a request and has shared "
                "a name and phone number. Do not invent contacts."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "client_name": {
                        "type": "string",
                        "description": "Client name as provided by the user",
                    },
                    "client_phone": {
                        "type": "string",
                        "description": "Phone number as provided by the user",
                    },
                    "message": {
                        "type": "string",
                        "description": "Short summary of the request / brief",
                    },
                    "service_name": {
                        "type": "string",
                        "description": "Matched service name if known",
                    },
                    "service_id": {
                        "type": "string",
                        "description": (
                            "Matched service id if known "
                            "(ai.photo, design.card, …; legacy photo/card ok)"
                        ),
                    },
                },
                "required": ["client_name", "client_phone"],
            },
            handler=_handle_create_lead,
        )
    )
