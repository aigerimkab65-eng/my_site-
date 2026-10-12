#!/usr/bin/env python3
"""Единое SQLite-хранилище CRM: заказы, клиенты, товары, настройки, фото."""

from __future__ import annotations

import json
import mimetypes
import secrets
import sqlite3
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
UPLOADS = ROOT / "assets" / "products"
PRODUCTS_FILE = DATA / "products.json"
PRODUCTS_MIGRATED = DATA / "products.json.migrated"
CONFIG_FILE = DATA / "config.json"
ORDERS_DB = DATA / "crm.db"
BACKUPS_DIR = DATA / "backups"

# Serializes writers only. Readers use their own SQLite connections (WAL-safe).
DB_WRITE_LOCK = threading.Lock()
DB_LOCK = DB_WRITE_LOCK  # back-compat alias

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
EXT_MIME = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".gif": "image/gif",
}


def db_connect():
    DATA.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(ORDERS_DB), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=30000")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _table_cols(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def ensure_order_columns(conn):
    cols = _table_cols(conn, "orders")
    if "client_name" not in cols:
        conn.execute(
            "ALTER TABLE orders ADD COLUMN client_name TEXT NOT NULL DEFAULT ''"
        )
    if "client_phone" not in cols:
        conn.execute(
            "ALTER TABLE orders ADD COLUMN client_phone TEXT NOT NULL DEFAULT ''"
        )


def ensure_product_image_columns(conn):
    cols = _table_cols(conn, "products")
    if "image_blob" not in cols:
        conn.execute("ALTER TABLE products ADD COLUMN image_blob BLOB")
    if "image_mime" not in cols:
        conn.execute(
            "ALTER TABLE products ADD COLUMN image_mime TEXT NOT NULL DEFAULT ''"
        )


def get_setting(conn, key, default=None):
    row = conn.execute(
        "SELECT value FROM settings WHERE key = ?", (key,)
    ).fetchone()
    if row is None:
        return default
    return row["value"]


def set_setting(conn, key, value):
    conn.execute(
        """
        INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at
        """,
        (key, str(value), time.time()),
    )


def product_price_to_db(price):
    if price == "" or price is None:
        return None
    return float(price)


def migrate_products_from_json(conn):
    """One-shot import of legacy data/products.json (or .migrated) into SQLite."""
    count = conn.execute("SELECT COUNT(*) AS c FROM products").fetchone()["c"]
    if count:
        return 0
    sources = []
    if PRODUCTS_FILE.is_file():
        sources.append(PRODUCTS_FILE)
    if PRODUCTS_MIGRATED.is_file():
        sources.append(PRODUCTS_MIGRATED)
    if not sources:
        return 0

    items = None
    used = None
    for path in sources:
        try:
            parsed = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            print(f"[crm] skip products JSON {path.name}: {error}")
            continue
        if isinstance(parsed, list) and parsed:
            items = parsed
            used = path
            break
    if not items:
        return 0

    now = time.time()
    inserted = 0
    for index, item in enumerate(items):
        if not isinstance(item, dict) or not item.get("id") or not item.get("name"):
            continue
        stamp = now - index * 0.001
        conn.execute(
            """
            INSERT OR IGNORE INTO products (
                id, name, price, currency, kind, description, image,
                image_blob, image_mime, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, '', ?, ?)
            """,
            (
                str(item["id"])[:64],
                str(item.get("name") or "")[:120],
                product_price_to_db(item.get("price")),
                str(item.get("currency") or "kzt").lower()[:8],
                str(item.get("kind") or "product").lower()[:32],
                str(item.get("description") or "")[:2000],
                str(item.get("image") or "")[:300],
                stamp,
                stamp,
            ),
        )
        inserted += 1

    if used == PRODUCTS_FILE:
        migrated = PRODUCTS_FILE.with_suffix(".json.migrated")
        try:
            PRODUCTS_FILE.replace(migrated)
            print(f"[crm] products migrated {PRODUCTS_FILE.name} → {migrated.name}")
        except OSError as error:
            print(f"[crm] products in SQLite; rename failed: {error}")
    else:
        print(f"[crm] products restored from {used.name} ({inserted} rows)")
    return inserted


