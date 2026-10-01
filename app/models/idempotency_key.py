from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING, Any

from sqlalchemy import Enum as SQLEnum
from sqlalchemy import ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.order import Order
    from app.models.user import User


class IdempotencyStatus(str, Enum):
    PROCESSING = "processing"
    COMPLETED = "completed"


class IdempotencyKey(Base):
    __tablename__ = "idempotency_keys"

    __table_args__ = (
        UniqueConstraint("user_id", "key", name="uq_idempotency_keys_user_id_key"),
        Index("ix_idempotency_keys_created_at", "created_at"),
    )

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    key: Mapped[str] = mapped_column(String(255), nullable=False)

    request_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    status: Mapped[IdempotencyStatus] = mapped_column(
        SQLEnum(IdempotencyStatus, native_enum=False),
        default=IdempotencyStatus.PROCESSING,
        nullable=False,
    )
    response_code: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)

    order_id: Mapped[int | None] = mapped_column(
        ForeignKey("orders.id", ondelete="SET NULL"), nullable=True
    )

    user: Mapped[User] = relationship("User")
    order: Mapped[Order | None] = relationship("Order")
