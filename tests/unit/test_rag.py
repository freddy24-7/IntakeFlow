"""Stage 5 without Azure: chunking, the fake index, answering and rule 6."""

from typing import Any

import pytest
from synthetic.build import generate
from synthetic.write import render_document

from app.agents.prompts import ANSWER_CONTRACT, load_prompt
from app.inference.fakes import FakeChatModel, FakeEmbeddingModel
from app.rag.answer import NOT_FOUND, LlmAnswer, answer_question, build_user_prompt, resolve
from app.rag.azure_search import AzureSearchIndex, index_definition, to_document, to_passage
from app.rag.chunking import chunk_contract
from app.rag.fakes import InMemorySearchIndex
from app.rag.interfaces import Passage
from app.rag.retriever import ContractRetriever
from app.reading.fakes import extract_text_layer
from app.reading.interfaces import PageText, ReadResult

CONTRACT = ReadResult(
    pages=[
        PageText(
            1,
            "Dienstverleningsovereenkomst Noordzee Logistiek B.V. - Arens Software B.V.\n"
            "Contractnummer OVK-2025-001\nPartijen\n1. Noordzee Logistiek B.V.\n"
            "Artikel 1. Looptijd\n1.1 Deze overeenkomst gaat in op 1 januari 2025.\n"
            "Artikel 2. Opzegging\n2.1 Opzegtermijn van 3 maanden,\n"
            "OVK-2025-001 - pagina 1 van 2",
        ),
        PageText(
            2,
            "schriftelijk per aangetekende brief.\n"
            "Artikel 3. Toepasselijk recht en geschillen\n3.1 Nederlands recht.\n"
            "OVK-2025-001 - pagina 2 van 2",
        ),
    ]
)


def test_contract_is_split_per_clause_with_start_page() -> None:
    title, chunks = chunk_contract(CONTRACT)

    assert title.startswith("Dienstverleningsovereenkomst")
    assert [(c.clause_number, c.heading, c.page) for c in chunks] == [
        (0, "Aanhef", 1),
        (1, "Looptijd", 1),
        (2, "Opzegging", 1),
        (3, "Toepasselijk recht en geschillen", 2),
    ]
    # A clause that runs over a page break stays one passage, without the page footer.
    assert chunks[2].text == "2.1 Opzegtermijn van 3 maanden, schriftelijk per aangetekende brief."
    assert "pagina" not in " ".join(chunk.text for chunk in chunks)


def test_chunks_match_the_labels_of_every_synthetic_contract() -> None:
    dataset = generate(40, seed=3)
    for doc in dataset.documents:
        if doc.contract is None:
            continue
        pdf = render_document(doc, dataset.plans[doc.doc_id])
        _, chunks = chunk_contract(ReadResult(pages=extract_text_layer(pdf)))
        found = {(c.clause_number, c.heading, c.page) for c in chunks}
        labelled = {(c.number, c.heading, c.page) for c in doc.contract.clauses}
        assert labelled <= found


def _passage(number: int, supplier: str, heading: str, text: str, page: int = 1) -> Passage:
    return Passage(
        id=f"{supplier}-{number}",
        document_id=supplier,
        title=f"Dienstverleningsovereenkomst Noordzee Logistiek B.V. - {supplier}",
        clause_number=number,
        heading=heading,
        page=page,
        text=text,
    )


PASSAGES = [
    _passage(3, "Arens Software B.V.", "Opzegging", "Opzegtermijn van 3 maanden.", page=2),
    _passage(5, "Arens Software B.V.", "Facturering en betaling", "Betaling binnen 30 dagen."),
    _passage(3, "Willems Transport B.V.", "Opzegging", "Opzegtermijn van 6 maanden."),
]


async def _index() -> tuple[InMemorySearchIndex, FakeEmbeddingModel]:
    index, embedder = InMemorySearchIndex(), FakeEmbeddingModel()
    embedded = await embedder.embed([passage.text for passage in PASSAGES])
    await index.upsert(PASSAGES, embedded.vectors)
    return index, embedder


async def _ask(
    answer: LlmAnswer, question: str = "Wat is de opzegtermijn bij Arens Software?"
) -> Any:
    index, embedder = await _index()
    model = FakeChatModel(answers={LlmAnswer: answer})
    result = await answer_question(
        question,
        index=index,
        embedder=embedder,
        model=model,
        prompt=load_prompt(ANSWER_CONTRACT),
        top=3,
    )
    return result, model


async def test_fake_index_finds_by_keywords_and_upsert_replaces() -> None:
    index, embedder = await _index()
    await index.upsert(PASSAGES[:1], (await embedder.embed(["again"])).vectors)

    query = "opzegtermijn Arens Software"
    found = await index.search(query, (await embedder.embed([query])).vectors[0], top=1)

    assert len(index.passages) == 3
    assert found == [PASSAGES[0]]


async def test_answer_cites_title_clause_and_page_looked_up_by_code() -> None:
    result, model = await _ask(LlmAnswer(found=True, answer="3 maanden.", passages=[1]))

    assert (result.found, result.text) == (True, "3 maanden.")
    [citation] = result.citations
    assert citation.passage is result.offered[0]
    assert (citation.passage.clause_number, citation.passage.page) == (3, 2)
    assert "Arens Software B.V." in citation.passage.title
    assert "[1] Dienstverleningsovereenkomst" in model.calls[0].user
    assert "Artikel 3. Opzegging" in model.calls[0].user


