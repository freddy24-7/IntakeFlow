"""Splits a contract into one passage per clause (PRD F7).

A clause is the unit a contract manager asks about and the unit a citation
points to, so it is also the unit that is embedded and indexed. Each passage
keeps its clause number, heading and the page it starts on.
"""

import re
from dataclasses import dataclass

from app.reading.interfaces import ReadResult

# "Artikel 3. Opzegging", and the English forms for contracts in English.
_CLAUSE = re.compile(r"^(?:Artikel|Article|Clause)\s+(\d+)\s*[.:]?\s*(.*)$", re.IGNORECASE)
_PAGE_FOOTER = re.compile(r"pagina\s+\d+\s+van\s+\d+|page\s+\d+\s+of\s+\d+", re.IGNORECASE)
PREAMBLE_HEADING = "Aanhef"
_AFTER_TITLE = re.compile(
    r"^(Contractnummer|Contract number|Partijen|Parties|\d+\.)", re.IGNORECASE
)
MAX_TITLE_LINES = 3


@dataclass(frozen=True)
class Chunk:
    clause_number: int  # 0 for the text before the first clause
    heading: str
    page: int  # page the clause starts on, 1-based
    text: str


def chunk_contract(reading: ReadResult) -> tuple[str, list[Chunk]]:
    """Return the contract's title and its clauses in order."""
    title_lines: list[str] = []
    title_done = False
    chunks: list[Chunk] = []
    number, heading, page = 0, PREAMBLE_HEADING, 1
    lines: list[str] = []

    def close() -> None:
        text = " ".join(" ".join(lines).split())
        if text:
            chunks.append(Chunk(number, heading, page, text))

    for read_page in reading.pages:
        for raw in read_page.text.splitlines():
            line = raw.strip()
            if not line or _PAGE_FOOTER.search(line):
                continue
            match = _CLAUSE.match(line)
            # The title names the parties and can wrap over several lines. It ends
            # at the first line that starts something else.
            if not title_done:
                if match or _AFTER_TITLE.match(line) or len(title_lines) == MAX_TITLE_LINES:
                    title_done = True
                else:
                    title_lines.append(line)
                    continue
            if match:
                close()
                number, heading = int(match.group(1)), match.group(2).strip()
                page, lines = read_page.number, []
            else:
                lines.append(line)
    close()
    return " ".join(title_lines), chunks
