# Card 1: Foundations and data

Stage 1 of the PRD. No Azure, no LangChain yet: this stage builds what the later stages plug into and are measured against.

## What was decided and why

**Our own interfaces before any framework.** `app/inference/interfaces.py` and `app/reading/interfaces.py` define `ChatModel`, `EmbeddingModel` and `DocumentReader` as plain Python protocols. LangChain and the Azure SDKs arrive in stage 2 as implementations of these. The trade-off: one extra layer to maintain, in exchange for tests that run without Azure and a framework that can be swapped. In Muni Mailbox the model calls were hand-built, so the layer was there by default. With a framework it has to be chosen on purpose.

**Guarantees are enforced twice.** The ERP rule (only approved documents) is checked in `post_to_erp` and again by a database trigger. The audit log has no update or delete function and a trigger refuses both. The application check gives a clear error, and the trigger catches code that goes around the application.

**Tests that read the source.** `tests/architecture.py` parses every file under `app/` and `scripts/` and reports model-client imports outside the two allowed packages, and any mention of the ERP model or table outside the gateway. Each check is also run against a small tree that breaks the rule on purpose, so we know the check can fail.

**Audit log moved from stage 3 to stage 1.** Rule 2 says a step that already ran is recognised by its audit record, so the log has to exist before the first step is written.

**Labels describe the page and the expected outcome separately.** `invoice` in the ground truth is what is printed, including deliberate errors, because that is what extraction is measured against. `expected_failures` names the validation check that should catch the document, which is what routing will be measured against.

**Content hard cases never overlap.** Each invoice has at most one content error, so a failed check has one known cause. Visual cases (scan, skew, stamp) are drawn independently and can land on the same document.

**PDFs are not committed, labels are.** The PDFs are rebuilt from the seed. A test regenerates the 200 labels and compares them with the committed files, so labels cannot be edited by hand without CI failing.

**Contracts leave clauses out on purpose.** Some contracts have no clause on price indexation, liability or confidentiality. In stage 5 a question about a missing clause is one the system must decline.

## What was seen in practice

- Faker's Dutch company names include real companies. The first run produced an invoice from "NS". Supplier names are now built from a surname and a line of business.
- 83 tests pass locally in about 2 seconds. Line coverage is 97% over `app/` and `scripts/`.
- Generating 200 documents takes about 2.5 seconds, and the PDFs total about 4 MB.
- Same seed, same PDF bytes on this machine (reportlab's `invariant` mode). Not checked across operating systems: the scanned pages go through pdfium's renderer, which may differ by platform. The labels do not depend on it.
- CI is written but has not run yet, because the branch has not been pushed.

## What is still open

- The scans are rasterised clean renders with blur and rotation. No noise, shadows, folds or handwriting. How hard they are for Document Intelligence is unknown until stage 2.
- All contracts are Dutch. The PRD asks for "Dutch with some English", which is covered for invoices only.
- Questions for the contract Q&A evaluation are not generated yet. The facts they will be built from are in the labels.
- Purchase orders are written to `purchase_orders.json` but not loaded into the database yet. That belongs with the purchase order check in stage 3.
- VAT numbers are format-valid only. They do not pass the Dutch check-digit test, which the PRD does not ask for.
- No Azure subscription yet. Stage 2 needs Document Intelligence and Azure OpenAI.
