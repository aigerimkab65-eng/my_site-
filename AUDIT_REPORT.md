# AUDIT_REPORT — aigerim-landing

**Дата:** 2026-10-11  
**Режим:** только чтение (код не менялся, миграции/прод-данные не трогались)  
**Объект:** `/Users/ajgerim/Desktop/Projects/aigerim-landing`

---

## 1. Резюме

Платформа — лендинг услуг + CRM-админка на одном Python-сервере и React (Vite). Модель продаж: заявка → WhatsApp/Telegram; **онлайн-оплаты и публичной регистрации нет** (это не «сломанный» checkout, а отсутствие фичи). CRM, лиды, AI-чат, PDF каталога/счёта — рабочие, с заметной зрелостью (idempotency, rate limit, WAL SQLite, ErrorBoundary).

По аудиту: **~8 критичных/высоких**, **~12 средних**, остальное низкий/техдолг.  
Топ-5 самых опасных:

1. **STUB-01** — в PDF-счёте захардкожены фейковые реквизиты (BIN `000…`, IIK `KZ000…`, «ул. Примерная»).
2. **ERR-01** — session-cookie = детерминированный HMAC(password), Max-Age **1 год**; logout не инвалидирует токен на сервере.
3. **ERR-02** — без `.env` админ-пароль **автогенерируется** и кладётся в SQLite (риск «потерянного» доступа / неожиданного деплоя).
4. **ERR-06 + ERR-01** — cookie-auth админки без CSRF/Origin-check при долгоживущей сессии.
5. **FE-ERR-01/02** — после логина сбои загрузки заказов/клиентов глотаются → пустые списки без ошибки.

---

## 2. Карта проекта

### Стек

| Слой | Технологии |
|------|------------|
| Фронт | React 19, React Router 7, Vite 6 (`src/`, сборка → `dist/`) |
| Бэк | `server.py` — `ThreadingHTTPServer` (stdlib), раздаёт API + `dist/` |
| БД | SQLite `data/crm.db` (WAL), обёртка `crm_store.py` |
| PDF | ReportLab + Pillow (`pdf_export/`) |
| AI | OpenAI-compatible API (`ai/`), локальный rule-based fallback |
| Тесты | `test_*.py`, Playwright e2e (`e2e/`) |
| Хостинг (по DEPLOY.md) | systemd + nginx/Caddy reverse proxy, HTTPS |

### Структура папок (логика)

```
aigerim-landing/
  server.py, crm_store.py     # API + CRM
  src/                        # React UI (landing + /admin)
  ai/                         # консультант, tools (catalog, leads)
  pdf_export/                 # каталог PDF + счёт-фактура
  data/                       # crm.db, backups, логи (gitignore)
  scripts/                    # migrate_to_sqlite, run-server
  e2e/, test_*.py             # тесты
  assets/, public/            # статика/иконки
  .env / .env.example         # секреты / шаблон
```

### Страницы / экраны

| Маршрут | Экран | Статус |
|---------|--------|--------|
| `/` | Landing (Hero, Story, Services, Process, Contact, Chat, LeadModal) | Реализован |
| `/admin` | Login → Orders / Clients / Products | Реализован |
| `/admin.html` | Redirect → `/admin` | Реализован |
| `*` | Redirect → `/` | Реализован |
| Публичный каталог `#shop` / карточка товара | — | **Нет UI** (есть API + мёртвые i18n/CSS) |
| Регистрация / восстановление пароля | — | **Нет** (только пароль админа) |
| Оплата | — | **Нет** |

### API-эндпоинты

| Method | Path | Auth |
|--------|------|------|
| GET | `/api/health` | нет |
| GET | `/api/me` | cookie → `{ok}` |
| GET | `/api/products` | нет (публичный каталог) |
| GET | `/api/products/catalog.pdf` | admin cookie |
| GET | `/api/orders` | admin |
| GET | `/api/orders/<id>/invoice.pdf` | admin |
| GET | `/api/clients` | admin |
| GET | `/assets/products/<id>.ext` | нет (BLOB из SQLite) |
| POST | `/api/login`, `/api/logout` | нет / cookie clear |
| POST | `/api/chat` | нет (+ rate limit, concurrency) |
| POST | `/api/orders` | нет (+ rate limit, idempotency) |
| POST | `/api/orders/<id>` | admin (status/notes) |
| POST | `/api/clients/<phone_key>` | admin |
| POST | `/api/products`, `/api/products/<id>` | admin (multipart) |
| DELETE | `/api/orders/<id>`, `/api/products/<id>` | admin |

