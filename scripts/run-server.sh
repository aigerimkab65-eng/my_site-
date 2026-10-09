#!/bin/zsh
set -euo pipefail
ROOT="/Users/ajgerim/Desktop/Projects/aigerim-landing"
cd "$ROOT"

needs_build() {
  [ ! -f "dist/index.html" ] && return 0
  if find src index.html package.json package-lock.json vite.config.js \
      -type f -newer dist/index.html 2>/dev/null | grep -q .; then
    return 0
  fi
  return 1
}

if needs_build; then
  echo "Собираю фронт (npm run build)..."
  if [ -x "$ROOT/.tools/node-v22.14.0-darwin-arm64/bin/npm" ]; then
    export PATH="$ROOT/.tools/node-v22.14.0-darwin-arm64/bin:$PATH"
  fi
  npm run build
fi

export PORT="${PORT:-8765}"
export BIND_HOST="${BIND_HOST:-127.0.0.1}"
exec /usr/bin/python3 -u "$ROOT/server.py"
