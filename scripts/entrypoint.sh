#!/usr/bin/env sh
set -e

echo "==> Applying database migrations (alembic upgrade head)"
alembic upgrade head

echo "==> Starting API server on :${APP_PORT:-8080}"
exec uvicorn app.main:app --host 0.0.0.0 --port "${APP_PORT:-8080}" --no-access-log
