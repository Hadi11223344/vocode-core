"""
Alembic Environment Configuration
===================================

This module configures Alembic to work with our async SQLAlchemy engine
and the VOIA ORM models. It supports both offline (SQL generation) and
online (direct DB connection) migration modes.

Usage:
    # Generate a new migration after changing models:
    cd voice_platform
    alembic revision --autogenerate -m "description of change"

    # Apply migrations:
    alembic upgrade head

    # View current version:
    alembic current

    # View migration history:
    alembic history
"""

import asyncio
import os
import sys
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

# Add voice_platform parent to path so imports work
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from voice_platform.database import DATABASE_URL, Base

# Alembic Config object
config = context.config

# Setup loggers from alembic.ini
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata for autogenerate support
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode — generates SQL without connecting."""
    url = DATABASE_URL
    # Strip async driver suffix for offline SQL generation
    for async_driver in ("+aiosqlite", "+asyncpg"):
        url = url.replace(async_driver, "")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection):
    """Run migrations with a live connection."""
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode with async engine."""
    connectable = create_async_engine(
        DATABASE_URL,
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
