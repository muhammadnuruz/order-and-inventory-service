"""Order statuses, constraints and indexes

Revision ID: 9c1f3b7d2a64
Revises: 47b2cca1c9ba
Create Date: 2026-10-01 16:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9c1f3b7d2a64'
down_revision: Union[str, Sequence[str], None] = '47b2cca1c9ba'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = ('users', 'products', 'orders', 'order_items', 'idempotency_keys')


def upgrade() -> None:
    """Upgrade schema."""
    for table in TABLES:
        op.alter_column(table, 'updated_at', server_default=sa.text('now()'))

    op.execute("UPDATE orders SET status = 'CONFIRMED' WHERE status IN ('PAID', 'SHIPPED', 'DELIVERED')")
    op.execute("UPDATE orders SET expires_at = created_at + interval '15 minutes' WHERE expires_at IS NULL")
    op.alter_column('orders', 'expires_at', existing_type=sa.DateTime(timezone=True), nullable=False)
    op.create_check_constraint('ck_orders_status', 'orders', "status IN ('PENDING', 'CONFIRMED', 'CANCELLED')")
    op.create_check_constraint('ck_orders_total_price_non_negative', 'orders', 'total_price >= 0')
    op.create_index('ix_orders_user_id', 'orders', ['user_id'])
    op.create_index(
        'ix_orders_pending_expires_at', 'orders', ['expires_at'],
        postgresql_where=sa.text("status = 'PENDING'"),
    )

    op.alter_column('order_items', 'quantity', server_default=None)
    op.create_check_constraint('ck_order_items_quantity_positive', 'order_items', 'quantity > 0')
    op.create_check_constraint('ck_order_items_unit_price_non_negative', 'order_items', 'unit_price >= 0')
    op.create_unique_constraint('uq_order_items_order_id_product_id', 'order_items', ['order_id', 'product_id'])
    op.create_index('ix_order_items_product_id', 'order_items', ['product_id'])

    op.execute("UPDATE idempotency_keys SET status = 'PROCESSING' WHERE status = 'FAILED'")
    op.create_index('ix_idempotency_keys_created_at', 'idempotency_keys', ['created_at'])


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index('ix_idempotency_keys_created_at', table_name='idempotency_keys')

    op.drop_index('ix_order_items_product_id', table_name='order_items')
    op.drop_constraint('uq_order_items_order_id_product_id', 'order_items', type_='unique')
    op.drop_constraint('ck_order_items_unit_price_non_negative', 'order_items', type_='check')
    op.drop_constraint('ck_order_items_quantity_positive', 'order_items', type_='check')

    op.drop_index('ix_orders_pending_expires_at', table_name='orders')
    op.drop_index('ix_orders_user_id', table_name='orders')
    op.drop_constraint('ck_orders_total_price_non_negative', 'orders', type_='check')
    op.drop_constraint('ck_orders_status', 'orders', type_='check')
    op.alter_column('orders', 'expires_at', existing_type=sa.DateTime(timezone=True), nullable=True)
    op.execute("UPDATE orders SET status = 'PAID' WHERE status = 'CONFIRMED'")

    for table in TABLES:
        op.alter_column(table, 'updated_at', server_default=None)
