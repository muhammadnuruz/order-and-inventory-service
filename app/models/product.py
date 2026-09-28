from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import String, Numeric, Integer, CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from decimal import Decimal

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.order_item import OrderItem

class Product(Base):
    __tablename__ = "products"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    price: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    stock_quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    __table_args__ = (
        CheckConstraint("price >= 0", name="check_product_price_non_negative"),
        CheckConstraint("stock_quantity >= 0", name="check_product_stock_non_negative"),
    )
    order_items: Mapped[list[OrderItem]] = relationship(
        "OrderItem", back_populates="product"
    )
