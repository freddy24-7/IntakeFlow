"""Loads versioned prompt files from `prompts/`. The file name is the version."""

from dataclasses import dataclass
from functools import cache
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parents[2] / "prompts"

CLASSIFY = "classify_v1"
EXTRACT_INVOICE = "extract_invoice_v1"


@dataclass(frozen=True)
class Prompt:
    version: str
    text: str


@cache
def load_prompt(version: str) -> Prompt:
    text = (PROMPTS_DIR / f"{version}.md").read_text(encoding="utf-8")
    return Prompt(version=version, text=text.strip())
