"""The door to the search index. Azure AI Search in production, an in-memory
index in tests, both behind `SearchIndex`."""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Passage:
    """One clause of one contract, with what a citation needs."""

    id: str
    document_id: str
    title: str
    clause_number: int
    heading: str
    page: int
    text: str


class SearchIndex(Protocol):
    async def upsert(self, passages: Sequence[Passage], vectors: Sequence[list[float]]) -> None:
        """Add or replace passages. Safe to repeat: a passage id is stored once."""
        ...

    async def search(self, query: str, vector: list[float], top: int) -> list[Passage]:
        """Hybrid search: keyword and vector results combined, best first."""
        ...
