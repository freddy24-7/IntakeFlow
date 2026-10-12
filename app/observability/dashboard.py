"""Figures for the team lead's dashboard (PRD F9), from the application's own records.

Only uploaded documents count. Documents registered by the evaluation scripts
are left out, so the dashboard shows how the application is used, not how it
was tested.
"""

import json
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from statistics import median
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.schema import INVOICE_LABELS
from app.db.models import AuditRecord, Document, DocumentStatus, Review, UsageRecord
from app.observability.prices import call_cost
from app.review.service import ACTION_APPROVED
from app.workflow.ingest import STEP_UPLOADED
from app.workflow.routing_steps import STEP_APPLIED, STEP_NON_INVOICE

UPLOAD = "upload"
ACCURACY_FILE = Path("reports/extraction-latest.json")


@dataclass
class Share:
    part: int
    whole: int

    @property
    def percent(self) -> str:
        return "n.v.t." if not self.whole else f"{100 * self.part / self.whole:.0f}%"


@dataclass
class Dashboard:
    per_day: list[tuple[str, int]]
    by_status: dict[str, int]
    auto_approved: Share
    corrected: Share
    median_seconds_to_result: float | None
    cost_per_document: Decimal | None
    documents_with_cost: int
    accuracy: dict[str, Any] | None = field(default=None)


async def load_dashboard(session: AsyncSession, accuracy_file: Path = ACCURACY_FILE) -> Dashboard:
    uploads = select(Document.id).where(Document.origin == UPLOAD)

    day = func.date(Document.created_at)
    per_day = (
        await session.execute(
            select(day, func.count())
            .where(Document.origin == UPLOAD)
            .group_by(day)
            .order_by(day.desc())
            .limit(14)
        )
    ).all()

    statuses = Counter(
        dict(
            (
                await session.execute(
                    select(Document.status, func.count())
                    .where(Document.origin == UPLOAD)
                    .group_by(Document.status)
                )
            ).all()
        )
    )

    # Share handled without a person, of the invoices and credit notes that have a result.
    decided = dict(
        (
            await session.execute(
                select(Document.status, func.count())
                .where(
                    Document.origin == UPLOAD,
                    Document.document_type.in_(INVOICE_LABELS),
                    Document.status.in_(
                        [
                            DocumentStatus.AUTO_APPROVED.value,
                            DocumentStatus.APPROVED.value,
                            DocumentStatus.REJECTED.value,
                            DocumentStatus.IN_REVIEW.value,
                        ]
                    ),
                )
                .group_by(Document.status)
            )
        ).all()
    )
    auto = Share(decided.get(DocumentStatus.AUTO_APPROVED.value, 0), sum(decided.values()))

    approvals = (
        await session.execute(
            select(Review.unchanged, func.count())
            .where(Review.action == ACTION_APPROVED, Review.document_id.in_(uploads))
            .group_by(Review.unchanged)
        )
    ).all()
    approved = {unchanged: count for unchanged, count in approvals}
    corrected = Share(approved.get(False, 0), sum(approved.values()))

    # Time from upload to the pipeline's result (auto-approved or handed to a person).
    times = (
        await session.execute(
            select(
                AuditRecord.document_id,
                func.min(AuditRecord.created_at).filter(AuditRecord.step == STEP_UPLOADED),
                func.max(AuditRecord.created_at).filter(
                    AuditRecord.step.in_([STEP_APPLIED, STEP_NON_INVOICE])
                ),
            )
            .where(AuditRecord.document_id.in_(uploads))
            .group_by(AuditRecord.document_id)
        )
    ).all()
    durations = [
        (finished - started).total_seconds()
        for _, started, finished in times
        if started is not None and finished is not None
    ]

    usage = (
        await session.execute(select(UsageRecord).where(UsageRecord.document_id.in_(uploads)))
    ).scalars()
    costs: dict[Any, Decimal] = {}
    for record in usage:
        cost = call_cost(
            model=record.model,
            pages=record.pages,
            input_tokens=record.input_tokens,
            output_tokens=record.output_tokens,
        )
        if cost is not None:
            costs[record.document_id] = costs.get(record.document_id, Decimal(0)) + cost

    return Dashboard(
        per_day=[(str(date_), count) for date_, count in per_day],
        by_status=dict(statuses),
        auto_approved=auto,
        corrected=corrected,
        median_seconds_to_result=median(durations) if durations else None,
        cost_per_document=sum(costs.values(), Decimal(0)) / len(costs) if costs else None,
        documents_with_cost=len(costs),
        accuracy=_accuracy(accuracy_file),
    )


def _accuracy(path: Path) -> dict[str, Any] | None:
    """Field accuracy from the latest evaluation run, written by evaluate_extraction.py."""
    if not path.exists():
        return None
    loaded: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return loaded
