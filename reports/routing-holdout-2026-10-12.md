# Routing evaluation, 2026-10-12

| Setting | Value |
| --- | --- |
| Extractions from | azure |
| Invoices and credit notes | 186 |
| Auto-approve threshold | 0.9 |
| Score | mean of the field scores |
| Score of a field without Document Intelligence confidence | 0.8 |
| Purchase order tolerance | 1% |
| Reference date for the date checks | 2026-10-12 |

A document is auto-approved only when no validation check fails and the score meets the threshold. **A wrong auto-approval** is an auto-approved document where any extracted field differs from the label, or where the label names a problem that should have stopped it. Validation and routing are recomputed here from the stored extractions, with the same functions the pipeline uses.

## At the configured threshold

| Variant | Auto-approved | Wrong among auto-approved | To review | Not extracted |
| --- | --- | --- | --- | --- |
| Combined | 8.6% (16/186) | 0.0% (0/16) | 91.4% (170/186) | 0 |
| Model only | 0.0% (0/186) | n/a | 100.0% (186/186) | 0 |
| Document Intelligence only | 10.2% (19/186) | 15.8% (3/19) | 89.8% (167/186) | 0 |

## Combined

### Labelled problems caught by validation

| Problem | Caught |
| --- | --- |
| due_date_before_invoice_date | 100.0% (4/4) |
| duplicate_invoice | 100.0% (6/6) |
| iban_checksum | 100.0% (5/5) |
| po_amount_out_of_tolerance | 100.0% (5/5) |
| po_missing | 100.0% (9/9) |
| po_not_found | 100.0% (4/4) |
| po_supplier_mismatch | 100.0% (4/4) |
| totals_mismatch | 100.0% (7/7) |
| vat_number_format | 100.0% (4/4) |

### Why documents went to review

| Reason | Documents |
| --- | --- |
| score_below_threshold | 162 |
| totals_mismatch | 14 |
| po_missing | 9 |
| po_amount_out_of_tolerance | 6 |
| duplicate_invoice | 6 |
| iban_checksum | 5 |
| flagged_supplier_name | 5 |
| vat_number_format | 4 |
| due_date_before_invoice_date | 4 |
| po_not_found | 4 |
| po_supplier_mismatch | 4 |
| flagged_vat | 3 |
| missing_subtotal | 2 |
| flagged_due_date | 2 |
| flagged_subtotal | 2 |
| flagged_iban | 2 |
| missing_vat | 1 |

Documents with nothing wrong that still went to review: 88.0% (117/133) of the documents with nothing wrong.

| Reason | Documents |
| --- | --- |
| score_below_threshold | 117 |
| flagged_supplier_name | 5 |
| flagged_iban | 2 |

### Threshold sweep

Auto-approved documents and, in brackets, how many of them were wrong.

| Threshold | Score = mean | Score = min |
| --- | --- | --- |
| 0.50 | 127 (0) | 91 (0) |
| 0.60 | 127 (0) | 34 (0) |
| 0.70 | 127 (0) | 4 (0) |
| 0.80 | 125 (0) | 0 (0) |
| 0.85 | 83 (0) | 0 (0) |
| 0.90 | 16 (0) | 0 (0) |
| 0.92 | 1 (0) | 0 (0) |
| 0.94 | 0 (0) | 0 (0) |
| 0.96 | 0 (0) | 0 (0) |
| 0.98 | 0 (0) | 0 (0) |
| 0.99 | 0 (0) | 0 (0) |

With validation alone (threshold 0): 127 auto-approved, 0 of them wrong.

## Model only

### Labelled problems caught by validation

| Problem | Caught |
| --- | --- |
| due_date_before_invoice_date | 100.0% (4/4) |
| duplicate_invoice | 100.0% (6/6) |
| iban_checksum | 100.0% (5/5) |
| po_amount_out_of_tolerance | 100.0% (5/5) |
| po_missing | 100.0% (9/9) |
| po_not_found | 100.0% (4/4) |
| po_supplier_mismatch | 100.0% (4/4) |
| totals_mismatch | 100.0% (7/7) |
| vat_number_format | 100.0% (4/4) |

