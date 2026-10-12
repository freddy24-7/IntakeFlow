"""Fakes behind the model interfaces, so the pipeline runs in seconds without Azure."""

import hashlib
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from pydantic import BaseModel

from app.inference.interfaces import EmbeddingResult, ModelUsage, StructuredResult

# A scripted answer is either a fixed value or a function of the user prompt.
type Scripted = BaseModel | Callable[[str], BaseModel]


@dataclass(frozen=True)
class RecordedCall:
    system: str
    user: str
    schema: type[BaseModel]


@dataclass
class FakeChatModel:
    """Returns the scripted answer for the requested schema and records every call."""

    answers: dict[type[BaseModel], Scripted] = field(default_factory=dict)
    calls: list[RecordedCall] = field(default_factory=list)
    model: str = "fake-chat"

    async def structured[T: BaseModel](
        self, *, system: str, user: str, schema: type[T]
    ) -> StructuredResult[T]:
        self.calls.append(RecordedCall(system=system, user=user, schema=schema))
        if schema not in self.answers:
            raise LookupError(f"FakeChatModel has no scripted answer for {schema.__name__}")
        scripted = self.answers[schema]
        value = scripted if isinstance(scripted, BaseModel) else scripted(user)
        if not isinstance(value, schema):
            raise TypeError(f"scripted answer for {schema.__name__} is {type(value).__name__}")
        usage = ModelUsage(
            model=self.model,
            input_tokens=_rough_tokens(system) + _rough_tokens(user),
            output_tokens=_rough_tokens(value.model_dump_json()),
            latency_ms=0.0,
        )
        return StructuredResult(value=value, usage=usage)


@dataclass
class FakeEmbeddingModel:
    """Deterministic bag-of-words vectors: each word is hashed to one dimension.

    Texts that share words get similar vectors, which is enough for tests of
    search. It knows nothing about meaning: a paraphrase gets no credit.
    """

    dimensions: int = 64
    model: str = "fake-embedding"

    async def embed(self, texts: Sequence[str]) -> EmbeddingResult:
        vectors = [self._vector(text) for text in texts]
        usage = ModelUsage(
            model=self.model,
            input_tokens=sum(_rough_tokens(text) for text in texts),
            output_tokens=0,
            latency_ms=0.0,
        )
        return EmbeddingResult(vectors=vectors, usage=usage)

    def _vector(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        for word in re.findall(r"\w+", text.casefold()):
            digest = hashlib.sha256(word.encode("utf-8")).digest()
            vector[int.from_bytes(digest[:4], "big") % self.dimensions] += 1.0
        return vector


def _rough_tokens(text: str) -> int:
    return max(1, len(text) // 4)
