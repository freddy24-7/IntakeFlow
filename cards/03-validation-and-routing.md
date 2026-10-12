# Card 3: Validation and routing

Stage 3 of the PRD. Measured on 12 October 2026 on the stored extractions of stage 2 (186 invoices and credit notes, seed 42). No new Azure calls were needed. Full report: `reports/routing-2026-10-12.md`.

## What was decided and why

**Checks are plain code.** Totals, dates, VAT number format, IBAN checksum, purchase order and duplicates are checked without any model. `rules.validate` returns the names of the checks that failed.

**One function decides.** `scoring.decide` auto-approves only when no check failed and the score meets the threshold, and it records every reason for review, not only the first. A source-reading test fails if any other file sets the auto-approved status.

**A flagged field is a failed check.** A test with a deliberately wrong model found this: with the score as a mean, one flagged invoice number among ten confident fields scored 0.945 and was auto-approved. A disagreement between two sources is now a validation failure in its own right.

**Decisions are stored per extraction run, applied once per document.** That lets the evaluation compare the three variants on the same documents, while the document's status and the ERP booking follow the one configured variant.

**Three defences against paying twice.** The duplicate check in validation, a check in the ERP gateway, and a unique constraint on supplier and invoice number in the database.

**LangGraph for the workflow.** The graph declares the branching, gives the four Azure nodes a retry policy and saves state to Postgres after every node. Compared with the hand-built Redis Streams worker in Muni Mailbox: much less code for retries and resuming, and the flow can be read from the edges. The costs: a second Postgres driver (`psycopg`, next to `asyncpg`), checkpoint tables that the library creates outside our migrations, and type hints loose enough that the graph builder had to be left untyped under `mypy --strict`.

**The checkpoint adds less than expected.** Our steps were already idempotent, so starting a failed document over would also continue where it stopped. What the checkpoint adds is a record of which node a run stopped at. A test shows a run resuming from Postgres with a new graph object, without reading the text a second time.

**Dead letters.** A failed run is counted on the document with the kind of error (never its message). After three failed runs the document gets status `failed`.

## What was seen in practice

Validation caught every labelled problem: 48 of 48, in all three variants. No document with a wrong IBAN, a duplicate, a wrong total or a purchase order problem was auto-approved at any threshold.

| Variant | Auto-approved at threshold 0.90 | Wrong among them | Auto-approved by validation alone | Wrong among them |
| --- | --- | --- | --- | --- |
| Combined | 12.4% (23/186) | 0 | 72.6% (135/186) | 3 |
| Model only | 0% (0/186) | n/a | 72.0% (134/186) | 4 |
| Document Intelligence only | 12.4% (23/186) | 0 | 73.1% (136/186) | 1 |

- **The threshold chosen before measuring (0.90) is close to useless.** It sends 83% of the documents with nothing wrong to a person. The pipeline is safe and saves almost no work.
- **The score does not separate right from wrong.** Document scores sit between 0.78 and 0.93, with a median of 0.87. Document Intelligence's median confidence for the invoice total is 0.66, on a field it got right 186 times out of 186. Its confidence is not a probability of being correct on this data.
- **Validation does almost all of the work.** With the score ignored, 135 documents are auto-approved in the combined variant and 3 are wrong (2.2%).
- **The wrong auto-approvals are extraction errors that arithmetic cannot see.** In the combined variant: line items in the wrong order on two skewed scans (the sum is unchanged) and a missing VAT rate on a 0% line. For Document Intelligence only: a supplier name cut short. In none of them were the supplier, invoice number, amounts or IBAN wrong, but they count as wrong by the definition set before measuring.
- **The model-only variant has no confidence at all**, so every field gets the configured default (0.80) and the threshold is all or nothing.
- **Document Intelligence only is again the best variant on this set**: most auto-approvals, fewest wrong, half the cost.
- **Rate limits from stage 2 are handled.** Tests show a throttled call retried inside a run, and a document parked as failed after three failed runs. This was tested with fakes, not by provoking real rate limits.

## What is still open

- **The threshold and the variant.** Any value picked now is picked by looking at these 186 documents. It should be confirmed on a set with a different seed before it is quoted as a result.
- **A better score.** Options: leave the score out and rely on validation; weigh only the fields that matter for payment; or calibrate Document Intelligence's confidence per field against the labels. Each needs a held-out set to be believed.
- **Line items are not cross-checked** between the two sources, which is where the remaining wrong auto-approvals come from.
- **The order of line items** counts as an error in the evaluation. Whether it should is a business question.
- **The workflow has not run against Azure end to end.** Its steps were measured in stage 2 and the graph is tested with fakes. The first real upload through the graph is still to come.
- **Contracts stop after classification** with status `processing` until stage 5 indexes them.
- **Checkpoint tables are never cleaned up.**

## Settings fixed before the hold-out run

Written and committed on 12 October 2026, before the hold-out set (seed 43) was generated or run. The seed 42 results above were used to choose these, so seed 42 cannot confirm them.

- **Routing: validation alone.** Auto-approve threshold 0, so a document is auto-approved when no check fails and no field is flagged. Reason: the score did not separate right from wrong on seed 42.
- **Variant: Document Intelligence only.** Reason: most auto-approvals and fewest wrong ones on seed 42 (136 auto-approved, 1 wrong), at half the cost of combined.
- **What will be reported:** auto-approval rate and wrong auto-approvals on the hold-out set for all three variants, with the two choices above as the result to quote, whatever it turns out to be.
- Rules, prompts, the Document Intelligence mapping and the definition of a wrong auto-approval stay exactly as they are at this commit.
