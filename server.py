#!/usr/bin/env python3
"""Сайт и админка. Все CRM-данные — PostgreSQL через crm_store."""

import base64
import cgi
import gzip
import hashlib
import hmac
import json
import math
import mimetypes
import os
import re
import secrets
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from ai.bootstrap import get_engine, init as init_ai
from ai.core.files import is_allowed_chat_attachment
from ai.features.consultant.attachments import build_openai_messages
from ai.tools.catalog import (
    SERVICE_PRICES_KZT,
    normalize_service_id,
    service_by_id,
)
import bcrypt

from crm_store import (
    ADMIN_SESSION_TTL_SEC,
    BACKUPS_DIR,
    DATA,
    DB_LOCK,
    DB_WRITE_LOCK,
    IMAGE_EXT,
    ROOT,
    UPLOADS,
    IntegrityError,
    create_admin_session,
    database_label,
    db_connect,
    delete_admin_session,
    delete_all_admin_sessions,
    ensure_order_columns,
    get_admin_password_hash_from_db,
    get_admin_session,
    get_product_image_bytes,
    init_crm_db,
    prune_expired_admin_sessions,
    product_id_from_image_url,
    product_price_to_db,
    set_admin_password_hash,
)

_BACKUP_TABLES = (
    "orders",
    "clients",
    "products",
    "settings",
    "order_idempotency",
    "admin_sessions",
)

mimetypes.add_type("font/woff2", ".woff2")

DIST = ROOT / "dist"
MAX_IMAGE = 8 * 1024 * 1024
CHAT_RATE = {}
CHAT_RATE_LOCK = threading.Lock()
CHAT_RATE_LIMIT = 30
CHAT_RATE_WINDOW = 600
CHAT_MAX_MESSAGES = 12
CHAT_MAX_CHARS = 800
CHAT_MAX_ATTACHMENTS = 3
CHAT_MAX_FILE_BYTES = 4 * 1024 * 1024
CHAT_MAX_REQUEST_BYTES = 18 * 1024 * 1024
CHAT_I18N = {
    "ru": {
        "rateLimit": "Слишком много запросов. Подождите немного.",
        "needSession": "Нужна сессия чата",
        "needMessage": "Напишите сообщение или прикрепите файл",
        "unavailable": "Сервис временно недоступен. Попробуйте позже.",
    },
    "en": {
        "rateLimit": "Too many requests. Please wait a moment.",
        "needSession": "Chat session is required",
        "needMessage": "Write a message or attach a file",
        "unavailable": "Service is temporarily unavailable. Please try again later.",
    },
    "kz": {
        "rateLimit": "Сұраныс тым көп. Біраз күтіңіз.",
        "needSession": "Чат сессиясы қажет",
        "needMessage": "Хабарлама жазыңыз немесе файл тіркеңіз",
        "unavailable": "Сервис уақытша қолжетімсіз. Кейінірек қайталап көріңіз.",
    },
}
ORDER_SOURCES = {"service", "custom", "chat", "contact", "shop"}
ORDER_STATUSES = {"new", "in_progress", "done", "cancelled"}
# Soft anti-dupe window when the same person resubmits the same service quickly
# (network retry without key, or AI calling create_lead twice).
ORDER_DEDUPE_WINDOW_SEC = 120
# Per-thread flag set by create_order: True if a new row was inserted.
_CREATE_ORDER_META = threading.local()
ORDER_RATE = {}
ORDER_RATE_LOCK = threading.Lock()
ORDER_RATE_LIMIT = 40
ORDER_RATE_WINDOW = 600
LOGIN_RATE = {}
LOGIN_RATE_LOCK = threading.Lock()
LOGIN_RATE_LIMIT = 20
LOGIN_RATE_WINDOW = 600


def load_env():
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


# Cached bcrypt hash only — never keep the plaintext password in memory after boot.
_ADMIN_PASSWORD_HASH = None


def hash_admin_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode(
        "ascii"
    )


def verify_admin_password(plain: str, password_hash: str) -> bool:
    if not plain or not password_hash:
        return False
    try:
        return bcrypt.checkpw(
            plain.encode("utf-8"),
            password_hash.encode("ascii"),
        )
    except (ValueError, TypeError):
        return False


def ensure_admin_credentials():
    """
    Require ADMIN_PASSWORD or ADMIN_PASSWORD_HASH in .env. Store only bcrypt hash
    in PostgreSQL. Never auto-generate credentials. Never log the password.
    """
    global _ADMIN_PASSWORD_HASH
    load_env()
    env_hash = os.environ.get("ADMIN_PASSWORD_HASH", "").strip()
    env_pass = os.environ.get("ADMIN_PASSWORD", "").strip()
    if not env_hash and not env_pass:
        raise SystemExit(
            "FATAL: set ADMIN_PASSWORD or ADMIN_PASSWORD_HASH in .env "
            "(admin credentials are required; auto-generation was removed)."
        )

    db_hash = get_admin_password_hash_from_db()

    if env_hash:
        if not env_hash.startswith("$2"):
            raise SystemExit(
                "FATAL: ADMIN_PASSWORD_HASH must be a bcrypt hash "
                "(starts with $2a$ / $2b$ / $2y$)."
            )
        if db_hash != env_hash:
            set_admin_password_hash(env_hash)
            if db_hash:
                delete_all_admin_sessions()
                print(
                    "[auth] admin password hash updated from env; all sessions cleared.",
                    file=sys.stderr,
                )
        _ADMIN_PASSWORD_HASH = env_hash
        return {"password_hash": env_hash}

    # ADMIN_PASSWORD provided (plaintext only for bootstrap / verify — not stored).
    if db_hash and verify_admin_password(env_pass, db_hash):
        _ADMIN_PASSWORD_HASH = db_hash
        return {"password_hash": db_hash}

    new_hash = hash_admin_password(env_pass)
    set_admin_password_hash(new_hash)
    if db_hash:
        delete_all_admin_sessions()
        print(
            "[auth] admin password changed; all sessions cleared.",
            file=sys.stderr,
        )
    else:
        print(
            "[auth] admin password hash stored in PostgreSQL settings.",
            file=sys.stderr,
        )
    _ADMIN_PASSWORD_HASH = new_hash
    return {"password_hash": new_hash}


def load_config():
    """Return {password_hash}. Alias for ensure_admin_credentials (tests / login)."""
    global _ADMIN_PASSWORD_HASH
    if _ADMIN_PASSWORD_HASH:
        return {"password_hash": _ADMIN_PASSWORD_HASH}
    return ensure_admin_credentials()


def product_row_to_dict(row):
    raw = row["price"]
    if raw is None:
        price = ""
    else:
        number = float(raw)
        price = int(number) if number.is_integer() else round(number, 2)
    return {
        "id": row["id"],
        "name": row["name"] or "",
        "price": price,
        "currency": row["currency"] or "kzt",
        "kind": row["kind"] or "product",
        "description": row["description"] or "",
        "image": row["image"] or "",
    }


def get_product(product_id):
    product_id = clean_text(product_id, 64)
    if not product_id:
        return None
    conn = db_connect()
    try:
        row = conn.execute(
            "SELECT * FROM products WHERE id = ?", (product_id,)
        ).fetchone()
    finally:
        conn.close()
    return product_row_to_dict(row) if row else None


def load_products():
    conn = db_connect()
    try:
        rows = conn.execute(
            "SELECT * FROM products ORDER BY created_at DESC, id DESC"
        ).fetchall()
    finally:
        conn.close()
    return [product_row_to_dict(row) for row in rows]


