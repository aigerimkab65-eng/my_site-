# Деплой aigerim-landing (сайт + CRM)

Фронт — React (Vite) в `src/`, сборка в `dist/`. Бэкенд — `server.py` (API + раздача `dist/`).
Исходники (`src/`, корневой `index.html` для Vite) снаружи не отдаются.

## Docker (рекомендуется)

Нужны Docker + Compose. В корне проекта должен быть `.env` (из `.env.example`).

```bash
cp -n .env.example .env   # если ещё нет
# отредактировать ADMIN_PASSWORD (или HASH) / SELLER_* и т.д.

docker compose up -d --build
```

Сайт: http://127.0.0.1:8765/ · админка: /admin · health: /api/health

- Порт снаружи по умолчанию только `127.0.0.1` (не торчит в LAN). Для телефона в Wi‑Fi: `HOST_BIND=0.0.0.0 docker compose up -d`.
- Внутри контейнера `BIND_HOST=0.0.0.0` (иначе publish не работает).
- PostgreSQL — сервис `db` (volume `pgdata`). Папка `./data` — бэкапы (`crm-*.json.gz`) и uploads. Entrypoint чинит владельца `./data` под uid `10001`.
- Фото товаров хранятся в PostgreSQL (`BYTEA`), не в образе.
- Задайте `POSTGRES_PASSWORD` / `DATABASE_URL` в `.env`. Миграция со старого SQLite: `python3 scripts/migrate_sqlite_to_postgres.py`.
- За nginx: `proxy_set_header X-Forwarded-Proto $scheme;` и при необходимости `TRUSTED_PROXIES` (IP docker-bridge / хоста, не только 127.0.0.1).
- Остановка: `docker compose down` (данные в `./data` остаются).
- Логи: `docker compose logs -f web`
- Не коммить `.env`. `docker compose config` печатает секреты в stdout — не шарить вывод.

## Быстрый чеклист

1. Скопировать проект на сервер, создать `.env` из `.env.example`.
2. Задать `ADMIN_PASSWORD_HASH` (предпочтительно на проде) или `ADMIN_PASSWORD`. Без них сервер **не стартует**.
3. Заполнить обязательные `SELLER_*` (включая явный `SELLER_VAT_RATE=0` для «Без НДС» или `16` для НДС). Пустой VAT → счёт не генерируется (400).
4. Если сайт открывается и с `www`, и без — задать  
   `ALLOWED_ORIGINS=https://example.com,https://www.example.com` (иначе CSRF 403 в админке).
5. `npm ci && npm run build` — собрать фронт в `dist/` (нужен Node 18+).
6. `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
   (ReportLab + Pillow + bcrypt; в `pdf_export/fonts/` уже лежат TTF).
7. Перезапустить сервис после установки зависимостей, например:
   `sudo systemctl restart aigerim-landing` (имя unit смотрите в своём systemd).
8. `BIND_HOST=127.0.0.1` — сервер слушает только localhost; снаружи — **nginx/Caddy** с HTTPS.
   Прокси **обязан** передавать `X-Forwarded-Proto: https` — иначе Secure-cookie не выставится
   (или задайте `SECURE_COOKIES=1`). Если Secure включён, а сайт открыт по `http://` — логин «не работает».
   Также нужны `Host` / `X-Forwarded-Host`, `X-Real-IP` / `X-Forwarded-For`.
9. **Не затирать volume Postgres (`pgdata`) и `data/backups`.** В PostgreSQL — заказы, товары, сессии.
   Новый деплой без БД = все вылогинены + пустая CRM. Нужен `DATABASE_URL`.
10. Systemd (или аналог) держит `server.py` постоянно запущенным (и доступный Postgres).
11. Мониторинг: `GET /api/health` → `{"ok":true,"db":"up","storage":"postgresql",...}`.
12. Бэкапы: `data/backups/crm-*.json.gz` (авто при старте и каждые `CRM_BACKUP_INTERVAL_SEC`). Копировать на другой диск / облако.
13. После деплоя руками: вход в `/admin` → сохранить любое изменение в заказе → скачать счёт-фактуру.
14. Опционально: `python3 test_crm_reliability.py`, `python3 test_invoice.py`, `npm run test:e2e`.

## Локальная разработка фронта

```bash
python3 server.py          # API на :8765
npm run dev                # Vite на :5173, /api проксируется на :8765
```

## Пример systemd

```ini
[Unit]
Description=Aigerim landing
After=network.target

[Service]
Type=simple
WorkingDirectory=/var/www/aigerim-landing
EnvironmentFile=/var/www/aigerim-landing/.env
ExecStart=/var/www/aigerim-landing/.venv/bin/python3 server.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
```

## Пример nginx (фрагмент)

```nginx
server {
    listen 443 ssl http2;
    server_name example.com;

    # Product images up to 8M; chat multipart up to ~18M. Default nginx is 1m → 413.
    client_max_body_size 25m;

    location / {
        proxy_pass http://127.0.0.1:8765;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

Глобально (на сервере) можно так же положить файл `/etc/nginx/conf.d/upload-size.conf`:

```nginx
client_max_body_size 25m;
```

Затем: `sudo nginx -t && sudo systemctl reload nginx`.

## Проверки после выкладки

| Проверка | Ожидание |
|----------|----------|
| `/` | Главная открывается |
| `/admin` | Форма входа → после логина видны заказы |
| Сохранить статус/заметку заказа | 200, без CSRF 403 |
| Счёт-фактура PDF | PDF; при пустых `SELLER_*` — 400 со списком полей |
| `/api/health` | `ok: true` |
| `/data/crm.db` | 404 |
| Заявка с сайта | Заказ в админке, клиент по телефону |

## Переменные CRM / auth / CSRF

| Переменная | По умолчанию | Смысл |
|------------|--------------|--------|
| `CRM_BACKUP_ON_START` | `1` | Бэкап при запуске сервера |
| `CRM_BACKUP_INTERVAL_SEC` | `21600` | Период бэкапа (6 ч) |
| `CRM_BACKUP_KEEP` | `14` | Сколько файлов хранить |
| `TRUSTED_PROXIES` | `127.0.0.1,::1` | Пиры для `X-Real-IP` / `X-Forwarded-For` |
| `SECURE_COOKIES` | auto по `X-Forwarded-Proto` | `1` = всегда Secure; `0` = никогда |
| `ALLOWED_ORIGINS` | (Host / X-Forwarded-Host) | Доп. Origin для CSRF (www + apex) |
| `ADMIN_PASSWORD_HASH` | — | Предпочтительно на проде вместо plaintext |
| `SELLER_VAT_RATE` | обязателен | `0` = Без НДС; пусто = ошибка счёта |
