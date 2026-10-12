# Card 2: Reading and extraction

Stage 2 of the PRD. First stage with LangChain and with real Azure calls. Measured on 12 October 2026 on the 200 synthetic documents (seed 42), 186 of them invoices and credit notes. Full report: `reports/extraction-2026-10-12.md`.

## What was decided and why

**Read first, then classify.** A scanned PDF has no text until it is read, so the cheap read model (`prebuilt-read`) runs on every document, the classifier works on that text, and the expensive invoice model (`prebuilt-invoice`) runs only on invoices and credit notes.

**Two schemas.** The model fills in a flat, text-only schema where every property is required, because that is what strict structured output accepts. The application stores a second shape with canonical values, the page, the printed text and flags. LangChain's `with_structured_output` does the first part. It is one call, at the price of having to know which JSON-schema features strict mode accepts.

**The model normalises, the code checks.** The model returns each value normalised and as printed. Our own parsers for Dutch (1.234,56) and English (1,234.56) numbers and dates re-read the printed form, and a difference is flagged.

**Three variants behind one step.** Document Intelligence only, model only, and combined (the model sees Document Intelligence's fields as a second opinion, and differing fields are flagged). Results are keyed by variant, prompt version and model, so a new prompt is a new run next to the old one.

**Keyless access.** `az login` locally, key access switched off on both resources. There is no key in the repository, in `.env` or anywhere else.

**Evaluation runs are namespaced.** The harness can run with fakes that answer from the ground truth. Without a namespace a real run would have reused a fake reading, because steps are skipped when their audit record exists.

## What was seen in practice

| Measure | Combined | Model only | Document Intelligence only |
| --- | --- | --- | --- |
| Documents with every field right | 97.3% (181/186) | 94.6% (176/186) | 98.4% (183/186) |
| Cost per invoice | € 0.0206 | € 0.0100 | € 0.0105 |

Classification with `gpt-4.1-mini`: 200 of 200 right, including the reminders and order confirmations that mention invoice numbers.

- **Document Intelligence only scored highest and costs half of combined.** This is not the result the project was set up to show. Two things qualify it. The synthetic layouts are clean and regular. And the 98.4% includes one piece of our own logic, described next.
- **Without that logic, Document Intelligence gets VAT wrong on 71 of 186 documents.** On every invoice with two VAT rates it read both per-rate amounts correctly but returned only one of them, or nothing, as `TotalTax`. Summing its own per-rate amounts in our mapping fixed all 71. The first 10-document run, before the fix, is kept in `reports/extraction-2026-10-12-first-10.md`.
- **A second opinion is not independent.** In that first run the model in the combined variant copied the incomplete `TotalTax` once, although the model on its own summed correctly. Because the two then agreed, nothing was flagged. Agreement between the model and a value it was shown proves little.
- **The model's weak spot is tables on skewed scans.** 6 of the 10 documents the model-only variant got wrong are skewed scans. The read model returns the text of a rotated table in an order that mixes rows, and the model then pairs quantities with the wrong prices. Document Intelligence's invoice model, which sees the layout, got all 9 skewed scans right. Straight scans and stamps were not a problem for any variant.
- **Line items are the weakest field for the model** (95.7% model only, 98.4% combined), and VAT rate on a line is sometimes left empty for 0% lines.
- **Flags, as far as the numbers go:** in the combined variant 4 fields were flagged, 2 of them wrong, and both wrong single-value fields were among the flagged. Line items cannot be flagged yet. Four flags are too few to conclude anything.
- **Rate limits are real.** With 6 documents at a time, 5 documents failed with a rate-limit error and 1 with a timeout after LangChain's retries ran out. Running the script again processed only those 6. Idempotent steps made that a non-event, but the pipeline itself has no handling for it yet.
- **Latency per call (median, 95th percentile):** classification 0.6 s and 1.1 s, extraction 3.6 s and 10.8 s, invoice fields 7.3 s and 7.6 s, text reading 2.3 s and 19.2 s. Measured from a laptop, so network time is included.
- **Cost:** about € 5.40 for the full run, computed from token and page counts at list prices. Not yet compared with the Azure invoice.
- **Quota decided the deployment type.** The subscription had no quota for the EU data-zone deployment of these models, so they run as regional Standard deployments in Sweden Central.

## What is still open

- **Which variant the pipeline should use.** On this set Document Intelligence only is the most accurate and the cheapest, but it has no flags and its strength may come from the clean synthetic layouts. The number that should decide is auto-approval precision per variant, which stage 3 measures.
- **Skewed tables for the model.** Options: read with the layout model (about 7 times the price of read) for scans only, or give the model Document Intelligence's line items in the combined variant, which already happens and helps (2 wrong against 6).
- **Flagging line items.** Disagreement on line items between the two sources is not flagged.
- **Retries and dead-letter handling** for rate limits and timeouts belong to stage 3.
- **Classification confidence** comes from the model itself and was not evaluated. With 200 of 200 right there was no wrong answer to test it on.
- **All numbers are on synthetic documents** and are an upper bound for real ones. The scans have no noise, folds or handwriting.
- **One measurement.** The run was not repeated, so there is no estimate of run-to-run variation.
