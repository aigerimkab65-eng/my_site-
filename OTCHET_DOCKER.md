# Отчёт: контейнеризация проекта aigerim-landing в Docker

**Проект:** лендинг + CRM (React/Vite + Python)  
**Цель работы:** упаковать приложение в Docker так, чтобы его можно было собрать и запустить одной командой без ручной установки Node.js и Python-зависимостей на хосте.  
**Дата:** 12 октября 2026

---

## 1. Краткое описание проекта

Приложение состоит из двух частей:

| Часть | Технологии | Роль |
|--------|------------|------|
| Frontend | React, Vite | Сайт и админка; сборка в папку `dist/` |
| Backend | Python (`server.py`), PostgreSQL | API, раздача статики, CRM, PDF, AI-консультант |

В обычном (не Docker) режиме нужно: `npm run build`, затем `python3 server.py`.  
В Docker оба шага выполняются внутри образов автоматически.

---

## 2. Что было сделано

Созданы файлы контейнеризации:

1. **`Dockerfile`** — инструкция сборки образа (multi-stage).
2. **`docker-compose.yml`** — запуск сервиса, порты, volume, переменные окружения.
3. **`.dockerignore`** — исключение лишнего из контекста сборки (`.git`, `node_modules`, `.venv`, `.env`, тесты и т.д.).
4. **`docker-entrypoint.sh`** — подготовка каталогов данных и запуск процесса от непривилегированного пользователя.

---

## 3. Архитектура Docker-сборки (multi-stage)

### Стадия 1 — `frontend` (образ `node:22-alpine`)

1. Копируются `package.json` / `package-lock.json`.
2. Устанавливаются зависимости: `npm ci`.
3. Копируются исходники фронтенда и ассеты.
4. Выполняется `npm run build` → появляется `dist/`.

### Стадия 2 — `runtime` (образ `python:3.12-slim`)

1. Устанавливаются системные библиотеки для Pillow/PDF (JPEG, zlib, FreeType).
2. Устанавливаются Python-пакеты из `requirements.txt`.
3. Копируются backend-файлы: `server.py`, `crm_store.py`, `ai/`, `pdf_export/`.
4. Из стадии frontend копируется готовый `dist/`.
5. Настраивается пользователь `app` (UID 10001), healthcheck, entrypoint.

**Зачем multi-stage:** в финальном образе нет Node.js и исходников React — меньше размер и поверхность атаки, быстрее деплой.

---

## 4. Запуск через Docker Compose

### Команды

```bash
cd aigerim-landing

# Первый запуск / после изменений кода
docker compose up -d --build

# Обычный запуск (если образ уже собран)
docker compose up -d

# Логи
docker compose logs -f web

# Остановка (данные CRM в ./data сохраняются)
docker compose down
```

### Адреса после запуска

- Сайт: http://127.0.0.1:8765/
- Админка: http://127.0.0.1:8765/admin
- Health-check: http://127.0.0.1:8765/api/health

### Переменные окружения

Файл `.env` (на основе `.env.example`) подключается через `env_file` в Compose.  
Внутри контейнера принудительно задаётся `BIND_HOST=0.0.0.0`, иначе опубликованный порт не будет доступен с хоста.

Порт с хоста по умолчанию слушает только **localhost** (`127.0.0.1:8765`) — это безопаснее.  
Для доступа с телефона в Wi‑Fi:

```bash
HOST_BIND=0.0.0.0 docker compose up -d
```

---

## 5. Надёжность и безопасность (принятые решения)

| Решение | Зачем |
|---------|--------|
| Volume `./data:/app/data` | бэкапы CRM и uploads; сами данные CRM — в volume Postgres `pgdata` |
| `.env` не копируется в образ | Секреты не попадают в слои Docker-образа |
| Пользователь UID 10001 | Процесс не работает от root |
| `docker-entrypoint.sh` | Чинит права на смонтированный `data/` (важно на Linux VPS) |
| `HEALTHCHECK` | Docker сам проверяет `/api/health` |
| `restart: unless-stopped` | Автоперезапуск после сбоя / перезагрузки Docker |
| `init: true` | Корректная обработка сигналов и дочерних процессов |
| `.dockerignore` | Быстрее сборка, в контекст не попадают секреты и мусор |

Фото товаров хранятся в PostgreSQL как BYTEA (volume `pgdata`), а не «внутри» временного слоя контейнера.

---

## 6. Проверка работоспособности

После сборки и запуска были проверены:

- статус контейнера: **healthy**;
- `GET /api/health` → `{"ok": true, "db": "up", ...}`;
- главная страница и админка → HTTP 200;
- статические ассеты (например `/assets/hero.jpg`) → HTTP 200;
- доступ к чувствительным путям (`/data/crm.db`, `/.env`, `/server.py`) → HTTP 404;
- после `docker compose restart` данные CRM сохраняются.

---

## 7. Структура Docker-файлов (итог)

```
aigerim-landing/
├── Dockerfile              # multi-stage сборка
├── docker-compose.yml      # оркестрация одного сервиса web
├── docker-entrypoint.sh    # права на data/ + drop privileges
├── .dockerignore           # исключения из build context
├── .env                    # секреты (локально, не в git)
├── .env.example            # шаблон переменных
├── requirements.txt        # Python-зависимости
├── package.json            # Node/Vite зависимости
├── server.py               # backend
├── src/                    # frontend (React)
└── data/                   # persistent CRM (volume)
```

---

## 8. Вывод

Проект полностью упакован в Docker:

- сборка фронтенда и запуск бэкенда выполняются в контейнере;
- для запуска достаточно Docker Desktop / Docker Engine и команды `docker compose up -d --build`;
- данные CRM сохраняются на хосте в `./data`;
- учтены базовые практики: multi-stage, non-root, healthcheck, volume, изоляция секретов.

Таким образом, приложение можно демонстрировать и запускать воспроизводимо на любой машине с Docker, без ручной настройки окружения Node.js/Python.

---

## 9. Приложение: фрагменты конфигурации

### Dockerfile (идея)

```dockerfile
FROM node:22-alpine AS frontend
# ... npm ci && npm run build → dist/

FROM python:3.12-slim AS runtime
# ... pip install -r requirements.txt
# COPY --from=frontend /build/dist ./dist
# ENTRYPOINT ["/docker-entrypoint.sh"]
# CMD ["python", "server.py"]
```

### docker-compose.yml (идея)

```yaml
services:
  web:
    build: .
    ports:
      - "127.0.0.1:8765:8765"
    env_file: .env
    volumes:
      - ./data:/app/data
    restart: unless-stopped
```
