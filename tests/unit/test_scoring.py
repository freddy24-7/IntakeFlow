"""Scoring and rule 3: the model never approves alone."""

import itertools

import pytest

from app.agents.schema import (
    FLAG_DI_DISAGREES,
    FLAG_NORMALISATION_MISMATCH,
    FLAG_UNPARSEABLE,
    ExtractedInvoice,
    FieldValue,
)
from app.validation import scoring
from app.validation.scoring import AUTO_APPROVE, REVIEW, aggregate, decide, field_scores


def _decide(failures: list[str], score: float, classification: float = 0.99) -> scoring.Decision:
    return decide(
        failures=failures,
        score=score,
        threshold=0.9,
        classification_confidence=classification,
        classification_threshold=0.8,
    )


def test_auto_approval_needs_no_failures_and_a_score_at_the_threshold() -> None:
    assert _decide([], 0.9) == scoring.Decision(AUTO_APPROVE, [])
    assert _decide([], 0.95).decision == AUTO_APPROVE


def test_a_perfect_score_cannot_approve_an_invoice_that_fails_a_check() -> None:
    """Built wrongly on purpose: the model is certain, the IBAN is wrong."""
    decision = _decide(["iban_checksum"], 1.0)

    assert decision == scoring.Decision(REVIEW, ["iban_checksum"])


def test_passing_every_check_is_not_enough_with_a_low_score() -> None:
    assert _decide([], 0.89) == scoring.Decision(REVIEW, ["score_below_threshold"])


def test_uncertain_classification_goes_to_review() -> None:
    assert _decide([], 1.0, classification=0.5) == scoring.Decision(
        REVIEW, ["classification_uncertain"]
    )


def test_every_reason_is_recorded() -> None:
    decision = _decide(["totals_mismatch", "po_missing"], 0.2, classification=0.1)

    assert decision.reasons == [
        "totals_mismatch",
        "po_missing",
        "classification_uncertain",
        "score_below_threshold",
    ]


def test_no_combination_with_a_failure_is_ever_auto_approved() -> None:
    scores = (0.0, 0.5, 0.9, 1.0)
    for score, classification in itertools.product(scores, scores):
        assert _decide(["duplicate_invoice"], score, classification).decision == REVIEW


def test_field_scores_use_di_confidence_defaults_and_flags() -> None:
    invoice = ExtractedInvoice(
        fields={
            "with_di": FieldValue(value="x", di_confidence=0.97),
            "model_only": FieldValue(value="x"),
            "disagrees": FieldValue(value="x", di_confidence=0.97, flags=[FLAG_DI_DISAGREES]),
            "low_and_disagrees": FieldValue(
                value="x", di_confidence=0.3, flags=[FLAG_DI_DISAGREES]
            ),
            "unreadable": FieldValue(value=None, flags=[FLAG_UNPARSEABLE]),
            "misread": FieldValue(
                value="1.23", di_confidence=0.99, flags=[FLAG_NORMALISATION_MISMATCH]
            ),
            "absent": FieldValue(),
        },
        line_items=[],
    )

    assert field_scores(invoice, default_confidence=0.8) == {
        "with_di": 0.97,
        "model_only": 0.8,
        "disagrees": 0.5,
        "low_and_disagrees": 0.3,
        "unreadable": 0.0,
        "misread": 0.0,
    }


def test_aggregate() -> None:
    scores = {"a": 1.0, "b": 0.5}

    assert aggregate(scores, "mean") == 0.75
    assert aggregate(scores, "min") == 0.5
    assert aggregate({}, "mean") == 0.0
    with pytest.raises(ValueError, match="unknown score aggregate"):
        aggregate(scores, "median")


def test_configured_default_is_validation_alone() -> None:
    """The measured setting. Changing it should be a deliberate, measured step."""
    from app.config import Settings

    assert Settings(_env_file=None, database_url="unused").auto_approve_threshold == 0.0
