# IntakeFlow: PRD

A portfolio project: an Azure-hosted pipeline that turns incoming invoices and supplier contracts (PDF) into validated structured data, routes uncertain cases to a person, and answers questions about the contract archive with citations. Built with LangChain and LangGraph on Azure services.

**Status:** draft for building with Claude Code. Verify current Azure service names, limits, prices and language support before each stage, as they change.

---

## 1. Why this project

- It targets what Forward Deployed / AI Engineer vacancies in the Netherlands ask for: document intelligence, pipelines over many documents, LLMs connected to data and APIs, deployment in Azure, and attention to reliability, quality, latency and cost.
- It complements Muni Mailbox. Muni Mailbox was built by hand on open-source parts (FastAPI, Redis Streams, Presidio, ChromaDB, Ollama/Mistral). IntakeFlow uses a framework (LangChain, LangGraph) and Azure-native services. The comparison between the two is part of the deliverable.
- All data is synthetic, so there are no privacy or licensing problems.

**The question the project works through:** how do you get reliable structured data out of messy documents with an LLM, know how reliable it is, and keep a person in charge of the uncertain cases, at a cost you can state per document?

## 2. Scenario

A fictional mid-size Dutch company, "Noordzee Logistiek B.V.", receives about 200 documents per week by upload or mail: supplier invoices, credit notes and a smaller number of contracts. Today a finance employee types the data into the accounting system and checks invoices against purchase orders by hand.

IntakeFlow reads each document, extracts the fields, checks them against the purchase order data, and approves clean documents automatically. Anything uncertain or inconsistent goes to a review queue. Contracts are indexed so staff can ask questions such as "Wat is de opzegtermijn in het contract met leverancier X?" and get an answer with the source passage.

## 3. Users and roles

| Role | Sees and does |
| --- | --- |
| Finance clerk | Review queue, side-by-side document and extracted fields, correct and approve or reject |
| Contract manager | Asks questions over the contract archive, sees cited passages |
| Team lead | Dashboard: volumes, share handled automatically, accuracy, cost per document |

Authentication is out of scope for stage 1 (demo user picker, as in Muni Mailbox). Stage 6 adds Microsoft Entra ID as an optional extra.

## 4. Scope

**In scope**
- Upload and ingestion of PDFs (digital and scanned)
- Layout and field extraction
- LLM-based structured extraction and normalisation
- Validation rules and cross-checks against purchase order data
- Confidence scoring and routing
- Human review queue with approve, correct and reject
- Contract question answering with citations
- Evaluation harness with a labelled synthetic test set
- Cost and latency tracking per document
- Deployment on Azure with infrastructure as code and CI/CD

**Out of scope**
- Real accounting integration (a mock "ERP" table stands in)
- Real payments, real customer data
- Multi-tenant support
- Fine-tuning models

## 5. Workflow

Implemented as a LangGraph graph with persisted state, so each document's progress is stored and a run can be resumed.

```
Upload -> Read text (Azure Document Intelligence layout/read: text and layout, every document)
       -> Classify (invoice / credit note / contract / other)
       -> Read fields (Document Intelligence prebuilt invoice, invoices and credit notes only)
       -> Extract (LLM, structured output against a schema)
       -> Validate (rules + purchase order cross-check)
       -> Score (combine field confidences and validation results)
            |-- high confidence, all checks pass --> Auto-approve -> Mock ERP
            |-- otherwise ------------------------> Review queue -> Clerk -> Approve / Correct / Reject
       Contracts also -> Chunk -> Embed -> Index in Azure AI Search
```

Design rules, carried over from Muni Mailbox:
- Each step does one job and writes its result to the database.
- A step that already ran is skipped on retry (idempotent).
- The model never decides on approval alone. Auto-approval requires deterministic checks to pass, and the thresholds are configurable and measured.
- Corrections by a clerk are stored next to the model's output, never over it, so "approved unchanged" stays measurable.

## 6. Functional requirements

**F1 Ingestion**
- Upload single or multiple PDFs. Store the original in Blob Storage, metadata in PostgreSQL.
- Reject non-PDF and oversized files with a clear message.

**F2 Classification**
- Classify document type with an LLM call that returns a label and a confidence. Unknown types go to review.
- Classification runs on the text from the layout/read pass, because a scanned PDF has no text before it is read.