### Why documents went to review

| Reason | Documents |
| --- | --- |
| score_below_threshold | 186 |
| totals_mismatch | 18 |
| po_missing | 9 |
| po_amount_out_of_tolerance | 7 |
| duplicate_invoice | 6 |
| iban_checksum | 5 |
| vat_number_format | 4 |
| due_date_before_invoice_date | 4 |
| po_not_found | 4 |
| po_supplier_mismatch | 4 |
| missing_vat | 1 |
| flagged_vat | 1 |

Documents with nothing wrong that still went to review: 100.0% (129/129) of the documents with nothing wrong.

| Reason | Documents |
| --- | --- |
| score_below_threshold | 129 |

### Threshold sweep

Auto-approved documents and, in brackets, how many of them were wrong.

| Threshold | Score = mean | Score = min |
| --- | --- | --- |
| 0.50 | 130 (1) | 130 (1) |
| 0.60 | 130 (1) | 130 (1) |
| 0.70 | 130 (1) | 130 (1) |
| 0.80 | 130 (1) | 130 (1) |
| 0.85 | 0 (0) | 0 (0) |
| 0.90 | 0 (0) | 0 (0) |
| 0.92 | 0 (0) | 0 (0) |
| 0.94 | 0 (0) | 0 (0) |
| 0.96 | 0 (0) | 0 (0) |
| 0.98 | 0 (0) | 0 (0) |
| 0.99 | 0 (0) | 0 (0) |

With validation alone (threshold 0): 130 auto-approved, 1 of them wrong.

## Document Intelligence only

### Wrong auto-approvals

| Document | Labelled problem | Extraction fully right |
| --- | --- | --- |
| doc-0052 | none | False |
| doc-0149 | none | False |
| doc-0177 | none | False |

### Labelled problems caught by validation

| Problem | Caught |
| --- | --- |
| due_date_before_invoice_date | 100.0% (4/4) |
| duplicate_invoice | 100.0% (6/6) |
| iban_checksum | 100.0% (5/5) |
| po_amount_out_of_tolerance | 100.0% (5/5) |
| po_missing | 100.0% (9/9) |
| po_not_found | 100.0% (4/4) |
| po_supplier_mismatch | 100.0% (4/4) |
| totals_mismatch | 100.0% (7/7) |
| vat_number_format | 100.0% (4/4) |

### Why documents went to review

| Reason | Documents |
| --- | --- |
| score_below_threshold | 159 |
| totals_mismatch | 14 |
| missing_iban | 12 |
| po_missing | 9 |
| iban_checksum | 7 |
| po_amount_out_of_tolerance | 6 |
| due_date_before_invoice_date | 6 |
| duplicate_invoice | 6 |
| vat_number_format | 4 |
| po_not_found | 4 |
| po_supplier_mismatch | 4 |
| missing_subtotal | 2 |
| missing_due_date | 1 |
| flagged_due_date | 1 |
| flagged_subtotal | 1 |

Documents with nothing wrong that still went to review: 86.6% (103/119) of the documents with nothing wrong.

| Reason | Documents |
| --- | --- |
| score_below_threshold | 103 |

### Threshold sweep

Auto-approved documents and, in brackets, how many of them were wrong.

| Threshold | Score = mean | Score = min |
| --- | --- | --- |
| 0.50 | 123 (4) | 90 (3) |
| 0.60 | 123 (4) | 36 (3) |
| 0.70 | 123 (4) | 6 (2) |
| 0.80 | 123 (4) | 0 (0) |
| 0.85 | 86 (3) | 0 (0) |
| 0.90 | 19 (3) | 0 (0) |
| 0.92 | 1 (0) | 0 (0) |
| 0.94 | 0 (0) | 0 (0) |
| 0.96 | 0 (0) | 0 (0) |
| 0.98 | 0 (0) | 0 (0) |
| 0.99 | 0 (0) | 0 (0) |

With validation alone (threshold 0): 123 auto-approved, 4 of them wrong.

