# IntakeFlow

A portfolio project: a pipeline that turns synthetic invoices and contracts (PDF) into validated structured data, sends uncertain cases to a human reviewer, and answers questions about a contract archive with citations. Planned on Azure with LangChain and LangGraph. The full plan is in [docs/PRD.md](docs/PRD.md).

It is a demo, not a product. The company is fictional and all documents are generated.

## Status

Stage 1 of 7 (foundations and data) is built. **Nothing has been deployed to or run in Azure yet**, and no model has been called: there are no extraction, accuracy, latency or cost results to report.

| Stage | State |
| --- | --- |
| 1. Foundations and data | Built, tested locally |
| 2. Reading and extraction | Not started |
| 3. Validation and routing | Not started |
| 4. Review interface | Not started |
| 5. Contract Q&A | Not started |
| 6. Azure deployment | Not started |
| 7. Write-up | Not started |

What exists today:

- A synthetic set of 200 documents with ground truth, from a fixed seed (see below).
- PostgreSQL schema with an append-only, hash-chained audit log.
- A mock ERP with one write function that refuses unapproved documents.
- Interfaces for chat models, embeddings and document reading, each with a fake, so later stages can be tested without Azure.
- Tests that read the source tree and fail if a second path to the ERP or a stray model client appears.

## The synthetic set

`uv run python scripts/generate_synthetic.py --documents 200 --seed 42` writes PDFs and a ground-truth JSON per document to `data/synthetic/documents/`. The JSON files and `purchase_orders.json` are committed. The PDFs are rebuilt from the seed.

| Type | Documents |
| --- | --- |
| Invoice | 165 |
| Credit note | 21 |
| Contract | 8 |
| Other mail | 6 |

| Hard case | Documents | Validation failure it should cause |
| --- | --- | --- |
| Scanned (no text layer) | 14 | none |
| Scanned and skewed | 9 | none |
| Stamp over the totals | 9 | none |
| Missing PO number | 9 | `po_missing` |
| Total does not add up | 7 | `totals_mismatch` |
| Duplicate invoice | 6 | `duplicate_invoice` |
| Wrong IBAN | 5 | `iban_checksum` |
| PO amount differs | 5 | `po_amount_out_of_tolerance` |
| Unknown PO number | 4 | `po_not_found` |
| PO belongs to another supplier | 4 | `po_supplier_mismatch` |
| Malformed VAT number | 4 | `vat_number_format` |
| Due date before invoice date | 4 | `due_date_before_invoice_date` |

138 of the 186 invoices and credit notes carry no expected failure. These counts come from `data/synthetic/manifest.json`.

Limits of this data: the scans are clean renders that were rasterised, blurred and rotated, not paper that went through a scanner. Real invoices are messier, so any accuracy measured on this set will be an upper bound.

## Running it locally

```bash
cp .env.example .env                      # then choose a local database password
uv sync
docker compose up -d                      # local PostgreSQL
uv run alembic upgrade head
uv run python scripts/generate_synthetic.py --documents 200 --seed 42
uv run uvicorn app.main:app --reload      # http://localhost:8000/health
uv run pytest tests/unit tests/integration
uv run ruff check . && uv run mypy .
```

The integration tests need the local PostgreSQL. They use a separate database (`<name>_test`) that is rebuilt on every run.
