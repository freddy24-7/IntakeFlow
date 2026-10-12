# CLAUDE.md

Guidance for Claude Code when working on **IntakeFlow**. Read `docs/PRD.md` first (copy of `intakeflow-prd.md`). The PRD is the source of truth for scope, workflow and stages. If this file and the PRD disagree, stop and ask.

## What this project is

A portfolio project: an Azure-hosted pipeline that turns synthetic invoices and contracts (PDF) into validated structured data, routes uncertain cases to a human reviewer, and answers questions about a contract archive with citations. Built with Python, LangChain and LangGraph on Azure services (Document Intelligence, Azure OpenAI, AI Search, Blob Storage, Container Apps).

It is a demo, not a product. All data is synthetic. There is no real customer data, ever.

## How we work

- Work **one stage at a time**, in the order given in the PRD (section 11). Each stage ends with working software, passing tests and a short concept note in `cards/` (what was decided and why, what was seen in practice, what is still open).
- Before starting a stage, state the plan in a few lines and wait for confirmation if it changes scope, adds a dependency or touches Azure resources.
- Prefer small, reviewable changes. Commit per logical step with a clear message.
- When something is ambiguous, ask. Do not guess at requirements.

## Architecture rules (do not break these)

1. **One door to a model.** All LLM, embedding and Document Intelligence calls go through the interfaces in `app/inference/` (and `app/reading/`), and all Azure AI Search calls through the interface in `app/rag/`. No other module imports an Azure or LangChain model client or the search client directly.
2. **Steps are stateless and idempotent.** A step reads its input from the database and writes its output to the database. A step that already ran (recognised by its audit record) is skipped on retry. Every step must be safe to receive twice.
3. **The model never approves alone.** Auto-approval requires deterministic validation to pass and the combined score to meet the configured threshold. Thresholds live in configuration, and changes to them are measured.
4. **One path to the (mock) ERP.** Only documents with status `approved` or `auto_approved` may be written there, through a single function. A test reads the source and fails if a second path appears.
5. **Human edits never overwrite model output.** Store corrections next to the model's extraction so "approved unchanged" stays a simple lookup.
6. **Citations are resolved by code.** The model answers with passage numbers, and the code looks up title and page. Any number that was not offered is dropped and reported. The system must be able to answer "not found in the documents".
7. **The audit log is append-only and hash-chained.** Do not add update or delete paths for it.
8. **No document content or personal identifiers in logs or metric labels.** Use correlation IDs.

## Tech and conventions

- Python 3.12, FastAPI, async throughout. PostgreSQL with SQLAlchemy 2 (async) and Alembic. Pydantic v2 for schemas and settings.
- LangGraph for the workflow with persisted state. LangChain for model wrappers, structured output, loaders and retrievers. Keep LangChain usage behind our own interfaces so it can be swapped.
- Frontend: server-rendered Jinja2 with HTMX. No SPA framework.
- Dependency management with `uv`. Pin versions. Do not add a dependency without saying why.
- Type hints everywhere. `mypy --strict` must pass. `ruff` for lint and format.
- Small modules, one job each. Layout as in the PRD: `app/agents|workflow|reading|inference|rag|review|audit|auth|observability|web`, plus `prompts/`, `tests/`, `deploy/`, `cards/`, `scripts/`.
- Prompts are versioned files in `prompts/`, not inline strings.
- Dutch numbers and dates (`1.234,56`, `15-10-2026`) must be handled explicitly and tested.
- Code, comments and docs in English. UI text may be Dutch.

## Testing

- `pytest` for unit and integration, `Playwright` for a few end-to-end browser tests.
- Models, Document Intelligence and AI Search are replaced by **fakes behind the same interfaces**, so the pipeline runs in seconds without Azure. Real-service tests are marked `azure` and run only on request.
- Tests build the pipeline wrongly on purpose to prove the guarantees hold (rules 1, 3 and 4 above).
- CI (GitHub Actions) runs lint, types and tests, and fails below the coverage gate (start at 70%, raise it later).
- Evaluation is a script, not a test: `scripts/evaluate_extraction.py` and `scripts/evaluate_qa.py` produce reports against the labelled synthetic set. Never edit labels to improve a score.

## Data

- The generator in `scripts/generate_synthetic.py` uses a fixed seed and writes ground truth next to every document.
- **Label everything before measuring**, including hard cases. What is not labelled is not measured.
- Do not download or add real invoices, contracts or personal data. If one is needed for a test, generate it.

## Azure rules (cost and safety)

- **Never create, scale up or deploy billable Azure resources without explicit confirmation** in the current conversation. Show the intended resources and rough cost first.
- Infrastructure is code (Bicep or Terraform, decision in the PRD). One command creates the environment and one command deletes it.
- Use managed identity and Key Vault. **Never put keys, connection strings or tokens in the repository, in logs, or in chat.** `.env` is git-ignored, and `.env.example` documents the variables.
- Set a budget alert before the first deployment. Prefer scale-to-zero and the smallest tiers. Remind the user to delete resources when a session ends.
- Verify current service names, limits, prices and language support (especially Dutch in Document Intelligence) before relying on them. Do not assume.

## Honesty rules

- Report only numbers that were measured, with how they were measured. Include unflattering results.
- The README must say plainly what was built, what was deployed and run in Azure, and what was not.
- If something does not work or was not tested, say so. Do not describe planned work as done.
- Do not claim production use, real customers or real data.

## Definition of done (per stage)

- Code works and is covered by tests that pass locally and in CI.
- `ruff`, `mypy --strict` and the test suite are green.
- The relevant evaluation was run and the result recorded.
- A concept note is added to `cards/`.
- The README and PRD status are updated if scope or decisions changed.
- No secrets, no real data, no stray billable resources.

## Commands (create these in stage 1 and keep this list current)

```bash
cp .env.example .env                      # once, then choose a local database password
uv sync                                   # install dependencies
docker compose up -d                      # local PostgreSQL (reads .env)
uv run alembic upgrade head               # migrations
uv run python scripts/generate_synthetic.py --documents 200 --seed 42
uv run uvicorn app.main:app --reload      # http://localhost:8000
uv run pytest tests/unit tests/integration
uv run playwright install chromium        # once, downloads the test browser
uv run pytest tests/e2e                   # browser tests (start their own server and database)
uv run ruff check . && uv run mypy .
uv run python scripts/evaluate_extraction.py --services oracle --limit 20   # harness check, no Azure
uv run python scripts/evaluate_extraction.py --services azure               # real measurement, costs money
uv run python scripts/evaluate_routing.py --services azure                  # routing, on stored extractions
uv run python scripts/evaluate_qa.py --services oracle                      # contract Q&A harness check, no Azure
uv run python scripts/evaluate_qa.py --services azure                       # contract Q&A, asks every question again (costs money)
uv run python scripts/load_purchase_orders.py                               # purchase orders into the database
uv run pytest tests/azure -m azure        # smoke test against real Azure, on request only
./deploy/up.sh --what-if                  # preview the Azure environment, changes nothing
./deploy/up.sh                            # create it (needs explicit confirmation first)
./deploy/up-app.sh                        # also deploy the application (costs money while it exists, confirm first)
./deploy/down-app.sh                      # remove the application, keep the AI resources
./deploy/down.sh                          # delete everything
```

## Working with the author

The author is a developer moving into AI engineering and uses this project to learn: LangChain, LangGraph and Azure. Explain choices briefly as you go, name the trade-offs (especially framework vs hand-built), and prefer clear code over clever code. Do not compare with other projects in the README or the cards.
