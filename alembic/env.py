from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool

from alembic import context
from app.core.config import settings

# Alembic Config object — gives access to values in alembic.ini.
config = context.config

# Inject the DB URL at runtime from Settings rather than hardcoding it in
# alembic.ini. This keeps the single source of truth in the app config / env.
config.set_main_option("sqlalchemy.url", settings.SYNC_DATABASE_URL)

# Configure Python logging from the alembic.ini [loggers] sections.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# No ORM metadata: migrations are written by hand as plain SQL.
target_metadata = None


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Emits SQL to stdout using only a URL (no live DB connection). Useful for
    generating a migration script to run by hand:  alembic upgrade head --sql
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode against a live database.

    We build a normal SYNC engine (see module docstring) and run migrations
    inside a transaction so a failing migration rolls back cleanly.
    """
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


# Entry point: pick offline vs online based on how Alembic was invoked.
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