def insert_product(product):
    now = time.time()
    blob = product.get("_image_blob")
    mime = product.get("_image_mime") or ""
    with DB_WRITE_LOCK:
        conn = db_connect()
        try:
            conn.execute(
                """
                INSERT INTO products (
                    id, name, price, currency, kind, description, image,
                    image_blob, image_mime, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    product["id"],
                    product["name"],
                    product_price_to_db(product.get("price")),
                    product.get("currency") or "kzt",
                    product.get("kind") or "product",
                    product.get("description") or "",
                    product.get("image") or "",
                    blob,
                    mime,
                    now,
                    now,
                ),
            )
            conn.commit()
        finally:
            conn.close()
    return get_product(product["id"])


def update_product_record(product):
    blob = product.get("_image_blob")
    mime = product.get("_image_mime")
    with DB_WRITE_LOCK:
        conn = db_connect()
        try:
            if blob is not None:
                cur = conn.execute(
                    """
                    UPDATE products SET
                        name = ?, price = ?, currency = ?, kind = ?,
                        description = ?, image = ?, image_blob = ?,
                        image_mime = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        product["name"],
                        product_price_to_db(product.get("price")),
                        product.get("currency") or "kzt",
                        product.get("kind") or "product",
                        product.get("description") or "",
                        product.get("image") or "",
                        blob,
                        mime or "",
                        time.time(),
                        product["id"],
                    ),
                )
            else:
                cur = conn.execute(
                    """
                    UPDATE products SET
                        name = ?, price = ?, currency = ?, kind = ?,
                        description = ?, image = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        product["name"],
                        product_price_to_db(product.get("price")),
                        product.get("currency") or "kzt",
                        product.get("kind") or "product",
                        product.get("description") or "",
                        product.get("image") or "",
                        time.time(),
                        product["id"],
                    ),
                )
            if cur.rowcount == 0:
                raise ValueError("Товар не найден")
            conn.commit()
        finally:
            conn.close()
    return get_product(product["id"])


def delete_product(product_id):
    product_id = clean_text(product_id, 64)
    if not product_id:
        raise ValueError("Некорректные данные")
    with DB_WRITE_LOCK:
        conn = db_connect()
        try:
            row = conn.execute(
                "SELECT * FROM products WHERE id = ?", (product_id,)
            ).fetchone()
            if row is None:
                raise ValueError("Товар не найден")
            previous = product_row_to_dict(row)
            conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
            conn.commit()
        finally:
            conn.close()
    return previous


def save_products(products):
    """Replace catalog (tests / rare bulk ops). Prefer insert/update/delete."""
    with DB_WRITE_LOCK:
        conn = db_connect()
        try:
            conn.execute("DELETE FROM products")
            now = time.time()
            for index, product in enumerate(products or []):
                # Preserve list order: first item = newest.
                stamp = now - index * 0.001
                conn.execute(
                    """
                    INSERT INTO products (
                        id, name, price, currency, kind, description, image,
                        image_blob, image_mime, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        product["id"],
                        product.get("name") or "",
                        product_price_to_db(product.get("price")),
                        product.get("currency") or "kzt",
                        product.get("kind") or "product",
                        product.get("description") or "",
                        product.get("image") or "",
                        product.get("_image_blob"),
                        product.get("_image_mime") or "",
                        stamp,
                        stamp,
                    ),
                )
            conn.commit()
        finally:
            conn.close()


def backup_settings():
    load_env()
    try:
        interval = int(os.environ.get("CRM_BACKUP_INTERVAL_SEC", "21600"))
    except ValueError:
        interval = 21600
    interval = max(300, min(interval, 7 * 86400))
    try:
        keep = int(os.environ.get("CRM_BACKUP_KEEP", "14"))
    except ValueError:
        keep = 14
    keep = max(1, min(keep, 120))
    on_start = os.environ.get("CRM_BACKUP_ON_START", "1").strip().lower() not in {
        "0",
        "false",
        "no",
    }
    return interval, keep, on_start


