"""
Alembic environment configuration for PGVectorRAGIndexer.

Reads database connection settings from the existing DatabaseConfig
so there is no duplication of connection parameters.
"""

import sys
import os
from logging.config import fileConfig

from sqlalchemy import engine_from_config, pool
from alembic import context

# Add project root to path so we can import config
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import get_config

# Alembic Config object
config = context.config

# Set up logging from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# No SQLAlchemy MetaData for autogenerate (we use raw SQL migrations)
target_metadata = None


def get_database_url() -> str:
    """Get database URL.

    Priority:
    1. sqlalchemy.url already set in Alembic config (e.g., by tests or CLI)
    2. DatabaseConfig.connection_string from application config
    """
    # Check if URL was explicitly set (e.g., by tests or programmatic callers)
    url = config.get_main_option("sqlalchemy.url")
    if url:
        return url

    # Fall back to application config
    try:
        app_config = get_config()
        return app_config.database.connection_string
    except Exception:
        raise RuntimeError(
            "No database URL configured. Set sqlalchemy.url in alembic.ini "
            "or configure DatabaseConfig via environment variables."
        )


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    Generates SQL scripts without connecting to the database.
    """
    url = get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    Connects to the database and applies migrations directly.

    NOTE: We use AUTOCOMMIT isolation level because pgvector's
    CREATE EXTENSION must be committed before the VECTOR type
    is available for CREATE TABLE in the same migration.
    """
    # Build SQLAlchemy config with our database URL
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = get_database_url()

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect().execution_options(
        isolation_level="AUTOCOMMIT"
    ) as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
        )
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
