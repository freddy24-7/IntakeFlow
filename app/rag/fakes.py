"""An in-memory search index for tests. Same hybrid idea as the real one, in miniature."""

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from app.rag.interfaces import Passage

_WORD = re.compile(r"\w+")
RRF_K = 60


def _words(text: str) -> set[str]:
    return {word.casefold() for word in _WORD.findall(text)}


def _cosine(first: Sequence[float], second: Sequence[float]) -> float:
    dot = sum(a * b for a, b in zip(first, second, strict=True))
    norm = math.sqrt(sum(a * a for a in first)) * math.sqrt(sum(b * b for b in second))
    return dot / norm if norm else 0.0


@dataclass
class InMemorySearchIndex:
    passages: dict[str, Passage] = field(default_factory=dict)
    vectors: dict[str, list[float]] = field(default_factory=dict)

    async def upsert(self, passages: Sequence[Passage], vectors: Sequence[list[float]]) -> None:
        for passage, vector in zip(passages, vectors, strict=True):
            self.passages[passage.id] = passage
            self.vectors[passage.id] = vector

    async def search(self, query: str, vector: list[float], top: int) -> list[Passage]:
        """Rank by keyword overlap and by vector similarity, then combine the two
        rankings with reciprocal rank fusion, as Azure AI Search does."""
        query_words = _words(query)

        def keyword(passage: Passage) -> float:
            return float(
                len(query_words & _words(f"{passage.title} {passage.heading} {passage.text}"))
            )

        def similarity(passage: Passage) -> float:
            return _cosine(vector, self.vectors[passage.id])

        scores: dict[str, float] = dict.fromkeys(self.passages, 0.0)
        for ranking in (keyword, similarity):
            ordered = sorted(self.passages.values(), key=ranking, reverse=True)
            for rank, passage in enumerate(ordered, start=1):
                scores[passage.id] += 1 / (RRF_K + rank)
        best = sorted(self.passages.values(), key=lambda p: scores[p.id], reverse=True)
        return best[:top]
