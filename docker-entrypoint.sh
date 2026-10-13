#!/bin/sh
set -eu

# Bind-mounted ./data may be owned by the host user. Ensure the app user can write
# CRM DB, WAL files, and backups (critical on Linux VPS; no-op when already ok).
mkdir -p /app/data/backups /app/data/uploads /app/assets/products

if [ "$(id -u)" = "0" ]; then
  if ! setpriv --reuid=10001 --regid=10001 --clear-groups -- test -w /app/data 2>/dev/null; then
    chown -R app:app /app/data /app/assets/products || true
  fi
  exec setpriv --reuid=10001 --regid=10001 --clear-groups -- "$@"
fi

exec "$@"
