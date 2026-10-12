"""Starts the application with fake services on its own database for the browser tests."""

import asyncio
import os
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import httpx
import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool
from synthetic.build import Dataset, generate
from synthetic.write import render_document

from app.config import get_settings
from tests.e2e.server import DOCUMENTS, SEED

REPO_ROOT = Path(__file__).resolve().parents[2]


async def _recreate(server_url: str, name: str) -> None:
    engine = create_async_engine(
        make_url(server_url).set(database="postgres"),
        isolation_level="AUTOCOMMIT",
        poolclass=NullPool,
    )
    async with engine.connect() as connection:
        await connection.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        await connection.execute(text(f'CREATE DATABASE "{name}"'))
    await engine.dispose()


@pytest.fixture(scope="session")
def base_url() -> Iterator[str]:
    """Used by pytest-playwright as the address of the application."""
    configured = make_url(get_settings().database_url)
    e2e_url = configured.set(database=f"{configured.database}_e2e")
    url_text = e2e_url.render_as_string(hide_password=False)
    database = e2e_url.database
    assert database is not None

    def prepare_database() -> None:
        asyncio.run(_recreate(url_text, database))
        alembic_config = Config(str(REPO_ROOT / "alembic.ini"))
        alembic_config.attributes["url"] = url_text
        command.upgrade(alembic_config, "head")

    # Playwright keeps an event loop running in this thread, and both steps
    # start their own, so they run in another thread.
    with ThreadPoolExecutor(max_workers=1) as executor:
        executor.submit(prepare_database).result()

    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    environment = {
        **os.environ,
        "DATABASE_URL": url_text,
        "PYTHONPATH": f"{REPO_ROOT}{os.pathsep}{REPO_ROOT / 'scripts'}",
    }
    server = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "tests.e2e.server:app", "--port", str(port)],
        cwd=REPO_ROOT,
        env=environment,
    )
    address = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                if httpx.get(f"{address}/health", timeout=1).status_code == 200:
                    break
            except httpx.HTTPError:
                time.sleep(0.2)
        else:
            raise RuntimeError("the application did not start")
        yield address
    finally:
        server.terminate()
        server.wait(timeout=10)


@pytest.fixture(scope="session")
def dataset() -> Dataset:
    return generate(DOCUMENTS, SEED)


@pytest.fixture(scope="session")
def pdf_folder(dataset: Dataset, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """The digital documents of the set as files, for the upload form."""
    folder = tmp_path_factory.mktemp("pdfs")
    for truth in dataset.documents:
        if not truth.scanned:
            (folder / truth.filename).write_bytes(
                render_document(truth, dataset.plans[truth.doc_id])
            )
    return folder
