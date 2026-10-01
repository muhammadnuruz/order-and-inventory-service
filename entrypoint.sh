#!/bin/sh

set -eu

if [ "$#" -eq 0 ]; then
    echo "entrypoint: running database migrations"
    alembic upgrade head
    set -- gunicorn app.main:app -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000 \
        -w "${WEB_CONCURRENCY:-4}" --forwarded-allow-ips "*"
fi

exec "$@"
