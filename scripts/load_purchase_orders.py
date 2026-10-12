"""Load the synthetic purchase orders into the database.

uv run python scripts/load_purchase_orders.py
"""

import argparse
import asyncio
import json
from pathlib import Path

from app.config import get_settings
from app.db.base import create_engine, create_session_factory
from app.validation.purchase_orders import upsert_purchase_orders


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path, default=Path("data/synthetic/purchase_orders.json"))
    arguments = parser.parse_args()

    orders = json.loads(arguments.file.read_text(encoding="utf-8"))
    engine = create_engine(get_settings().database_url)
    try:
        async with create_session_factory(engine)() as session:
            count = await upsert_purchase_orders(session, orders)
            await session.commit()
    finally:
        await engine.dispose()
    print(f"Loaded {count} purchase orders.")


if __name__ == "__main__":
    asyncio.run(main())
