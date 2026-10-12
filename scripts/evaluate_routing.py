"""Measure validation and routing: auto-approval precision and rate, review workload.

    uv run python scripts/evaluate_routing.py --services azure

Works on the extractions stored by scripts/evaluate_extraction.py. Documents
that were not extracted yet are extracted first, which costs money with
`--services azure`. When everything is already extracted, nothing is called.
"""

import argparse
import asyncio
import json
from datetime import date
from pathlib import Path

from evaluation.oracle import oracle_services
from evaluation.routing import build_routing_report
from evaluation.run import load_dataset, run_evaluation

from app.agents.extract import VARIANTS
from app.config import get_settings
from app.db.base import create_engine, create_session_factory
from app.storage.local import LocalStorage
from app.workflow.services import build_azure_services


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--services", choices=("azure", "oracle"), required=True)
    parser.add_argument("--data", type=Path, default=Path("data/synthetic"))
    parser.add_argument("--limit", type=int, default=None, help="only the first N documents")
    parser.add_argument(
        "--name", default="eval", help="name of the run: keeps sets apart and labels the report"
    )
    parser.add_argument("--out", type=Path, default=None, help="report file (default: reports/)")
    arguments = parser.parse_args()

    settings = get_settings()
    documents = load_dataset(arguments.data / "documents", arguments.limit)
    orders = json.loads((arguments.data / "purchase_orders.json").read_text(encoding="utf-8"))
    if arguments.services == "azure":
        services = build_azure_services(settings)
    else:
        services = oracle_services(documents, LocalStorage(settings.storage_dir))

    engine = create_engine(settings.database_url)
    try:
        results = await run_evaluation(
            create_session_factory(engine),
            services,
            documents,
            VARIANTS,
            namespace=f"{arguments.name}-{arguments.services}",
            concurrency=2,
        )
    finally:
        await engine.dispose()
        close = getattr(services.reader, "close", None)
        if close is not None:
            await close()

    report = build_routing_report(
        results.documents,
        VARIANTS,
        orders,
        settings,
        today=date.today(),
        services_kind=arguments.services,
    )
    out = arguments.out
    if out is None and arguments.services == "azure":
        suffix = f"-first-{arguments.limit}" if arguments.limit else ""
        label = "" if arguments.name == "eval" else f"-{arguments.name}"
        out = Path("reports") / f"routing{label}-{date.today().isoformat()}{suffix}.md"
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(report + "\n", encoding="utf-8")
        print(f"Report written to {out}")
    else:
        print(report)


if __name__ == "__main__":
    asyncio.run(main())
