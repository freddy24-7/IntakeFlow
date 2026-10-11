"""Renders a dataset and writes PDFs, ground truth and purchase orders to disk."""

import json
from collections import Counter
from pathlib import Path

from synthetic.build import Dataset, RenderPlan
from synthetic.render import render_contract, render_invoice, render_letter
from synthetic.scan import rasterise
from synthetic.truth import DocumentTruth


def render_document(doc: DocumentTruth, plan: RenderPlan) -> bytes:
    if doc.contract is not None:
        pdf = render_contract(doc.contract)
    elif doc.invoice is not None:
        pdf = render_invoice(doc, plan.supplier, plan.stamp_text)
    else:
        assert plan.letter is not None
        pdf = render_letter(plan.supplier, *plan.letter)
    if doc.scanned:
        pdf = rasterise(pdf, doc.skew_degrees or 0.0)
    return pdf


def manifest(dataset: Dataset) -> dict[str, object]:
    documents = dataset.documents
    return {
        "seed": dataset.seed,
        "documents": len(documents),
        "purchase_orders": len(dataset.purchase_orders),
        "by_type": dict(sorted(Counter(doc.doc_type for doc in documents).items())),
        "by_hard_case": dict(
            sorted(Counter(case for doc in documents for case in doc.hard_cases).items())
        ),
        "without_expected_failure": sum(
            1 for doc in documents if doc.invoice is not None and not doc.expected_failures
        ),
    }


def write_dataset(dataset: Dataset, out_dir: Path) -> None:
    """Write `documents/doc-NNNN.pdf` with `doc-NNNN.json` next to it, plus two summary files."""
    documents_dir = out_dir / "documents"
    documents_dir.mkdir(parents=True, exist_ok=True)
    for stale in documents_dir.glob("doc-*"):
        stale.unlink()

    for doc in dataset.documents:
        (documents_dir / doc.filename).write_bytes(render_document(doc, dataset.plans[doc.doc_id]))
        truth_path = documents_dir / f"{doc.doc_id}.json"
        truth_path.write_text(doc.model_dump_json(indent=2) + "\n", encoding="utf-8")

    purchase_orders = [po.model_dump(mode="json") for po in dataset.purchase_orders]
    (out_dir / "purchase_orders.json").write_text(
        json.dumps(purchase_orders, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest(dataset), indent=2) + "\n", encoding="utf-8"
    )
