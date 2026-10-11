"""Fake services that answer from the ground truth.

They exist to test the evaluation harness end to end without Azure. A report
made with them says nothing about extraction quality, and is marked as such.
"""

import re

from pydantic import BaseModel
from synthetic.truth import DocumentTruth

from app.agents.extract import DI_FIELD_NAMES
from app.agents.schema import ClassificationAnswer, LlmField, LlmInvoice, LlmLineItem
from app.inference.fakes import FakeChatModel
from app.reading.fakes import FakeDocumentReader, content_key, extract_text_layer
from app.reading.interfaces import PageText, ReadField, ReadResult
from app.storage.interfaces import Storage
from app.workflow.steps import Services
from evaluation.metrics import truth_fields

ORACLE_MODEL = "oracle"
_MARKER = re.compile(r"ORACLE (doc-\d+)")


def _llm_invoice(truth: DocumentTruth) -> LlmInvoice:
    assert truth.invoice is not None
    fields = {
        name: LlmField(value=value, page=1 if value else None, source_text=value)
        for name, value in truth_fields(truth.invoice).items()
    }
    lines = [
        LlmLineItem(
            description=line.description,
            quantity=str(line.quantity),
            unit_price=str(line.unit_price),
            vat_rate=str(line.vat_rate),
            line_total=str(line.line_total),
        )
        for line in truth.invoice.line_items
    ]
    return LlmInvoice(**fields, line_items=lines)


def _di_fields(truth: DocumentTruth) -> list[ReadField]:
    assert truth.invoice is not None
    fields = [
        ReadField(DI_FIELD_NAMES[name], value, 0.99, 1)
        for name, value in truth_fields(truth.invoice).items()
        if value is not None
    ]
    for index, line in enumerate(truth.invoice.line_items):
        cells = {
            "Description": line.description,
            "Quantity": str(line.quantity),
            "UnitPrice": str(line.unit_price),
            "TaxRate": str(line.vat_rate),
            "Amount": str(line.line_total),
        }
        fields += [ReadField(f"Items[{index}].{k}", v, 0.99, 1) for k, v in cells.items()]
    return fields


def oracle_services(documents: list[tuple[DocumentTruth, bytes]], storage: Storage) -> Services:
    truths = {truth.doc_id: truth for truth, _ in documents}
    texts: dict[str, ReadResult] = {}
    invoice_fields: dict[str, list[ReadField]] = {}
    for truth, content in documents:
        key = content_key(content)
        if key in texts:  # a duplicate invoice has the same bytes as its original
            continue
        # The marker tells the fake model which document it is looking at.
        pages = [PageText(p.number, p.text) for p in extract_text_layer(content)]
        pages[0] = PageText(1, f"ORACLE {truth.doc_id}\n{pages[0].text}")
        texts[key] = ReadResult(pages=pages)
        if truth.invoice is not None:
            invoice_fields[key] = _di_fields(truth)

    def _truth(user: str) -> DocumentTruth:
        match = _MARKER.search(user)
        assert match is not None
        return truths[match.group(1)]

    def classify(user: str) -> BaseModel:
        return ClassificationAnswer(label=_truth(user).doc_type, confidence=0.99)

    def extract(user: str) -> BaseModel:
        return _llm_invoice(_truth(user))

    return Services(
        storage=storage,
        reader=FakeDocumentReader(texts=texts, invoice_fields=invoice_fields),
        classifier=FakeChatModel(answers={ClassificationAnswer: classify}, model=ORACLE_MODEL),
        classifier_name=ORACLE_MODEL,
        extractor=FakeChatModel(answers={LlmInvoice: extract}, model=ORACLE_MODEL),
        extractor_name=ORACLE_MODEL,
    )
