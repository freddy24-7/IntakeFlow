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
    # Which extraction the pipeline uses: "combined", "llm_only" or "di_only".
    extraction_variant: str = "combined"


@lru_cache
def get_settings() -> Settings:
    return Settings()
