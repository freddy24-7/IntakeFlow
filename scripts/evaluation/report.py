"""Turns evaluation results into a Markdown report."""

from collections import Counter
from collections.abc import Sequence
from datetime import date
from decimal import Decimal

from app.agents.extract import VARIANT_COMBINED, VARIANT_DI_ONLY, VARIANT_LLM_ONLY
from app.agents.schema import INVOICE_LABELS
from app.observability.prices import PRICES_AS_OF
from app.workflow import steps
from app.workflow.steps import Services
from evaluation import metrics
from evaluation.metrics import DocumentScore, Rate
from evaluation.run import DocumentResult, RunResults, StepUsage

VARIANT_TITLES = {
    VARIANT_DI_ONLY: "Document Intelligence only",
    VARIANT_LLM_ONLY: "Model only",
    VARIANT_COMBINED: "Combined",
}
VISUAL_GROUPS = ("scanned", "scanned_skewed", "stamp")


def _table(header: Sequence[str], rows: Sequence[Sequence[object]]) -> list[str]:
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    # A "|" inside a cell (run keys have them) would otherwise split the column.
    lines += [
        "| " + " | ".join(str(cell).replace("|", "\\|") for cell in row) + " |" for row in rows
    ]
    return [*lines, ""]


def _scores(
    documents: Sequence[DocumentResult], variant: str, doc_type: str | None = None
) -> list[DocumentScore]:
    return [
        metrics.score_document(result.truth, result.extractions.get(variant))
        for result in documents
        if result.truth.invoice is not None
        and (doc_type is None or result.truth.doc_type == doc_type)
    ]


def _group(result: DocumentResult) -> list[str]:
    groups = [case for case in VISUAL_GROUPS if case in result.truth.hard_cases]
    if result.truth.language == "en":
        groups.append("english")
    return groups or ["digital, Dutch, no stamp"]


def _milliseconds(value: float | None) -> str:
    return "n/a" if value is None else f"{value:,.0f} ms"


def _euros(value: Decimal) -> str:
    return f"€ {value:.4f}"


def _variant_steps(services: Services, variant: str) -> list[str]:
    """The steps one invoice goes through when the pipeline uses this variant."""
    names = [steps.STEP_READ_TEXT, f"classified:{steps.classify_run_key(services)}"]
    if variant != VARIANT_LLM_ONLY:
        names.append(steps.STEP_READ_FIELDS)
    # Document Intelligence only needs no model call: mapping its fields is free.
    if variant != VARIANT_DI_ONLY:
        names.append(f"extracted:{steps.extract_run_key(services, variant)}")
    return names


