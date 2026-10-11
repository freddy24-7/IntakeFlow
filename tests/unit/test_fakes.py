import pytest
from pydantic import BaseModel

from app.inference.fakes import FakeChatModel, FakeEmbeddingModel
from app.reading.fakes import FakeDocumentReader, content_key
from app.reading.interfaces import PageText, ReadField, ReadResult


class Label(BaseModel):
    label: str
    confidence: float


class Other(BaseModel):
    value: int


async def test_fake_chat_returns_scripted_answer_and_records_the_call() -> None:
    model = FakeChatModel(answers={Label: Label(label="invoice", confidence=0.97)})

    result = await model.structured(system="classify", user="some text", schema=Label)

    assert result.value == Label(label="invoice", confidence=0.97)
    assert result.usage.model == "fake-chat"
    assert result.usage.input_tokens > 0
    assert [(call.system, call.user, call.schema) for call in model.calls] == [
        ("classify", "some text", Label)
    ]


async def test_fake_chat_answer_can_depend_on_the_prompt() -> None:
    model = FakeChatModel(
        answers={
            Label: lambda user: Label(
                label="contract" if "clause" in user else "other", confidence=0.5
            )
        }
    )

    assert (
        await model.structured(system="", user="clause 3", schema=Label)
    ).value.label == "contract"
    assert (await model.structured(system="", user="hello", schema=Label)).value.label == "other"


async def test_fake_chat_fails_loudly_when_unscripted_or_wrongly_scripted() -> None:
    with pytest.raises(LookupError):
        await FakeChatModel().structured(system="", user="", schema=Label)
    with pytest.raises(TypeError):
        await FakeChatModel(answers={Label: Other(value=1)}).structured(
            system="", user="", schema=Label
        )


async def test_fake_embeddings_are_deterministic() -> None:
    model = FakeEmbeddingModel(dimensions=4)

    first = await model.embed(["opzegtermijn", "aansprakelijkheid", "opzegtermijn"])

    assert len(first.vectors) == 3
    assert all(len(vector) == 4 for vector in first.vectors)
    assert first.vectors[0] == first.vectors[2]
    assert first.vectors[0] != first.vectors[1]


async def test_fake_reader_returns_canned_results_by_content() -> None:
    content = b"not really a pdf"
    canned = ReadResult(
        pages=[PageText(number=1, text="Factuur 123"), PageText(number=2, text="x")]
    )
    fields = [ReadField(name="InvoiceId", value="123", confidence=0.9, page=1)]
    reader = FakeDocumentReader(
        texts={content_key(content): canned}, invoice_fields={content_key(content): fields}
    )

    assert await reader.read_text(content) == canned
    assert canned.text == "Factuur 123\nx"
    with_fields = await reader.read_invoice_fields(content)
    assert with_fields.fields == fields
    assert with_fields.pages == canned.pages
