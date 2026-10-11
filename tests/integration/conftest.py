"""Integration tests run against local PostgreSQL (docker compose up -d).

They use a separate database, the configured name plus "_test", which is
dropped and rebuilt from the Alembic migrations once per test run. Each test
runs in a transaction that is rolled back afterwards.
"""

import asyncio
from collections.abc import AsyncIterator

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import URL, make_url, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings


async def _recreate_database(server_url: URL, name: str) -> None:
    engine = create_async_engine(
        server_url.set(database="postgres"), isolation_level="AUTOCOMMIT", poolclass=NullPool
    )
    async with engine.connect() as connection:
        await connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        await connection.execute(text(f'CREATE DATABASE "{name}"'))
    await engine.dispose()


@pytest.fixture(scope="session")
def test_database_url() -> URL:
    configured = make_url(get_settings().database_url)
    test_url = configured.set(database=f"{configured.database}_test")
    assert test_url.database is not None
    asyncio.run(_recreate_database(configured, test_url.database))

    alembic_config = Config("alembic.ini")
    alembic_config.attributes["url"] = test_url.render_as_string(hide_password=False)
    command.upgrade(alembic_config, "head")
    return test_url


@pytest.fixture
async def session_factory(
    test_database_url: URL,
) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    """Sessions that share one connection and one outer transaction. Code under
    test may commit as often as it likes: everything is rolled back afterwards."""
    engine = create_async_engine(test_database_url, poolclass=NullPool)
    async with engine.connect() as connection:
        transaction = await connection.begin()
        yield async_sessionmaker(
            bind=connection, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        await transaction.rollback()
    await engine.dispose()


@pytest.fixture
async def session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as db_session:
        yield db_session
