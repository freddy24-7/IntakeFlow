"""The one door to a model (rule 1).

Every LLM and embedding call in the application goes through these protocols.
Real implementations (Azure OpenAI through LangChain) are added in stage 2 in
this package. Nothing outside `app/inference/` and `app/reading/` imports a
model client, and a test enforces that.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel


@dataclass(frozen=True)
class ModelUsage:
    """What one call cost. Recorded per document for the cost and latency report."""

    model: str
    input_tokens: int
    output_tokens: int
    latency_ms: float


@dataclass(frozen=True)
class StructuredResult[T: BaseModel]:
    value: T
    usage: ModelUsage


class ChatModel(Protocol):
    async def structured[T: BaseModel](
        self, *, system: str, user: str, schema: type[T]
    ) -> StructuredResult[T]:
        """Answer as an instance of `schema`."""
        ...


@dataclass(frozen=True)
class EmbeddingResult:
    vectors: list[list[float]]
    usage: ModelUsage


class EmbeddingModel(Protocol):
    async def embed(self, texts: Sequence[str]) -> EmbeddingResult: ...