### Фоновые задачи

- Поток `crm-backup` (`start_backup_scheduler`): бэкап SQLite при старте и каждые `CRM_BACKUP_INTERVAL_SEC` (дефолт 6 ч), prune `CRM_BACKUP_KEEP`.

### Внешние интеграции

| Интеграция | Где | Примечание |
|------------|-----|------------|
| OpenAI (или совместимый base URL) | `ai/core/llm.py` | опционально; без ключа — local |
| WhatsApp / Telegram | ссылки в UI и PDF | не API, deep-link |
| Email | — | нет |
| Платёжный шлюз | — | нет |
| Файловое облако | — | фото в SQLite BLOB |
| PDF | локально ReportLab | каталог + счёт |

### Конфиги и env

- `.env` (gitignore) + `.env.example`
- Переменные: `PORT`, `BIND_HOST`, `ADMIN_PASSWORD`, `ADMIN_SECRET`, `SECURE_COOKIES`, `TRUSTED_PROXIES`, `CRM_BACKUP_*`, `OPENAI_API_KEY`, `OPENAI_MODEL`, `OPENAI_BASE_URL`
- Деплой: `DEPLOY.md`, systemd/nginx примеры
- Кредиты админа также могут жить в SQLite `settings` (миграция из `config.json`)

**Содержимое live `.env` в отчёт не включалось** (секреты). Проверен шаблон `.env.example`.

---

## 3. Таблица находок

### STUB / заглушки / фоллбеки

---

#### STUB-01 · 🔴 Критично

| | |
|--|--|
| **Файл** | `pdf_export/config.py:29–43` |
| **Что не так** | Реквизиты продавца для счёта — явные заглушки с комментарием «replace with real values later». |
| **Фрагмент** | `"bin": "000000000000"`, `"address": "г. Алматы, ул. Примерная, д. 1"`, `"iik": "KZ000000000000000000"` |
| **Чем грозит** | Клиент/банк получают юридически невалидный счёт; риск отказа платежа и претензий. |
| **Как исправить** | Вынести `SELLER` в env/settings; блокировать генерацию invoice, пока BIN/IIK/адрес — placeholder. |

---

#### STUB-02 · 🟠 Высокий

| | |
|--|--|
| **Файл** | `src/i18n/translations.js` (ключи `shop.*`, ~72–89 и аналоги kz/en); `src/styles.css` (~983–1116); **нет** компонента Shop |
| **Что не так** | Полный набор строк/стилей публичного каталога, но UI и пункт меню отсутствуют. API `GET /api/products` есть. |
| **Фрагмент** | `"shop.empty": "Скоро здесь появятся товары."`, `"shop.order": "заказать"` |
| **Чем грозит** | Источник `shop` в CRM/заказах недостижим с сайта; ложное ощущение готового магазина. |
| **Как исправить** | Сделать секцию Shop + `fetch /api/products`, либо удалить мёртвые i18n/CSS и source `shop`. |

---

#### STUB-03 · 🟠 Высокий

| | |
|--|--|
| **Файл** | `src/components/admin/Products.jsx` (весь файл — список + PDF); `src/i18n/translations.js:140–171` (`admin.newTitle`, `admin.add`, `admin.edit`, `admin.confirmDelete`…) |
| **Что не так** | API create/update/delete товаров **есть** (`server.py:1862–1884`), UI CRUD **нет**; строки админки «добавить/изменить» не подключены. |
| **Фрагмент** | Products: только чекбоксы + `handleDownloadPdf`; нет форм create/edit. |
| **Чем грозит** | Товары нельзя вести из админки без прямого API/скриптов; каталог PDF пустеет. |
| **Как исправить** | Подключить формы к `POST /api/products` / `POST|DELETE /api/products/<id>` или убрать обещающие ключи i18n. |

