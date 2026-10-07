# --- frontend build
FROM node:22-alpine AS ui
WORKDIR /ui
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- API + static UI
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 APP_ENV=production STATIC_DIR=/app/static
WORKDIR /app/backend
COPY backend/requirements.txt .
RUN pip install -r requirements.txt
COPY backend/ .
COPY --from=ui /ui/dist /app/static
RUN useradd -r -u 10001 epm && mkdir -p /data && chown epm /data
USER epm
EXPOSE 8000
# Run migrations as a separate release step in production: `docker compose run --rm api alembic upgrade head`
CMD ["uvicorn", "api.main:app_factory", "--factory", "--host", "0.0.0.0", "--port", "8000"]
