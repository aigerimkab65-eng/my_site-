#!/usr/bin/env python3
"""Восстановление CRM из data/backups/crm-*.json.gz в PostgreSQL.

По умолчанию вставляет только отсутствующие PK (безопасно повторять).
С --replace перезаписывает строки с тем же ключом.
"""

from __future__ import annotations

import argparse
import base64
import gzip
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from crm_store import (  # noqa: E402
    DB_WRITE_LOCK,
    database_label,
    db_connect,
    init_schema,
)

TABLE_KEYS = {
    "orders": "id",
    "clients": "phone_key",
    "products": "id",
    "settings": "key",
    "order_idempotency": "key",
    "admin_sessions": "token",
}

# Restore order respects FK: orders before order_idempotency.
RESTORE_ORDER = (
    "orders",
    "clients",
    "products",
    "settings",
    "admin_sessions",
    "order_idempotency",
)


def load_backup(path: Path) -> dict:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict) or "tables" not in payload:
        raise SystemExit(f"Некорректный бэкап: {path}")
    return payload


def restore_row(conn, table: str, row: dict, replace: bool) -> str:
    data = dict(row)
    if table == "products" and data.pop("_image_blob_b64", False):
        raw = data.get("image_blob") or ""
        data["image_blob"] = base64.b64decode(raw) if raw else None

    pk = TABLE_KEYS[table]
    key = data.get(pk)
    if key is None:
        return "skip"

    cols = [c for c in data.keys() if not c.startswith("_")]
    placeholders = ", ".join(["?"] * len(cols))
    col_list = ", ".join(cols)
    values = tuple(data[c] for c in cols)

    exists = conn.execute(
        f"SELECT 1 AS x FROM {table} WHERE {pk} = ?", (key,)
    ).fetchone()
    if exists and not replace:
        return "skip"
    if exists and replace:
        sets = ", ".join(f"{c} = ?" for c in cols if c != pk)
        conn.execute(
            f"UPDATE {table} SET {sets} WHERE {pk} = ?",
            tuple(data[c] for c in cols if c != pk) + (key,),
        )
        return "update"

    if table in ("orders", "products", "settings", "order_idempotency", "admin_sessions", "clients"):
        conn.execute(
            f"INSERT INTO {table} ({col_list}) VALUES ({placeholders})",
            values,
        )
        return "insert"
    return "skip"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "backup",
        nargs="?",
        help="Путь к crm-*.json.gz (по умолчанию — самый свежий в data/backups)",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Перезаписывать существующие строки",
    )
    args = parser.parse_args()

    if args.backup:
        path = Path(args.backup)
    else:
        files = sorted(Path(ROOT / "data" / "backups").glob("crm-*.json.gz"))
        if not files:
            raise SystemExit("Нет crm-*.json.gz в data/backups")
        path = files[-1]

    if not path.is_file():
        raise SystemExit(f"Файл не найден: {path}")

    payload = load_backup(path)
    print(f"Backup:     {path}")
    print(f"PostgreSQL: {database_label()}")
    print(f"Mode:       {'replace' if args.replace else 'insert-missing'}")

    stats = {t: {"insert": 0, "update": 0, "skip": 0} for t in RESTORE_ORDER}
    with DB_WRITE_LOCK:
        conn = db_connect()
        try:
            init_schema(conn)
            for table in RESTORE_ORDER:
                rows = payload.get("tables", {}).get(table) or []
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    # Skip orphan idempotency if order missing
                    if table == "order_idempotency":
                        oid = row.get("order_id")
                        if oid and not conn.execute(
                            "SELECT 1 AS x FROM orders WHERE id = ?", (oid,)
                        ).fetchone():
                            stats[table]["skip"] += 1
                            continue
                    action = restore_row(conn, table, row, args.replace)
                    stats[table][action] += 1
            conn.commit()
        finally:
            conn.close()

    for table, counts in stats.items():
        print(
            f"  {table}: +{counts['insert']} ~{counts['update']} "
            f"skip={counts['skip']}"
        )
    print("Done.")


if __name__ == "__main__":
    main()
