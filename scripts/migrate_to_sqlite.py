#!/usr/bin/env python3
"""Устарело: CRM переведена на PostgreSQL.

Используйте:
  python3 scripts/migrate_sqlite_to_postgres.py [path/to/crm.db]
"""

from __future__ import annotations

import sys


def main():
    print(
        "SQLite больше не используется как основное хранилище.\n"
        "Перенос: python3 scripts/migrate_sqlite_to_postgres.py [data/crm.db]",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
