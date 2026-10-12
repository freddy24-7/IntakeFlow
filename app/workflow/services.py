"""Builds the real services from the settings."""

from typing import Any

from app.config import Settings
from app.inference.azure_openai import AzureOpenAIChatModel, AzureOpenAIEmbeddingModel
from app.rag.azure_search import AzureSearchIndex
from app.reading.azure_di import AzureDocumentReader
from app.storage.local import LocalStorage
from app.workflow.steps import Services


class AzureNotConfiguredError(Exception):
    pass


def azure_is_configured(settings: Settings) -> bool:
    return bool(settings.azure_document_intelligence_endpoint and settings.azure_openai_endpoint)


def build_azure_services(settings: Settings, index_name: str | None = None) -> Services:
    if not azure_is_configured(settings):
        raise AzureNotConfiguredError(
            "Set AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT and AZURE_OPENAI_ENDPOINT (see .env.example)."
        )

    def chat(deployment: str) -> AzureOpenAIChatModel:
        return AzureOpenAIChatModel.connect(
            endpoint=settings.azure_openai_endpoint,
            deployment=deployment,
            api_version=settings.azure_openai_api_version,
        )

    return Services(
        storage=LocalStorage(settings.storage_dir),
        reader=AzureDocumentReader.connect(endpoint=settings.azure_document_intelligence_endpoint),
        classifier=chat(settings.azure_openai_classify_deployment),
        classifier_name=settings.azure_openai_classify_deployment,
        extractor=chat(settings.azure_openai_extract_deployment),
        extractor_name=settings.azure_openai_extract_deployment,
        **_search_services(settings, index_name or settings.azure_search_index),
    )


def _search_services(settings: Settings, index_name: str) -> dict[str, Any]:
    """The parts for contract search, or nothing when no search endpoint is set."""
    if not settings.azure_search_endpoint:
        return {}
    return {
        "embedder": AzureOpenAIEmbeddingModel.connect(
            endpoint=settings.azure_openai_endpoint,
            deployment=settings.azure_openai_embedding_deployment,
            api_version=settings.azure_openai_api_version,
            dimensions=settings.embedding_dimensions,
        ),
        "embedder_name": settings.azure_openai_embedding_deployment,
        "search": AzureSearchIndex.connect(
            endpoint=settings.azure_search_endpoint,
            name=index_name,
            dimensions=settings.embedding_dimensions,
            semantic=settings.search_semantic_ranker,
        ),
        "search_name": index_name,
        "answerer": AzureOpenAIChatModel.connect(
            endpoint=settings.azure_openai_endpoint,
            deployment=settings.azure_openai_answer_deployment,
            api_version=settings.azure_openai_api_version,
        ),
        "answerer_name": settings.azure_openai_answer_deployment,
    }
