#!/bin/zsh
ROOT="/Users/ajgerim/Desktop/Projects/aigerim-landing"
PIDFILE="$ROOT/data/server.pid"

echo "Останавливаю сайт..."

if [ -f "$PIDFILE" ]; then
  kill "$(cat "$PIDFILE")" 2>/dev/null || true
  rm -f "$PIDFILE"
fi

pkill -f "$ROOT/server.py" 2>/dev/null || true
lsof -t -iTCP:8765 -sTCP:LISTEN 2>/dev/null | xargs kill 2>/dev/null || true
sleep 1
lsof -t -iTCP:8765 -sTCP:LISTEN 2>/dev/null | xargs kill -9 2>/dev/null || true

if curl -sf "http://127.0.0.1:8765/api/health" >/dev/null 2>&1; then
  echo "Всё ещё отвечает — проверь процессы вручную."
else
  echo "Остановлено."
fi
sleep 2
