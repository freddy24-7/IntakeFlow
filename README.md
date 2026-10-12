# IntakeFlow

A portfolio project: a pipeline that turns synthetic invoices and contracts (PDF) into validated structured data, sends uncertain cases to a human reviewer, and answers questions about a contract archive with citations. Planned on Azure with LangChain and LangGraph. The full plan is in [docs/PRD.md](docs/PRD.md).

It is a demo, not a product. The company is fictional and all documents are generated.

## Status

Stages 1 to 3 are done. Stages 2 and 3 were measured against real Azure services (Document Intelligence and Azure OpenAI in Sweden Central) from a laptop. The application itself is **not deployed in Azure**: it runs locally and calls those two services.

| Stage | State |
| --- | --- |
| 1. Foundations and data | Done |
| 2. Reading and extraction | Done, measured on 12 October 2026 |
| 3. Validation and routing | Done, measured on 12 October 2026 |
| 4. Review interface | Not started |
| 5. Contract Q&A | Not started |
| 6. Azure deployment | Not started |
| 7. Write-up | Not started |

## Measured results so far

One run on the 200 synthetic documents (186 invoices and credit notes), not repeated. Models: `gpt-4.1-mini` for classification, `gpt-4.1` for extraction. Full report with every field, latency and method: [reports/extraction-2026-10-12.md](reports/extraction-2026-10-12.md). What was learned: [cards/02-reading-and-extraction.md](cards/02-reading-and-extraction.md).

| Measure | Combined | Model only | Document Intelligence only |
| --- | --- | --- | --- |
| Documents with every field right | 97.3% (181/186) | 94.6% (176/186) | 98.4% (183/186) |
| Cost per invoice | € 0.0206 | € 0.0100 | € 0.0105 |

- Classification: 200 of 200 right.
- A field counts as right only when it equals the label exactly after normalising. An invoice needs all eleven fields and all line items right to count.
- Document Intelligence on its own scored highest. Its figure includes one fix of ours: it returned an incomplete VAT total on all 71 invoices with two VAT rates, and we sum its per-rate amounts instead. Without that fix its VAT field is wrong on 71 of 186.
- The model's errors are mostly line items on skewed scans.
- Cost is computed from token and page counts at list prices of 11 October 2026, and has not been compared with the Azure invoice.
- The documents are synthetic and clean, so these numbers are an upper bound for real invoices.

### Routing (stage 3)

Measured on the same 186 extractions, without new Azure calls. Full report: [reports/routing-2026-10-12.md](reports/routing-2026-10-12.md). What was learned: [cards/03-validation-and-routing.md](cards/03-validation-and-routing.md).

| Variant | Auto-approved at threshold 0.90 | Wrong among them | Auto-approved by validation alone | Wrong among them |
| --- | --- | --- | --- | --- |
| Combined | 12.4% (23/186) | 0 | 72.6% (135/186) | 3 |
| Model only | 0% (0/186) | n/a | 72.0% (134/186) | 4 |
| Document Intelligence only | 12.4% (23/186) | 0 | 73.1% (136/186) | 1 |

- Validation caught all 48 labelled problems (wrong IBAN, duplicate, wrong total, purchase order problems and so on) in every variant. None was auto-approved at any threshold.
- A wrong auto-approval is an auto-approved document where any extracted field differs from the label, or where a labelled problem was missed. All wrong ones here are extraction errors that arithmetic cannot see, such as line items in the wrong order.
- The threshold of 0.90 was set before measuring and turns out close to useless: it sends 83% of the documents with nothing wrong to review. The score, built mostly on Document Intelligence's confidence, does not separate right from wrong on this data.

### Hold-out check (second set, seed 43)

After the first set, two settings were written down and committed before a second set of 200 documents with other suppliers was generated and run: route by validation alone (no score threshold), and use the Document Intelligence only variant. Reports: [extraction](reports/extraction-holdout-2026-10-12.md), [routing](reports/routing-holdout-2026-10-12.md).

| Variant | Documents with every field right | Auto-approved by validation alone | Wrong among them |
| --- | --- | --- | --- |
| Combined | 96.2% (179/186) | 68.3% (127/186) | 0 |
| Model only | 93.5% (174/186) | 69.9% (130/186) | 1 |
| Document Intelligence only | 84.9% (158/186) | 66.1% (123/186) | 4 |

- The result for the settings fixed in advance: 123 of 186 auto-approved, 4 of them wrong (3.3%).
- Routing by validation alone held up: every labelled problem was caught again, in all three variants.
- The choice of variant did not: Document Intelligence only was the best variant on the first set and the worst on the second. Its errors cluster per supplier layout (14 wrong IBANs from two suppliers), so 186 documents from 25 suppliers are far fewer independent samples than they look.
- Over both sets (372 documents, about 50 suppliers) the three variants auto-approve 259 to 264 documents with 3 to 5 wrong. That is too close to rank them.

What exists today:

- A synthetic set of 200 documents with ground truth, from a fixed seed (see below).
- PostgreSQL schema with an append-only, hash-chained audit log.
- A mock ERP with one write function that refuses unapproved documents.
- Interfaces for chat models, embeddings and document reading, each with a fake and an Azure implementation.
- An upload endpoint and four idempotent pipeline steps: read text, classify, read invoice fields, extract.
- Three extraction variants: Document Intelligence only, model only, and combined.
- Validation rules, scoring and routing, with auto-approved documents booked in the mock ERP.
- A LangGraph workflow with retries, state saved in Postgres, resume, and dead-letter handling.
- An evaluation script that reports field accuracy, exact-match rate, latency and cost per invoice.
- A Bicep file for the Azure resources, with one command to create and one to delete them.
- Tests that read the source tree and fail if a second path to the ERP or a stray model client appears.

Not built yet: the review interface, contract Q&A, and deployment of the application to Azure. The workflow has been tested with fakes; its steps were measured against Azure one by one, but no document has gone through the whole graph against Azure yet.

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
uv run python scripts/load_purchase_orders.py
uv run python scripts/evaluate_extraction.py --services oracle --limit 20   # harness check, no Azure
uv run python scripts/evaluate_routing.py --services oracle --limit 20      # same, for routing
```

## Azure (stage 2)

```bash
./deploy/up.sh --what-if                  # preview, changes nothing
./deploy/up.sh                            # create: budget alert, Document Intelligence, Azure OpenAI
uv run pytest tests/azure -m azure        # smoke test against the real services
uv run python scripts/evaluate_extraction.py --services azure --limit 10
./deploy/down.sh                          # delete everything
```

Sign-in is keyless through `az login`. Key access is switched off on both resources, so there are no keys to store. Both resources are pay-per-use and cost nothing while idle.

The integration tests need the local PostgreSQL. They use a separate database (`<name>_test`) that is rebuilt on every run.