---

#### STUB-04 · 🟠 Высокий

| | |
|--|--|
| **Файл** | `ai/core/engine.py:54–73`; `server.py:1676–1683`; `ai/core/llm.py:53–57` |
| **Что не так** | Ошибка OpenAI/engine → ответ пользователю с текстом «Сервис временно недоступен…» при **HTTP 200** и `mode: "local"` (успешный JSON). |
| **Фрагмент** | `except Exception: reply, used = None, ()` → `RunResult(reply="Сервис временно недоступен…", mode="local")` |
| **Чем грозит** | Сбои маскируются под нормальный ответ; мониторинг не видит 5xx; заявки через tools могут не создаться без явного fail. |
| **Как исправить** | Флаг `degraded: true` и/или HTTP 503 при полном отказе; structured log причины (без секретов); 1–2 retry на 429/5xx. |

---

#### STUB-05 · 🟡 Средний

| | |
|--|--|
| **Файл** | `src/lib/prices.js:5–15`; `ai/tools/catalog.py:13+` (дублирование); `src/components/landing/Services.jsx` |
| **Что не так** | Цены услуг захардкожены на клиенте и в AI-каталоге (комментарий «keep in sync»). |
| **Фрагмент** | `SERVICE_PRICES_KZT = { "ai.photo": 25000, ... }` |
| **Чем грозит** | Расхождение фронт/бэк при ручном обновлении одной стороны → неверная цена в WhatsApp до ответа сервера (сервер при `serviceId` перезаписывает из каталога — частично смягчает). |
| **Как исправить** | Один источник правды (API/конфиг) для UI и `SERVICE_CATALOG`. |

---

#### STUB-06 · 🟡 Средний

| | |
|--|--|
| **Файл** | `src/lib/prices.js:17–19` |
| **Что не так** | Курсы `KZT_TO_RUB` / `KZT_TO_USD` — приблизительные константы («not for billing»). |
| **Фрагмент** | `KZT_TO_RUB = 0.18; KZT_TO_USD = 0.00185` |
| **Чем грозит** | Отображаемые цены в RUB/USD вводят в заблуждение. |
| **Как исправить** | Пометка в UI / только KZT / актуальный курс с оговоркой. |

---

#### STUB-07 · ⚪ Низкий

| | |
|--|--|
| **Файл** | `src/components/landing/ChatWidget.jsx:617`; `src/i18n/translations.js` (`chat.status`) |
| **Что не так** | Бейдж «онлайн» статичен, не связан с availability API. |
| **Чем грозит** | При недоступности `/api/chat` статус всё равно «онлайн». |
| **Как исправить** | Убрать бейдж или завязать на health/ошибку чата. |

---

#### STUB-08 · ⚪ Низкий

| | |
|--|--|
| **Файл** | `pdf_export/catalog.py:191–207, 324–326` |
| **Что не так** | При недоступном фото — placeholder (буква имени). Штатный UX fallback. |
| **Чем грозит** | Каталог PDF без фото выглядит «пустым», данные не ломаются. |
| **Как исправить** | Опционально подпись «нет фото». |

---

#### STUB-09 · ⚪ Низкий

| | |
|--|--|
| **Файл** | `pdf_export/money_words.py:66` |
| **Что не так** | Комментарий «simplified, sufficient for homework invoices» — упрощённые казахские суммы прописью. |
| **Чем грозит** | Формальные ошибки в тексте суммы на kz в юр. документе. |
| **Как исправить** | Довести правила или ограничить invoice `lang=ru` для юр. документов. |

---

#### STUB-10 · ⚪ Низкий

| | |
|--|--|
| **Файл** | `src/i18n/translations.js` (`nav.shop`, `nav.admin`); `src/components/landing/Header.jsx:23–44` |
| **Что не так** | Ключи nav.shop/admin есть, в хедере не используются. |
| **Чем грозит** | Мёртвые переводы / техдолг. |
| **Как исправить** | Добавить ссылки или удалить ключи. |

---

### ERR / безопасность / обработка ошибок

---

#### ERR-01 · 🟠 Высокий

