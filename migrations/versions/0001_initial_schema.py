from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE users (
            id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            email         text NOT NULL UNIQUE,
            password_hash text NOT NULL,
            created_at    timestamptz NOT NULL DEFAULT now()
        );
        """
    )

    op.execute(
        """
        CREATE TABLE products (
            id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            name           text NOT NULL,
            price          double precision NOT NULL CHECK (price > 0),
            stock_quantity integer NOT NULL CHECK (stock_quantity >= 0),
            created_at     timestamptz NOT NULL DEFAULT now(),
            updated_at     timestamptz NOT NULL DEFAULT now()
        );
        """
    )

    op.execute(
        """
        CREATE TABLE orders (
            id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id      uuid NOT NULL REFERENCES users (id),
            status       text NOT NULL DEFAULT 'pending'
                         CHECK (status IN ('pending', 'confirmed', 'cancelled')),
            total_price  double precision NOT NULL,
            created_at   timestamptz NOT NULL DEFAULT now(),
            expires_at   timestamptz,
            confirmed_at timestamptz,
            cancelled_at timestamptz
        );
        """
    )
    op.execute(
        "CREATE INDEX idx_orders_status_expires ON orders (status, expires_at);"
    )
    op.execute("CREATE INDEX idx_orders_user ON orders (user_id);")

    op.execute(
        """
        CREATE TABLE order_items (
            id         uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            order_id   uuid NOT NULL REFERENCES orders (id) ON DELETE CASCADE,
            product_id uuid NOT NULL REFERENCES products (id),
            quantity   integer NOT NULL CHECK (quantity > 0),
            unit_price double precision NOT NULL
        );
        """
    )
    op.execute("CREATE INDEX idx_order_items_order ON order_items (order_id);")

    op.execute(
        """
        CREATE TABLE idempotency_keys (
            id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            user_id         uuid NOT NULL REFERENCES users (id),
            idempotency_key text NOT NULL,
            status          text NOT NULL DEFAULT 'processing'
                            CHECK (status IN ('processing', 'completed')),
            order_id        uuid REFERENCES orders (id),
            response_code   integer,
            response_body   jsonb,
            created_at      timestamptz NOT NULL DEFAULT now(),
            UNIQUE (user_id, idempotency_key)
        );
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS idempotency_keys;")
    op.execute("DROP TABLE IF EXISTS order_items;")
    op.execute("DROP TABLE IF EXISTS orders;")
    op.execute("DROP TABLE IF EXISTS products;")
    op.execute("DROP TABLE IF EXISTS users;")
