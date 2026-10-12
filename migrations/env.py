"""Alembic environment (async). The URL comes from the settings, or from
`config.attributes["url"]` when tests point it at the test database."""

import asyncio

from alembic import context
from sqlalchemy import Connection, pool
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.db import models  # noqa: F401  (registers the tables on Base.metadata)
from app.db.base import Base

target_metadata = Base.metadata


def _database_url() -> str:
    override = context.config.attributes.get("url")
    return str(override) if override else get_settings().database_url


def _is_ours(name: str | None, type_: str, parent_names: object) -> bool:
    """Leave alone the tables LangGraph's checkpointer creates for itself."""
    return type_ != "table" or name in target_metadata.tables


def _run(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, include_name=_is_ours)
    with context.begin_transaction():
        context.run_migrations()


async def _run_online() -> None:
    engine = create_async_engine(_database_url(), poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(_run)
    await engine.dispose()


if context.is_offline_mode():
    raise SystemExit("Offline migrations are not supported in this project.")

asyncio.run(_run_online())