| | |
|--|--|
| **Файл** | `server.py:1100–1107`, `1122–1132`, `1720–1739` |
| **Что не так** | `session_token = HMAC(secret, password)` — один и тот же токен для всех сессий; `SESSION_MAX_AGE = 1 year`. Logout только очищает cookie у клиента. |
| **Фрагмент** | `SESSION_MAX_AGE = 60 * 60 * 24 * 365` + `hmac.new(cfg["secret"].encode(), cfg["password"].encode(), …)` |
| **Чем грозит** | Украденная cookie валидна год; смена пароля без смены secret оставляет схему предсказуемой относительно пары password+secret. |
| **Как исправить** | Random opaque session id в server-side store; короткий TTL; invalidate on logout/password change. |

---

#### ERR-02 · 🟠 Высокий

| | |
|--|--|
| **Файл** | `server.py:94–115` |
| **Что не так** | Если нет `ADMIN_PASSWORD`/`ADMIN_SECRET` и нет записи в БД — генерируется случайный пароль в SQLite + stderr. |
| **Фрагмент** | `"password": secrets.token_urlsafe(12)` → `save_admin_config_to_db` |
| **Чем грозит** | На проде без `.env` сервис «тихо» стартует с неизвестным паролем; пароль лежит в БД. |
| **Как исправить** | В production (`BIND_HOST`≠localhost или явный `ENV=production`) — fail-fast без credentials. |

---

#### ERR-03 · 🟡 Средний

| | |
|--|--|
| **Файл** | `server.py:414–417` |
| **Что не так** | `/api/health` публично отдаёт `error: str(exception)` при падении БД. |
| **Фрагмент** | `payload["error"] = str(error)` |
| **Чем грозит** | Утечка путей/деталей SQLite наружу. |
| **Как исправить** | Клиенту только `"db":"down"`; детали — в лог. |

---

#### ERR-04 · 🟡 Средний

| | |
|--|--|
| **Файл** | `ai/core/llm.py:53–57`, `117–119` |
| **Что не так** | OpenAI: timeout 20s, **без retries**, любая ошибка → `None` **без лога**. |
| **Фрагмент** | `except Exception: return None` |
| **Чем грозит** | Краткий сетевой сбой → silent local fallback; нет observability. |
| **Как исправить** | Логировать status/latency; retry на 429/5xx. |

---

#### ERR-05 · 🟡 Средний

| | |
|--|--|
| **Файл** | `server.py:1565–1598` vs `create_order` IntegrityError `792–808` |
| **Что не так** | `do_POST` ловит только `ValueError` / `JSONDecodeError`. `IntegrityError` без idem-key / коллизия id → необработанный 500. |
| **Фрагмент** | `except ValueError` / `except json.JSONDecodeError` — нет `sqlite3.Error` |
| **Чем грозит** | Редкий сырой 500 вместо JSON; хуже UX лида. |
| **Как исправить** | Ловить `sqlite3.Error` → JSON 409/500. |

---

#### ERR-06 · 🟡 Средний

| | |
|--|--|
| **Файл** | `server.py:1122–1132` (SameSite=Lax); admin POST/DELETE без Origin-check |
| **Что не так** | State-changing admin API по cookie без CSRF-токена / проверки Origin. |
| **Чем грозит** | Чужой сайт может дернуть действия от имени залогиненного админа. |
| **Как исправить** | CSRF token / проверка `Origin`/`Referer` / `SameSite=Strict` для admin. |

---

#### ERR-07 · ⚪ Низкий

| | |
|--|--|
| **Файл** | `server.py:1444–1448` |
| **Что не так** | `int(Content-Length)` без try — битый заголовок → необработанное исключение. |
| **Чем грозит** | 500 вместо 400. |
| **Как исправить** | try/except → 400. |

---

#### ERR-08 · ⚪ Низкий

| | |
|--|--|
| **Файл** | `ai/core/registry.py` (сериализация ошибок tool); `ai/tools/leads.py:74–79` |
| **Что не так** | Ошибки tool уходят как `str(exc)` / `"Failed to create lead"` в контент для модели → могут попасть в reply. |
| **Чем грозит** | Внутренние тексты валидации в чате пользователю. |
| **Как исправить** | Стабильные коды ошибок для tools; промпт: не цитировать сырой error. |

