# Extraction evaluation, 2026-10-12

| Setting | Value |
| --- | --- |
| Services | azure |
| Documents | 200 (186 invoices and credit notes) |
| Dataset seed | 43 |
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
| supplier_name | 100.0% (186/186) | 100.0% (186/186) | 97.3% (181/186) |
| supplier_vat_number | 100.0% (186/186) | 100.0% (186/186) | 100.0% (186/186) |
| iban | 100.0% (186/186) | 100.0% (186/186) | 92.5% (172/186) |
| invoice_number | 100.0% (186/186) | 100.0% (186/186) | 100.0% (186/186) |
| invoice_date | 100.0% (186/186) | 100.0% (186/186) | 100.0% (186/186) |
| due_date | 100.0% (186/186) | 100.0% (186/186) | 98.4% (183/186) |
| currency | 100.0% (186/186) | 100.0% (186/186) | 100.0% (186/186) |
| subtotal | 96.8% (180/186) | 96.8% (180/186) | 96.8% (180/186) |
| vat | 97.3% (181/186) | 97.8% (182/186) | 97.3% (181/186) |
| total | 100.0% (186/186) | 99.5% (185/186) | 100.0% (186/186) |
| purchase_order_reference | 100.0% (186/186) | 100.0% (186/186) | 100.0% (186/186) |
| line_items | 100.0% (186/186) | 96.8% (180/186) | 99.5% (185/186) |

### invoice (166 documents)

| Field | Combined | Model only | Document Intelligence only |
| --- | --- | --- | --- |
| supplier_name | 100.0% (166/166) | 100.0% (166/166) | 98.2% (163/166) |
| supplier_vat_number | 100.0% (166/166) | 100.0% (166/166) | 100.0% (166/166) |
| iban | 100.0% (166/166) | 100.0% (166/166) | 92.2% (153/166) |
| invoice_number | 100.0% (166/166) | 100.0% (166/166) | 100.0% (166/166) |
| invoice_date | 100.0% (166/166) | 100.0% (166/166) | 100.0% (166/166) |
| due_date | 100.0% (166/166) | 100.0% (166/166) | 98.2% (163/166) |
| currency | 100.0% (166/166) | 100.0% (166/166) | 100.0% (166/166) |
| subtotal | 96.4% (160/166) | 96.4% (160/166) | 96.4% (160/166) |
| vat | 97.0% (161/166) | 98.2% (163/166) | 97.0% (161/166) |
| total | 100.0% (166/166) | 99.4% (165/166) | 100.0% (166/166) |
| purchase_order_reference | 100.0% (166/166) | 100.0% (166/166) | 100.0% (166/166) |
| line_items | 100.0% (166/166) | 96.4% (160/166) | 99.4% (165/166) |

### credit_note (20 documents)

| Field | Combined | Model only | Document Intelligence only |
| --- | --- | --- | --- |
| supplier_name | 100.0% (20/20) | 100.0% (20/20) | 90.0% (18/20) |
| supplier_vat_number | 100.0% (20/20) | 100.0% (20/20) | 100.0% (20/20) |
| iban | 100.0% (20/20) | 100.0% (20/20) | 95.0% (19/20) |
| invoice_number | 100.0% (20/20) | 100.0% (20/20) | 100.0% (20/20) |
| invoice_date | 100.0% (20/20) | 100.0% (20/20) | 100.0% (20/20) |
| due_date | 100.0% (20/20) | 100.0% (20/20) | 100.0% (20/20) |
| currency | 100.0% (20/20) | 100.0% (20/20) | 100.0% (20/20) |
| subtotal | 100.0% (20/20) | 100.0% (20/20) | 100.0% (20/20) |
| vat | 100.0% (20/20) | 95.0% (19/20) | 100.0% (20/20) |
| total | 100.0% (20/20) | 100.0% (20/20) | 100.0% (20/20) |
| purchase_order_reference | 100.0% (20/20) | 100.0% (20/20) | 100.0% (20/20) |
| line_items | 100.0% (20/20) | 100.0% (20/20) | 100.0% (20/20) |

## Documents with every field right

| Variant | Exact match |
| --- | --- |
| Combined | 96.2% (179/186) |
| Model only | 93.5% (174/186) |
| Document Intelligence only | 84.9% (158/186) |

## By kind of page

Share of fields right (line items count as one field).

| Kind | Documents | Combined | Model only | Document Intelligence only |
| --- | --- | --- | --- | --- |
| digital, Dutch, no stamp | 123 | 100.0% (1476/1476) | 99.7% (1472/1476) | 98.5% (1454/1476) |
| english | 35 | 99.8% (419/420) | 100.0% (420/420) | 100.0% (420/420) |
| scanned | 14 | 100.0% (168/168) | 100.0% (168/168) | 100.0% (168/168) |
| scanned_skewed | 9 | 100.0% (108/108) | 95.4% (103/108) | 100.0% (108/108) |
| stamp | 9 | 90.7% (98/108) | 92.6% (100/108) | 88.9% (96/108) |

## Flags in the combined variant

| Measure | Value |
| --- | --- |
| Wrong fields that were flagged | 36.4% (4/11) |
| Flagged fields that were wrong | 28.6% (4/14) |

## Latency and cost per step

| Step | Calls | Median | 95th percentile | Total cost |
| --- | --- | --- | --- | --- |
| classified:classify_v1\|gpt-4.1-mini | 200 | 706 ms | 1,177 ms | € 0.0580 |
| extracted:combined\|extract_invoice_v2\|gpt-4.1 | 186 | 3,434 ms | 5,665 ms | € 1.9187 |
| extracted:llm_only\|extract_invoice_v2\|gpt-4.1 | 186 | 3,319 ms | 5,021 ms | € 1.5641 |
| read_invoice_fields | 186 | 7,309 ms | 7,425 ms | € 1.6367 |
| read_text | 200 | 2,295 ms | 3,331 ms | € 0.2746 |

## Cost per invoice, by variant

| Variant | Per invoice | Per 1,000 invoices |
| --- | --- | --- |
| Combined | € 0.0208 | € 20.78 |
| Model only | € 0.0101 | € 10.07 |
| Document Intelligence only | € 0.0105 | € 10.46 |

Cost is the mean cost per call of each step an invoice goes through, at the unit prices of 2026-10-11 in app/observability/prices.py. Latency is per call, as seen from this machine.

