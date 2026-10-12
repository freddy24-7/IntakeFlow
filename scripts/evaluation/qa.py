"""Measures contract question answering against the labelled questions.

For each question it records what the search offered and what the system
answered, and compares both with the label: was the right clause among the
passages, is the answer the labelled value, do the citations point to the right
clause and page, and does the system decline when the contract has no such clause.
"""

import asyncio
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from synthetic.questions import QuestionTruth
from synthetic.truth import DocumentTruth

from app.agents.prompts import ANSWER_CONTRACT, load_prompt
from app.observability.prices import PRICES_AS_OF, call_cost
from app.rag.answer import Answer, answer_question
from app.rag.interfaces import SearchIndex
from app.workflow import routing_steps, steps
from app.workflow.steps import Services
from evaluation import metrics
from evaluation.metrics import Rate
from evaluation.report import _table
from evaluation.run import ensure_ingested


def load_questions(data_dir: Path, limit: int | None) -> list[QuestionTruth]:
    raw = json.loads((data_dir / "questions.json").read_text(encoding="utf-8"))
    return [QuestionTruth.model_validate(item) for item in raw][:limit]


async def index_contracts(
    session_factory: async_sessionmaker[AsyncSession],
    services: Services,
    documents: Sequence[tuple[DocumentTruth, bytes]],
    namespace: str,
) -> dict[str, str]:
    """Read and index every contract of the set. Returns database id -> doc id.
    Both steps are skipped for contracts that were handled before."""
    contracts = [(truth, content) for truth, content in documents if truth.contract is not None]
    ids = await ensure_ingested(session_factory, services, contracts, namespace)
    for document_id in ids.values():
        async with session_factory() as session:
            await steps.read_text(session, services, document_id)
            await session.commit()
        async with session_factory() as session:
            await routing_steps.index_contract(session, services, document_id)
            await session.commit()
    return {str(document_id): doc_id for doc_id, document_id in ids.items()}


def contains_value(answer: str, accepted: Sequence[str]) -> bool:
    """Is one of the accepted values in the answer, as a whole number or word?
    "3" must not match inside "30" or "13"."""
    for value in accepted:
        pattern = rf"(?<![\w.,]){re.escape(value)}(?![\w]|[.,]\d)"
        if re.search(pattern, answer, re.IGNORECASE):
            return True
    return False


@dataclass
class Asked:
    question: QuestionTruth
    answer: Answer | None = None
    error: str | None = None
    # (doc id, clause number, page) of each passage offered and of each one cited
    offered: list[tuple[str, int, int]] = field(default_factory=list)
    cited: list[tuple[str, int, int]] = field(default_factory=list)

    @property
    def target(self) -> tuple[str, int] | None:
        question = self.question
        if question.doc_id is None or question.clause_number is None:
            return None
        return question.doc_id, question.clause_number

    @property
    def retrieved_rank(self) -> int | None:
        for rank, (doc_id, clause, _) in enumerate(self.offered, start=1):
            if (doc_id, clause) == self.target:
                return rank
        return None

    @property
    def answered(self) -> bool:
        return self.answer is not None and self.answer.found

    @property
    def right_value(self) -> bool:
        return self.answered and contains_value(self.answer.text, self.question.accepted)  # type: ignore[union-attr]

    @property
    def cites_target(self) -> bool:
        return any((doc_id, clause) == self.target for doc_id, clause, _ in self.cited)

    @property
    def cites_right_page(self) -> bool:
        return any(
            (doc_id, clause) == self.target and page == self.question.page
            for doc_id, clause, page in self.cited
        )

    @property
    def cites_other_contract(self) -> bool:
        return any(doc_id != self.question.doc_id for doc_id, _, _ in self.cited)


async def ask_all(
    questions: Sequence[QuestionTruth],
    *,
    index: SearchIndex,
    services: Services,
    doc_ids: dict[str, str],
    top: int,
    concurrency: int = 2,
    attempts: int = 4,
    pause_seconds: float = 15.0,
) -> list[Asked]:
    assert services.embedder is not None
    assert services.answerer is not None
    embedder, model = services.embedder, services.answerer
    prompt = load_prompt(ANSWER_CONTRACT)
    limiter = asyncio.Semaphore(concurrency)

    def locate(document_id: str, clause: int, page: int) -> tuple[str, int, int]:
        return doc_ids.get(document_id, "other set"), clause, page

    async def ask(question: QuestionTruth) -> Asked:
        asked = Asked(question)
        async with limiter:
            # Answers are not stored, so a question that hits a rate limit is
            # asked again here, after a pause, instead of being lost.
            for attempt in range(1, attempts + 1):
                try:
                    answer = await answer_question(
                        question.question,
                        index=index,
                        embedder=embedder,
                        model=model,
                        prompt=prompt,
                        top=top,
                    )
                    break
                except Exception as error:
                    if attempt == attempts:
                        asked.error = type(error).__name__
                        return asked
                    await asyncio.sleep(pause_seconds * attempt)
        asked.answer = answer
        asked.offered = [locate(p.document_id, p.clause_number, p.page) for p in answer.offered]
        asked.cited = [
            locate(c.passage.document_id, c.passage.clause_number, c.passage.page)
            for c in answer.citations
        ]
        return asked

    return list(await asyncio.gather(*(ask(question) for question in questions)))


