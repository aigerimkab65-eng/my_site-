#!/usr/bin/env python3
"""Одноразовая / повторно безопасная миграция всех CRM-данных в data/crm.db."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from crm_store import (  # noqa: E402
    DATA,
    ORDERS_DB,
    db_connect,
    init_crm_db,
)


def summary():
    conn = db_connect()
    try:
        tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
        ]
        counts = {}
        for table in ("orders", "clients", "products", "settings"):
            if table in tables:
                counts[table] = conn.execute(
                    f"SELECT COUNT(*) AS c FROM {table}"
                ).fetchone()["c"]
        blobs = 0
        if "products" in tables:
            blobs = conn.execute(
                "SELECT COUNT(*) AS c FROM products WHERE image_blob IS NOT NULL"
            ).fetchone()["c"]
        return tables, counts, blobs
    finally:
        conn.close()


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    print(f"DB: {ORDERS_DB}")
    init_crm_db()
    tables, counts, blobs = summary()
    print("Tables:", ", ".join(tables))
    for name, count in counts.items():
        print(f"  {name}: {count}")
    print(f"  product images in SQLite: {blobs}")
    print("Done.")


if __name__ == "__main__":
    main()
