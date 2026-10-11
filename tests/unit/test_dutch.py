from datetime import date
from decimal import Decimal

import pytest

from app.common.dutch import (
    format_dutch_date,
    format_dutch_date_long,
    format_dutch_decimal,
    parse_dutch_date,
    parse_dutch_decimal,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("1.234,56", "1234.56"),
        ("€ 1.234,56", "1234.56"),
        ("€\u00a01.234.567,89", "1234567.89"),
        ("-12,50", "-12.50"),
        ("1234,5", "1234.5"),
        ("0,09", "0.09"),
        ("250", "250"),
        # A dot followed by three digits is a thousands separator in Dutch.
        ("1.234", "1234"),
    ],
)
def test_parse_dutch_decimal(text: str, expected: str) -> None:
    assert parse_dutch_decimal(text) == Decimal(expected)


@pytest.mark.parametrize("text", ["1,234.56", "12.5", "1.23,45", "abc", "", "1,2,3"])
def test_parse_dutch_decimal_rejects_other_formats(text: str) -> None:
    with pytest.raises(ValueError, match="not a Dutch-formatted number"):
        parse_dutch_decimal(text)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1234.56", "1.234,56"),
        ("1234567.8", "1.234.567,80"),
        ("0.5", "0,50"),
        ("-1500", "-1.500,00"),
        ("999.999", "1.000,00"),
    ],
)
def test_format_dutch_decimal(value: str, expected: str) -> None:
    assert format_dutch_decimal(Decimal(value)) == expected


def test_decimal_round_trip() -> None:
    value = Decimal("98765.43")
    assert parse_dutch_decimal(format_dutch_decimal(value)) == value


@pytest.mark.parametrize(
    "text",
    ["15-10-2026", "15/10/2026", "15.10.2026", "15 oktober 2026", "15 okt. 2026", "15 Okt 2026"],
)
def test_parse_dutch_date(text: str) -> None:
    assert parse_dutch_date(text) == date(2026, 10, 15)


def test_parse_dutch_date_is_day_first() -> None:
    assert parse_dutch_date("03-04-2026") == date(2026, 4, 3)


@pytest.mark.parametrize("text", ["2026-10-15", "15 October 2026", "31-02-2026", "soon"])
def test_parse_dutch_date_rejects_other_formats(text: str) -> None:
    with pytest.raises(ValueError):
        parse_dutch_date(text)


def test_format_dutch_dates() -> None:
    assert format_dutch_date(date(2026, 3, 5)) == "05-03-2026"
    assert format_dutch_date_long(date(2026, 3, 5)) == "5 maart 2026"
    assert parse_dutch_date(format_dutch_date_long(date(2026, 3, 5))) == date(2026, 3, 5)
