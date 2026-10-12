"""Scoring and the routing decision (PRD F6).

The score says how much the extraction is to be trusted. It never overrides
validation: `decide` auto-approves only when no check failed AND the score
meets the threshold (rule 3). This function is the only place where that
decision is made.
"""

from dataclasses import dataclass

from app.agents.schema import (
    FLAG_DI_DISAGREES,
    FLAG_NORMALISATION_MISMATCH,
    FLAG_UNPARSEABLE,
    ExtractedInvoice,
)

AUTO_APPROVE, REVIEW = "auto_approve", "review"
REASON_LOW_SCORE = "score_below_threshold"
REASON_CLASSIFICATION = "classification_uncertain"
AGGREGATES = ("mean", "min")
# A field where the two sources disagree is worth at most this much.
DISAGREEMENT_CAP = 0.5


def field_scores(invoice: ExtractedInvoice, *, default_confidence: float) -> dict[str, float]:
    """A score between 0 and 1 for every field that has a value.

    Document Intelligence's confidence where there is one. The model gives no
    usable confidence, so a field it alone produced gets `default_confidence`.
    Flags lower the score: a value the code could not read back scores 0.
    """
    scores = {}
    for name, field in invoice.fields.items():
        if field.value is None and not field.flags:
            continue
        score = field.di_confidence if field.di_confidence is not None else default_confidence
        if FLAG_DI_DISAGREES in field.flags:
            score = min(score, DISAGREEMENT_CAP)
        if FLAG_UNPARSEABLE in field.flags or FLAG_NORMALISATION_MISMATCH in field.flags:
            score = 0.0
        scores[name] = score
    return scores


def aggregate(scores: dict[str, float], method: str) -> float:
    if method not in AGGREGATES:
        raise ValueError(f"unknown score aggregate: {method}")
    if not scores:
        return 0.0
    values = list(scores.values())
    return min(values) if method == "min" else sum(values) / len(values)


@dataclass(frozen=True)
class Decision:
    decision: str
    reasons: list[str]


def decide(
    *,
    failures: list[str],
    score: float,
    threshold: float,
    classification_confidence: float,
    classification_threshold: float,
) -> Decision:
    """Every reason for review is recorded, not only the first."""
    reasons = list(failures)
    if classification_confidence < classification_threshold:
        reasons.append(REASON_CLASSIFICATION)
    if score < threshold:
        reasons.append(REASON_LOW_SCORE)
    return Decision(REVIEW if reasons else AUTO_APPROVE, reasons)