**F3 Reading**
- Use Azure Document Intelligence (prebuilt invoice model and layout/read) for text and fields. Verify Dutch support and field coverage before relying on it.
- Layout/read runs on every document before classification. The prebuilt invoice model runs after classification, only on invoices and credit notes.
- Keep the raw reading result for debugging and for comparing with the LLM's output.

**F4 Extraction**
- LangChain structured output into a Pydantic schema: supplier name, supplier VAT number (BTW-nummer), IBAN, invoice number, invoice date, due date, currency, line items, subtotal, VAT, total, purchase order reference.
- Each field carries the source text span or page, so the reviewer can see where it came from.
- Where Document Intelligence and the LLM disagree, flag the field.

**F5 Validation**
- Totals equal the sum of the lines plus VAT, within rounding.
- Dates are plausible, and the due date is not before the invoice date.
- BTW-nummer format check, and IBAN checksum.
- Purchase order exists, supplier matches, amount within tolerance.
- Duplicate invoice detection (same supplier and number).

**F6 Routing and review**
- Route by combined score and rule outcomes. Every routing decision records the reasons.
- Review page shows the document next to the extracted fields, with disagreements and failed checks highlighted.
- Clerk can edit, approve or reject. Only approved data reaches the mock ERP, through one code path that requires a reviewed or auto-approved status. A test enforces this.

**F7 Contract Q&A**
- Chunk contracts by clause, embed them, and index them in Azure AI Search (hybrid: keyword and vector).
- Answers cite the clause and page. The model answers with passage numbers, and the code resolves them to title and page, so a source cannot be invented.
- If no passage supports an answer, the system says so.

**F8 Audit**
- Every step is written to an append-only, hash-chained audit log (same approach as Muni Mailbox).

**F9 Dashboard**
- Documents per day, share auto-approved, share corrected by clerks, median time to result, cost per document, field-level accuracy against the labelled set.

## 7. Technology

| Layer | Choice | Note |
| --- | --- | --- |
| Language and API | Python 3.12, FastAPI, async | Same as earlier projects |
| Orchestration | LangGraph, with LangChain for model, parsing and retrieval components | The framework is the point of the project |
| Models | Azure OpenAI (chat and embeddings) in an EU region | Behind a thin model interface so it stays swappable |
| Document reading | Azure AI Document Intelligence | Prebuilt invoice and layout |
| Search | Azure AI Search (hybrid, with the semantic ranker if available) | Replaces ChromaDB from Muni Mailbox |
| Storage | Azure Blob Storage (files), PostgreSQL (state, audit, results) | Keep Postgres as a container in early stages to save cost |
| Queue | In-process worker behind a small interface locally, Azure Queue Storage from stage 6 | Replaces Redis Streams |
| Hosting | Azure Container Apps | Scale to zero where possible |
| Secrets and identity | Managed identity, Key Vault | No keys in the repository |
| Infrastructure as code | Bicep | One command to create and to delete the environment |
| Observability | OpenTelemetry to Application Insights. LangSmith traces stay an optional later switch | Logs without document content or personal identifiers |
| Frontend | Server-rendered Jinja2 with HTMX | Same as Muni Mailbox |
| Quality | pytest, Playwright, ruff, mypy, GitHub Actions | Coverage gate in CI |

**Testing approach:** the models, Document Intelligence and Search are replaced by fakes behind the same interfaces, so the pipeline logic runs in CI without Azure. A smaller set of integration tests runs against real services on demand.

## 8. Synthetic data

- Generate 150 to 200 documents with known ground truth: invoices with varied layouts, fonts, languages (Dutch with some English), line item counts, VAT rates, credit notes, and a handful of contracts with clauses on notice period, price indexation, liability and termination.
- Include hard cases on purpose: scanned and skewed pages, stamps, missing PO number, totals that do not add up, duplicate invoices, a wrong IBAN, amounts with Dutch number formatting (1.234,56).
- Keep the generator and the ground-truth files in the repository, with a fixed random seed.
- Label everything before measuring, including the hard cases. **Lesson from Muni Mailbox: what is not labelled is not measured.**

## 9. Evaluation and measured results

Report these in the README, with how each was measured, including the unflattering ones.

| Measure | Method |
| --- | --- |
| Field-level accuracy per field | Extracted vs ground truth, per field and per document type |
| Exact-match document rate | Share of documents with every field right |
| Auto-approval precision | Of auto-approved documents, how many had an error (the most important number) |
| Auto-approval rate | Share approved without a person |
| Review workload | Share routed to review, and why |
| Contract Q&A | Right clause among the top results, citation correctness, and a set of unanswerable questions where the right behaviour is to decline |
| Latency | Median and 95th percentile per document, per step |
| Cost | Tokens and service charges per document, and per 1,000 documents |
| Baseline comparison | Document Intelligence only vs LLM only vs combined |