---

#### FE-ERR-01 · 🟠 Высокий

| | |
|--|--|
| **Файл** | `src/pages/AdminPage.jsx:64,72,79` |
| **Что не так** | Опасные фоллбеки: `data.orders \|\| []`, `data.clients \|\| []`, `Array.isArray(data) ? data : []` — при странной форме ответа показывается «пусто». |
| **Фрагмент** | `setOrders(data.orders \|\| []);` / `setProducts(Array.isArray(data) ? data : []);` |
| **Чем грозит** | Сбой API можно принять за отсутствие заказов/товаров. |
| **Как исправить** | Если нет массива — throw / setError; не подменять тишиной. |

---

#### FE-ERR-02 · 🟠 Высокий

| | |
|--|--|
| **Файл** | `src/pages/AdminPage.jsx:96–104`, `119–121`, `124–128` |
| **Что не так** | Silent `catch (_)` при init panel и смене языка; `handleLoginSuccess` без try/catch вокруг `loadPanelData`. |
| **Фрагмент** | `} catch (_) { // Panel stays open; lists can be refreshed manually. }` |
| **Чем грозит** | После входа пустые списки без сообщения; unhandled rejection при логине. |
| **Как исправить** | Баннер/toast ошибки + retry (как у `handleRefreshOrders`). |

---

#### FE-ERR-03 · 🟡 Средний

| | |
|--|--|
| **Файл** | `src/components/admin/OrderModal.jsx:91–105`, `289–296` |
| **Что не так** | Удаление заказа без флага `deleting` / disable кнопки (в отличие от save/invoice). |
| **Чем грозит** | Двойной клик → гонки DELETE / UX. |
| **Как исправить** | Флаг `deleting` + `disabled`. |

---

#### FE-ERR-04 · 🟡 Средний

| | |
|--|--|
| **Файл** | `src/components/admin/OrderModal.jsx:254–261` |
| **Что не так** | `href={clientWa \|\| "#"}` + `aria-disabled`; клик обрабатывается JS (`preventDefault` + alert), но без JS/`#` — якорь. |
| **Чем грозит** | Jump на `#` / путаница при отсутствии телефона. |
| **Как исправить** | `button disabled` или не рендерить ссылку без номера. |

---

#### FE-ERR-05 · ⚪ Низкий

| | |
|--|--|
| **Файл** | `src/pages/AdminPage.jsx:214–218` |
| **Что не так** | При `checking` показываются заголовок/нота логина без полей и без спиннера. |
| **Чем грозит** | Краткий UX-глюк «форма без инпутов». |
| **Как исправить** | Текст «Проверяю сессию…» / spinner. |

---

#### FE-ERR-06 · ⚪ Низкий

| | |
|--|--|
| **Файл** | `src/lib/adminApi.js:13`; `LeadModal.jsx:127`; `ChatWidget.jsx:525` |
| **Что не так** | `response.json().catch(() => ({}))` маскирует не-JSON тело. |
| **Чем грозит** | Generic error вместо диагностики (приемлемо для UX). |
| **Как исправить** | Логировать status/text в console в dev. |

---

#### DB-01 · 🟡 Средний

| | |
|--|--|
| **Файл** | `crm_store.py:23–24`; `server.py:663–755` (soft-dedupe) |
| **Что не так** | `DB_WRITE_LOCK` — in-process. Soft-dedupe без UNIQUE constraint; multi-worker без idem-key → возможны дубли. |
| **Чем грозит** | Дубли заявок при нескольких процессах. |
| **Как исправить** | Один worker **или** частичный UNIQUE + обязательный Idempotency-Key с клиента. |

---

#### CFG-01 · ⚪ Низкий (допустимый дефолт)

| | |
|--|--|
| **Файл** | `.env.example:1–4`; `server.py:1900–1901` |
| **Что не так** | Дефолт `BIND_HOST=127.0.0.1`, `PORT=8765` — безопасно. `OPENAI_API_KEY` пустой → local mode без падения. |
| **Чем грозит** | Без ключа AI деградирует осознанно (см. STUB-04). |
| **Как исправить** | Документировать degraded mode в `/api/health` (`ai: local\|openai`). |

