"""Measure contract question answering: retrieval, answers, citations, declining.

    uv run python scripts/evaluate_qa.py --services azure
    uv run python scripts/evaluate_qa.py --services azure \\
        --data data/synthetic-holdout --name holdout

Each run asks every question again, so with `--services azure` each run costs money.
"""

import argparse
import asyncio
import dataclasses
import uuid
from datetime import date
from pathlib import Path

from evaluation.oracle import oracle_answerer, oracle_services
from evaluation.qa import Asked, ask_all, build_qa_report, index_contracts, load_questions
from evaluation.run import load_dataset
from sqlalchemy import func, select

from app.config import get_settings
from app.db.base import create_engine, create_session_factory
from app.db.models import ContractPassage
from app.rag.azure_search import AzureSearchIndex
from app.rag.interfaces import SearchIndex
from app.storage.local import LocalStorage
from app.workflow.services import build_azure_services


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--services", choices=("azure", "oracle"), required=True)
    parser.add_argument("--data", type=Path, default=Path("data/synthetic"))
    parser.add_argument("--name", default="eval", help="name of the run and of its search index")
    parser.add_argument("--limit", type=int, default=None, help="only the first N questions")
    parser.add_argument(
        "--semantic", choices=("off", "on", "both"), default="both", help="semantic ranker"
    )
    parser.add_argument("--out", type=Path, default=None)
    arguments = parser.parse_args()

    settings = get_settings()
    documents = load_dataset(arguments.data / "documents", None)
    questions = load_questions(arguments.data, arguments.limit)
    index_name = f"contracts-{arguments.name}"
    semantic_index: SearchIndex | None = None
    if arguments.services == "azure":
        services = build_azure_services(settings, index_name=index_name)
        services = dataclasses.replace(services, storage=LocalStorage(settings.storage_dir))
        semantic_index = AzureSearchIndex.connect(
            endpoint=settings.azure_search_endpoint,
            name=index_name,
            dimensions=settings.embedding_dimensions,
            semantic=True,
        )
    else:
        # The in-memory index starts empty in every process, so the indexing step
        # gets a name of its own and runs again.
        services = dataclasses.replace(
            oracle_services(documents, LocalStorage(settings.storage_dir)),
            search_name=f"memory-{uuid.uuid4().hex[:8]}",
            answerer=oracle_answerer(questions, documents),
            answerer_name="oracle",
        )
    assert services.search is not None

    engine = create_engine(settings.database_url)
    session_factory = create_session_factory(engine)
    try:
        doc_ids = await index_contracts(
            session_factory, services, documents, f"{arguments.name}-{arguments.services}"
        )
        async with session_factory() as session:
            passages = (
                await session.execute(
                    select(func.count())
                    .select_from(ContractPassage)
                    .where(ContractPassage.document_id.in_(list(doc_ids)))
                )
            ).scalar_one()

        async def run(index: SearchIndex) -> list[Asked]:
            return await ask_all(
                questions,
                index=index,
                services=services,
                doc_ids=doc_ids,
                top=settings.search_top_k,
            )

        runs = {}
        if arguments.semantic in ("off", "both") or semantic_index is None:
            runs["Hybrid search"] = await run(services.search)
        if arguments.semantic in ("on", "both") and semantic_index is not None:
            runs["Hybrid search with semantic ranker"] = await run(semantic_index)
    finally:
        await engine.dispose()
        for closable in (services.reader, services.search, semantic_index):
            close = getattr(closable, "close", None)
            if close is not None:
                await close()

    report = build_qa_report(
        runs,
        services=services,
        top=settings.search_top_k,
        contracts=len(doc_ids),
        passages=passages,
        services_kind=arguments.services,
        today=date.today(),
    )
    out = arguments.out
    if out is None and arguments.services == "azure":
        label = "" if arguments.name == "eval" else f"-{arguments.name}"
        suffix = f"-first-{arguments.limit}" if arguments.limit else ""
        out = Path("reports") / f"qa{label}-{date.today().isoformat()}{suffix}.md"
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report + "\n", encoding="utf-8")
        print(f"Report written to {out}")
    else:
        print(report)


if __name__ == "__main__":
    asyncio.run(main())
