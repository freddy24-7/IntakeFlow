"""The door to document reading (rule 1).

The real implementation (Azure Document Intelligence) is added in stage 2 in
this package. Two calls, matching the workflow: text and layout for every
document, then invoice fields only for invoices and credit notes.
"""

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class PageText:
    number: int  # 1-based
    text: str


@dataclass(frozen=True)
class ReadField:
    name: str
    value: str
    confidence: float
    page: int


@dataclass(frozen=True)
class ReadResult:
    pages: list[PageText]
    fields: list[ReadField] = field(default_factory=list)
    # Kept for debugging and for comparing with the LLM's output (PRD F3).
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return "\n".join(page.text for page in self.pages)


class DocumentReader(Protocol):
    async def read_text(self, content: bytes) -> ReadResult:
        """Text and layout. Runs on every document, before classification."""
        ...

    async def read_invoice_fields(self, content: bytes) -> ReadResult:
        """Prebuilt invoice fields. Runs only on invoices and credit notes."""
        ...