---

### Не проблемы (осознанно / допустимо)

| Тема | Почему OK |
|------|-----------|
| Silent catch вокруг `localStorage` | Private mode; не маскирует API |
| Placeholder input (`chat.placeholder`) | UI hint, не mock data |
| PDF empty catalog → «Нет товаров» | `catalog.py:424` — явный empty state |
| Invoice без цены → «по договорённости» | `invoice.py:249–253` |
| Password compare через SHA256+compare_digest | `server.py:1728–1731` — timing-safe |
| Blocklist `.env` / `data/` / `src/` | `server.py:1156–1226` |
| LeadModal Idempotency-Key + submittingRef | сильная защита двойного submit |
| ErrorBoundary | `src/components/ErrorBoundary.jsx` + `main.jsx` |
| Тестовые FakeHandler / temp DB | только `test_*.py` |

---

## 4. Ключевые сценарии (кнопка → БД)

### 4.1 Регистрация / вход / восстановление пароля

| Шаг | Поведение | При сбое |
|-----|-----------|----------|
| Регистрация пользователя | **Нет** | — |
| Восстановление пароля | **Нет** | — |
| Admin login (`Login.jsx` → `POST /api/login`) | Rate limit; hash compare; cookie session | 429 / 401 с текстом; кнопка `disabled` при submit |
| Session check (`GET /api/me`) | Silent fail → форма логина | OK |
| Logout | Clear cookie; клиент выходит даже если запрос упал | Сессия на сервере всё ещё валидна (ERR-01) |

### 4.2 Каталог и карточка товара

| Шаг | Поведение | При сбое |
|-----|-----------|----------|
| Публичный каталог | **UI нет** (STUB-02) | Пользователь не видит товары |
| `GET /api/products` | Публичный список из SQLite | Необработанный connect fail → 500 handler |
| Admin Products | Список + PDF | Silent empty при init (FE-ERR-02); refresh показывает alert |
| Карточка товара на сайте | **Нет** | — |
| Заказ из shop | Source `shop` на бэке есть, UI не вызывает | — |

### 4.3 Создание / изменение / отмена заказа

| Шаг | Поведение | При сбое |
|-----|-----------|----------|
| LeadModal submit | Валидация name/phone → `POST /api/orders` + Idempotency-Key → WhatsApp tab | Ошибка inline; вкладка WA закрывается (`external.cancel`) |
| Сервер create_order | Валидация; цена из каталога (не от клиента); soft-dedupe; idempotency | ValueError → 400; IntegrityError без key → 500 (ERR-05); rate limit 429 |
| AI create_lead | Tool → тот же create_order + chat-idem key | Tool error → модель может не сказать явно (ERR-08) |
| Admin update status/notes | Auth + validation statuses | 401/400/404 JSON |
| Delete order | Auth + confirm | Нет double-submit lock (FE-ERR-03); 404 если нет |
| Клиенты | Агрегация из orders + meta `clients` | Не отдельная транзакция «заказ+клиент» при create (клиент появляется из заказа) |

**Гонки:** двойной клик LeadModal — закрыт ref+Idempotency-Key. Два процесса без key — риск дубля (DB-01). «Последний товар на складе» — **склада/остатков нет** (не применимо).

### 4.4 Оплата

**Не реализована.** Оплата вне продукта (WhatsApp/перевод по счёту). PDF-счёт с фейковыми реквизитами (STUB-01) — главный риск «денежного» пути.

### 4.5 Экспорт PDF

| Сценарий | Поведение | При сбое |
|----------|-----------|----------|
| Каталог (`GET …/catalog.pdf`) | Auth; filter ids; ReportLab | 500 JSON «Не удалось сформировать PDF»; traceback в лог |
| Пустой каталог | PDF с текстом «Нет товаров» | OK |
| Нет фото | Placeholder буква | OK (STUB-08) |
| Длинные названия | wrap/ellipsis в catalog/invoice | Усечение визуально |
| Кириллица / KZ | Шрифты Noto/Montserrat/Cormorant в `pdf_export/fonts/` | Если шрифт отсутствует — ошибка генерации → 500 |
| Счёт (`invoice.pdf`) | Auth; 404 если нет заказа; пустая цена → «по договорённости» | 500 JSON; **фейковые реквизиты всегда** (STUB-01) |
| Сумма прописью kz | Упрощённые правила (STUB-09) | Формальная неточность |

