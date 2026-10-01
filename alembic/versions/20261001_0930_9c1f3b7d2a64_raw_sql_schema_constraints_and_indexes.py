"""Order statuses, constraints, indexes and updated_at trigger

Revision ID: 9c1f3b7d2a64
Revises: 47b2cca1c9ba
Create Date: 2026-10-01 09:30:00.000000

"""
from collections.abc import Sequence

from alembic import op

revision: str = "9c1f3b7d2a64"
down_revision: str | Sequence[str] | None = "47b2cca1c9ba"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ("users", "products", "orders", "order_items", "idempotency_keys")


def upgrade() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ALTER COLUMN updated_at SET DEFAULT now()")
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_updated_at
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION set_updated_at()
            """
        )

    op.execute(
        """
        ALTER TABLE orders ALTER COLUMN status TYPE varchar(16) USING lower(status);
        UPDATE orders SET status = 'confirmed' WHERE status IN ('paid', 'shipped', 'delivered');
        ALTER TABLE orders ALTER COLUMN status SET DEFAULT 'pending';
        ALTER TABLE orders ADD CONSTRAINT ck_orders_status
            CHECK (status IN ('pending', 'confirmed', 'cancelled'));
        ALTER TABLE orders ADD CONSTRAINT ck_orders_total_price_non_negative
            CHECK (total_price >= 0);
        UPDATE orders SET expires_at = created_at + interval '15 minutes' WHERE expires_at IS NULL;
        ALTER TABLE orders ALTER COLUMN expires_at SET NOT NULL;

        CREATE INDEX ix_orders_user_id ON orders (user_id);
        CREATE INDEX ix_orders_pending_expires_at ON orders (expires_at) WHERE status = 'pending';
        """
    )

    op.execute(
        """
        ALTER TABLE order_items ALTER COLUMN quantity DROP DEFAULT;
        ALTER TABLE order_items ADD CONSTRAINT ck_order_items_quantity_positive
            CHECK (quantity > 0);
        ALTER TABLE order_items ADD CONSTRAINT ck_order_items_unit_price_non_negative
            CHECK (unit_price >= 0);
        ALTER TABLE order_items ADD CONSTRAINT uq_order_items_order_id_product_id
            UNIQUE (order_id, product_id);
        CREATE INDEX ix_order_items_product_id ON order_items (product_id);
        """
    )

    op.execute(
        """
        ALTER TABLE idempotency_keys ALTER COLUMN status TYPE varchar(16) USING lower(status);
        UPDATE idempotency_keys SET status = 'processing' WHERE status = 'failed';
        ALTER TABLE idempotency_keys ALTER COLUMN status SET DEFAULT 'processing';
        ALTER TABLE idempotency_keys ADD CONSTRAINT ck_idempotency_keys_status
            CHECK (status IN ('processing', 'completed'));
        CREATE INDEX ix_idempotency_keys_created_at ON idempotency_keys (created_at);
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP INDEX ix_idempotency_keys_created_at;
        ALTER TABLE idempotency_keys DROP CONSTRAINT ck_idempotency_keys_status;
        ALTER TABLE idempotency_keys ALTER COLUMN status DROP DEFAULT;
        ALTER TABLE idempotency_keys ALTER COLUMN status TYPE varchar(10) USING upper(status);

        DROP INDEX ix_order_items_product_id;
        ALTER TABLE order_items DROP CONSTRAINT uq_order_items_order_id_product_id;
        ALTER TABLE order_items DROP CONSTRAINT ck_order_items_unit_price_non_negative;
        ALTER TABLE order_items DROP CONSTRAINT ck_order_items_quantity_positive;

        DROP INDEX ix_orders_pending_expires_at;
        DROP INDEX ix_orders_user_id;
        ALTER TABLE orders ALTER COLUMN expires_at DROP NOT NULL;
        ALTER TABLE orders DROP CONSTRAINT ck_orders_total_price_non_negative;
        ALTER TABLE orders DROP CONSTRAINT ck_orders_status;
        ALTER TABLE orders ALTER COLUMN status DROP DEFAULT;
        UPDATE orders SET status = 'paid' WHERE status = 'confirmed';
        ALTER TABLE orders ALTER COLUMN status TYPE varchar(9) USING upper(status);
        """
    )

    for table in TABLES:
        op.execute(f"DROP TRIGGER trg_{table}_updated_at ON {table}")
        op.execute(f"ALTER TABLE {table} ALTER COLUMN updated_at DROP DEFAULT")
    op.execute("DROP FUNCTION set_updated_at()")
