# --- frontend build ---
FROM node:22-alpine AS frontend
WORKDIR /build
COPY package.json package-lock.json ./
RUN npm ci
COPY index.html vite.config.js ./
# public/assets → ../assets (symlink); copy assets first so the link resolves.
COPY assets ./assets
COPY public ./public
COPY src ./src
RUN npm run build

# --- runtime ---
FROM python:3.12-slim AS runtime
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8765 \
    BIND_HOST=0.0.0.0

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libjpeg62-turbo \
        zlib1g \
        libfreetype6 \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 --shell /usr/sbin/nologin app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py crm_store.py ./
COPY ai ./ai
COPY pdf_export ./pdf_export
COPY --from=frontend /build/dist ./dist
COPY docker-entrypoint.sh /docker-entrypoint.sh

RUN mkdir -p /app/data/uploads /app/data/backups /app/assets/products \
    && chown -R app:app /app \
    && chmod 755 /docker-entrypoint.sh

# Entrypoint starts as root only to fix volume ownership (backups/uploads), then drops to uid 10001.
EXPOSE 8765

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=3)"

ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["python", "server.py"]