def build_qa_report(
    runs: dict[str, list[Asked]],
    *,
    services: Services,
    top: int,
    contracts: int,
    passages: int,
    services_kind: str,
    today: date,
) -> str:
    out = [f"# Contract Q&A evaluation, {today.isoformat()}", ""]
    if services_kind != "azure":
        out += ["> **Not a measurement.** This run used fake services.", ""]
    first = next(iter(runs.values()))
    out += _table(
        ["Setting", "Value"],
        [
            ["Services", services_kind],
            ["Contracts indexed", f"{contracts} ({passages} passages)"],
            ["Questions", len(first)],
            ["Passages offered per question", top],
            ["Embedding model", services.embedder_name],
            ["Answering model", f"{services.answerer_name}, prompt {ANSWER_CONTRACT}"],
        ],
    )
    out += [
        "An answer is right when it contains the labelled value. A citation is right when it"
        " points to the labelled clause of the contract the question is about. For a question"
        " about a clause the contract does not have, the right behaviour is to decline.",
        "",
    ]

    for name, asked in runs.items():
        out += [f"## {name}", ""]
        failed = [item for item in asked if item.error]
        if failed:
            out += [
                "Failed: " + ", ".join(f"{i.question.question_id} ({i.error})" for i in failed),
                "",
            ]
        done = [item for item in asked if item.answer is not None]
        answerable = [item for item in done if item.question.answerable]
        unanswerable = [item for item in done if not item.question.answerable]
        right = [item for item in answerable if item.right_value]
        answered = [item for item in answerable if item.answered]

        out += ["### Search", ""]
        out += _table(
            ["Measure", "Value"],
            [
                [
                    f"Right clause among the {top} passages",
                    Rate(sum(i.retrieved_rank is not None for i in answerable), len(answerable)),
                ],
                [
                    "Right clause ranked first",
                    Rate(sum(i.retrieved_rank == 1 for i in answerable), len(answerable)),
                ],
            ],
        )

        out += ["### Questions the contract answers", ""]
        out += _table(
            ["Outcome", "Questions"],
            [
                ["Right answer", Rate(len(right), len(answerable))],
                [
                    "Answered with another value",
                    Rate(len(answered) - len(right), len(answerable)),
                ],
                [
                    "Declined although the answer is there",
                    Rate(len(answerable) - len(answered), len(answerable)),
                ],
            ],
        )

        out += ["### Citations on answered questions", ""]
        out += _table(
            ["Measure", "Value"],
            [
                [
                    "Cites the labelled clause",
                    Rate(sum(i.cites_target for i in answered), len(answered)),
                ],
                [
                    "Cited page equals the labelled page",
                    Rate(sum(i.cites_right_page for i in answered), len(answered)),
                ],
                [
                    "Cites a clause of another contract",
                    Rate(sum(i.cites_other_contract for i in answered), len(answered)),
                ],
                [
                    "Passage numbers that were never offered (dropped by the code)",
                    sum(len(i.answer.dropped) for i in done if i.answer),
                ],
            ],
        )

        out += ["### Questions without an answer in the contract", ""]
        missing = [i for i in unanswerable if i.question.doc_id is not None]
        uncovered = [i for i in unanswerable if i.question.doc_id is None]
        out += _table(
            ["Kind", "Rightly declined"],
            [
                [
                    "This contract has no such clause, others do",
                    Rate(sum(not i.answered for i in missing), len(missing)),
                ],
                [
                    "No contract covers the subject",
                    Rate(sum(not i.answered for i in uncovered), len(uncovered)),
                ],
            ],
        )
        wrongly = [i for i in unanswerable if i.answered]
        if wrongly:
            out += _table(
                ["Answered although it should decline", "Cited", "Answer given"],
                [
                    [
                        i.question.question_id,
                        ", ".join(f"{d} art. {c}" for d, c, _ in i.cited),
                        i.answer.text if i.answer else "",
                    ]
                    for i in wrongly
                ],
            )

        out += ["### By phrasing (questions the contract answers)", ""]
        rows = []
        for phrasing in ("near", "paraphrase", "english"):
            group = [i for i in answerable if i.question.phrasing == phrasing]
            rows.append(
                [
                    phrasing,
                    Rate(sum(i.retrieved_rank is not None for i in group), len(group)),
                    Rate(sum(i.right_value for i in group), len(group)),
                ]
            )
        out += _table(["Phrasing", f"Right clause in top {top}", "Right answer"], rows)

        latencies = [u.latency_ms for i in done if i.answer for u in i.answer.usage[1:]]
        cost = Decimal(0)
        for item in done:
            assert item.answer is not None
            for usage in item.answer.usage:
                cost += call_cost(
                    model=usage.model,
                    pages=0,
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                ) or Decimal(0)
        median, high = metrics.median_or_none(latencies), metrics.percentile(latencies, 95)
        out += ["### Latency and cost", ""]
        out += _table(
            ["Measure", "Value"],
            [
                ["Answering call, median", "n/a" if median is None else f"{median:,.0f} ms"],
                ["Answering call, 95th percentile", "n/a" if high is None else f"{high:,.0f} ms"],
                ["Cost per question", f"€ {cost / len(done):.4f}" if done else "n/a"],
                ["Cost of this run", f"€ {cost:.2f}"],
            ],
        )
    out += [
        f"Cost at the unit prices of {PRICES_AS_OF}. Embedding tokens are estimated, model"
        " tokens are as reported. The search service is on the free tier.",
        "",
    ]
    return "\n".join(out)
