# Деплой aigerim-landing (сайт + CRM)

Фронт — React (Vite) в `src/`, сборка в `dist/`. Бэкенд — `server.py` (API + раздача `dist/`).
Исходники (`src/`, корневой `index.html` для Vite) снаружи не отдаются.

## Быстрый чеклист

1. Скопировать проект на сервер, создать `.env` из `.env.example`.
2. Задать сильные `ADMIN_PASSWORD` и `ADMIN_SECRET` (уникальные, не из примера).
3. `npm ci && npm run build` — собрать фронт в `dist/` (нужен Node 18+).
4. `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
   (ReportLab + Pillow для PDF-каталога; в `pdf_export/fonts/` уже лежат TTF).
5. Перезапустить сервис после установки зависимостей, например:
   `sudo systemctl restart aigerim-landing` (имя unit смотрите в своём systemd).
6. `BIND_HOST=127.0.0.1` — сервер слушает только localhost; снаружи — **nginx/Caddy** с HTTPS.
   Прокси должен передавать `X-Forwarded-Proto: https` — тогда session cookie ставится с `Secure`.
   При необходимости: `SECURE_COOKIES=1` в `.env`.
7. Systemd (или аналог) держит `server.py` постоянно запущенным.
8. Мониторинг: `GET /api/health` → `{"ok":true,"db":"up",...}`.
9. Бэкапы: `data/backups/crm-*.db` (авто при старте и каждые `CRM_BACKUP_INTERVAL_SEC`). Копировать на другой диск / облако.
10. Хранилище: всё CRM в одном `data/crm.db` (orders, clients, products + фото BLOB, settings). Legacy `config.json` / `products.json` мигрируют при старте (`python3 scripts/migrate_to_sqlite.py`).
11. После деплоя: `python3 test_crm_reliability.py`, `python3 test_pdf_catalog.py` и `npm run test:e2e` (опционально).
12. PDF-каталог (админ): `GET /api/products/catalog.pdf?lang=ru|kz|en&ids=…` — только с session cookie.

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

## Проверки после выкладки

| Проверка | Ожидание |
|----------|----------|
| `/` | Главная открывается |
| `/admin` | Форма входа |
| `/api/health` | `ok: true` |
| `/data/crm.db` | 404 |
| Заявка с сайта | Заказ в админке, клиент по телефону |

## Переменные CRM

| Переменная | По умолчанию | Смысл |
|------------|--------------|--------|
| `CRM_BACKUP_ON_START` | `1` | Бэкап при запуске сервера |
| `CRM_BACKUP_INTERVAL_SEC` | `21600` | Период бэкапа (6 ч) |
| `CRM_BACKUP_KEEP` | `14` | Сколько файлов хранить |