async def test_a_passage_number_that_was_not_offered_is_dropped_and_reported() -> None:
    """Rule 6, built wrongly on purpose: the model cites passage 7 of 3."""
    result, _ = await _ask(LlmAnswer(found=True, answer="3 maanden.", passages=[1, 7, 0, 1]))

    assert [citation.number for citation in result.citations] == [1]
    assert result.dropped == [7, 0]


async def test_an_answer_with_only_invented_sources_is_not_shown() -> None:
    result, _ = await _ask(LlmAnswer(found=True, answer="12 maanden.", passages=[9]))

    assert (result.found, result.text, result.citations) == (False, NOT_FOUND, [])
    assert result.dropped == [9]


@pytest.mark.parametrize(
    "answer",
    [
        LlmAnswer(found=False, answer="", passages=[]),
        LlmAnswer(found=False, answer="Misschien 3 maanden.", passages=[1]),  # says not found
        LlmAnswer(found=True, answer="3 maanden.", passages=[]),  # no source at all
        LlmAnswer(found=True, answer="  ", passages=[1]),
    ],
)
async def test_the_system_can_say_not_found(answer: LlmAnswer) -> None:
    result, _ = await _ask(answer)

    assert (result.found, result.text, result.citations) == (False, NOT_FOUND, [])


async def test_an_empty_index_answers_not_found_without_calling_the_model() -> None:
    model = FakeChatModel()
    result = await answer_question(
        "Wat is de opzegtermijn?",
        index=InMemorySearchIndex(),
        embedder=FakeEmbeddingModel(),
        model=model,
        prompt=load_prompt(ANSWER_CONTRACT),
        top=3,
    )

    assert (result.found, result.text) == (False, NOT_FOUND)
    assert model.calls == []


def test_resolve_and_prompt_helpers() -> None:
    citations, dropped = resolve(LlmAnswer(found=True, answer="x", passages=[2, 4]), PASSAGES)

    assert [c.passage for c in citations] == [PASSAGES[1]]
    assert dropped == [4]
    prompt = build_user_prompt("Vraag?", PASSAGES[:2])
    assert prompt.startswith("<question>\nVraag?\n</question>")
    assert "[2] " in prompt
    assert "[3] " not in prompt


async def test_langchain_retriever_returns_documents_with_citation_metadata() -> None:
    index, embedder = await _index()
    retriever = ContractRetriever(index=index, embedder=embedder, top=2)

    documents = await retriever.ainvoke("opzegtermijn Arens Software")

    assert len(documents) == 2
    assert documents[0].page_content == "Opzegtermijn van 3 maanden."
    assert documents[0].metadata["clause_number"] == 3
    assert documents[0].metadata["page"] == 2


def test_azure_index_definition_and_document_conversion() -> None:
    definition = index_definition("contracts", 1024)
    fields = {field.name: field for field in definition.fields}

    assert fields["id"].key is True
    assert fields["text"].analyzer_name == "nl.microsoft"
    assert fields["vector"].vector_search_dimensions == 1024
    document = to_document(PASSAGES[0], [0.1, 0.2])
    assert document["vector"] == [0.1, 0.2]
    assert to_passage({**document, "@search.score": 1.0}) == PASSAGES[0]


class _SearchClient:
    def __init__(self) -> None:
        self.uploaded: list[dict[str, Any]] = []
        self.searches: list[dict[str, Any]] = []

    async def merge_or_upload_documents(self, documents: list[dict[str, Any]]) -> None:
        self.uploaded += documents

    async def search(self, **options: Any) -> Any:
        self.searches.append(options)

        async def results() -> Any:
            for document in self.uploaded:
                yield document

        return results()


class _IndexClient:
    def __init__(self) -> None:
        self.created: list[str] = []

    async def create_or_update_index(self, definition: Any) -> None:
        self.created.append(definition.name)


async def test_azure_index_creates_the_index_once_and_searches_hybrid() -> None:
    client, index_client = _SearchClient(), _IndexClient()
    plain = AzureSearchIndex(client, index_client, name="contracts", dimensions=2, semantic=False)
    ranked = AzureSearchIndex(client, index_client, name="contracts", dimensions=2, semantic=True)

    await plain.upsert(PASSAGES[:2], [[0.1, 0.2], [0.3, 0.4]])
    await plain.upsert(PASSAGES[2:], [[0.5, 0.6]])
    found = await plain.search("opzegtermijn", [0.1, 0.2], top=3)
    await ranked.search("opzegtermijn", [0.1, 0.2], top=3)

    assert index_client.created == ["contracts"]
    assert found == PASSAGES
    hybrid, semantic = client.searches
    assert hybrid["search_text"] == "opzegtermijn"  # keyword part
    assert hybrid["vector_queries"][0].fields == "vector"  # vector part
    assert "query_type" not in hybrid
    assert semantic["query_type"] == "semantic"


def test_a_title_that_wraps_over_two_lines_is_kept_whole() -> None:
    """Seen with the fakes: long supplier names wrap, and a title cut at the first
    line loses the name that tells contracts apart."""
    reading = ReadResult(
        pages=[
            PageText(
                1,
                "Dienstverleningsovereenkomst Noordzee Logistiek B.V. - Uitzendbureau van den\n"
                "Nuwenhuijzen & Tuithof\nContractnummer OVK-2025-002\nPartijen\n"
                "Artikel 1. Looptijd\n1.1 Tekst.",
            )
        ]
    )

    title, chunks = chunk_contract(reading)

    assert title.endswith("Uitzendbureau van den Nuwenhuijzen & Tuithof")
    assert chunks[0].text.startswith("Contractnummer")