def migrate_config_from_json(conn):
    """Move data/config.json into settings. Plain passwords are NOT stored —
    only a note is printed; set ADMIN_PASSWORD in .env instead."""
    if get_setting(conn, "admin_password_hash"):
        return False
    if not CONFIG_FILE.is_file():
        return False
    try:
        cfg = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"[crm] skip config.json: {error}")
        return False
    password = str(cfg.get("password") or "").strip()
    dest = CONFIG_FILE.with_suffix(".json.migrated")
    try:
        if dest.exists():
            dest.unlink()
        CONFIG_FILE.replace(dest)
        if password:
            print(
                f"[crm] config.json moved to {dest.name}; "
                "set ADMIN_PASSWORD in .env (plaintext from config.json was not stored).",
                flush=True,
            )
        else:
            print(f"[crm] config migrated → {dest.name}")
    except OSError as error:
        print(f"[crm] config rename failed: {error}")
        return False
    return True


def migrate_product_images_from_disk(conn):
    """Load assets/products/* into products.image_blob when missing."""
    ensure_product_image_columns(conn)
    rows = conn.execute(
        "SELECT id, image, image_blob FROM products"
    ).fetchall()
    moved = 0
    for row in rows:
        if row["image_blob"]:
            continue
        candidates = []
        rel = (row["image"] or "").strip()
        if rel:
            candidates.append(ROOT / rel)
        if UPLOADS.is_dir():
            candidates.extend(UPLOADS.glob(f"{row['id']}.*"))
        for path in candidates:
            try:
                if not path.is_file():
                    continue
                if path.suffix.lower() not in IMAGE_EXT:
                    continue
                data = path.read_bytes()
                if len(data) < 32:
                    continue
                mime = EXT_MIME.get(path.suffix.lower()) or (
                    mimetypes.guess_type(path.name)[0] or "application/octet-stream"
                )
                stored_ext = ".jpg" if path.suffix.lower() == ".jpeg" else path.suffix.lower()
                image_path = f"assets/products/{row['id']}{stored_ext}"
                conn.execute(
                    """
                    UPDATE products
                    SET image = ?, image_blob = ?, image_mime = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (image_path, data, mime, time.time(), row["id"]),
                )
                moved += 1
                break
            except OSError:
                continue
    if moved:
        print(f"[crm] product images → SQLite blobs: {moved}")
    return moved


def _copy_orders_from(src_conn, dst_conn):
    # Never ALTER the source (backups open read-only).
    ensure_order_columns(dst_conn)
    src_cols = _table_cols(src_conn, "orders")
    needed = [
        "id",
        "created_at",
        "updated_at",
        "source",
        "service_id",
        "service_name",
        "message",
        "price_from",
        "currency",
        "lang",
        "status",
        "notes",
        "visitor_id",
        "page_path",
        "client_name",
        "client_phone",
    ]
    select_cols = [c for c in needed if c in src_cols]
    if "id" not in select_cols:
        return 0
    rows = src_conn.execute(
        f"SELECT {', '.join(select_cols)} FROM orders"
    ).fetchall()
    inserted = 0
    for row in rows:
        values = {c: row[c] for c in select_cols}
        values.setdefault("client_name", "")
        values.setdefault("client_phone", "")
        values.setdefault("service_id", "")
        values.setdefault("service_name", "")
        values.setdefault("message", "")
        values.setdefault("currency", "kzt")
        values.setdefault("lang", "ru")
        values.setdefault("status", "new")
        values.setdefault("notes", "")
        values.setdefault("visitor_id", "")
        values.setdefault("page_path", "")
        values.setdefault("price_from", None)
        cur = dst_conn.execute(
            """
            INSERT OR IGNORE INTO orders (
                id, created_at, updated_at, source, service_id, service_name,
                message, price_from, currency, lang, status, notes,
                visitor_id, page_path, client_name, client_phone
            ) VALUES (
                :id, :created_at, :updated_at, :source, :service_id, :service_name,
                :message, :price_from, :currency, :lang, :status, :notes,
                :visitor_id, :page_path, :client_name, :client_phone
            )
            """,
            values,
        )
        inserted += cur.rowcount
    return inserted


def _copy_clients_from(src_conn, dst_conn):
    if "clients" not in {
        r[0] for r in src_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }:
        return 0
    rows = src_conn.execute(
        "SELECT phone_key, phone, name, note, hidden, updated_at FROM clients"
    ).fetchall()
    inserted = 0
    updated = 0
    for row in rows:
        existing = dst_conn.execute(
            "SELECT updated_at, note, name FROM clients WHERE phone_key = ?",
            (row["phone_key"],),
        ).fetchone()
        if existing is None:
            dst_conn.execute(
                """
                INSERT INTO clients (phone_key, phone, name, note, hidden, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    row["phone_key"],
                    row["phone"] or "",
                    row["name"] or "",
                    row["note"] or "",
                    int(row["hidden"] or 0),
                    float(row["updated_at"] or 0),
                ),
            )
            inserted += 1
            continue
        # Keep newer / richer client metadata from backups.
        if float(row["updated_at"] or 0) > float(existing["updated_at"] or 0):
            dst_conn.execute(
                """
                UPDATE clients SET
                    phone = ?, name = ?, note = ?, hidden = ?, updated_at = ?
                WHERE phone_key = ?
                """,
                (
                    row["phone"] or "",
                    row["name"] or "",
                    row["note"] or "",
                    int(row["hidden"] or 0),
                    float(row["updated_at"] or 0),
                    row["phone_key"],
                ),
            )
            updated += 1
        elif (not (existing["note"] or "").strip()) and (row["note"] or "").strip():
            dst_conn.execute(
                """
                UPDATE clients SET note = ?, name = COALESCE(NULLIF(name, ''), ?),
                    updated_at = ?
                WHERE phone_key = ?
                """,
                (
                    row["note"] or "",
                    row["name"] or "",
                    time.time(),
                    row["phone_key"],
                ),
            )
            updated += 1
    return inserted + updated


