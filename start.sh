#!/bin/zsh
cd "$(dirname "$0")"
ROOT="$(pwd)"

needs_build() {
  [ ! -f "dist/index.html" ] && return 0
  if find src index.html package.json package-lock.json vite.config.js \
      -type f -newer dist/index.html 2>/dev/null | grep -q .; then
    return 0
  fi
  return 1
}

if needs_build; then
  echo "Собираю фронт..."
  if [ -x "$ROOT/.tools/node-v22.14.0-darwin-arm64/bin/npm" ]; then
    export PATH="$ROOT/.tools/node-v22.14.0-darwin-arm64/bin:$PATH"
  fi
  npm run build || exit 1
fi

echo "Запускаю сайт на http://127.0.0.1:8765/"
echo "Админка:        http://127.0.0.1:8765/admin"
echo "Остановить: Ctrl+C"
echo ""
exec python3 server.py
