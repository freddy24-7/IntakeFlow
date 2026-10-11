"""Builds the real services from the settings."""

from app.config import Settings
from app.inference.azure_openai import AzureOpenAIChatModel
from app.reading.azure_di import AzureDocumentReader
from app.storage.local import LocalStorage
from app.workflow.steps import Services


class AzureNotConfiguredError(Exception):
    pass


def azure_is_configured(settings: Settings) -> bool:
    return bool(settings.azure_document_intelligence_endpoint and settings.azure_openai_endpoint)


def build_azure_services(settings: Settings) -> Services:
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
    )