def _copy_products_from(src_conn, dst_conn):
    if "products" not in {
        r[0] for r in src_conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }:
        return 0
    ensure_product_image_columns(dst_conn)
    src_cols = _table_cols(src_conn, "products")
    has_blob = "image_blob" in src_cols
    rows = src_conn.execute("SELECT * FROM products").fetchall()
    changed = 0
    for row in rows:
        keys = set(row.keys())
        exists = dst_conn.execute(
            "SELECT id, image_blob FROM products WHERE id = ?", (row["id"],)
        ).fetchone()
        blob = row["image_blob"] if has_blob and "image_blob" in keys else None
        mime = (row["image_mime"] if has_blob and "image_mime" in keys else "") or ""
        if exists is None:
            dst_conn.execute(
                """
                INSERT INTO products (
                    id, name, price, currency, kind, description, image,
                    image_blob, image_mime, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    row["name"] or "",
                    row["price"],
                    row["currency"] or "kzt",
                    row["kind"] or "product",
                    row["description"] or "",
                    row["image"] or "",
                    blob,
                    mime,
                    float(row["created_at"] or time.time()),
                    float(row["updated_at"] or time.time()),
                ),
            )
            changed += 1
        elif blob and not exists["image_blob"]:
            dst_conn.execute(
                """
                UPDATE products
                SET image_blob = ?, image_mime = ?, image = COALESCE(NULLIF(image, ''), ?),
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    blob,
                    mime,
                    row["image"] or "",
                    time.time(),
                    row["id"],
                ),
            )
            changed += 1
    return changed


def merge_from_backups(conn, force=False):
    """Restore any rows present in data/backups/*.db but missing from live DB."""
    if not force and get_setting(conn, "legacy_backups_merged") == "1":
        return {"orders": 0, "clients": 0, "products": 0}
    if not BACKUPS_DIR.is_dir():
        set_setting(conn, "legacy_backups_merged", "1")
        return {"orders": 0, "clients": 0, "products": 0}

    totals = {"orders": 0, "clients": 0, "products": 0}
    files = sorted(BACKUPS_DIR.glob("crm-*.db"))
    for path in files:
        try:
            src = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=30)
            src.row_factory = sqlite3.Row
            try:
                totals["orders"] += _copy_orders_from(src, conn)
                totals["clients"] += _copy_clients_from(src, conn)
                totals["products"] += _copy_products_from(src, conn)
            finally:
                src.close()
        except sqlite3.Error as error:
            print(f"[crm] skip backup {path.name}: {error}")
    set_setting(conn, "legacy_backups_merged", "1")
    if any(totals.values()):
        print(
            "[crm] merged from backups: "
            f"orders+{totals['orders']}, clients~{totals['clients']}, "
            f"products~{totals['products']}"
        )
    return totals