### 4.6 Админка / товары

| Действие | UI | API | При сбое |
|----------|----|-----|----------|
| Логин | Login.jsx | POST /api/login | см. 4.1 |
| Заказы/клиенты | список, модалка | GET/POST/DELETE | silent init (FE-ERR-02) |
| Товары list + PDF | Products.jsx | GET products, catalog.pdf | OK на refresh |
| CRUD товаров | **Нет UI** | POST/DELETE есть | Операции только вручную/скриптом (STUB-03) |

---

## 5. Покрытие

### Проверено (исходники прочитаны / просмотрены целиком или по критичным секциям + grep)

**Backend / CRM / AI / PDF**

- `server.py`, `crm_store.py`
- `ai/__init__.py`, `ai/bootstrap.py`
- `ai/core/{__init__,engine,llm,types,files,registry}.py`
- `ai/tools/{__init__,catalog,leads}.py`
- `ai/features/__init__.py`, `ai/features/consultant/{__init__,feature,prompt,local,attachments}.py`
- `pdf_export/{__init__,config,fonts,i18n,images,money_words,invoice,catalog}.py`
- `scripts/migrate_to_sqlite.py`, `scripts/run-server.sh`
- `test_chat_hardening.py`, `test_crm_reliability.py`, `test_invoice.py`, `test_pdf_catalog.py`
- `requirements.txt`, `.env.example`, `.gitignore`, `DEPLOY.md`

**Frontend**

- `src/main.jsx`, `src/App.jsx`, `src/styles.css`
- `src/pages/{LandingPage,AdminPage}.jsx`
- `src/components/ErrorBoundary.jsx`, `LangSwitch.jsx`
- `src/components/landing/{Header,Hero,Story,Services,Process,Contact,Footer,LeadModal,ContactModal,ChatWidget}.jsx`
- `src/components/admin/{Login,Orders,Clients,Products,OrderModal}.jsx`
- `src/hooks/{useModalA11y,useReveal}.js`
- `src/i18n/{I18nContext,translations}.js`
- `src/lib/{adminApi,adminFormat,downloadFile,prices,whatsapp}.js`
- `index.html`, `vite.config.js`, `package.json`
- `e2e/lead-modal.spec.js`, `playwright.config.cjs`
- `public/site.webmanifest`

**Конфиги запуска:** `Start Site.command`, `Stop Site.command`, `start.sh`

### Не удалось проверить / вне scope

| Что | Почему |
|-----|--------|
| Содержимое live `.env` | Секреты; не читалось в отчёт |
| Содержимое `data/crm.db` / реальные заказы | Прод/локальные данные; read-only без инспекции PII |
| Прогон e2e / unit в рантайме | ТЗ: не чинить и не полагаться на запуск; тесты читались как код |
| Бинарные ассеты (jpg/png/woff2/ttf) | Не код; наличие TTF на диске в `pdf_export/fonts/` по дереву файлов — да, содержимое глифов не аудировалось |
| Реальный nginx/systemd на VPS | Только примеры в `DEPLOY.md` |
| Поведение multi-worker gunicorn | Код single `ThreadingHTTPServer`; multi-process не развёрнут в репо |
| Живой OpenAI / реальные таймауты сети | Нет вызовов наружу в рамках аудита |
| `docs/esf-spec/`, PDF-samples | Спеки/сэмплы, не runtime |
| Корневые фото в `Projects/*.jpg` | Не часть приложения |

---

## 6. Что сделано хорошо

