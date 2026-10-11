"""Smoke tests against the real Azure services. They cost a little money and
run only on request:

    uv run pytest tests/azure -m azure

They check that the real services answer in the shapes the adapters assume.
Accuracy is measured by scripts/evaluate_extraction.py, not here.
"""

import pytest
from synthetic.build import generate
from synthetic.write import render_document

from app.agents.classify import classify
from app.agents.prompts import CLASSIFY, load_prompt
from app.config import get_settings
from app.workflow.services import azure_is_configured, build_azure_services

pytestmark = pytest.mark.azure


@pytest.fixture(scope="module")
def invoice_pdf() -> bytes:
    dataset = generate(30, seed=1)
    doc = next(d for d in dataset.documents if d.doc_type == "invoice" and not d.scanned)
    return render_document(doc, dataset.plans[doc.doc_id])


async def test_read_classify_and_invoice_fields(invoice_pdf: bytes) -> None:
    settings = get_settings()
    if not azure_is_configured(settings):
        pytest.skip("Azure endpoints are not set in .env")
    services = build_azure_services(settings)

    text = await services.reader.read_text(invoice_pdf)
    assert len(text.pages) == 1
    assert text.text.strip()

    answer, usage = await classify(services.classifier, load_prompt(CLASSIFY), text)
    assert answer.label == "invoice"
    assert usage.input_tokens > 0

    fields = await services.reader.read_invoice_fields(invoice_pdf)
    assert {field.name for field in fields.fields} >= {"InvoiceId", "InvoiceTotal"}