def init_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id TEXT PRIMARY KEY,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            source TEXT NOT NULL,
            service_id TEXT NOT NULL DEFAULT '',
            service_name TEXT NOT NULL DEFAULT '',
            message TEXT NOT NULL DEFAULT '',
            price_from REAL,
            currency TEXT NOT NULL DEFAULT 'kzt',
            lang TEXT NOT NULL DEFAULT 'ru',
            status TEXT NOT NULL DEFAULT 'new',
            notes TEXT NOT NULL DEFAULT '',
            visitor_id TEXT NOT NULL DEFAULT '',
            page_path TEXT NOT NULL DEFAULT '',
            client_name TEXT NOT NULL DEFAULT '',
            client_phone TEXT NOT NULL DEFAULT ''
        )
        """
    )
    ensure_order_columns(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS clients (
            phone_key TEXT PRIMARY KEY,
            phone TEXT NOT NULL DEFAULT '',
            name TEXT NOT NULL DEFAULT '',
            note TEXT NOT NULL DEFAULT '',
            hidden INTEGER NOT NULL DEFAULT 0,
            updated_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            price REAL,
            currency TEXT NOT NULL DEFAULT 'kzt',
            kind TEXT NOT NULL DEFAULT 'product',
            description TEXT NOT NULL DEFAULT '',
            image TEXT NOT NULL DEFAULT '',
            image_blob BLOB,
            image_mime TEXT NOT NULL DEFAULT '',
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )
    ensure_product_image_columns(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_orders_phone ON orders(client_phone)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_orders_visitor ON orders(visitor_id)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_orders_source ON orders(source)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_products_created ON products(created_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_products_kind ON products(kind)"
    )
    # Idempotency keys: same key → same order (retry-safe creates).
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS order_idempotency (
            key TEXT PRIMARY KEY,
            order_id TEXT NOT NULL UNIQUE,
            created_at REAL NOT NULL,
            FOREIGN KEY (order_id) REFERENCES orders(id) ON DELETE CASCADE
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_order_idempotency_created "
        "ON order_idempotency(created_at DESC)"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_orders_dedupe "
        "ON orders(client_phone, service_id, source, created_at DESC)"
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_sessions (
            token TEXT PRIMARY KEY,
            csrf_token TEXT NOT NULL,
            created_at REAL NOT NULL,
            last_seen_at REAL NOT NULL,
            expires_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_admin_sessions_expires "
        "ON admin_sessions(expires_at)"
    )


# Admin session TTL (also used by server.py cookie Max-Age).
ADMIN_SESSION_TTL_SEC = 7 * 24 * 60 * 60


def create_admin_session(ttl_sec=ADMIN_SESSION_TTL_SEC):
    """Create a random opaque session + CSRF token. Returns dict."""
    token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_urlsafe(32)
    now = time.time()
    expires_at = now + float(ttl_sec)
    with DB_WRITE_LOCK:
        conn = db_connect()
        try:
            conn.execute(
                """
                INSERT INTO admin_sessions
                    (token, csrf_token, created_at, last_seen_at, expires_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (token, csrf_token, now, now, expires_at),
            )
            conn.commit()
        finally:
            conn.close()
    return {
        "token": token,
        "csrf_token": csrf_token,
        "created_at": now,
        "last_seen_at": now,
        "expires_at": expires_at,
    }