def prune_backups(keep):
    if not BACKUPS_DIR.is_dir():
        return
    files = sorted(
        list(BACKUPS_DIR.glob("crm-*.json.gz"))
        + list(BACKUPS_DIR.glob("crm-*.db"))
        + list(BACKUPS_DIR.glob("crm-*.dump")),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for old in files[keep:]:
        try:
            old.unlink()
        except OSError:
            pass


def _serialize_backup_row(table, row):
    item = dict(row)
    if table == "products" and item.get("image_blob") is not None:
        item["image_blob"] = base64.b64encode(bytes(item["image_blob"])).decode(
            "ascii"
        )
        item["_image_blob_b64"] = True
    return item


def backup_crm_db(reason="manual"):
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest = BACKUPS_DIR / f"crm-{stamp}.json.gz"
    payload = {
        "version": 1,
        "engine": "postgresql",
        "created_at": time.time(),
        "reason": reason,
        "tables": {},
    }
    with DB_WRITE_LOCK:
        conn = db_connect()
        try:
            for table in _BACKUP_TABLES:
                rows = conn.execute(f"SELECT * FROM {table}").fetchall()
                payload["tables"][table] = [
                    _serialize_backup_row(table, row) for row in rows
                ]
        finally:
            conn.close()
    with gzip.open(dest, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, separators=(",", ":"))
    _, keep, _ = backup_settings()
    prune_backups(keep)
    print(f"[crm-backup] {reason}: {dest.name}")
    return dest


def start_backup_scheduler():
    interval, _, on_start = backup_settings()
    if on_start:
        try:
            backup_crm_db("startup")
        except Exception as error:
            print(f"[crm-backup] startup failed: {error}")

    def loop():
        while True:
            time.sleep(interval)
            try:
                backup_crm_db("scheduled")
            except Exception as error:
                print(f"[crm-backup] scheduled failed: {error}")

    thread = threading.Thread(target=loop, daemon=True, name="crm-backup")
    thread.start()
    print(f"[crm-backup] every {interval}s, dir {BACKUPS_DIR}")


def health_status():
    payload = {
        "ok": True,
        "ts": time.time(),
        "db": "up",
        "storage": "postgresql",
        "orders": 0,
        "clients": 0,
        "products": 0,
        "settings": 0,
    }
    try:
        conn = db_connect()
        try:
            conn.execute("SELECT 1").fetchone()
            payload["orders"] = conn.execute(
                "SELECT COUNT(*) AS count FROM orders"
            ).fetchone()["count"]
            payload["clients"] = conn.execute(
                "SELECT COUNT(*) AS count FROM clients"
            ).fetchone()["count"]
            payload["products"] = conn.execute(
                "SELECT COUNT(*) AS count FROM products"
            ).fetchone()["count"]
            payload["settings"] = conn.execute(
                "SELECT COUNT(*) AS count FROM settings"
            ).fetchone()["count"]
        finally:
            conn.close()
    except Exception as error:
        payload["ok"] = False
        payload["db"] = "down"
        # Do not leak connection details to public health clients.
        print(f"[health] database check failed: {error}", file=sys.stderr)
    return payload


def init_orders_db():
    """Back-compat name used by tests; full init lives in crm_store."""
    init_crm_db()


def parse_client_from_message(message):
    msg = message or ""
    name_match = re.search(r"(?:Имя|Name|Аты)\s*:\s*([^\n\r]+)", msg, re.I)
    phone_match = re.search(r"(?:Телефон|Phone|телефон)\s*:\s*([+\d\s()-]+)", msg, re.I)
    name = name_match.group(1).strip() if name_match else ""
    phone = ""
    if phone_match:
        raw = phone_match.group(1).strip()
        try:
            phone = clean_client_phone(raw)
        except ValueError:
            phone = ""
    return name, phone


def effective_order_client(row):
    keys = set(row.keys())
    name = ((row["client_name"] if "client_name" in keys else "") or "").strip()
    phone = ((row["client_phone"] if "client_phone" in keys else "") or "").strip()
    if not name or not phone:
        parsed_name, parsed_phone = parse_client_from_message(
            row["message"] if "message" in keys else ""
        )
        if not name and parsed_name:
            name = parsed_name
        if not phone and parsed_phone:
            phone = parsed_phone
    return name, phone


def order_row_to_dict(row):
    name, phone = effective_order_client(row)
    return {
        "id": row["id"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "source": row["source"],
        "serviceId": row["service_id"] or "",
        "serviceName": row["service_name"] or "",
        "message": row["message"] or "",
        "priceFrom": row["price_from"],
        "currency": row["currency"] or "kzt",
        "lang": row["lang"] or "ru",
        "status": row["status"] or "new",
        "notes": row["notes"] or "",
        "visitorId": row["visitor_id"] or "",
        "pagePath": row["page_path"] or "",
        "clientName": name or "",
        "clientPhone": phone or "",
    }


def clean_client_name(value):
    name = clean_text(value, 80)
    if len(name) < 2:
        raise ValueError("Укажите имя")
    return name


def clean_client_phone(value):
    raw = (value or "").strip()
    digits = re.sub(r"\D+", "", raw)
    if raw.startswith("+") and digits:
        phone = "+" + digits
    elif digits.startswith("8") and len(digits) == 11:
        phone = "+7" + digits[1:]
    elif digits.startswith("7") and len(digits) == 11:
        phone = "+" + digits
    elif len(digits) == 10:
        phone = "+7" + digits
    else:
        phone = ("+" + digits) if digits else ""
    if len(re.sub(r"\D+", "", phone)) < 10:
        raise ValueError("Укажите номер телефона")
    if len(phone) > 20:
        raise ValueError("Укажите номер телефона")
    return phone


def order_allowed(ip):
    now = time.time()
    with ORDER_RATE_LOCK:
        stamps = [ts for ts in ORDER_RATE.get(ip, []) if now - ts < ORDER_RATE_WINDOW]
        if len(stamps) >= ORDER_RATE_LIMIT:
            ORDER_RATE[ip] = stamps
            return False
        stamps.append(now)
        ORDER_RATE[ip] = stamps
        return True


def login_allowed(ip):
    now = time.time()
    with LOGIN_RATE_LOCK:
        stamps = [ts for ts in LOGIN_RATE.get(ip, []) if now - ts < LOGIN_RATE_WINDOW]
        if len(stamps) >= LOGIN_RATE_LIMIT:
            LOGIN_RATE[ip] = stamps
            return False
        stamps.append(now)
        LOGIN_RATE[ip] = stamps
        return True


def clean_order_price(value):
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise ValueError("Некорректные данные") from None
    if not math.isfinite(number):
        raise ValueError("Некорректные данные")
    if number < 0 or number > 1_000_000_000:
        raise ValueError("Некорректные данные")
    if number.is_integer():
        return int(number)
    return round(number, 2)


def trusted_proxy_peers():
    raw = os.environ.get("TRUSTED_PROXIES", "127.0.0.1,::1")
    return {part.strip() for part in raw.split(",") if part.strip()}


def client_ip(handler):
    """Client IP for rate limits. Trust X-Real-IP / XFF only from TRUSTED_PROXIES."""
    peer = (handler.client_address[0] if handler.client_address else "") or "unknown"
    if peer not in trusted_proxy_peers():
        return peer
    real = (handler.headers.get("X-Real-IP") or "").strip()
    if real:
        return real.split(",", 1)[0].strip() or peer
    xff = (handler.headers.get("X-Forwarded-For") or "").strip()
    if xff:
        parts = [part.strip() for part in xff.split(",") if part.strip()]
        if parts:
            return parts[-1]
    return peer


def clean_idempotency_key(value):
    """Normalize client/AI idempotency key; empty means 'no key'."""
    raw = str(value or "").strip()
    if not raw:
        return ""
    # Allow UUID / hex / url-safe tokens from browsers and tools.
    cleaned = re.sub(r"[^A-Za-z0-9._:-]", "", raw)[:128]
    return cleaned


def create_order(payload):
    source = clean_text(payload.get("source"), 32).lower() or "service"
    if source not in ORDER_SOURCES:
        raise ValueError("Некорректные данные")
    service_id = clean_text(payload.get("serviceId"), 80)
    service_name = clean_text(payload.get("serviceName"), 160)
    message = clean_text(payload.get("message"), 2000)
    client_name = clean_client_name(payload.get("clientName"))
    client_phone = clean_client_phone(payload.get("clientPhone"))
    if not service_name and not message:
        raise ValueError("Некорректные данные")
    if not service_name:
        service_name = {
            "custom": "Индивидуальный проект",
            "chat": "Чат-консультант",
            "contact": "Контакт WhatsApp",
            "shop": "Товар из каталога",
        }.get(source, "Заказ")
    lang = clean_text(payload.get("lang"), 8).lower() or "ru"
    if lang not in {"ru", "kz", "en"}:
        lang = "ru"
    # Never trust client-supplied price/currency for billing fields.
    # Only shop catalog or shared service catalog may set them.
    currency = "kzt"
    price_from = None

    # Shop orders: trust DB catalog, not client-supplied price/name.
    if source == "shop":
        if not service_id:
            raise ValueError("Некорректные данные")
        product = get_product(service_id)
        if not product:
            raise ValueError("Товар не найден")
        service_name = clean_text(product.get("name"), 160) or service_name
        currency = clean_currency(product.get("currency") or "kzt")
        raw_price = product.get("price")
        price_from = (
            None
            if raw_price == "" or raw_price is None
            else clean_order_price(raw_price)
        )
    else:
        # Landing / chat services: trust shared catalog, not client price.
        # Accept legacy short ids (photo → ai.photo).
        canonical_id = normalize_service_id(service_id)
        catalog_service = service_by_id(canonical_id) if canonical_id else None
        if catalog_service:
            service_id = catalog_service["id"]
            catalog_name = catalog_service["name"].get(lang) or catalog_service["name"]["ru"]
            if not service_name or service_name in {
                "Чат-консультант",
                "Заказ",
                "Индивидуальный проект",
            }:
                service_name = clean_text(catalog_name, 160) or service_name
            price_from = clean_order_price(SERVICE_PRICES_KZT[service_id])
            currency = "kzt"

    visitor_id = clean_text(payload.get("visitorId"), 80)
    page_path = clean_text(payload.get("pagePath"), 200)
    idem_key = clean_idempotency_key(
        payload.get("idempotencyKey") or payload.get("idempotency_key")
    )
    now = time.time()
    order_id = secrets.token_hex(8)
    created = True
    with DB_WRITE_LOCK:
        conn = db_connect()
        try:
            ensure_order_columns(conn)
            # 1) Exact replay: same Idempotency-Key → same order (no duplicate).
            if idem_key:
                existing = conn.execute(
                    """
                    SELECT o.* FROM order_idempotency i
                    JOIN orders o ON o.id = i.order_id
                    WHERE i.key = ?
                    """,
                    (idem_key,),
                ).fetchone()
                if existing:
                    created = False
                    _CREATE_ORDER_META.created = created
                    return order_row_to_dict(existing)

            # 2) Soft dedupe: same phone + service + source within a short window.
            since = now - ORDER_DEDUPE_WINDOW_SEC
            recent = conn.execute(
                """
                SELECT * FROM orders
                WHERE client_phone = ?
                  AND source = ?
                  AND service_id = ?
                  AND created_at >= ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (client_phone, source, service_id, since),
            ).fetchone()
            if recent is None and not service_id:
                recent = conn.execute(
                    """
                    SELECT * FROM orders
                    WHERE client_phone = ?
                      AND source = ?
                      AND service_name = ?
                      AND created_at >= ?
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (client_phone, source, service_name, since),
                ).fetchone()
            if recent:
                # Refresh mutable fields so CRM matches the WhatsApp text the client sends.
                conn.execute(
                    """
                    UPDATE orders SET
                        updated_at = ?,
                        message = ?,
                        client_name = ?,
                        service_name = ?,
                        price_from = ?,
                        currency = ?,
                        lang = ?,
                        visitor_id = CASE WHEN ? != '' THEN ? ELSE visitor_id END,
                        page_path = CASE WHEN ? != '' THEN ? ELSE page_path END
                    WHERE id = ?
                    """,
                    (
                        now,
                        message,
                        client_name,
                        service_name,
                        price_from,
                        currency,
                        lang,
                        visitor_id,
                        visitor_id,
                        page_path,
                        page_path,
                        recent["id"],
                    ),
                )
                if idem_key:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO order_idempotency (key, order_id, created_at)
                        VALUES (?, ?, ?)
                        """,
                        (idem_key, recent["id"], now),
                    )
                conn.commit()
                refreshed = conn.execute(
                    "SELECT * FROM orders WHERE id = ?",
                    (recent["id"],),
                ).fetchone()
                created = False
                _CREATE_ORDER_META.created = created
                return order_row_to_dict(refreshed or recent)

            try:
                conn.execute(
                    """
                    INSERT INTO orders (
                        id, created_at, updated_at, source, service_id, service_name,
                        message, price_from, currency, lang, status, notes,
                        visitor_id, page_path, client_name, client_phone
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'new', '', ?, ?, ?, ?)
                    """,
                    (
                        order_id,
                        now,
                        now,
                        source,
                        service_id,
                        service_name,
                        message,
                        price_from,
                        currency,
                        lang,
                        visitor_id,
                        page_path,
                        client_name,
                        client_phone,
                    ),
                )
                if idem_key:
                    conn.execute(
                        """
                        INSERT INTO order_idempotency (key, order_id, created_at)
                        VALUES (?, ?, ?)
                        """,
                        (idem_key, order_id, now),
                    )
                conn.commit()
            except IntegrityError:
                # Another writer (e.g. second process) won the idempotency race.
                conn.rollback()
                if idem_key:
                    raced = conn.execute(
                        """
                        SELECT o.* FROM order_idempotency i
                        JOIN orders o ON o.id = i.order_id
                        WHERE i.key = ?
                        """,
                        (idem_key,),
                    ).fetchone()
                    if raced:
                        created = False
                        _CREATE_ORDER_META.created = created
                        return order_row_to_dict(raced)
                raise
            row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        finally:
            conn.close()
    _CREATE_ORDER_META.created = created
    return order_row_to_dict(row)


def list_orders(status=None, limit=200):
    limit = max(1, min(int(limit or 200), 500))
    query = "SELECT * FROM orders"
    params = []
    if status:
        if status not in ORDER_STATUSES:
            raise ValueError("Некорректные данные")
        query += " WHERE status = ?"
        params.append(status)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    conn = db_connect()
    try:
        rows = conn.execute(query, params).fetchall()
    finally:
        conn.close()
    return [order_row_to_dict(row) for row in rows]


def get_order(order_id):
    order_id = clean_text(order_id, 64)
    if not order_id:
        return None
    conn = db_connect()
    try:
        row = conn.execute(
            "SELECT * FROM orders WHERE id = ?", (order_id,)
        ).fetchone()
    finally:
        conn.close()
    return order_row_to_dict(row) if row else None


def order_stats():
    conn = db_connect()
    try:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS count FROM orders GROUP BY status"
        ).fetchall()
        total = conn.execute("SELECT COUNT(*) AS count FROM orders").fetchone()["count"]
        fresh = conn.execute(
            "SELECT COUNT(*) AS count FROM orders WHERE status = 'new'"
        ).fetchone()["count"]
    finally:
        conn.close()
    by_status = {status: 0 for status in ORDER_STATUSES}
    for row in rows:
        by_status[row["status"]] = row["count"]
    return {"total": total, "new": fresh, "byStatus": by_status}


def update_order(order_id, payload):
    order_id = clean_text(order_id, 64)
    if not order_id:
        raise ValueError("Некорректные данные")
    fields = []
    values = []
    if "status" in payload:
        status = clean_text(payload.get("status"), 32).lower()
        if status not in ORDER_STATUSES:
            raise ValueError("Некорректные данные")
        fields.append("status = ?")
        values.append(status)
    if "notes" in payload:
        fields.append("notes = ?")
        values.append(clean_text(payload.get("notes"), 2000))
    if not fields:
        raise ValueError("Некорректные данные")
    fields.append("updated_at = ?")
    values.append(time.time())
    values.append(order_id)
    with DB_WRITE_LOCK:
        conn = db_connect()
        try:
            cur = conn.execute(
                "UPDATE orders SET " + ", ".join(fields) + " WHERE id = ?",
                values,
            )
            if cur.rowcount == 0:
                raise ValueError("Заказ не найден")
            conn.commit()
            row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
        finally:
            conn.close()
    return order_row_to_dict(row)


def normalize_phone_key(phone):
    digits = re.sub(r"\D+", "", str(phone or ""))
    if not digits:
        return ""
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    elif len(digits) == 10:
        digits = "7" + digits
    return digits


def format_display_phone(phone_key, fallback=""):
    raw = (fallback or "").strip()
    if raw:
        return raw
    if phone_key and phone_key.startswith("7") and len(phone_key) == 11:
        return "+" + phone_key
    return ("+" + phone_key) if phone_key else ""


def list_clients(include_hidden=False):
    conn = db_connect()
    try:
        order_rows = conn.execute(
            """
            SELECT client_name, client_phone, service_name, message, created_at, lang
            FROM orders
            ORDER BY created_at DESC
            """
        ).fetchall()
        meta_rows = conn.execute(
            "SELECT phone_key, phone, name, note, hidden, updated_at FROM clients"
        ).fetchall()
    finally:
        conn.close()

    meta = {
        row["phone_key"]: {
            "phone": row["phone"] or "",
            "name": row["name"] or "",
            "note": row["note"] or "",
            "hidden": bool(row["hidden"]),
            "updatedAt": row["updated_at"],
        }
        for row in meta_rows
    }

    grouped = {}
    for row in order_rows:
        client_name, client_phone = effective_order_client(row)
        phone_key = normalize_phone_key(client_phone)
        if not phone_key:
            continue
        item = grouped.get(phone_key)
        if not item:
            item = {
                "id": phone_key,
                "phoneKey": phone_key,
                "phone": format_display_phone(phone_key, client_phone),
                "name": client_name,
                "orderCount": 0,
                "lastOrderAt": row["created_at"],
                "lastServiceName": (row["service_name"] or "").strip(),
                "lang": row["lang"] or "ru",
                "note": "",
                "hidden": False,
            }
            grouped[phone_key] = item
        item["orderCount"] += 1
        if not item["name"] and client_name:
            item["name"] = client_name
        if not item["lastServiceName"] and (row["service_name"] or "").strip():
            item["lastServiceName"] = (row["service_name"] or "").strip()

    clients = []
    for phone_key, item in grouped.items():
        extra = meta.get(phone_key)
        if extra:
            if extra["name"]:
                item["name"] = extra["name"]
            if extra["phone"]:
                item["phone"] = extra["phone"]
            item["note"] = extra["note"]
            item["hidden"] = extra["hidden"]
        if not include_hidden and item["hidden"]:
            continue
        if not item["name"]:
            item["name"] = item["phone"] or "Клиент"
        clients.append(item)

    # Include saved clients with no orders yet
    for phone_key, extra in meta.items():
        if phone_key in grouped:
            continue
        if not include_hidden and extra["hidden"]:
            continue
        clients.append(
            {
                "id": phone_key,
                "phoneKey": phone_key,
                "phone": format_display_phone(phone_key, extra["phone"]),
                "name": extra["name"] or format_display_phone(phone_key, extra["phone"]) or "Клиент",
                "orderCount": 0,
                "lastOrderAt": None,
                "lastServiceName": "",
                "lang": "ru",
                "note": extra["note"],
                "hidden": extra["hidden"],
            }
        )

    clients.sort(key=lambda c: (c["lastOrderAt"] or 0), reverse=True)
    return clients


def update_client(phone_key, payload):
    phone_key = normalize_phone_key(phone_key)
    if not phone_key:
        raise ValueError("Некорректные данные")
    note = None
    hidden = None
    name = None
    phone = None
    if "note" in payload:
        note = clean_text(payload.get("note"), 2000)
    if "hidden" in payload:
        hidden = 1 if payload.get("hidden") else 0
    if "name" in payload:
        name = clean_text(payload.get("name"), 80)
    if "phone" in payload:
        phone = clean_text(payload.get("phone"), 20)
    if note is None and hidden is None and name is None and phone is None:
        raise ValueError("Некорректные данные")

    now = time.time()
    with DB_WRITE_LOCK:
        conn = db_connect()
        try:
            row = conn.execute(
                "SELECT phone_key, phone, name, note, hidden FROM clients WHERE phone_key = ?",
                (phone_key,),
            ).fetchone()
            current_phone = format_display_phone(phone_key, (row["phone"] if row else "") or "")
            current_name = (row["name"] if row else "") or ""
            current_note = (row["note"] if row else "") or ""
            current_hidden = int(row["hidden"]) if row else 0
            next_phone = phone if phone is not None else current_phone
            next_name = name if name is not None else current_name
            next_note = note if note is not None else current_note
            next_hidden = hidden if hidden is not None else current_hidden
            conn.execute(
                """
                INSERT INTO clients (phone_key, phone, name, note, hidden, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(phone_key) DO UPDATE SET
                    phone = excluded.phone,
                    name = excluded.name,
                    note = excluded.note,
                    hidden = excluded.hidden,
                    updated_at = excluded.updated_at
                """,
                (phone_key, next_phone, next_name, next_note, next_hidden, now),
            )
            conn.commit()
            saved = conn.execute(
                "SELECT phone_key, phone, name, note, hidden, updated_at FROM clients WHERE phone_key = ?",
                (phone_key,),
            ).fetchone()
        finally:
            conn.close()

    return {
        "id": saved["phone_key"],
        "phoneKey": saved["phone_key"],
        "phone": format_display_phone(saved["phone_key"], saved["phone"]),
        "name": saved["name"] or format_display_phone(saved["phone_key"], saved["phone"]) or "Клиент",
        "note": saved["note"] or "",
        "hidden": bool(saved["hidden"]),
        "updatedAt": saved["updated_at"],
    }


def delete_order(order_id):
    order_id = clean_text(order_id, 64)
    if not order_id:
        raise ValueError("Некорректные данные")
    with DB_WRITE_LOCK:
        conn = db_connect()
        try:
            cur = conn.execute("DELETE FROM orders WHERE id = ?", (order_id,))
            conn.commit()
            if cur.rowcount == 0:
                raise ValueError("Заказ не найден")
        finally:
            conn.close()


# Opaque server-side sessions (PostgreSQL). Extended on each authenticated request.
SESSION_MAX_AGE = ADMIN_SESSION_TTL_SEC  # 7 days


def request_wants_secure_cookie(handler):
    """
    True behind HTTPS reverse proxy, or when SECURE_COOKIES=1.

    Prod checklist: nginx/Caddy must send X-Forwarded-Proto: https, OR set
    SECURE_COOKIES=1. If Secure is set but the site is opened over plain http,
    the browser will not store the session cookie and admin login will look broken.
    """
    flag = os.environ.get("SECURE_COOKIES", "").strip().lower()
    if flag in {"1", "true", "yes", "on"}:
        return True
    if flag in {"0", "false", "no", "off"}:
        return False
    # Only trust forwarded proto from reverse proxies we configured.
    peer = (handler.client_address[0] if handler.client_address else "") or ""
    if peer not in trusted_proxy_peers():
        return False
    proto = handler.headers.get("X-Forwarded-Proto", "").split(",", 1)[0].strip().lower()
    return proto == "https"


def session_cookie(token, max_age=SESSION_MAX_AGE, secure=False):
    parts = [
        f"session={token}",
        "HttpOnly",
        "Path=/",
        "SameSite=Lax",
        f"Max-Age={int(max_age)}",
    ]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


# Only these can be served as static files. Everything else (source, env, db, venv) stays private.
STATIC_EXT = {
    ".html",
    ".css",
    ".js",
    ".map",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
    ".svg",
    ".ico",
    ".woff",
    ".woff2",
    ".ttf",
    ".otf",
    ".txt",
    ".xml",
    ".webmanifest",
}
PRIVATE_PREFIXES = (
    "data/",
    ".venv/",
    ".git/",
    "src/",
    "node_modules/",
    ".tools/",
    "e2e/",
    "scripts/",
    "test-results/",
    "playwright-report/",
    "pdf_export/",
    "docs/",
)
PRIVATE_NAMES = {
    ".env",
    ".env.example",
    ".gitignore",
    "server.py",
    "crm_store.py",
    "requirements.txt",
    "crm.db",
    "config.json",
    "config.json.migrated",
    "products.json",
    "products.json.migrated",
    "package.json",
    "package-lock.json",
    "vite.config.js",
    "playwright.config.cjs",
    # Vite entry / source-adjacent files — never serve from project root.
    "i18n.js",
    "styles.css",
    "script.js",
    "admin.js",
    "test_crm_reliability.py",
    "DEPLOY.md",
    "Projects.code-workspace",
    "Start Site.command",
    "Stop Site.command",
    "start.sh",
}


def _is_under(path, base):
    try:
        path.relative_to(base)
        return True
    except ValueError:
        return False


def spa_index():
    """React build entry (Vite outDir=dist)."""
    path = DIST / "index.html"
    return path if path.is_file() else None


def is_private_url_path(url_path):
    """True for source/secrets paths that must never get SPA fallback either."""
    rel = unquote(url_path).split("?", 1)[0].lstrip("/")
    if not rel:
        return False
    first = rel.split("/", 1)[0]
    if rel.startswith(".") or first.startswith("."):
        return True
    if rel in PRIVATE_NAMES or first in PRIVATE_NAMES:
        return True
    if any(rel == p.rstrip("/") or rel.startswith(p) for p in PRIVATE_PREFIXES):
        return True
    return False


def safe_file(url_path):
    rel = unquote(url_path).split("?", 1)[0].lstrip("/")
    if not rel or rel in {"admin", "admin.html", "index.html"}:
        return spa_index()
    # Block hidden files, private dirs, and non-public names before resolve().
    if is_private_url_path(url_path):
        return None

    # Product uploads are written live under ROOT/assets/products — prefer that.
    candidates = []
    if rel.startswith("assets/products/"):
        candidates.append(ROOT / rel)
    if DIST.is_dir():
        candidates.append(DIST / rel)
    candidates.append(ROOT / rel)

    for candidate in candidates:
        path = candidate.resolve()
        if not (_is_under(path, ROOT) or path == ROOT):
            continue
        if path.is_dir():
            path = path / "index.html"
        if not path.is_file():
            continue
        if path.suffix.lower() not in STATIC_EXT:
            continue
        if path.name in PRIVATE_NAMES:
            continue
        # Old vanilla front leftovers, if anyone restores them.
        if ".legacy." in path.name or path.name.endswith(".legacy.html"):
            continue
        # Never serve source/test trees even if extension matches.
        if any(
            _is_under(path, ROOT / p.rstrip("/"))
            for p in (
                "src",
                "node_modules",
                ".tools",
                "e2e",
                "data",
                "scripts",
                "test-results",
                "playwright-report",
            )
        ):
            continue
        # Root Vite entry is for `npm run dev` only; production uses dist/.
        if path == (ROOT / "index.html").resolve():
            continue
        return path
    return None


def remove_image(rel):
    """Best-effort cleanup of legacy on-disk product uploads (blobs live in PostgreSQL)."""
    if not rel:
        return
    path = (ROOT / rel).resolve()
    uploads = UPLOADS.resolve()
    if path.is_file() and (path == uploads or uploads in path.parents):
        path.unlink()


def save_image(fileitem, product_id):
    """Read upload into memory for PostgreSQL BYTEA storage (no disk write)."""
    filename = fileitem.filename or ""
    ext = Path(filename).suffix.lower()
    if ext not in IMAGE_EXT:
        raise ValueError("Нужно фото JPG, PNG, WebP или GIF")
    data = fileitem.file.read(MAX_IMAGE + 1)
    if len(data) > MAX_IMAGE:
        raise ValueError("Фото больше 8 МБ")
    if len(data) < 32:
        raise ValueError("Файл фото пустой")
    stored_ext = ".jpg" if ext == ".jpeg" else ext
    mime = {
        ".jpg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }.get(stored_ext, "application/octet-stream")
    return {
        "path": f"assets/products/{product_id}{stored_ext}",
        "blob": data,
        "mime": mime,
    }


def clean_text(value, limit):
    text = " ".join((value or "").split())
    return text[:limit]


def clean_price(value):
    raw = (value or "").strip().replace(" ", "").replace(",", ".")
    if raw == "":
        return ""
    number = float(raw)
    if number < 0 or number > 1_000_000_000:
        raise ValueError("Укажите нормальную цену")
    if number.is_integer():
        return int(number)
    return round(number, 2)


CURRENCIES = {"kzt", "usd", "rub"}
KINDS = {"product", "service"}


def clean_currency(value):
    code = (value or "kzt").strip().lower()
    if code not in CURRENCIES:
        raise ValueError("Некорректные данные")
    return code


def clean_kind(value):
    kind = (value or "product").strip().lower()
    if kind not in KINDS:
        raise ValueError("Некорректные данные")
    return kind


def chat_allowed(ip):
    now = time.time()
    with CHAT_RATE_LOCK:
        stamps = [ts for ts in CHAT_RATE.get(ip, []) if now - ts < CHAT_RATE_WINDOW]
        if len(stamps) >= CHAT_RATE_LIMIT:
            CHAT_RATE[ip] = stamps
            return False
        stamps.append(now)
        CHAT_RATE[ip] = stamps
        return True


def normalize_chat_messages(raw, allow_empty_last=False):
    """Keep only user turns — ignore client-forged assistant/system history."""
    if not isinstance(raw, list):
        raise ValueError("Некорректные данные")
    cleaned = []
    for item in raw[-CHAT_MAX_MESSAGES:]:
        if not isinstance(item, dict):
            continue
        role = item.get("role")
        content = " ".join(str(item.get("content") or "").split())
        if role != "user":
            continue
        if not content:
            if allow_empty_last:
                cleaned.append({"role": "user", "content": ""})
            continue
        cleaned.append({"role": "user", "content": content[:CHAT_MAX_CHARS]})
    if not cleaned:
        raise ValueError("Напишите сообщение")
    if not cleaned[-1]["content"] and not allow_empty_last:
        raise ValueError("Напишите сообщение")
    return cleaned


def decode_attachment_data(raw_data):
    value = str(raw_data or "").strip()
    if not value:
        raise ValueError("Пустой файл")
    if "," in value and value.lower().startswith("data:"):
        value = value.split(",", 1)[1]
    value = re.sub(r"\s+", "", value)
    try:
        data = base64.b64decode(value, validate=False)
    except Exception:
        raise ValueError("Не удалось прочитать файл")
    if not data:
        raise ValueError("Пустой файл")
    if len(data) > CHAT_MAX_FILE_BYTES:
        raise ValueError("Файл больше 4 МБ")
    return data


def normalize_chat_attachments(raw):
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("Некорректные вложения")
    if len(raw) > CHAT_MAX_ATTACHMENTS:
        raise ValueError("Можно прикрепить не больше 3 файлов")
    cleaned = []
    for item in raw[:CHAT_MAX_ATTACHMENTS]:
        if not isinstance(item, dict):
            continue
        name = clean_text(item.get("name"), 120) or "file"
        mime = clean_text(item.get("type"), 120).lower() or "application/octet-stream"
        data = decode_attachment_data(item.get("data"))
        allowed, normalized_mime = is_allowed_chat_attachment(name, mime, data)
        if not allowed:
            raise ValueError("Этот тип файла не поддерживается")
        cleaned.append({"name": name, "type": normalized_mime, "data": data})
    return cleaned



class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        print("[%s] %s" % (self.log_date_time_string(), fmt % args))

    def _maybe_slide_session_cookie(self):
        """Re-emit session cookie so browser Max-Age tracks server-side sliding TTL."""
        token = getattr(self, "_slide_session_token", None)
        if not token:
            return
        secure = request_wants_secure_cookie(self)
        self.send_header(
            "Set-Cookie",
            session_cookie(token, max_age=SESSION_MAX_AGE, secure=secure),
        )

    def send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self._maybe_slide_session_cookie()
        self.end_headers()
        self.wfile.write(body)

    def read_json(self, max_bytes=1_000_000):
        length = int(self.headers.get("Content-Length", "0"))
        if length > max_bytes:
            raise ValueError("Слишком большой запрос")
        raw = self.rfile.read(length) if length else b"{}"
        return json.loads(raw.decode("utf-8"))

    def read_form(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length > MAX_IMAGE + 1_000_000:
            raise ValueError("Файл слишком большой")
        environ = {
            "REQUEST_METHOD": "POST",
            "CONTENT_TYPE": self.headers.get("Content-Type", ""),
            "CONTENT_LENGTH": str(length),
        }
        return cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ=environ)

    def cookies(self):
        found = {}
        for part in self.headers.get("Cookie", "").split(";"):
            if "=" in part:
                key, value = part.strip().split("=", 1)
                found[key] = value
        return found

    def current_session(self, *, touch=True):
        """Return valid admin session dict or None (extends TTL when touch=True)."""
        token = self.cookies().get("session", "")
        session = get_admin_session(token, touch=touch)
        # Mark cookie for refresh so browser Max-Age slides with server expiry.
        if session and touch:
            self._slide_session_token = session["token"]
        return session

    def authed(self):
        return self.current_session(touch=True) is not None

    def do_GET(self):
        path = urlparse(self.path).path
        query = parse_qs(urlparse(self.path).query)
        if path == "/api/products/catalog.pdf":
            self.serve_catalog_pdf(query)
            return
        if path == "/api/products":
            self.send_json(load_products())
            return
        if path == "/api/me":
            session = self.current_session(touch=True)
            if session:
                self.send_json(
                    {"ok": True, "csrfToken": session["csrf_token"]}
                )
            else:
                self.send_json({"ok": False})
            return
        if path == "/api/health":
            health = health_status()
            self.send_json(health, 200 if health.get("ok") else 503)
            return
        if path == "/api/orders":
            if not self.require_auth():
                return
            status = (query.get("status") or [None])[0]
            limit = (query.get("limit") or ["200"])[0]
            try:
                orders = list_orders(status=status, limit=limit)
                stats = order_stats()
            except ValueError as error:
                self.send_json({"error": str(error)}, 400)
                return
            self.send_json({"orders": orders, "stats": stats})
            return
        # GET /api/orders/<id>/invoice.pdf
        if path.startswith("/api/orders/") and path.endswith("/invoice.pdf"):
            order_id = path[len("/api/orders/") : -len("/invoice.pdf")]
            self.serve_invoice_pdf(order_id, query)
            return
        if path == "/api/clients":
            if not self.require_auth():
                return
            include_hidden = (query.get("includeHidden") or ["0"])[0] in {"1", "true", "yes"}
            clients = list_clients(include_hidden=include_hidden)
            self.send_json({"clients": clients, "total": len(clients)})
            return
        # Product photos are stored as PostgreSQL BYTEA; URL stays /assets/products/<id>.ext
        product_id = product_id_from_image_url(path)
        if product_id:
            stored = get_product_image_bytes(product_id)
            if stored:
                data, mime = stored
                self.send_response(200)
                self.send_header("Content-Type", mime)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "public, max-age=86400")
                self.end_headers()
                self.wfile.write(data)
                return
        file_path = safe_file(path)
        # SPA fallback: client routes like /admin are handled by React Router.
        # Never fall back for private trees (node_modules, src, data, …).
        if (
            file_path is None
            and spa_index() is not None
            and not is_private_url_path(path)
        ):
            accept = self.headers.get("Accept", "")
            looks_like_page = (
                path == "/admin"
                or path.endswith("/")
                or "." not in Path(path).name
            )
            if looks_like_page and ("text/html" in accept or accept == "" or "*/*" in accept):
                file_path = spa_index()
        if file_path is None:
            self.send_error(404)
            return
        data = file_path.read_bytes()
        mime = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        # Browsers are picky about favicon MIME / caching after 404s.
        if file_path.suffix.lower() == ".ico":
            mime = "image/x-icon"
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        if file_path.suffix in {".html", ".js", ".css"}:
            self.send_header("Cache-Control", "no-cache")
        elif file_path.suffix.lower() in {".ico", ".svg", ".png", ".webp"} and (
            "favicon" in file_path.name.lower() or file_path.name == "apple-touch-icon.png"
        ):
            self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        path = urlparse(self.path).path
        try:
            if path == "/api/login":
                self.login()
                return
            if path == "/api/logout":
                if self.require_csrf() is None:
                    return
                self.logout()
                return
            if path == "/api/chat":
                self.chat()
                return
            if path == "/api/orders":
                self.create_order_request()
                return
            if path.startswith("/api/orders/"):
                self.update_order_request(path.rsplit("/", 1)[-1])
                return
            if path.startswith("/api/clients/"):
                self.update_client_request(path.rsplit("/", 1)[-1])
                return
            if path == "/api/products":
                self.create_product()
                return
            if path.startswith("/api/products/"):
                self.update_product(path.rsplit("/", 1)[-1])
                return
        except ValueError as error:
            self.send_json({"error": str(error)}, 400)
            return
        except json.JSONDecodeError:
            self.send_json({"error": "Некорректные данные"}, 400)
            return
        self.send_json({"error": "Не найдено"}, 404)

    def create_order_request(self):
        ip = client_ip(self)
        if not order_allowed(ip):
            self.send_json({"error": "Слишком много запросов. Подождите немного."}, 429)
            return
        body = self.read_json()
        if not isinstance(body, dict):
            raise ValueError("Некорректные данные")
        # Prefer explicit header; fall back to JSON field.
        header_key = self.headers.get("Idempotency-Key") or self.headers.get(
            "idempotency-key"
        )
        if header_key and not body.get("idempotencyKey"):
            body["idempotencyKey"] = header_key
        order = create_order(body)
        # 201 = newly created, 200 = safe replay (same key / soft dedupe).
        created = getattr(_CREATE_ORDER_META, "created", True)
        self.send_json(order, 201 if created else 200)

    def update_order_request(self, order_id):
        if self.require_csrf() is None:
            return
        body = self.read_json()
        order = update_order(order_id, body)
        self.send_json(order)

    def update_client_request(self, phone_key):
        if self.require_csrf() is None:
            return
        body = self.read_json()
        client = update_client(phone_key, body)
        self.send_json(client)

    def chat(self):
        """Stateless reply: only the messages/attachments from this request are used.
        No chat history is stored or shared between visitors."""
        ip = client_ip(self)
        if not chat_allowed(ip):
            # Lang unknown before body parse; UI uses its own i18n for 429.
            self.send_json({"error": CHAT_I18N["ru"]["rateLimit"]}, 429)
            return
        body = self.read_json(CHAT_MAX_REQUEST_BYTES)
        lang = str(body.get("lang") or "ru").strip().lower()
        if lang not in {"ru", "kz", "en"}:
            lang = "ru"
        msg = CHAT_I18N.get(lang, CHAT_I18N["ru"])
        # sessionId is accepted for client isolation; server never persists chats.
        session_id = str(body.get("sessionId") or "").strip()[:80]
        if not session_id:
            self.send_json({"error": msg["needSession"]}, 400)
            return
        attachments = normalize_chat_attachments(body.get("attachments"))
        messages = normalize_chat_messages(body.get("messages"), allow_empty_last=bool(attachments))
        if not messages[-1]["content"] and not attachments:
            self.send_json({"error": msg["needMessage"]}, 400)
            return
        try:
            engine = get_engine()
        except RuntimeError:
            engine = init_ai(create_order=create_order)
        try:
            result = engine.run(
                "consultant",
                messages,
                lang=lang,
                attachments=attachments,
                context={"session_id": session_id},
                build_api_messages=build_openai_messages,
            )
        except Exception:
            self.send_json(
                {
                    "reply": msg["unavailable"],
                    "mode": "local",
                    "sessionId": session_id,
                }
            )
            return
        self.send_json(
            {"reply": result.reply, "mode": result.mode, "sessionId": session_id}
        )

    def do_DELETE(self):
        path = urlparse(self.path).path
        if path.startswith("/api/orders/"):
            if self.require_csrf() is None:
                return
            try:
                delete_order(path.rsplit("/", 1)[-1])
            except ValueError as error:
                status = 404 if "не найден" in str(error).lower() else 400
                self.send_json({"error": str(error)}, status)
                return
            self.send_json({"ok": True})
            return
        if not path.startswith("/api/products/"):
            self.send_json({"error": "Не найдено"}, 404)
            return
        if self.require_csrf() is None:
            return
        product_id = path.rsplit("/", 1)[-1]
        try:
            removed = delete_product(product_id)
        except ValueError as error:
            status = 404 if "не найден" in str(error).lower() else 400
            self.send_json({"error": str(error)}, status)
            return
        remove_image(removed.get("image"))
        self.send_json({"ok": True})

    def login(self):
        ip = client_ip(self)
        if not login_allowed(ip):
            self.send_json({"error": "Слишком много попыток входа. Подождите немного."}, 429)
            return
        body = self.read_json()
        cfg = load_config()
        password = str(body.get("password", ""))
        if not verify_admin_password(password, cfg.get("password_hash") or ""):
            self.send_json({"error": "Неверный пароль"}, 401)
            return
        session = create_admin_session(ttl_sec=SESSION_MAX_AGE)
        payload = {"ok": True, "csrfToken": session["csrf_token"]}
        self.send_response(200)
        body_out = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body_out)))
        secure = request_wants_secure_cookie(self)
        self.send_header(
            "Set-Cookie",
            session_cookie(session["token"], max_age=SESSION_MAX_AGE, secure=secure),
        )
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body_out)

    def logout(self):
        token = self.cookies().get("session", "")
        delete_admin_session(token)
        self.send_response(200)
        body = b'{"ok": true}'
        secure = request_wants_secure_cookie(self)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header(
            "Set-Cookie", session_cookie("", max_age=0, secure=secure)
        )
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def require_auth(self):
        if self.authed():
            return True
        self.send_json({"error": "Нужно войти"}, 401)
        return False

    def allowed_origins(self):
        """
        Origins accepted for CSRF checks.
        - http(s)://Host and http(s)://X-Forwarded-Host (first hop)
        - ALLOWED_ORIGINS from .env (www/apex / CDN)
        - Local Vite/preview origins (changeOrigin proxies Host to :8765 while
          browser Origin stays :5173/:4173 — without these, admin saves 403 in npm run dev)
        """
        allowed = {
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:4173",
            "http://127.0.0.1:4173",
        }
        raw = os.environ.get("ALLOWED_ORIGINS", "").strip()
        if raw:
            for part in raw.split(","):
                origin = part.strip().rstrip("/")
                if origin:
                    allowed.add(origin)
        hosts = []
        host = (self.headers.get("Host") or "").strip()
        if host:
            hosts.append(host)
        xf_host = (self.headers.get("X-Forwarded-Host") or "").split(",", 1)[0].strip()
        if xf_host and xf_host not in hosts:
            hosts.append(xf_host)
        for h in hosts:
            allowed.add(f"http://{h}")
            allowed.add(f"https://{h}")
        return {a.rstrip("/") for a in allowed}

    def origin_allowed(self):
        """Same-origin / allowlist check for cookie-authenticated mutations (CSRF)."""
        allowed = self.allowed_origins()
        if not allowed:
            return False
        origin = (self.headers.get("Origin") or "").strip().rstrip("/")
        if origin:
            return origin in allowed
        referer = (self.headers.get("Referer") or "").strip()
        if referer:
            return any(
                referer == a
                or referer.startswith(a + "/")
                or referer.startswith(a + "?")
                for a in allowed
            )
        return False

    def require_csrf(self):
        """
        Auth + CSRF token + Origin/Referer for state-changing admin requests.
        Returns session dict on success, None after sending 401/403.
        """
        session = self.current_session(touch=True)
        if session is None:
            self.send_json({"error": "Нужно войти"}, 401)
            return None
        header = (
            self.headers.get("X-CSRF-Token")
            or self.headers.get("x-csrf-token")
            or ""
        ).strip()
        expected = session.get("csrf_token") or ""
        if not header or not expected or not hmac.compare_digest(header, expected):
            self.send_json(
                {
                    "error": "Недействительный CSRF-токен. Обновите страницу и войдите снова."
                },
                403,
            )
            return None
        if not self.origin_allowed():
            self.send_json(
                {"error": "Запрос отклонён: неверный Origin/Referer."},
                403,
            )
            return None
        return session

    def product_from_form(self, form, product_id, previous=None):
        name = clean_text(form.getfirst("name"), 120)
        if not name:
            raise ValueError("Напишите название")
        description = clean_text(form.getfirst("description"), 2000)
        price = clean_price(form.getfirst("price"))
        currency = clean_currency(form.getfirst("currency"))
        kind = clean_kind(form.getfirst("kind"))
        image = previous.get("image") if previous else ""
        image_blob = None
        image_mime = None
        upload = form["image"] if "image" in form else None
        if upload is not None and getattr(upload, "filename", None):
            saved = save_image(upload, product_id)
            image = saved["path"]
            image_blob = saved["blob"]
            image_mime = saved["mime"]
        if not image:
            raise ValueError("Добавьте фото")
        product = {
            "id": product_id,
            "name": name,
            "price": price,
            "currency": currency,
            "kind": kind,
            "description": description,
            "image": image,
        }
        if image_blob is not None:
            product["_image_blob"] = image_blob
            product["_image_mime"] = image_mime
        return product

    def send_pdf(self, data, filename):
        self.send_response(200)
        self.send_header("Content-Type", "application/pdf")
        self.send_header(
            "Content-Disposition",
            'attachment; filename="%s"' % filename.replace('"', ""),
        )
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self._maybe_slide_session_cookie()
        self.end_headers()
        self.wfile.write(data)

    def serve_catalog_pdf(self, query):
        if not self.require_auth():
            return
        lang = (query.get("lang") or ["ru"])[0]
        lang = str(lang or "ru").strip().lower()
        if lang not in {"ru", "kz", "en"}:
            lang = "ru"
        ids_raw = (query.get("ids") or [""])[0]
        id_list = [part.strip() for part in str(ids_raw).split(",") if part.strip()]
        try:
            all_products = load_products()
            if id_list:
                by_id = {item["id"]: item for item in all_products}
                products = [by_id[pid] for pid in id_list if pid in by_id]
            else:
                products = all_products
            from pdf_export import build_catalog_pdf

            pdf_bytes = build_catalog_pdf(
                products, lang=lang, get_image=get_product_image_bytes
            )
        except Exception as error:
            import traceback

            print("[pdf-catalog] %s\n%s" % (error, traceback.format_exc()))
            self.send_json({"error": "Не удалось сформировать PDF"}, 500)
            return
        stamp = time.strftime("%d%m%Y")
        self.send_pdf(pdf_bytes, "Catalog_%s.pdf" % stamp)

    def serve_invoice_pdf(self, order_id, query):
        if not self.require_auth():
            return
        order = get_order(order_id)
        if order is None:
            self.send_json({"error": "Заказ не найден"}, 404)
            return
        lang = (query.get("lang") or [order.get("lang") or "ru"])[0]
        lang = str(lang or "ru").strip().lower()
        if lang not in {"ru", "kz", "en"}:
            lang = "ru"
        try:
            from pdf_export import SellerConfigError, build_invoice_pdf, invoice_number

            pdf_bytes = build_invoice_pdf(order, lang=lang)
            number = invoice_number(order.get("id") or "")
        except SellerConfigError as error:
            self.send_json(
                {
                    "error": str(error),
                    "missing": list(error.missing),
                },
                400,
            )
            return
        except Exception as error:
            import traceback

            print("[pdf-invoice] %s\n%s" % (error, traceback.format_exc()))
            self.send_json({"error": "Не удалось сформировать PDF"}, 500)
            return
        self.send_pdf(pdf_bytes, "Schet-faktura_%s.pdf" % number)

    def create_product(self):
        if self.require_csrf() is None:
            return
        form = self.read_form()
        product_id = secrets.token_hex(8)
        product = self.product_from_form(form, product_id)
        saved = insert_product(product)
        self.send_json(saved, 201)

    def update_product(self, product_id):
        if self.require_csrf() is None:
            return
        form = self.read_form()
        previous = get_product(product_id)
        if previous is None:
            self.send_json({"error": "Товар не найден"}, 404)
            return
        product = self.product_from_form(form, product_id, previous)
        # Persist PostgreSQL (incl. BYTEA) first; then drop any legacy disk file.
        saved = update_product_record(product)
        if saved and product.get("_image_blob") is not None:
            remove_image(previous.get("image"))
        self.send_json(saved)


def main():
    load_env()
    DATA.mkdir(parents=True, exist_ok=True)
    UPLOADS.mkdir(parents=True, exist_ok=True)
    init_crm_db()
    ensure_admin_credentials()
    prune_expired_admin_sessions()
    init_ai(create_order=create_order)
    if spa_index() is None:
        raise SystemExit(
            "Нет фронта: папка dist/ пуста. Выполни: npm run build\n"
            "или дважды кликни «Start Site.command»."
        )
    start_backup_scheduler()
    port = int(os.environ.get("PORT", "8765"))
    host = os.environ.get("BIND_HOST", "127.0.0.1").strip() or "127.0.0.1"
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Сайт:    http://{host}:{port}/")
    print(f"Админка: http://{host}:{port}/admin")
    print(f"Health:  http://{host}:{port}/api/health")
    print(f"CRM БД:  {database_label()}")
    server.serve_forever()


if __name__ == "__main__":
    main()
