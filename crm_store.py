#!/usr/bin/env python3
"""Единое PostgreSQL-хранилище CRM: заказы, клиенты, товары, настройки, фото.

Публичный API совместим с прежним SQLite-слоем: placeholders `?`,
`INSERT OR IGNORE`, dict-подобные строки. Подключение через DATABASE_URL.
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import secrets
import sqlite3
import threading
import time
from pathlib import Path

import psycopg
from psycopg import IntegrityError  # noqa: F401 — re-exported for server/tests
from psycopg import sql as psql
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
UPLOADS = ROOT / "assets" / "products"
PRODUCTS_FILE = DATA / "products.json"
PRODUCTS_MIGRATED = DATA / "products.json.migrated"
CONFIG_FILE = DATA / "config.json"
# Legacy path (SQLite). Kept for migration scripts and docs.
ORDERS_DB = DATA / "crm.db"
BACKUPS_DIR = DATA / "backups"

# Serializes writers. Readers open their own connections.
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

_INSERT_OR_IGNORE = re.compile(r"INSERT\s+OR\s+IGNORE\s+INTO", re.IGNORECASE)
_NAMED_PARAM = re.compile(r"(?<!:):([A-Za-z_][A-Za-z0-9_]*)")
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _load_dotenv():
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    try:
        text = env_path.read_text(encoding="utf-8")
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def database_url():
    _load_dotenv()
    url = (os.environ.get("DATABASE_URL") or "").strip()
    if not url:
        raise RuntimeError(
            "DATABASE_URL не задан. Пример: "
            "postgresql://aigerim:PASSWORD@127.0.0.1:5432/aigerim_crm"
        )
    return url


def database_label():
    """Short label for logs (no password)."""
    try:
        url = database_url()
    except RuntimeError:
        return "(DATABASE_URL unset)"
    try:
        from urllib.parse import urlparse

        parsed = urlparse(url)
        host = parsed.hostname or "?"
        port = f":{parsed.port}" if parsed.port else ""
        db = (parsed.path or "/").lstrip("/") or "?"
        schema = (os.environ.get("CRM_PG_SCHEMA") or "").strip()
        extra = f" schema={schema}" if schema else ""
        return f"postgresql://{host}{port}/{db}{extra}"
    except Exception:
        return "postgresql"


def adapt_sql(sql: str) -> str:
    """Translate SQLite-flavoured SQL to PostgreSQL."""
    ignore = bool(_INSERT_OR_IGNORE.search(sql))
    if ignore:
        sql = _INSERT_OR_IGNORE.sub("INSERT INTO", sql, count=1)
    sql = _NAMED_PARAM.sub(r"%(\1)s", sql)
    sql = sql.replace("?", "%s")
    if ignore:
        sql = sql.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    return sql


class PgConnection:
    """Thin wrapper: sqlite3-like execute/commit/close with `?` placeholders."""

    def __init__(self, raw: psycopg.Connection):
        self._raw = raw

    def execute(self, sql, params=None):
        adapted = adapt_sql(sql)
        if params is None:
            return self._raw.execute(adapted)
        if isinstance(params, dict):
            return self._raw.execute(adapted, params)
        return self._raw.execute(adapted, tuple(params))

    def commit(self):
        self._raw.commit()

    def rollback(self):
        self._raw.rollback()

    def close(self):
        self._raw.close()

    @property
    def raw(self):
        return self._raw


def db_connect():
    DATA.mkdir(parents=True, exist_ok=True)
    conn = psycopg.connect(database_url(), row_factory=dict_row)
    schema = (os.environ.get("CRM_PG_SCHEMA") or "").strip()
    if schema:
        if not _IDENT.match(schema):
            conn.close()
            raise ValueError(f"invalid CRM_PG_SCHEMA: {schema!r}")
        conn.execute(
            psql.SQL("SET search_path TO {}, public").format(
                psql.Identifier(schema)
            )
        )
        conn.commit()
    return PgConnection(conn)


def ensure_test_schema(schema: str | None = None) -> str:
    """Create an isolated schema for tests; sets CRM_PG_SCHEMA."""
    schema = schema or f"t_{secrets.token_hex(6)}"
    if not _IDENT.match(schema):
        raise ValueError(f"invalid schema name: {schema!r}")
    os.environ["CRM_PG_SCHEMA"] = schema
    conn = psycopg.connect(database_url(), row_factory=dict_row)
    try:
        conn.execute(
            psql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(
                psql.Identifier(schema)
            )
        )
        conn.commit()
    finally:
        conn.close()
    return schema


def drop_test_schema(schema: str | None = None):
    schema = (schema or os.environ.get("CRM_PG_SCHEMA") or "").strip()
    if not schema or not _IDENT.match(schema):
        return
    conn = psycopg.connect(database_url(), row_factory=dict_row)
    try:
        conn.execute(
            psql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(
                psql.Identifier(schema)
            )
        )
        conn.commit()
    finally:
        conn.close()


def _table_cols(conn, table):
    rows = conn.execute(
        """
        SELECT column_name AS name
        FROM information_schema.columns
        WHERE table_schema = current_schema()
          AND table_name = ?
        """,
        (table,),
    ).fetchall()
    return {row["name"] for row in rows}


def _table_names(conn):
    rows = conn.execute(
        """
        SELECT table_name AS name
        FROM information_schema.tables
        WHERE table_schema = current_schema()
          AND table_type = 'BASE TABLE'
        """
    ).fetchall()
    return {row["name"] for row in rows}


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
        conn.execute("ALTER TABLE products ADD COLUMN image_blob BYTEA")
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


def neutralize_legacy_product_json_files():
    """Wipe legacy JSON catalogs so deleted DB rows cannot be resurrected.

    products.json / products.json.migrated are one-shot migration sources only.
    Keeping product payloads on disk after import used to bring Audit Product
    back whenever the DB catalog was empty and the migration flag was missing.
    """
    for path in (PRODUCTS_FILE, PRODUCTS_MIGRATED):
        if not path.is_file():
            continue
        try:
            raw = path.read_text(encoding="utf-8").strip()
        except OSError as error:
            print(f"[crm] could not read legacy {path.name}: {error}")
            continue
        if raw in ("", "[]"):
            continue
        try:
            path.write_text("[]\n", encoding="utf-8")
            print(f"[crm] neutralized legacy {path.name}")
        except OSError as error:
            print(f"[crm] could not neutralize {path.name}: {error}")


def migrate_products_from_json(conn):
    """One-shot import of legacy data/products.json (or .migrated) into DB.

    Must never re-run after the first migration: an empty catalog (user deleted
    every product) used to re-import Audit Product from products.json.migrated
    on every container restart.
    """
    if get_setting(conn, "products_json_migrated") == "1":
        neutralize_legacy_product_json_files()
        return 0

    count = conn.execute("SELECT COUNT(*) AS c FROM products").fetchone()["c"]
    if count:
        # Live catalog already exists — mark done so an empty catalog later
        # does not resurrect rows from the legacy JSON file.
        set_setting(conn, "products_json_migrated", "1")
        neutralize_legacy_product_json_files()
        return 0

    sources = []
    if PRODUCTS_FILE.is_file():
        sources.append(PRODUCTS_FILE)
    if PRODUCTS_MIGRATED.is_file():
        sources.append(PRODUCTS_MIGRATED)
    if not sources:
        set_setting(conn, "products_json_migrated", "1")
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
        set_setting(conn, "products_json_migrated", "1")
        neutralize_legacy_product_json_files()
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
            print(f"[crm] products in PostgreSQL; rename failed: {error}")
    else:
        print(f"[crm] products restored from {used.name} ({inserted} rows)")

    set_setting(conn, "products_json_migrated", "1")
    # Always wipe payloads after import — flag alone is not enough if someone
    # clears settings or restores an old volume with the JSON still present.
    neutralize_legacy_product_json_files()
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
        print(f"[crm] product images → PostgreSQL bytea: {moved}")
    return moved


def _sqlite_table_cols(conn, table):
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def _copy_orders_from(src_conn, dst_conn):
    # Never ALTER the source (backups open read-only).
    ensure_order_columns(dst_conn)
    src_cols = _sqlite_table_cols(src_conn, "orders")
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
        inserted += cur.rowcount if cur.rowcount and cur.rowcount > 0 else 0
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
    src_cols = _sqlite_table_cols(src_conn, "products")
    has_blob = "image_blob" in src_cols
    rows = src_conn.execute("SELECT * FROM products").fetchall()
    changed = 0
    for row in rows:
        keys = set(row.keys())
        exists = dst_conn.execute(
            "SELECT id, image_blob FROM products WHERE id = ?", (row["id"],)
        ).fetchone()
        blob = row["image_blob"] if has_blob and "image_blob" in keys else None
        if blob is not None:
            blob = bytes(blob)
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
    """Restore any rows present in data/backups/*.db (legacy SQLite) but missing."""
    if not force and get_setting(conn, "legacy_backups_merged") == "1":
        return {"orders": 0, "clients": 0, "products": 0}
    if not BACKUPS_DIR.is_dir():
        set_setting(conn, "legacy_backups_merged", "1")
        return {"orders": 0, "clients": 0, "products": 0}

    totals = {"orders": 0, "clients": 0, "products": 0}
    files = sorted(BACKUPS_DIR.glob("crm-*.db"))
    for path in files:
        try:
            src = _open_sqlite_readonly(path)
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
            "[crm] merged from SQLite backups: "
            f"orders+{totals['orders']}, clients~{totals['clients']}, "
            f"products~{totals['products']}"
        )
    return totals


def _open_sqlite_readonly(path: Path):
    """Open SQLite for reading. WAL live DBs may need a short RW open first."""
    path = Path(path).resolve()
    try:
        # Flush WAL into the main file when we have write access.
        tmp = sqlite3.connect(str(path), timeout=30)
        try:
            tmp.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            tmp.commit()
        finally:
            tmp.close()
    except sqlite3.Error:
        pass
    try:
        conn = sqlite3.connect(
            f"file:{path.as_posix()}?mode=ro", uri=True, timeout=30
        )
    except sqlite3.Error:
        # Fallback: normal open (read queries only).
        conn = sqlite3.connect(str(path), timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def migrate_from_sqlite_file(sqlite_path=None, conn=None):
    """Copy all rows from a SQLite crm.db into the current PostgreSQL schema."""
    path = Path(sqlite_path) if sqlite_path else ORDERS_DB
    if not path.is_file():
        return {"orders": 0, "clients": 0, "products": 0, "settings": 0,
                "order_idempotency": 0, "admin_sessions": 0}

    own_conn = conn is None
    if own_conn:
        conn = db_connect()
    totals = {
        "orders": 0,
        "clients": 0,
        "products": 0,
        "settings": 0,
        "order_idempotency": 0,
        "admin_sessions": 0,
    }
    src = _open_sqlite_readonly(path)
    try:
        init_schema(conn)
        totals["orders"] = _copy_orders_from(src, conn)
        totals["clients"] = _copy_clients_from(src, conn)
        totals["products"] = _copy_products_from(src, conn)

        src_tables = {
            r[0] for r in src.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "settings" in src_tables:
            for row in src.execute(
                "SELECT key, value, updated_at FROM settings"
            ).fetchall():
                # Never import legacy plaintext passwords.
                if row["key"] in {"admin_password", "password"}:
                    continue
                existing = conn.execute(
                    "SELECT key FROM settings WHERE key = ?", (row["key"],)
                ).fetchone()
                if existing is None:
                    conn.execute(
                        """
                        INSERT INTO settings (key, value, updated_at)
                        VALUES (?, ?, ?)
                        """,
                        (row["key"], row["value"], float(row["updated_at"] or 0)),
                    )
                    totals["settings"] += 1

        if "order_idempotency" in src_tables:
            for row in src.execute(
                "SELECT key, order_id, created_at FROM order_idempotency"
            ).fetchall():
                # Only if order exists (FK).
                order = conn.execute(
                    "SELECT id FROM orders WHERE id = ?", (row["order_id"],)
                ).fetchone()
                if not order:
                    continue
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO order_idempotency (key, order_id, created_at)
                    VALUES (?, ?, ?)
                    """,
                    (row["key"], row["order_id"], float(row["created_at"] or 0)),
                )
                if cur.rowcount and cur.rowcount > 0:
                    totals["order_idempotency"] += 1

        if "admin_sessions" in src_tables:
            for row in src.execute(
                "SELECT token, csrf_token, created_at, last_seen_at, expires_at "
                "FROM admin_sessions"
            ).fetchall():
                cur = conn.execute(
                    """
                    INSERT OR IGNORE INTO admin_sessions
                        (token, csrf_token, created_at, last_seen_at, expires_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        row["token"],
                        row["csrf_token"],
                        float(row["created_at"] or 0),
                        float(row["last_seen_at"] or 0),
                        float(row["expires_at"] or 0),
                    ),
                )
                if cur.rowcount and cur.rowcount > 0:
                    totals["admin_sessions"] += 1

        if own_conn:
            conn.commit()
    finally:
        src.close()
        if own_conn:
            conn.close()
    return totals


def init_schema(conn):
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id TEXT PRIMARY KEY,
            created_at DOUBLE PRECISION NOT NULL,
            updated_at DOUBLE PRECISION NOT NULL,
            source TEXT NOT NULL,
            service_id TEXT NOT NULL DEFAULT '',
            service_name TEXT NOT NULL DEFAULT '',
            message TEXT NOT NULL DEFAULT '',
            price_from DOUBLE PRECISION,
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
            updated_at DOUBLE PRECISION NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            price DOUBLE PRECISION,
            currency TEXT NOT NULL DEFAULT 'kzt',
            kind TEXT NOT NULL DEFAULT 'product',
            description TEXT NOT NULL DEFAULT '',
            image TEXT NOT NULL DEFAULT '',
            image_blob BYTEA,
            image_mime TEXT NOT NULL DEFAULT '',
            created_at DOUBLE PRECISION NOT NULL,
            updated_at DOUBLE PRECISION NOT NULL
        )
        """
    )
    ensure_product_image_columns(conn)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            updated_at DOUBLE PRECISION NOT NULL
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
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS order_idempotency (
            key TEXT PRIMARY KEY,
            order_id TEXT NOT NULL UNIQUE,
            created_at DOUBLE PRECISION NOT NULL,
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
            created_at DOUBLE PRECISION NOT NULL,
            last_seen_at DOUBLE PRECISION NOT NULL,
            expires_at DOUBLE PRECISION NOT NULL
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
    """Create schema and migrate all legacy file-based data into PostgreSQL."""
    with DB_WRITE_LOCK:
        conn = db_connect()
        try:
            init_schema(conn)
            # One-shot: live SQLite file → PostgreSQL (if PG still empty of orders).
            orders_count = conn.execute(
                "SELECT COUNT(*) AS c FROM orders"
            ).fetchone()["c"]
            if orders_count == 0 and ORDERS_DB.is_file():
                if get_setting(conn, "sqlite_migrated") != "1":
                    totals = migrate_from_sqlite_file(ORDERS_DB, conn=conn)
                    set_setting(conn, "sqlite_migrated", "1")
                    if any(totals.values()):
                        print(
                            "[crm] migrated from SQLite crm.db: "
                            + ", ".join(f"{k}+{v}" for k, v in totals.items() if v)
                        )
            migrate_config_from_json(conn)
            migrate_products_from_json(conn)
            neutralize_legacy_product_json_files()
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
    """Return (bytes, mime) for a product image stored in DB, or None."""
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
