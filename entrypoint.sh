#!/bin/sh

set -eu

if [ "$#" -eq 0 ]; then
    echo "entrypoint: running database migrations"
    alembic upgrade head
    set -- gunicorn app.main:app -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000 -w 4
fi

exec "$@"
