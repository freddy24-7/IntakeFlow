"""Azure OpenAI behind the ChatModel interface, through LangChain.

LangChain does three things here: it turns a Pydantic schema into a strict
JSON-schema request, parses the answer back into that schema, and retries
failed calls with backoff. Hand-built in Muni Mailbox, this was a prompt that
asked for JSON plus our own parsing and retry code.
"""

import time
from collections.abc import Sequence
from typing import Any

from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from langchain_openai import AzureChatOpenAI, AzureOpenAIEmbeddings
from pydantic import BaseModel

from app.inference.interfaces import EmbeddingResult, ModelUsage, StructuredResult

TOKEN_SCOPE = "https://cognitiveservices.azure.com/.default"


class ModelOutputError(Exception):
    """The model answered, but not in the requested schema."""


class AzureOpenAIChatModel:
    def __init__(self, llm: Any, model_name: str) -> None:
        self._llm = llm
        self._model_name = model_name

    @classmethod
    def connect(
        cls, *, endpoint: str, deployment: str, api_version: str, max_retries: int = 5
    ) -> "AzureOpenAIChatModel":
        """Keyless sign-in: `az login` on a laptop, managed identity in Azure."""
        token_provider = get_bearer_token_provider(DefaultAzureCredential(), TOKEN_SCOPE)
        llm = AzureChatOpenAI(
            azure_endpoint=endpoint,
            azure_deployment=deployment,
            api_version=api_version,
            azure_ad_token_provider=token_provider,
            temperature=0,
            max_retries=max_retries,
            timeout=120,
        )
        return cls(llm, deployment)

    async def structured[T: BaseModel](
        self, *, system: str, user: str, schema: type[T]
    ) -> StructuredResult[T]:
        runnable = self._llm.with_structured_output(
            schema, method="json_schema", strict=True, include_raw=True
        )
        started = time.perf_counter()
        answer = await runnable.ainvoke([("system", system), ("human", user)])
        latency_ms = (time.perf_counter() - started) * 1000

        parsed = answer.get("parsed")
        if not isinstance(parsed, schema):
            # Rule 8: the answer may quote the document, so it is not put in the error.
            raise ModelOutputError(f"answer does not fit {schema.__name__}")
        tokens = getattr(answer.get("raw"), "usage_metadata", None) or {}
        usage = ModelUsage(
            model=self._model_name,
            input_tokens=int(tokens.get("input_tokens", 0)),
            output_tokens=int(tokens.get("output_tokens", 0)),
            latency_ms=latency_ms,
        )
        return StructuredResult(value=parsed, usage=usage)


class AzureOpenAIEmbeddingModel:
    """Azure OpenAI embeddings behind the EmbeddingModel interface, through LangChain.

    LangChain's embeddings interface returns vectors only, not token counts, so
    the usage here is an estimate (about four characters per token). The chat
    model above reports real counts.
    """

    def __init__(self, embeddings: Any, model_name: str) -> None:
        self._embeddings = embeddings
        self._model_name = model_name

    @classmethod
    def connect(
        cls, *, endpoint: str, deployment: str, api_version: str, dimensions: int
    ) -> "AzureOpenAIEmbeddingModel":
        token_provider = get_bearer_token_provider(DefaultAzureCredential(), TOKEN_SCOPE)
        embeddings = AzureOpenAIEmbeddings(
            azure_endpoint=endpoint,
            deployment=deployment,
            openai_api_version=api_version,
            azure_ad_token_provider=token_provider,
            dimensions=dimensions,
            max_retries=5,
        )
        return cls(embeddings, deployment)

    async def embed(self, texts: Sequence[str]) -> EmbeddingResult:
        started = time.perf_counter()
        vectors = await self._embeddings.aembed_documents(list(texts))
        usage = ModelUsage(
            model=self._model_name,
            input_tokens=sum(max(1, len(text) // 4) for text in texts),
            output_tokens=0,
            latency_ms=(time.perf_counter() - started) * 1000,
        )
        return EmbeddingResult(vectors=vectors, usage=usage)