def get_admin_session(token, *, touch=True, ttl_sec=ADMIN_SESSION_TTL_SEC):
    """Return session row dict if valid; optionally extend expiry on activity."""
    token = (token or "").strip()
    if not token:
        return None
    now = time.time()
    with DB_WRITE_LOCK:
        conn = db_connect()
        try:
            row = conn.execute(
                "SELECT * FROM admin_sessions WHERE token = ?",
                (token,),
            ).fetchone()
            if row is None:
                return None
            if float(row["expires_at"]) < now:
                conn.execute(
                    "DELETE FROM admin_sessions WHERE token = ?", (token,)
                )
                conn.commit()
                return None
            if touch:
                expires_at = now + float(ttl_sec)
                conn.execute(
                    """
                    UPDATE admin_sessions
                    SET last_seen_at = ?, expires_at = ?
                    WHERE token = ?
                    """,
                    (now, expires_at, token),
                )
                conn.commit()
                return {
                    "token": row["token"],
                    "csrf_token": row["csrf_token"],
                    "created_at": row["created_at"],
                    "last_seen_at": now,
                    "expires_at": expires_at,
                }
            return {
                "token": row["token"],
                "csrf_token": row["csrf_token"],
                "created_at": row["created_at"],
                "last_seen_at": row["last_seen_at"],
                "expires_at": row["expires_at"],
            }
        finally:
            conn.close()


def delete_admin_session(token):
    token = (token or "").strip()
    if not token:
        return
    with DB_WRITE_LOCK:
        conn = db_connect()
        try:
            conn.execute("DELETE FROM admin_sessions WHERE token = ?", (token,))
            conn.commit()
        finally:
            conn.close()


def delete_all_admin_sessions():
    with DB_WRITE_LOCK:
        conn = db_connect()
        try:
            conn.execute("DELETE FROM admin_sessions")
            conn.commit()
        finally:
            conn.close()


def prune_expired_admin_sessions():
    now = time.time()
    with DB_WRITE_LOCK:
        conn = db_connect()
        try:
            conn.execute(
                "DELETE FROM admin_sessions WHERE expires_at < ?", (now,)
            )
            conn.commit()
        finally:
            conn.close()


def init_crm_db():
    """Create schema and migrate all legacy file-based data into SQLite."""
    with DB_WRITE_LOCK:
        conn = db_connect()
        try:
            init_schema(conn)
            migrate_config_from_json(conn)
            migrate_products_from_json(conn)
            migrate_product_images_from_disk(conn)
            merge_from_backups(conn)
            conn.commit()
        finally:
            conn.close()


def get_admin_password_hash_from_db():
    """Return bcrypt hash string from settings, or None."""
    conn = db_connect()
    try:
        value = get_setting(conn, "admin_password_hash")
    finally:
        conn.close()
    value = (value or "").strip()
    return value or None


def set_admin_password_hash(password_hash):
    """Persist bcrypt hash; drop legacy plaintext admin_password if present."""
    password_hash = (password_hash or "").strip()
    if not password_hash:
        raise ValueError("password hash required")
    with DB_WRITE_LOCK:
        conn = db_connect()
        try:
            set_setting(conn, "admin_password_hash", password_hash)
            conn.execute("DELETE FROM settings WHERE key = ?", ("admin_password",))
            conn.commit()
        finally:
            conn.close()


def load_admin_config_from_db():
    """Back-compat: return {password_hash} if set, else None."""
    password_hash = get_admin_password_hash_from_db()
    if password_hash:
        return {"password_hash": password_hash}
    return None


def save_admin_config_to_db(password_hash, secret=None):
    """Persist password hash. `secret` ignored (legacy signature for tests)."""
    _ = secret
    set_admin_password_hash(password_hash)


def get_product_image_bytes(product_id):
    """Return (bytes, mime) for a product image stored in SQLite, or None."""
    product_id = (product_id or "").strip()
    if not product_id:
        return None
    conn = db_connect()
    try:
        row = conn.execute(
            "SELECT image_blob, image_mime, image FROM products WHERE id = ?",
            (product_id,),
        ).fetchone()
    finally:
        conn.close()
    if not row or not row["image_blob"]:
        return None
    mime = (row["image_mime"] or "").strip()
    if not mime:
        ext = Path(row["image"] or "").suffix.lower()
        mime = EXT_MIME.get(ext) or "application/octet-stream"
    return bytes(row["image_blob"]), mime


def product_id_from_image_url(url_path):
    """Parse /assets/products/<id>.ext → id."""
    rel = (url_path or "").split("?", 1)[0].lstrip("/")
    prefix = "assets/products/"
    if not rel.startswith(prefix):
        return None
    name = rel[len(prefix) :]
    if "/" in name or not name:
        return None
    stem = Path(name).stem
    if not stem or any(ch for ch in stem if not (ch.isalnum() or ch in "-_")):
        return None
    return stem
