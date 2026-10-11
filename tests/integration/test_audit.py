"""Rule 7: the audit log is append-only and hash-chained."""

import pytest
from sqlalchemy import delete, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import log as audit
from app.db.models import AuditRecord, Document


async def _document(session: AsyncSession) -> Document:
    document = Document(filename="doc-0001.pdf", content_sha256="0" * 64)
    session.add(document)
    await session.flush()
    return document


async def test_records_are_chained_and_verify(session: AsyncSession) -> None:
    document = await _document(session)

    first = await audit.append(session, step="uploaded", document_id=document.id)
    second = await audit.append(
        session, step="classified", document_id=document.id, payload={"label": "invoice"}
    )
    third = await audit.append(session, step="system_started")

    assert [first.seq, second.seq, third.seq] == [1, 2, 3]
    assert first.prev_hash == audit.GENESIS_HASH
    assert second.prev_hash == first.record_hash
    assert third.prev_hash == second.record_hash
    assert await audit.verify_chain(session) == audit.ChainVerification(ok=True, records_checked=3)


async def test_empty_chain_verifies(session: AsyncSession) -> None:
    assert await audit.verify_chain(session) == audit.ChainVerification(ok=True, records_checked=0)


async def test_step_already_ran_is_per_document_and_step(session: AsyncSession) -> None:
    document = await _document(session)
    other = await _document(session)
    await audit.append(session, step="classified", document_id=document.id)

    assert await audit.step_already_ran(session, document.id, "classified")
    assert not await audit.step_already_ran(session, document.id, "extracted")
    assert not await audit.step_already_ran(session, other.id, "classified")


async def test_update_is_refused_by_the_database(session: AsyncSession) -> None:
    await audit.append(session, step="uploaded")

    with pytest.raises(DBAPIError, match="append-only"):
        async with session.begin_nested():
            await session.execute(update(AuditRecord).values(step="changed"))


async def test_delete_is_refused_by_the_database(session: AsyncSession) -> None:
    await audit.append(session, step="uploaded")

    with pytest.raises(DBAPIError, match="append-only"):
        async with session.begin_nested():
            await session.execute(delete(AuditRecord))


async def test_truncate_is_refused_by_the_database(session: AsyncSession) -> None:
    with pytest.raises(DBAPIError, match="append-only"):
        async with session.begin_nested():
            await session.execute(text("TRUNCATE audit_log"))


async def test_tampering_behind_the_trigger_breaks_the_chain(session: AsyncSession) -> None:
    """Someone with database rights can switch the trigger off. The hash chain still shows it."""
    for step in ("uploaded", "classified", "extracted"):
        await audit.append(session, step=step, payload={"note": "original"})

    await session.execute(text("ALTER TABLE audit_log DISABLE TRIGGER USER"))
    await session.execute(
        text("""UPDATE audit_log SET payload = '{"note": "edited"}' WHERE seq = 2""")
    )

    result = await audit.verify_chain(session)
    assert result == audit.ChainVerification(ok=False, records_checked=1, first_bad_seq=2)


async def test_removing_a_record_breaks_the_chain(session: AsyncSession) -> None:
    for step in ("uploaded", "classified", "extracted"):
        await audit.append(session, step=step)

    await session.execute(text("ALTER TABLE audit_log DISABLE TRIGGER USER"))
    await session.execute(text("DELETE FROM audit_log WHERE seq = 2"))

    result = await audit.verify_chain(session)
    assert result == audit.ChainVerification(ok=False, records_checked=1, first_bad_seq=3)
