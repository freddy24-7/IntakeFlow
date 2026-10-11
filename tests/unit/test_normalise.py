from decimal import Decimal

import pytest

from app.agents import normalise
from app.agents.normalise import canonical, canonical_number, parse_number


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1234.56", "1234.56"),  # plain, as the model is asked to write it
        ("1.234,56", "1234.56"),  # Dutch
        ("€ 1.234,56", "1234.56"),
        ("1,234.56", "1234.56"),  # English
        ("€61,217.22", "61217.22"),
        ("EUR 250", "250.00"),
        ("-12,5", "-12.50"),
        ("12.5", "12.50"),
        ("1.234", "1234.00"),  # three digits after a dot: Dutch thousands
    ],
)
def test_amounts_in_three_formats(text: str, expected: str) -> None:
    assert canonical(normalise.AMOUNT, text) == expected


@pytest.mark.parametrize("text", ["twelve", "1.23,45", "1,23.45", "12-34"])
def test_unreadable_amount_is_not_guessed(text: str) -> None:
    assert canonical(normalise.AMOUNT, text) is None


@pytest.mark.parametrize(
    "text",
    ["2026-10-15", "15-10-2026", "15 oktober 2026", "15 October 2026", "October 15, 2026"],
)
def test_dates(text: str) -> None:
    assert canonical(normalise.DATE, text) == "2026-10-15"


def test_dutch_dates_are_day_first() -> None:
    assert canonical(normalise.DATE, "03-04-2026") == "2026-04-03"
    assert canonical(normalise.DATE, "sometime") is None


def test_identifiers_and_text() -> None:
    assert canonical(normalise.IBAN, "nl18 havn 1028 4398 63") == "NL18HAVN1028439863"
    assert canonical(normalise.VAT_NUMBER, "NL 9427.55.630.B73") == "NL942755630B73"
    assert canonical(normalise.CURRENCY, "€") == "EUR"
    assert canonical(normalise.CURRENCY, "eur") == "EUR"
    assert canonical(normalise.TEXT, "  Arens   Software B.V. ") == "Arens Software B.V."


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_empty_is_none(empty: str | None) -> None:
    assert canonical(normalise.TEXT, empty) is None
    assert canonical_number(empty) is None


def test_quantities_and_rates_keep_their_precision() -> None:
    assert canonical_number("2,5") == "2.5"
    assert canonical_number("21%") == "21"
    assert canonical_number("21.00") == "21"
    assert canonical_number("0") == "0"
    assert canonical_number("many") is None
    assert parse_number("16.5") == Decimal("16.5")
