from __future__ import annotations

from datetime import timedelta

from celery import Celery
from celery.schedules import crontab

from app.core.config import settings

celery_app = Celery(
    "order_and_inventory",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["app.tasks.jobs"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    result_expires=3600,
    timezone="UTC",
    enable_utc=True,
    worker_prefetch_multiplier=1,
)

celery_app.conf.beat_schedule = {
    "expire-pending-orders": {
        "task": "orders.expire_pending",
        "schedule": timedelta(seconds=settings.EXPIRE_ORDERS_INTERVAL_SECONDS),
        "options": {"expires": settings.EXPIRE_ORDERS_INTERVAL_SECONDS},
    },
    "purge-idempotency-keys": {
        "task": "idempotency_keys.purge_expired",
        "schedule": crontab(minute=0),
    },
}
