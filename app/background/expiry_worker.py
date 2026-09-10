import asyncio

from app.config import get_settings
from app.services import order_service

async def _run_loop() -> None:
    interval = get_settings().expiry_scan_interval_seconds
    while True:
        try:
            await order_service.expire_pending_orders()
        except Exception:
            raise

        await asyncio.sleep(interval)


def start(loop_holder: dict) -> None:
    loop_holder["task"] = asyncio.create_task(_run_loop())


async def stop(loop_holder: dict) -> None:
    task = loop_holder.get("task")
    if task is not None:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
