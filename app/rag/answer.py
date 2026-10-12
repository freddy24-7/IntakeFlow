"""Question answering over the contract archive with citations (PRD F7).

Rule 6: citations are resolved by code. The model sees numbered passages and
answers with numbers. The code turns each number into contract title, clause
and page. A number that was not offered is dropped and reported, and an answer
left without any valid citation is not shown: the system then says the answer
was not found in the documents.
"""

from dataclasses import dataclass, field

from pydantic import BaseModel, Field

from app.agents.prompts import Prompt
from app.inference.interfaces import ChatModel, EmbeddingModel, ModelUsage
from app.rag.interfaces import Passage, SearchIndex

NOT_FOUND = "Niet gevonden in de documenten."


class LlmAnswer(BaseModel):
    found: bool = Field(description="True only when the passages contain the answer.")
    answer: str = Field(description="The answer, or an empty text when not found.")
    passages: list[int] = Field(description="Numbers of the passages the answer rests on.")


@dataclass(frozen=True)
class Citation:
    number: int
    passage: Passage


@dataclass(frozen=True)
class Answer:
    found: bool
    text: str
    citations: list[Citation]
    # Passage numbers the model gave that were never offered. Reported, never shown as a source.
    dropped: list[int]
    offered: list[Passage]
    usage: list[ModelUsage] = field(default_factory=list)


def build_user_prompt(question: str, passages: list[Passage]) -> str:
    blocks = [
        f"[{number}] {passage.title}\n"
        f"Artikel {passage.clause_number}. {passage.heading}\n{passage.text}"
        for number, passage in enumerate(passages, start=1)
    ]
    joined = "\n\n".join(blocks)
    return f"<question>\n{question}\n</question>\n<passages>\n{joined}\n</passages>"


def resolve(answer: LlmAnswer, offered: list[Passage]) -> tuple[list[Citation], list[int]]:
    """Turn the model's passage numbers into citations. Unknown numbers are dropped."""
    citations, dropped, seen = [], [], set()
    for number in answer.passages:
        if number in seen:
            continue
        seen.add(number)
        if 1 <= number <= len(offered):
            citations.append(Citation(number, offered[number - 1]))
        else:
            dropped.append(number)
    return citations, dropped


async def answer_question(
    question: str,
    *,
    index: SearchIndex,
    embedder: EmbeddingModel,
    model: ChatModel,
    prompt: Prompt,
    top: int,
) -> Answer:
    embedded = await embedder.embed([question])
    offered = await index.search(question, embedded.vectors[0], top)
    if not offered:
        return Answer(False, NOT_FOUND, [], [], [], [embedded.usage])

    result = await model.structured(
        system=prompt.text, user=build_user_prompt(question, offered), schema=LlmAnswer
    )
    citations, dropped = resolve(result.value, offered)
    usage = [embedded.usage, result.usage]
    # No answer without a source that was really offered.
    if not result.value.found or not citations or not result.value.answer.strip():
        return Answer(False, NOT_FOUND, [], dropped, offered, usage)
    return Answer(True, result.value.answer.strip(), citations, dropped, offered, usage)
