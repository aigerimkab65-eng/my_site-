#!/usr/bin/env python3
"""Общая подготовка изолированной PostgreSQL-схемы для test_*.py."""

from __future__ import annotations

import atexit
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def _load_dotenv():
    env_path = ROOT / ".env"
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def prepare(prefix: str = "ak"):
    """Create temp schema + data dirs. Returns (crm_store, schema, data_dir)."""
    _load_dotenv()
    if not (os.environ.get("DATABASE_URL") or "").strip():
        raise SystemExit(
            "DATABASE_URL не задан. Поднимите Postgres: docker compose up -d db"
        )

    os.environ.setdefault("CRM_BACKUP_ON_START", "0")

    import crm_store  # noqa: E402

    schema = crm_store.ensure_test_schema()
    tmp = tempfile.TemporaryDirectory(prefix=f"{prefix}-")
    data = Path(tmp.name)
    crm_store.DATA = data
    # Non-existent path so init_crm_db does not import production SQLite into the test schema.
    crm_store.ORDERS_DB = data / "crm.db"
    crm_store.BACKUPS_DIR = data / "backups"
    crm_store.UPLOADS = data / "uploads"
    crm_store.PRODUCTS_FILE = data / "products.json"
    crm_store.PRODUCTS_MIGRATED = data / "products.json.migrated"
    crm_store.CONFIG_FILE = data / "config.json"
    crm_store.BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    crm_store.UPLOADS.mkdir(parents=True, exist_ok=True)

    def _cleanup():
        try:
            crm_store.drop_test_schema(schema)
        except Exception as error:
            print(f"[test] schema cleanup failed: {error}")
        tmp.cleanup()

    atexit.register(_cleanup)
    return crm_store, schema, data
