# Extraction evaluation, 2026-10-12

| Setting | Value |
| --- | --- |
| Services | azure |
| Documents | 10 (9 invoices and credit notes) |
| Dataset seed | 42 |
| Classification | classify_v1\|gpt-4.1-mini |
| Extraction, combined | combined\|extract_invoice_v1\|gpt-4.1 |
| Extraction, llm_only | llm_only\|extract_invoice_v1\|gpt-4.1 |
| Extraction, di_only | di_only |

A field counts as right when its canonical form equals the label's. No partial credit. An invoice that was not extracted, for example because it was classified as something else or failed, counts as every field wrong.

## Classification

Accuracy: 100.0% (10/10)

## Field accuracy

### Invoices and credit notes (9 documents)

| Field | Combined | Model only | Document Intelligence only |
| --- | --- | --- | --- |
| supplier_name | 100.0% (9/9) | 100.0% (9/9) | 100.0% (9/9) |
| supplier_vat_number | 100.0% (9/9) | 100.0% (9/9) | 100.0% (9/9) |
| iban | 100.0% (9/9) | 100.0% (9/9) | 100.0% (9/9) |
| invoice_number | 100.0% (9/9) | 100.0% (9/9) | 100.0% (9/9) |
| invoice_date | 100.0% (9/9) | 100.0% (9/9) | 100.0% (9/9) |
| due_date | 100.0% (9/9) | 100.0% (9/9) | 100.0% (9/9) |
| currency | 100.0% (9/9) | 100.0% (9/9) | 100.0% (9/9) |
| subtotal | 100.0% (9/9) | 100.0% (9/9) | 100.0% (9/9) |
| vat | 88.9% (8/9) | 100.0% (9/9) | 55.6% (5/9) |
| total | 100.0% (9/9) | 100.0% (9/9) | 100.0% (9/9) |
| purchase_order_reference | 100.0% (9/9) | 100.0% (9/9) | 100.0% (9/9) |
| line_items | 100.0% (9/9) | 100.0% (9/9) | 100.0% (9/9) |

### invoice (7 documents)

| Field | Combined | Model only | Document Intelligence only |
| --- | --- | --- | --- |
| supplier_name | 100.0% (7/7) | 100.0% (7/7) | 100.0% (7/7) |
| supplier_vat_number | 100.0% (7/7) | 100.0% (7/7) | 100.0% (7/7) |
| iban | 100.0% (7/7) | 100.0% (7/7) | 100.0% (7/7) |
| invoice_number | 100.0% (7/7) | 100.0% (7/7) | 100.0% (7/7) |
| invoice_date | 100.0% (7/7) | 100.0% (7/7) | 100.0% (7/7) |
| due_date | 100.0% (7/7) | 100.0% (7/7) | 100.0% (7/7) |
| currency | 100.0% (7/7) | 100.0% (7/7) | 100.0% (7/7) |
| subtotal | 100.0% (7/7) | 100.0% (7/7) | 100.0% (7/7) |
| vat | 85.7% (6/7) | 100.0% (7/7) | 42.9% (3/7) |
| total | 100.0% (7/7) | 100.0% (7/7) | 100.0% (7/7) |
| purchase_order_reference | 100.0% (7/7) | 100.0% (7/7) | 100.0% (7/7) |
| line_items | 100.0% (7/7) | 100.0% (7/7) | 100.0% (7/7) |

### credit_note (2 documents)

| Field | Combined | Model only | Document Intelligence only |
| --- | --- | --- | --- |
| supplier_name | 100.0% (2/2) | 100.0% (2/2) | 100.0% (2/2) |
| supplier_vat_number | 100.0% (2/2) | 100.0% (2/2) | 100.0% (2/2) |
| iban | 100.0% (2/2) | 100.0% (2/2) | 100.0% (2/2) |
| invoice_number | 100.0% (2/2) | 100.0% (2/2) | 100.0% (2/2) |
| invoice_date | 100.0% (2/2) | 100.0% (2/2) | 100.0% (2/2) |
| due_date | 100.0% (2/2) | 100.0% (2/2) | 100.0% (2/2) |
| currency | 100.0% (2/2) | 100.0% (2/2) | 100.0% (2/2) |
| subtotal | 100.0% (2/2) | 100.0% (2/2) | 100.0% (2/2) |
| vat | 100.0% (2/2) | 100.0% (2/2) | 100.0% (2/2) |
| total | 100.0% (2/2) | 100.0% (2/2) | 100.0% (2/2) |
| purchase_order_reference | 100.0% (2/2) | 100.0% (2/2) | 100.0% (2/2) |
| line_items | 100.0% (2/2) | 100.0% (2/2) | 100.0% (2/2) |

## Documents with every field right

| Variant | Exact match |
| --- | --- |
| Combined | 88.9% (8/9) |
| Model only | 100.0% (9/9) |
| Document Intelligence only | 55.6% (5/9) |

## By kind of page

Share of fields right (line items count as one field).

| Kind | Documents | Combined | Model only | Document Intelligence only |
| --- | --- | --- | --- | --- |
| digital, Dutch, no stamp | 8 | 99.0% (95/96) | 100.0% (96/96) | 96.9% (93/96) |
| english | 1 | 100.0% (12/12) | 100.0% (12/12) | 91.7% (11/12) |

## Flags in the combined variant

| Measure | Value |
| --- | --- |
| Wrong fields that were flagged | 0.0% (0/1) |
| Flagged fields that were wrong | 0.0% (0/1) |

## Latency and cost per step

| Step | Calls | Median | 95th percentile | Total cost |
| --- | --- | --- | --- | --- |
| classified:classify_v1\|gpt-4.1-mini | 10 | 662 ms | 13,017 ms | € 0.0031 |
| extracted:combined\|extract_invoice_v1\|gpt-4.1 | 9 | 3,810 ms | 16,299 ms | € 0.0877 |
| extracted:llm_only\|extract_invoice_v1\|gpt-4.1 | 9 | 3,190 ms | 4,900 ms | € 0.0709 |
| read_invoice_fields | 9 | 7,333 ms | 19,345 ms | € 0.0792 |
| read_text | 10 | 2,408 ms | 39,655 ms | € 0.0145 |

## Cost per invoice, by variant

| Variant | Per invoice | Per 1,000 invoices |
| --- | --- | --- |
| Combined | € 0.0203 | € 20.31 |
| Model only | € 0.0096 | € 9.64 |
| Document Intelligence only | € 0.0106 | € 10.56 |

Cost is the mean cost per call of each step an invoice goes through, at the unit prices of 2026-10-11 in app/observability/prices.py. Latency is per call, as seen from this machine.