1. **Цены заказов не доверяются клиенту** — `create_order` берёт цену из каталога услуг/товаров (`server.py:618–652`).
2. **Idempotency-Key** на лидах (фронт + AI chat) + soft-dedupe по телефону/услуге.
3. **Rate limits** на login / orders / chat; chat concurrency → 503 с понятным текстом.
4. **Защита статики** — blocklist `.env`, `data/`, `src/`, исходников (`PRIVATE_*`).
5. **SQLite WAL + busy_timeout + write lock**; бэкапы CRM по расписанию с логированием ошибок.
6. **PDF ошибки** — клиенту общий текст, traceback только в лог.
7. **LeadModal** — сильная защита double-submit + открытие WA после успешного API.
8. **ErrorBoundary** на корне React; ChatWidget — loading/error/timeout/abort.
9. **Дефолт `BIND_HOST=127.0.0.1`** — не торчит наружу без proxy.
10. **Invoice без цены** честно пишет «по договорённости», а не `0`.

---

## 7. Исправлено в волне 1 (2026-10-12)

| ID | Что сделано | Как проверено |
|----|-------------|----------------|
| **STUB-01** | Реквизиты счёта из `SELLER_*` в `.env`. Пустые обязательные поля → HTTP 400 со списком missing, PDF не генерируется. | `test_invoice.py` (в т.ч. `invoice_missing_seller`); smoke invoice 400→200 |
| **ERR-01** | Сессии: случайный токен в SQLite `admin_sessions`, TTL 7 дней с продлением при активности; logout удаляет сессию. Cookie HttpOnly + SameSite=Lax (+ Secure за HTTPS). | Smoke login/me/logout; `test_invoice.py` HTTP invoice |
| **ERR-02** | Убрана автогенерация пароля. Старт без `ADMIN_PASSWORD` / `ADMIN_PASSWORD_HASH` → FATAL. Хранение только bcrypt в settings; смена пароля чистит все сессии. | Smoke bcrypt login + SystemExit без env; `pip install bcrypt` |
| **ERR-06** | Admin POST/DELETE: `X-CSRF-Token` + Origin/Referer → иначе 403. Login/`/api/me` отдают `csrfToken`; `adminApi` шлёт заголовок. | Smoke DELETE 403 без CSRF / 200 с CSRF |
| **FE-ERR-01/02** | Админка: loading / ошибка + «Повторить» / пустой список только при валидном массиве. 401/403 → logout. Логи `[adminApi]` / `[admin]` в консоль. | Ревью `AdminPage.jsx` + сборка логики; smoke `/api/orders` после login |

**Коммиты:** `fix(STUB-01)`, `fix(ERR-01)`, `fix(ERR-02)`, `fix(ERR-06)`, `fix(FE-ERR-01/02)`.

**Общий smoke волны 1:** публичный лид, AI-чат, admin orders, invoice (missing→ok), catalog PDF — пройден.

### Что сделать на проде вручную

1. В `.env` задать **`ADMIN_PASSWORD_HASH`** (предпочтительно) или `ADMIN_PASSWORD` — без этого сервер не стартует.
2. Заполнить обязательные **`SELLER_*`**, включая явный **`SELLER_VAT_RATE=0`** («Без НДС») или `16` — пустой VAT больше не допускается.
3. При www + apex: **`ALLOWED_ORIGINS=https://domain,https://www.domain`**.
4. HTTPS: nginx с **`X-Forwarded-Proto: https`** или `SECURE_COOKIES=1` (не открывать прод по http с Secure).
5. **Сохранять `data/crm.db`** при деплое — там же таблица `admin_sessions`.
6. `pip install -r requirements.txt` (bcrypt) + `npm run build`.
7. **Перелогинить всех админов** после выкладки волны 1.
8. Ручная проверка: вход → сохранить изменение → скачать счёт.

### Pre-prod ответы (четыре проверки)

| Вопрос | Ответ |
|--------|--------|
| `SELLER_VAT_RATE` не задан? | **Ошибка 400**, не тихий 0%/12%. Явный `0` → в счёте «Без НДС». |
| Secure + HTTPS | Auto по `X-Forwarded-Proto`, либо `SECURE_COOKIES=1`. Без proto на HTTPS cookie не Secure; с Secure на http — логин «ломается». |
| CSRF Origin | Host + X-Forwarded-Host + `ALLOWED_ORIGINS` (www/apex). |
| Где сессии? | Таблица `admin_sessions` внутри **`data/crm.db`** (переживает рестарт, если `data/` не затирают). |

---

*Волна 1 внесена в код и закоммичена по ID находок.*
