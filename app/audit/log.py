"""Append-only, hash-chained audit log (rule 7).

Each record stores the hash of the record before it, so changing or removing an
old record breaks every hash after it. There is no update or delete function
here, and the database rejects both with a trigger (see the first migration).

Payloads hold ids, statuses, reasons and counts. Never document content or
personal identifiers (rule 8).
"""

import hashlib
import json
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AuditRecord

# Floats are left out on purpose: their text form is not stable enough to hash.
type JsonValue = str | int | bool | list[JsonValue] | dict[str, JsonValue] | None

GENESIS_HASH = "0" * 64
# Any fixed number works. It names the Postgres advisory lock that serialises appends.
_APPEND_LOCK_KEY = 7_302_114_001


@dataclass(frozen=True)
class ChainVerification:
    ok: bool
    records_checked: int
    first_bad_seq: int | None = None


def compute_hash(
    *,
    seq: int,
    document_id: uuid.UUID | None,
    step: str,
    payload: Mapping[str, JsonValue],
    created_at: datetime,
    prev_hash: str,
) -> str:
    body = json.dumps(
        {
            "seq": seq,
            "document_id": str(document_id) if document_id else None,
            "step": step,
            "payload": payload,
            "created_at": created_at.astimezone(UTC).isoformat(),
            "prev_hash": prev_hash,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


async def append(
    session: AsyncSession,
    *,
    step: str,
    document_id: uuid.UUID | None = None,
    payload: Mapping[str, JsonValue] | None = None,
) -> AuditRecord:
    """Add a record to the chain. The caller commits, so a step's output and its
    audit record land in the same transaction."""
    # Two appends at once would both read the same "last" record and fork the chain.
    await session.execute(select(func.pg_advisory_xact_lock(_APPEND_LOCK_KEY)))
    last = (
        await session.execute(select(AuditRecord).order_by(AuditRecord.seq.desc()).limit(1))
    ).scalar_one_or_none()

    seq = last.seq + 1 if last else 1
    prev_hash = last.record_hash if last else GENESIS_HASH
    created_at = datetime.now(UTC)
    body = dict(payload or {})
    record = AuditRecord(
        seq=seq,
        document_id=document_id,
        step=step,
        payload=body,
        created_at=created_at,
        prev_hash=prev_hash,
        record_hash=compute_hash(
            seq=seq,
            document_id=document_id,
            step=step,
            payload=body,
            created_at=created_at,
            prev_hash=prev_hash,
        ),
    )
    session.add(record)
    await session.flush()
    return record


async def step_already_ran(session: AsyncSession, document_id: uuid.UUID, step: str) -> bool:
    """Rule 2: a step that already ran is recognised by its audit record and skipped."""
    found = await session.execute(
        select(AuditRecord.seq)
        .where(AuditRecord.document_id == document_id, AuditRecord.step == step)
        .limit(1)
    )
    return found.first() is not None


async def verify_chain(session: AsyncSession) -> ChainVerification:
    """Recompute every hash from the start and report the first record that does not fit."""
    rows = await session.execute(
        select(
            AuditRecord.seq,
            AuditRecord.document_id,
            AuditRecord.step,
            AuditRecord.payload,
            AuditRecord.created_at,
            AuditRecord.prev_hash,
            AuditRecord.record_hash,
        ).order_by(AuditRecord.seq)
    )
    expected_prev = GENESIS_HASH
    checked = 0
    for seq, document_id, step, payload, created_at, prev_hash, record_hash in rows:
        recomputed = compute_hash(
            seq=seq,
            document_id=document_id,
            step=step,
            payload=payload,
            created_at=created_at,
            prev_hash=prev_hash,
        )
        if seq != checked + 1 or prev_hash != expected_prev or recomputed != record_hash:
            return ChainVerification(ok=False, records_checked=checked, first_bad_seq=seq)
        expected_prev = record_hash
        checked += 1
    return ChainVerification(ok=True, records_checked=checked)
