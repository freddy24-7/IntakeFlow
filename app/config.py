"""Application settings, read from the environment and a local .env file."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str
    # Rule 3: thresholds live in configuration, and changes to them are measured.
    # 0 means validation alone decides: no failed check and no flagged field.
    # Was 0.90 until 2026-10-12. Measured on two sets: the score did not separate
    # right from wrong, and 0 was fixed before the hold-out run that confirmed it
    # (cards/03-validation-and-routing.md).
    auto_approve_threshold: float = 0.0
    # How the field scores become one document score: "mean" or "min".
    score_aggregate: str = "mean"
    # Score of a field that only the model produced (it gives no usable confidence).
    score_default_confidence: float = 0.80
    # Below this the classifier's answer is not trusted and a person looks.
    classification_threshold: float = 0.80
    # Share of the purchase order amount an invoice total may differ by.
    po_amount_tolerance: float = 0.01
    # After this many failed runs a document is parked as failed (dead letter).
    max_attempts: int = 3
    max_upload_bytes: int = 20 * 1024 * 1024
    # Uploaded files, until Blob Storage replaces the local folder in stage 6.
    storage_dir: Path = Path("data/uploads")

    # Where uploads are kept: "local" (the folder above) or "blob".
    storage_backend: str = "local"
    azure_storage_blob_url: str = ""
    blob_container: str = "documents"
    # How an upload reaches the workflow: "in_process" (a task in the web
    # application) or "queue" (a message for the worker, see app/worker.py).
    dispatch_backend: str = "in_process"
    azure_storage_queue_url: str = ""
    queue_name: str = "documents"
    # Telemetry to Application Insights. Empty means off.
    applicationinsights_connection_string: str = ""

    # Azure. Empty endpoints mean "not configured": the app then refuses to
    # process documents instead of silently using a fake.
    # Sign-in is keyless (az login locally, managed identity later), so there
    # are no keys here.
    azure_document_intelligence_endpoint: str = ""
    azure_openai_endpoint: str = ""
    azure_openai_api_version: str = "2024-10-21"
    # Deployment names. A cheaper model classifies, a stronger one extracts.
    azure_openai_classify_deployment: str = "gpt-4.1-mini"
    azure_openai_extract_deployment: str = "gpt-4.1"
    # Contract search and question answering (stage 5).
    azure_search_endpoint: str = ""
    azure_search_index: str = "contracts"
    azure_openai_embedding_deployment: str = "text-embedding-3-large"
    # text-embedding-3-large can be shortened. 1024 keeps the index small.
    embedding_dimensions: int = 1024
    azure_openai_answer_deployment: str = "gpt-4.1"
    # Passages offered to the model per question.
    search_top_k: int = 5
    # Re-rank results with the semantic ranker (free monthly allowance, then billed).
    search_semantic_ranker: bool = False
    # Which extraction the pipeline uses: "combined", "llm_only" or "di_only".
    extraction_variant: str = "combined"


@lru_cache
def get_settings() -> Settings:
    return Settings()
