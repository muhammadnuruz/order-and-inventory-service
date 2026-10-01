from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order, OrderStatus
from app.models.order_item import OrderItem


class OrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        user_id: int,
        total_price: Decimal,
        expire_minutes: int,
        items: list[OrderItem],
    ) -> Order:
        order = Order(
            user_id=user_id,
            status=OrderStatus.PENDING,
            total_price=total_price,
            expires_at=func.now() + timedelta(minutes=expire_minutes),
            items=items,
        )
        self.session.add(order)
        await self.session.flush()
        await self.session.refresh(order, ["expires_at", "created_at", "updated_at"])
        return order

    async def get(self, order_id: int) -> Order | None:
        return await self.session.get(Order, order_id, populate_existing=True)

    async def cancel_pending(self, order_id: int, user_id: int) -> Order | None:
        return await self._transition(
            order_id,
            user_id,
            Order.status == OrderStatus.PENDING,
            status=OrderStatus.CANCELLED,
            cancelled_at=func.now(),
        )

    async def confirm_pending(self, order_id: int, user_id: int) -> Order | None:
        return await self._transition(
            order_id,
            user_id,
            (Order.status == OrderStatus.PENDING) & (Order.expires_at > func.now()),
            status=OrderStatus.CONFIRMED,
            confirmed_at=func.now(),
        )

    async def lock_expired_pending(self, limit: int) -> list[int]:
        result = await self.session.execute(
            select(Order.id)
            .where(Order.status == OrderStatus.PENDING, Order.expires_at <= func.now())
            .order_by(Order.id)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        return list(result.scalars().all())

    async def cancel_many(self, order_ids: list[int]) -> list[int]:
        result = await self.session.execute(
            update(Order)
            .where(Order.id.in_(order_ids), Order.status == OrderStatus.PENDING)
            .values(status=OrderStatus.CANCELLED, cancelled_at=func.now())
            .returning(Order.id)
            .execution_options(synchronize_session=False)
        )
        return list(result.scalars().all())

    async def _transition(
        self, order_id: int, user_id: int, condition: ColumnElement[bool], **values: Any
    ) -> Order | None:
        result = await self.session.execute(
            update(Order)
            .where(Order.id == order_id, Order.user_id == user_id, condition)
            .values(**values)
            .returning(Order.id)
            .execution_options(synchronize_session=False)
        )
        if result.scalar_one_or_none() is None:
            return None
        return await self.get(order_id)