def build_report(
    results: RunResults,
    services: Services,
    variants: Sequence[str],
    *,
    services_kind: str,
    seed: int | None,
    today: date,
) -> str:
    documents = results.documents
    money = [result for result in documents if result.truth.invoice is not None]
    out = [f"# Extraction evaluation, {today.isoformat()}", ""]
    if services_kind != "azure":
        out += [
            "> **Not a measurement.** This run used fake services that answer from the ground"
            " truth. It checks the evaluation harness, nothing else.",
            "",
        ]
    out += _table(
        ["Setting", "Value"],
        [
            ["Services", services_kind],
            ["Documents", f"{len(documents)} ({len(money)} invoices and credit notes)"],
            ["Dataset seed", seed if seed is not None else "unknown"],
            ["Classification", steps.classify_run_key(services)],
            *[[f"Extraction, {v}", steps.extract_run_key(services, v)] for v in variants],
        ],
    )
    out += [
        "A field counts as right when its canonical form equals the label's. No partial credit."
        " An invoice that was not extracted, for example because it was classified as something"
        " else or failed, counts as every field wrong.",
        "",
    ]

    failed = [result for result in documents if result.error]
    if failed:
        out += ["## Documents that failed", ""]
        out += _table(
            ["Document", "Error"], [[result.truth.doc_id, result.error] for result in failed]
        )

    out += ["## Classification", ""]
    right = sum(result.label == result.truth.doc_type for result in documents)
    out += [f"Accuracy: {Rate(right, len(documents))}", ""]
    confusion = Counter(
        (result.truth.doc_type, result.label or "no answer")
        for result in documents
        if result.label != result.truth.doc_type
    )
    if confusion:
        out += _table(
            ["Label", "Classified as", "Documents"],
            [[truth, label, count] for (truth, label), count in sorted(confusion.items())],
        )

    out += ["## Field accuracy", ""]
    for doc_type in (None, *INVOICE_LABELS):
        accuracy = {v: metrics.field_accuracy(_scores(documents, v, doc_type)) for v in variants}
        count = len(_scores(documents, variants[0], doc_type))
        if not count:
            continue
        title = "Invoices and credit notes" if doc_type is None else doc_type
        out += [f"### {title} ({count} documents)", ""]
        names = list(accuracy[variants[0]])
        out += _table(
            ["Field", *(VARIANT_TITLES[v] for v in variants)],
            [[name, *(accuracy[v][name] for v in variants)] for name in names],
        )

    out += ["## Documents with every field right", ""]
    out += _table(
        ["Variant", "Exact match"],
        [[VARIANT_TITLES[v], metrics.exact_match(_scores(documents, v))] for v in variants],
    )

    out += ["## By kind of page", ""]
    groups: dict[str, list[DocumentResult]] = {}
    for result in money:
        for group in _group(result):
            groups.setdefault(group, []).append(result)
    rows = []
    for group, members in sorted(groups.items()):
        cells: list[object] = [group, len(members)]
        for variant in variants:
            scores = _scores(members, variant)
            hits = sum(sum(score.correct.values()) for score in scores)
            total = sum(len(score.correct) for score in scores)
            cells.append(Rate(hits, total))
        rows.append(cells)
    out += ["Share of fields right (line items count as one field).", ""]
    out += _table(["Kind", "Documents", *(VARIANT_TITLES[v] for v in variants)], rows)

    if VARIANT_COMBINED in variants:
        caught, precise = metrics.flag_quality(_scores(documents, VARIANT_COMBINED))
        out += ["## Flags in the combined variant", ""]
        out += _table(
            ["Measure", "Value"],
            [
                ["Wrong fields that were flagged", caught],
                ["Flagged fields that were wrong", precise],
            ],
        )

    out += ["## Latency and cost per step", ""]
    step_rows = []
    for step, entry in sorted(results.usage.items()):
        step_rows.append(
            [
                step,
                entry.calls,
                _milliseconds(metrics.median_or_none(entry.latencies_ms)),
                _milliseconds(metrics.percentile(entry.latencies_ms, 95)),
                "no price known" if entry.unpriced else _euros(entry.cost),
            ]
        )
    out += _table(["Step", "Calls", "Median", "95th percentile", "Total cost"], step_rows)

    out += ["## Cost per invoice, by variant", ""]
    cost_rows = []
    for variant in variants:
        entries = [
            results.usage.get(step, StepUsage()) for step in _variant_steps(services, variant)
        ]
        if any(entry.unpriced for entry in entries) or not all(entry.calls for entry in entries):
            cost_rows.append([VARIANT_TITLES[variant], "n/a", "n/a"])
            continue
        per_document = sum((entry.cost / entry.calls for entry in entries), Decimal(0))
        cost_rows.append(
            [VARIANT_TITLES[variant], _euros(per_document), f"€ {per_document * 1000:.2f}"]
        )
    out += _table(["Variant", "Per invoice", "Per 1,000 invoices"], cost_rows)
    out += [
        f"Cost is the mean cost per call of each step an invoice goes through, at the unit"
        f" prices of {PRICES_AS_OF} in app/observability/prices.py. Latency is per call, as"
        f" seen from this machine.",
        "",
    ]
    return "\n".join(out)
