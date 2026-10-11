"""Runs the stage 2 steps in order for one document.

A plain loop for now. Stage 3 replaces it with a LangGraph graph that adds
validation, scoring and routing. Because the steps are idempotent, running a
document again after a failure continues where it stopped.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.workflow import steps
from app.workflow.steps import Services


async def process_document(
    session_factory: async_sessionmaker[AsyncSession],
    services: Services,
    document_id: uuid.UUID,
    variants: Sequence[str],
) -> str:
    """Process one document and return its label. Each step commits on its own."""
    async with session_factory() as session:
        await steps.read_text(session, services, document_id)
        await session.commit()

    async with session_factory() as session:
        label = await steps.classify_document(session, services, document_id)
        await session.commit()

    if not steps.needs_extraction(label):
        return label

    async with session_factory() as session:
        await steps.read_invoice_fields(session, services, document_id)
        await session.commit()

    for variant in variants:
        async with session_factory() as session:
            await steps.extract_invoice(session, services, document_id, variant)
            await session.commit()
    return label
