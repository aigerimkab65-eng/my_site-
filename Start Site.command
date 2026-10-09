#!/bin/zsh
cd "$(dirname "$0")"
ROOT="$(pwd)"
LOG="$ROOT/data/server.out.log"
ERR="$ROOT/data/server.err.log"
PIDFILE="$ROOT/data/server.pid"

mkdir -p "$ROOT/data"

# Read ADMIN_PASSWORD from .env without echoing it.
ADMIN_PASSWORD=""
if [ -f "$ROOT/.env" ]; then
  ADMIN_PASSWORD=$(
    grep -E '^[[:space:]]*ADMIN_PASSWORD=' "$ROOT/.env" | head -1 \
      | sed -E 's/^[[:space:]]*ADMIN_PASSWORD=//' \
      | sed -E 's/^["'\'']//; s/["'\'']$//'
  )
fi

echo ""
echo "============================================"
echo "  САЙТ:    http://127.0.0.1:8765/"
echo "  АДМИНКА: http://127.0.0.1:8765/admin"
echo "  Пароль:  из файла .env (ADMIN_PASSWORD)"
echo "============================================"
echo ""

needs_build() {
  [ ! -f "dist/index.html" ] && return 0
  # Rebuild when React source / Vite config is newer than the last build.
  if find src index.html package.json package-lock.json vite.config.js \
      -type f -newer dist/index.html 2>/dev/null | grep -q .; then
    return 0
  fi
  return 1
}

if needs_build; then
  echo "Собираю сайт..."
  if [ -x ".tools/node-v22.14.0-darwin-arm64/bin/npm" ]; then
    export PATH="$ROOT/.tools/node-v22.14.0-darwin-arm64/bin:$PATH"
  fi
  npm run build || {
    echo "Ошибка сборки."
    read "? Нажми Enter"
    exit 1
  }
fi

is_up() {
  curl -sf "http://127.0.0.1:8765/api/health" >/dev/null 2>&1
}

if is_up; then
  echo "Сервер уже работает."
else
  echo "Запускаю сервер..."
  # Kill stale listeners on 8765
  lsof -t -iTCP:8765 -sTCP:LISTEN 2>/dev/null | xargs kill 2>/dev/null || true
  sleep 0.5

  nohup /usr/bin/python3 -u "$ROOT/server.py" >>"$LOG" 2>>"$ERR" &
  echo $! > "$PIDFILE"
  disown $! 2>/dev/null || true

  echo -n "Жду "
  for i in {1..25}; do
    if is_up; then
      echo " готово."
      break
    fi
    echo -n "."
    sleep 0.4
  done
  echo ""
fi

if ! is_up; then
  echo "НЕ ЗАПУСТИЛСЯ. Последние строки лога:"
  tail -40 "$ERR" 2>/dev/null || true
  tail -20 "$LOG" 2>/dev/null || true
  read "? Нажми Enter"
  exit 1
fi

# Quick self-check: login (password via env, never printed / never in argv)
if [ -n "$ADMIN_PASSWORD" ]; then
  LOGIN=$(
    ADMIN_PASSWORD="$ADMIN_PASSWORD" python3 <<'PY' 2>/dev/null || true
import json, os, urllib.request
password = os.environ.get("ADMIN_PASSWORD", "")
req = urllib.request.Request(
    "http://127.0.0.1:8765/api/login",
    data=json.dumps({"password": password}).encode(),
    headers={"Content-Type": "application/json"},
    method="POST",
)
try:
    with urllib.request.urlopen(req, timeout=5) as resp:
        print(resp.read().decode())
except Exception as exc:
    print(str(exc))
PY
)
  if echo "$LOGIN" | grep -q '"ok"'; then
    echo "Проверка входа: OK"
  else
    echo "Внимание: health OK, но логин не прошёл. Смотри .env (ADMIN_PASSWORD)."
  fi
else
  echo "Внимание: ADMIN_PASSWORD не найден в .env — проверку входа пропустил."
fi

open "http://127.0.0.1:8765/admin"
open "http://127.0.0.1:8765/"

echo ""
echo "Сайт и админка открыты в браузере."
echo "Сервер работает в фоне — это окно можно закрыть."
echo "Остановить: дважды кликни Stop Site.command"
echo ""
sleep 3
exit 0
