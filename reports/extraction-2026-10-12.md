# Extraction evaluation, 2026-10-12

| Setting | Value |
| --- | --- |
| Services | azure |
| Documents | 200 (186 invoices and credit notes) |
| Dataset seed | 42 |
| Classification | classify_v1\|gpt-4.1-mini |
| Extraction, combined | combined\|extract_invoice_v2\|gpt-4.1 |
| Extraction, llm_only | llm_only\|extract_invoice_v2\|gpt-4.1 |
| Extraction, di_only | di_only\|map_v2 |

A field counts as right when its canonical form equals the label's. No partial credit. An invoice that was not extracted, for example because it was classified as something else or failed, counts as every field wrong.

## Classification

Accuracy: 100.0% (200/200)

## Field accuracy

### Invoices and credit notes (186 documents)

| Field | Combined | Model only | Document Intelligence only |
| --- | --- | --- | --- |
| supplier_name | 98.9% (184/186) | 99.5% (185/186) | 99.5% (185/186) |
| supplier_vat_number | 100.0% (186/186) | 100.0% (186/186) | 100.0% (186/186) |
| iban | 100.0% (186/186) | 100.0% (186/186) | 98.9% (184/186) |
| invoice_number | 100.0% (186/186) | 100.0% (186/186) | 100.0% (186/186) |
| invoice_date | 100.0% (186/186) | 100.0% (186/186) | 100.0% (186/186) |
| due_date | 100.0% (186/186) | 100.0% (186/186) | 100.0% (186/186) |
| currency | 100.0% (186/186) | 100.0% (186/186) | 100.0% (186/186) |
| subtotal | 100.0% (186/186) | 100.0% (186/186) | 100.0% (186/186) |
| vat | 100.0% (186/186) | 98.4% (183/186) | 100.0% (186/186) |
| total | 100.0% (186/186) | 100.0% (186/186) | 100.0% (186/186) |
| purchase_order_reference | 100.0% (186/186) | 100.0% (186/186) | 100.0% (186/186) |
| line_items | 98.4% (183/186) | 95.7% (178/186) | 100.0% (186/186) |

### invoice (165 documents)

| Field | Combined | Model only | Document Intelligence only |
| --- | --- | --- | --- |
| supplier_name | 98.8% (163/165) | 99.4% (164/165) | 99.4% (164/165) |
| supplier_vat_number | 100.0% (165/165) | 100.0% (165/165) | 100.0% (165/165) |
| iban | 100.0% (165/165) | 100.0% (165/165) | 98.8% (163/165) |
| invoice_number | 100.0% (165/165) | 100.0% (165/165) | 100.0% (165/165) |
| invoice_date | 100.0% (165/165) | 100.0% (165/165) | 100.0% (165/165) |
| due_date | 100.0% (165/165) | 100.0% (165/165) | 100.0% (165/165) |
| currency | 100.0% (165/165) | 100.0% (165/165) | 100.0% (165/165) |
| subtotal | 100.0% (165/165) | 100.0% (165/165) | 100.0% (165/165) |
| vat | 100.0% (165/165) | 98.2% (162/165) | 100.0% (165/165) |
| total | 100.0% (165/165) | 100.0% (165/165) | 100.0% (165/165) |
| purchase_order_reference | 100.0% (165/165) | 100.0% (165/165) | 100.0% (165/165) |
| line_items | 98.2% (162/165) | 95.2% (157/165) | 100.0% (165/165) |

### credit_note (21 documents)

| Field | Combined | Model only | Document Intelligence only |
| --- | --- | --- | --- |
| supplier_name | 100.0% (21/21) | 100.0% (21/21) | 100.0% (21/21) |
| supplier_vat_number | 100.0% (21/21) | 100.0% (21/21) | 100.0% (21/21) |
| iban | 100.0% (21/21) | 100.0% (21/21) | 100.0% (21/21) |
| invoice_number | 100.0% (21/21) | 100.0% (21/21) | 100.0% (21/21) |
| invoice_date | 100.0% (21/21) | 100.0% (21/21) | 100.0% (21/21) |
| due_date | 100.0% (21/21) | 100.0% (21/21) | 100.0% (21/21) |
| currency | 100.0% (21/21) | 100.0% (21/21) | 100.0% (21/21) |
| subtotal | 100.0% (21/21) | 100.0% (21/21) | 100.0% (21/21) |
| vat | 100.0% (21/21) | 100.0% (21/21) | 100.0% (21/21) |
| total | 100.0% (21/21) | 100.0% (21/21) | 100.0% (21/21) |
| purchase_order_reference | 100.0% (21/21) | 100.0% (21/21) | 100.0% (21/21) |
| line_items | 100.0% (21/21) | 100.0% (21/21) | 100.0% (21/21) |

## Documents with every field right

| Variant | Exact match |
| --- | --- |
| Combined | 97.3% (181/186) |
| Model only | 94.6% (176/186) |
| Document Intelligence only | 98.4% (183/186) |

## By kind of page

Share of fields right (line items count as one field).

| Kind | Documents | Combined | Model only | Document Intelligence only |
| --- | --- | --- | --- | --- |
| digital, Dutch, no stamp | 130 | 99.8% (1557/1560) | 99.8% (1557/1560) | 99.9% (1558/1560) |
| english | 33 | 99.7% (395/396) | 99.0% (392/396) | 100.0% (396/396) |
| scanned | 14 | 100.0% (168/168) | 99.4% (167/168) | 100.0% (168/168) |
| scanned_skewed | 9 | 98.1% (106/108) | 92.6% (100/108) | 100.0% (108/108) |
| stamp | 9 | 100.0% (108/108) | 100.0% (108/108) | 99.1% (107/108) |

## Flags in the combined variant

| Measure | Value |
| --- | --- |
| Wrong fields that were flagged | 100.0% (2/2) |
| Flagged fields that were wrong | 50.0% (2/4) |

## Latency and cost per step

| Step | Calls | Median | 95th percentile | Total cost |
| --- | --- | --- | --- | --- |
| classified:classify_v1\|gpt-4.1-mini | 200 | 627 ms | 1,128 ms | € 0.0578 |
| extracted:combined\|extract_invoice_v2\|gpt-4.1 | 186 | 3,621 ms | 10,775 ms | € 1.8872 |
| extracted:llm_only\|extract_invoice_v2\|gpt-4.1 | 186 | 3,384 ms | 10,668 ms | € 1.5443 |
| read_invoice_fields | 186 | 7,304 ms | 7,562 ms | € 1.6367 |
| read_text | 200 | 2,317 ms | 19,190 ms | € 0.2746 |

## Cost per invoice, by variant

| Variant | Per invoice | Per 1,000 invoices |
| --- | --- | --- |
| Combined | € 0.0206 | € 20.61 |
| Model only | € 0.0100 | € 9.96 |
| Document Intelligence only | € 0.0105 | € 10.46 |

Cost is the mean cost per call of each step an invoice goes through, at the unit prices of 2026-10-11 in app/observability/prices.py. Latency is per call, as seen from this machine.

