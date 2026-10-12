"""Loading purchase orders into the database."""

import json
from collections.abc import Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PurchaseOrder


async def upsert_purchase_orders(session: AsyncSession, orders: Sequence[dict[str, Any]]) -> int:
    """Insert or update by order number. The caller commits."""
    if not orders:
        return 0
    rows = [
        {
            "po_number": order["po_number"],
            "supplier_name": order["supplier_name"],
            "supplier_vat_number": order["supplier_vat_number"],
            "amount": Decimal(str(order["amount"])),
            "currency": order["currency"],
        }
        for order in orders
    ]
    statement = insert(PurchaseOrder).values(rows)
    updated = {
        name: statement.excluded[name]
        for name in ("supplier_name", "supplier_vat_number", "amount", "currency")
    }
    await session.execute(
        statement.on_conflict_do_update(index_elements=["po_number"], set_=updated)
    )
    return len(rows)


async def seed_from_file(session: AsyncSession, path: Path) -> int:
    """Load purchase orders from a JSON file. Safe to repeat: orders are updated in place."""
    orders = json.loads(path.read_text(encoding="utf-8"))
    count = await upsert_purchase_orders(session, orders)
    await session.commit()
    return count
