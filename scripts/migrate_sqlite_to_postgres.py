#!/usr/bin/env python3
"""Перенос data/crm.db (SQLite) → PostgreSQL (DATABASE_URL).

Безопасно повторять: строки с существующими PK пропускаются (OR IGNORE).
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from crm_store import (  # noqa: E402
    ORDERS_DB,
    database_label,
    db_connect,
    init_schema,
    migrate_from_sqlite_file,
)


def summary(conn):
    counts = {}
    for table in (
        "orders",
        "clients",
        "products",
        "settings",
        "order_idempotency",
        "admin_sessions",
    ):
        counts[table] = conn.execute(
            f"SELECT COUNT(*) AS c FROM {table}"
        ).fetchone()["c"]
    blobs = conn.execute(
        "SELECT COUNT(*) AS c FROM products WHERE image_blob IS NOT NULL"
    ).fetchone()["c"]
    return counts, blobs


def main():
    sqlite_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ORDERS_DB
    print(f"SQLite:     {sqlite_path}")
    print(f"PostgreSQL: {database_label()}")
    if not sqlite_path.is_file():
        raise SystemExit(f"Нет файла SQLite: {sqlite_path}")

    conn = db_connect()
    try:
        init_schema(conn)
        conn.commit()
        totals = migrate_from_sqlite_file(sqlite_path, conn=conn)
        conn.commit()
        counts, blobs = summary(conn)
    finally:
        conn.close()

    print("Inserted / merged:")
    for name, count in totals.items():
        print(f"  {name}: +{count}")
    print("Current totals:")
    for name, count in counts.items():
        print(f"  {name}: {count}")
    print(f"  product images (bytea): {blobs}")
    print("Done.")


if __name__ == "__main__":
    main()
