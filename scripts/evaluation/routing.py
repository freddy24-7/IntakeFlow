"""Measures validation and routing on stored extractions. No Azure calls.

It uses the same functions as the pipeline (`rules.validate`, `scoring.decide`)
but keeps everything in memory, so it can be run again after a rule or a
threshold changes and can try many thresholds at once.

A wrong auto-approval is an auto-approved document where either any extracted
field differs from the label, or the label names a problem (a wrong IBAN, a
duplicate) that should have stopped it.
"""

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from app.agents.schema import ExtractedInvoice
from app.config import Settings
from app.validation import rules, scoring
from evaluation import metrics
from evaluation.metrics import Rate
from evaluation.report import VARIANT_TITLES, _table
from evaluation.run import DocumentResult

SWEEP = (0.50, 0.60, 0.70, 0.80, 0.85, 0.90, 0.92, 0.94, 0.96, 0.98, 0.99)


@dataclass(frozen=True)
class Routed:
    doc_id: str
    expected_failures: list[str]
    extraction_exact: bool
    failures: list[str]  # checks that failed
    field_scores: dict[str, float]
    classification_confidence: float

    @property
    def has_error(self) -> bool:
        return bool(self.expected_failures) or not self.extraction_exact

    def decision(self, settings: Settings, threshold: float, aggregate: str) -> scoring.Decision:
        return scoring.decide(
            failures=self.failures,
            score=scoring.aggregate(self.field_scores, aggregate),
            threshold=threshold,
            classification_confidence=self.classification_confidence,
            classification_threshold=settings.classification_threshold,
        )


def route_documents(
    documents: Sequence[DocumentResult],
    variant: str,
    orders: Sequence[dict[str, Any]],
    settings: Settings,
    today: date,
) -> tuple[list[Routed], list[str]]:
    """Validate and score every invoice in document order. Returns the routed
    documents and the ids of invoices that have no extraction for this variant."""
    by_number = {
        order["po_number"]: rules.PurchaseOrderInfo(
            order["supplier_name"], order["supplier_vat_number"], Decimal(str(order["amount"]))
        )
        for order in orders
    }
    seen: set[tuple[str, str]] = set()
    routed, missing = [], []
    for result in documents:
        if result.truth.invoice is None:
            continue
        invoice: ExtractedInvoice | None = result.extractions.get(variant)
        if invoice is None or result.classification_confidence is None:
            missing.append(result.truth.doc_id)
            continue
        supplier = invoice.fields["supplier_name"].value
        number = invoice.fields["invoice_number"].value
        key = (supplier, number) if supplier and number else None
        reference = invoice.fields["purchase_order_reference"].value
        context = rules.ValidationContext(
            today=today,
            purchase_order=by_number.get(reference) if reference else None,
            is_duplicate=key in seen,
            po_tolerance=Decimal(str(settings.po_amount_tolerance)),
        )
        if key is not None:
            seen.add(key)
        routed.append(
            Routed(
                doc_id=result.truth.doc_id,
                expected_failures=result.truth.expected_failures,
                extraction_exact=metrics.score_document(result.truth, invoice).exact,
                failures=rules.validate(invoice, context),
                field_scores=scoring.field_scores(
                    invoice, default_confidence=settings.score_default_confidence
                ),
                classification_confidence=result.classification_confidence,
            )
        )
    return routed, missing


@dataclass(frozen=True)
class Outcome:
    auto_approved: list[Routed]
    reviewed: list[tuple[Routed, list[str]]]

    @property
    def wrong(self) -> list[Routed]:
        return [doc for doc in self.auto_approved if doc.has_error]


def outcome(
    routed: Sequence[Routed], settings: Settings, threshold: float, aggregate: str
) -> Outcome:
    auto, reviewed = [], []
    for doc in routed:
        decision = doc.decision(settings, threshold, aggregate)
        if decision.decision == scoring.AUTO_APPROVE:
            auto.append(doc)
        else:
            reviewed.append((doc, decision.reasons))
    return Outcome(auto, reviewed)