Planned comparison for the portfolio story: **IntakeFlow vs Muni Mailbox**, covering lines of code for retrieval and orchestration, how much control each gave, how each was tested, and what each cost to run.

## 10. Non-functional requirements

- **Reliability:** retries with backoff on all Azure calls, idempotent steps, dead-letter handling for documents that keep failing.
- **Security:** managed identity and Key Vault, private storage, no document text in logs, least-privilege roles.
- **Cost control:** budget alert, per-document cost recorded, a configuration switch for a cheaper model on classification, scale-to-zero hosting.
- **Operability:** one command to deploy, one to tear down, a health endpoint, and a runbook in the README.

## 11. Stages

Each stage ends with working software, tests and a short note of what was learned (as in the Muni Mailbox cards).

1. **Foundations and data.** Repository, CI, synthetic data generator with ground truth, local PostgreSQL, fake services, the mock ERP, and the hash-chained audit log (so steps are idempotent from stage 2 on).
2. **Reading and extraction.** Upload, classification, Document Intelligence integration, LangChain structured extraction, schema, per-call cost and latency recording, field-level evaluation, baseline comparison. Needs a minimal Bicep file for Document Intelligence and Azure OpenAI only, with a budget alert first.
3. **Validation and routing.** Rules, purchase order check, scoring, LangGraph workflow with persisted state, dead-letter handling.
4. **Review interface.** Queue, side-by-side review, edits stored separately, single path to the mock ERP, dashboard.
5. **Contract Q&A.** Chunking, embeddings, AI Search hybrid index, cited answers, unanswerable-question tests.
6. **Azure deployment.** Infrastructure as code, Container Apps, managed identity and Key Vault, Azure Queue Storage, CI/CD, monitoring, cost report. Optional: Entra ID login.
7. **Write-up.** README with measured results, honest findings, limits, and the IntakeFlow vs Muni Mailbox comparison.

Stages 1 to 3 already give a presentable first version. Stages 4 to 7 can follow.

## 12. Honest limits to state in the README

- A demo, not a product. Fictional company, synthetic documents.
- Real invoices are messier than generated ones, so accuracy numbers are an upper bound.
- Extraction quality depends on the models and may change when they are updated.
- State plainly which parts were deployed and run in Azure, and which were not.

## 13. Skill coverage map

| Skill from vacancies | Where in the project |
| --- | --- |
| Python applications, agents and services | FastAPI app, LangGraph workflow |
| LLMs connected to data, APIs and existing systems | Structured extraction, mock ERP, purchase order lookup |
| RAG, retrieval, document intelligence | Contract Q&A with AI Search, Document Intelligence |
| LangChain / LangGraph | Orchestration, structured output, retrievers |
| Deploy and manage in Azure | Container Apps, Blob, AI Search, Key Vault, managed identity, IaC |
| Reliability, security, quality, latency, cost | Evaluation, routing thresholds, cost per document, audit log |
| Test and improve with users | Review queue, tracking of clerk corrections |
| Translate a business problem into a technical solution | Scenario, requirements, the auto-approval precision target |

## 14. Open decisions

Decided on 2026-10-11:
- Infrastructure as code: Bicep (Azure-only project, no state file to manage).
- Traces: OpenTelemetry and Application Insights only. LangSmith can be switched on later.
- Workflow order: layout/read before classification (see section 5).
- Region and models (2026-10-12): Sweden Central, `gpt-4.1-mini` for classification and `gpt-4.1` for extraction, as regional Standard deployments because the subscription has no EU data-zone quota for them.
- Queue: in-process worker locally, Azure Queue Storage in stage 6.

Still open:
- Which extraction variant the pipeline uses. Two sets of 200 documents gave opposite rankings (Document Intelligence only best on seed 42, worst on seed 43), because errors cluster per supplier layout. Over both sets the variants are too close to rank. See cards/03-validation-and-routing.md.
- The auto-approve threshold. Routing by validation alone (threshold 0) was fixed in advance and held up on the hold-out set: every labelled problem caught, 0 to 4 wrong auto-approvals per variant out of 123 to 130. The configured default is still 0.90.
- How to score: leave the score out, weigh payment fields only, or calibrate Document Intelligence's confidence.
