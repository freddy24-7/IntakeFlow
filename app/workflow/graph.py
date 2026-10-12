"""The document workflow as a LangGraph graph (PRD section 5).

    read_text -> classify -+-> read_fields -> extract -> validate -> decide -> apply
                           +-> index          (contracts)
                           +-> non_invoice    (other mail)

What LangGraph adds over the plain loop of stage 2: the branching is declared
instead of written as if-statements, each node can have a retry policy, and
the state after every node is saved by a checkpointer, so a run that stopped
can be resumed and inspected. Our steps were already idempotent, so resuming
would also work by simply starting over. The checkpoint mainly adds a record
of where a run stopped.

Each node opens its own database session and commits, so a step's output and
its audit record are stored before the graph moves on.
"""

import uuid
from collections.abc import Awaitable, Callable
from datetime import date
from typing import Any, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import RetryPolicy
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.audit import log as audit
from app.config import Settings
from app.db.models import Document, DocumentStatus
from app.validation import scoring
from app.workflow import routing_steps, steps
from app.workflow.steps import Services

STEP_ATTEMPT_FAILED = "attempt_failed"
STEP_DEAD_LETTERED = "dead_lettered"


class PipelineState(TypedDict, total=False):
    document_id: str
    label: str
    decision: str


Node = Callable[[PipelineState], Awaitable[dict[str, str]]]
Step = Callable[[AsyncSession, uuid.UUID], Awaitable[dict[str, str] | None]]


def build_graph(
    session_factory: async_sessionmaker[AsyncSession],
    services: Services,
    settings: Settings,
    *,
    checkpointer: BaseCheckpointSaver[Any] | None,
    today: Callable[[], date] = date.today,
    retry_initial_interval: float = 1.0,
) -> Any:
    variant = settings.extraction_variant

    def node(step: Step) -> Node:
        async def run(state: PipelineState) -> dict[str, str]:
            async with session_factory() as session:
                update = await step(session, uuid.UUID(state["document_id"]))
                await session.commit()
            return update or {}

        return run

    async def read_text(session: AsyncSession, document_id: uuid.UUID) -> None:
        await steps.read_text(session, services, document_id)

    async def classify(session: AsyncSession, document_id: uuid.UUID) -> dict[str, str]:
        return {"label": await steps.classify_document(session, services, document_id)}

    async def read_fields(session: AsyncSession, document_id: uuid.UUID) -> None:
        await steps.read_invoice_fields(session, services, document_id)

    async def extract(session: AsyncSession, document_id: uuid.UUID) -> None:
        await steps.extract_invoice(session, services, document_id, variant)

    async def validate(session: AsyncSession, document_id: uuid.UUID) -> None:
        await routing_steps.validate_invoice(
            session, services, document_id, variant, settings=settings, today=today()
        )

    async def decide(session: AsyncSession, document_id: uuid.UUID) -> dict[str, str]:
        decision = await routing_steps.decide_routing(
            session, services, document_id, variant, settings=settings
        )
        return {"decision": decision}

    async def apply(session: AsyncSession, document_id: uuid.UUID) -> None:
        await routing_steps.apply_decision(session, services, document_id, variant)

    async def index(session: AsyncSession, document_id: uuid.UUID) -> dict[str, str]:
        await routing_steps.index_contract(session, services, document_id)
        return {"decision": "indexed"}

    def after_classify(state: PipelineState) -> str:
        if steps.needs_extraction(state["label"]):
            return "read_fields"
        # Without contract search configured, a contract goes to a person like other mail.
        if state["label"] == "contract" and services.search is not None:
            return "index"
        return "non_invoice"

    async def non_invoice(state: PipelineState) -> dict[str, str]:
        async with session_factory() as session:
            await routing_steps.route_non_invoice(
                session, uuid.UUID(state["document_id"]), state["label"]
            )
            await session.commit()
        return {"decision": scoring.REVIEW}

    # Calls to Azure can be throttled or time out: retry those nodes with backoff.
    azure_retry = RetryPolicy(
        max_attempts=3, initial_interval=retry_initial_interval, backoff_factor=2.0
    )
    # LangGraph's overloads for add_node do not accept a plain async callable under
    # mypy --strict, so the builder is left untyped. The nodes themselves are typed.
    graph: Any = StateGraph(PipelineState)
    graph.add_node("read_text", node(read_text), retry_policy=azure_retry)
    graph.add_node("classify", node(classify), retry_policy=azure_retry)
    graph.add_node("read_fields", node(read_fields), retry_policy=azure_retry)
    graph.add_node("extract", node(extract), retry_policy=azure_retry)
    graph.add_node("validate", node(validate))
    graph.add_node("decide", node(decide))
    graph.add_node("apply", node(apply))
    graph.add_node("index", node(index), retry_policy=azure_retry)
    graph.add_node("non_invoice", non_invoice)

    graph.add_edge(START, "read_text")
    graph.add_edge("read_text", "classify")
    graph.add_conditional_edges("classify", after_classify, ["read_fields", "index", "non_invoice"])
    graph.add_edge("read_fields", "extract")
    graph.add_edge("extract", "validate")
    graph.add_edge("validate", "decide")
    graph.add_edge("decide", "apply")
    graph.add_edge("apply", END)
    graph.add_edge("non_invoice", END)
    graph.add_edge("index", END)
    return graph.compile(checkpointer=checkpointer)


async def run_document(
    graph: Any,
    session_factory: async_sessionmaker[AsyncSession],
    document_id: uuid.UUID,
    *,
    max_attempts: int,
) -> PipelineState | None:
    """Run or resume the workflow for one document.

    Returns the final state, or None when the run failed. A failure is counted
    on the document, and after `max_attempts` failures the document is parked
    with status `failed` (dead letter) for a person to look at.
    """
    config = {"configurable": {"thread_id": str(document_id)}}
    try:
        unfinished = False
        if graph.checkpointer is not None:
            unfinished = bool((await graph.aget_state(config)).next)
        # None continues from the last saved node. New input starts from the top.
        start = None if unfinished else {"document_id": str(document_id)}
        result: PipelineState = await graph.ainvoke(start, config)
    except Exception as error:
        await _record_failure(session_factory, document_id, type(error).__name__, max_attempts)
        return None
    return result


async def _record_failure(
    session_factory: async_sessionmaker[AsyncSession],
    document_id: uuid.UUID,
    error_kind: str,
    max_attempts: int,
) -> None:
    """Rule 8: only the kind of error is stored, because a message can quote the document."""
    async with session_factory() as session:
        document = await session.get_one(Document, document_id)
        document.attempts += 1
        document.last_error = error_kind[:64]
        parked = document.attempts >= max_attempts
        if parked:
            document.status = DocumentStatus.FAILED.value
        await audit.append(
            session,
            step=STEP_DEAD_LETTERED if parked else STEP_ATTEMPT_FAILED,
            document_id=document_id,
            payload={"error": error_kind, "attempt": document.attempts},
        )
        await session.commit()