def build_routing_report(
    documents: Sequence[DocumentResult],
    variants: Sequence[str],
    orders: Sequence[dict[str, Any]],
    settings: Settings,
    *,
    today: date,
    services_kind: str,
) -> str:
    invoices = sum(result.truth.invoice is not None for result in documents)
    out = [f"# Routing evaluation, {today.isoformat()}", ""]
    if services_kind != "azure":
        out += [
            "> **Not a measurement.** The extractions behind this report come from fake"
            " services that answer from the ground truth.",
            "",
        ]
    out += _table(
        ["Setting", "Value"],
        [
            ["Extractions from", services_kind],
            ["Invoices and credit notes", invoices],
            ["Auto-approve threshold", settings.auto_approve_threshold],
            ["Score", f"{settings.score_aggregate} of the field scores"],
            [
                "Score of a field without Document Intelligence confidence",
                settings.score_default_confidence,
            ],
            ["Purchase order tolerance", f"{settings.po_amount_tolerance:.0%}"],
            ["Reference date for the date checks", today.isoformat()],
        ],
    )
    out += [
        "A document is auto-approved only when no validation check fails and the score meets"
        " the threshold. **A wrong auto-approval** is an auto-approved document where any"
        " extracted field differs from the label, or where the label names a problem that"
        " should have stopped it. Validation and routing are recomputed here from the stored"
        " extractions, with the same functions the pipeline uses.",
        "",
    ]

    per_variant = {v: route_documents(documents, v, orders, settings, today) for v in variants}
    configured = {
        v: outcome(routed, settings, settings.auto_approve_threshold, settings.score_aggregate)
        for v, (routed, _) in per_variant.items()
    }

    out += ["## At the configured threshold", ""]
    rows = []
    for variant in variants:
        result = configured[variant]
        rows.append(
            [
                VARIANT_TITLES[variant],
                Rate(len(result.auto_approved), invoices),
                Rate(len(result.wrong), len(result.auto_approved)),
                Rate(len(result.reviewed), invoices),
                len(per_variant[variant][1]),
            ]
        )
    out += _table(
        ["Variant", "Auto-approved", "Wrong among auto-approved", "To review", "Not extracted"],
        rows,
    )

    for variant in variants:
        routed, missing = per_variant[variant]
        result = configured[variant]
        out += [f"## {VARIANT_TITLES[variant]}", ""]
        if missing:
            out += [f"No extraction for: {', '.join(missing)}.", ""]

        if result.wrong:
            out += ["### Wrong auto-approvals", ""]
            out += _table(
                ["Document", "Labelled problem", "Extraction fully right"],
                [
                    [doc.doc_id, ", ".join(doc.expected_failures) or "none", doc.extraction_exact]
                    for doc in result.wrong
                ],
            )

        out += ["### Labelled problems caught by validation", ""]
        labelled: Counter[str] = Counter()
        caught: Counter[str] = Counter()
        for doc in routed:
            for failure in doc.expected_failures:
                labelled[failure] += 1
                caught[failure] += failure in doc.failures
        out += _table(
            ["Problem", "Caught"],
            [[name, Rate(caught[name], labelled[name])] for name in sorted(labelled)],
        )

        out += ["### Why documents went to review", ""]
        reasons = Counter(reason for _, why in result.reviewed for reason in why)
        out += _table(["Reason", "Documents"], reasons.most_common())

        unneeded = [(doc, why) for doc, why in result.reviewed if not doc.has_error]
        clean = sum(not doc.has_error for doc in routed)
        out += [
            f"Documents with nothing wrong that still went to review: {Rate(len(unneeded), clean)}"
            " of the documents with nothing wrong.",
            "",
        ]
        if unneeded:
            unneeded_reasons = Counter(reason for _, why in unneeded for reason in why)
            out += _table(["Reason", "Documents"], unneeded_reasons.most_common())

        out += ["### Threshold sweep", ""]
        out += [
            "Auto-approved documents and, in brackets, how many of them were wrong.",
            "",
        ]
        sweep_rows = []
        for threshold in SWEEP:
            cells: list[object] = [f"{threshold:.2f}"]
            for aggregate in scoring.AGGREGATES:
                swept = outcome(routed, settings, threshold, aggregate)
                cells.append(f"{len(swept.auto_approved)} ({len(swept.wrong)})")
            sweep_rows.append(cells)
        out += _table(["Threshold", *(f"Score = {a}" for a in scoring.AGGREGATES)], sweep_rows)

        no_score = outcome(routed, settings, 0.0, settings.score_aggregate)
        out += [
            f"With validation alone (threshold 0): {len(no_score.auto_approved)} auto-approved,"
            f" {len(no_score.wrong)} of them wrong.",
            "",
        ]
    return "\n".join(out)
