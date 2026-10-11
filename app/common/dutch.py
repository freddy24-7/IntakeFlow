"""Dutch number and date formats, parsed and written explicitly.

Dutch amounts use a dot for thousands and a comma for decimals (1.234,56), the
opposite of English. Parsing is strict on purpose: a value that does not look
Dutch raises ValueError instead of being guessed at.
"""

import re
from datetime import date
from decimal import Decimal

_DECIMAL_PATTERN = re.compile(r"^-?(\d{1,3}(\.\d{3})+|\d+)(,\d+)?$")
_NUMERIC_DATE_PATTERN = re.compile(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$")
_LONG_DATE_PATTERN = re.compile(r"^(\d{1,2})\s+([a-z]+)\.?\s+(\d{4})$")

MONTHS = (
    "januari",
    "februari",
    "maart",
    "april",
    "mei",
    "juni",
    "juli",
    "augustus",
    "september",
    "oktober",
    "november",
    "december",
)
_MONTH_NUMBERS = {name: index for index, name in enumerate(MONTHS, start=1)}
_MONTH_NUMBERS.update(
    {"jan": 1, "feb": 2, "mrt": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8}
    | {"sep": 9, "sept": 9, "okt": 10, "nov": 11, "dec": 12}
)


def parse_dutch_decimal(text: str) -> Decimal:
    """Parse '1.234,56', '€ 1.234,56' or '-12,50'. '1.234' means 1234, not 1.234."""
    cleaned = text.replace("€", "").replace("EUR", "").replace("\u00a0", "").replace(" ", "")
    if not _DECIMAL_PATTERN.match(cleaned):
        raise ValueError(f"not a Dutch-formatted number: {text!r}")
    return Decimal(cleaned.replace(".", "").replace(",", "."))


def format_dutch_decimal(value: Decimal, places: int = 2) -> str:
    """Format Decimal('1234.56') as '1.234,56'."""
    english = f"{value:,.{places}f}"
    return english.replace(",", "\u0000").replace(".", ",").replace("\u0000", ".")


def parse_dutch_date(text: str) -> date:
    """Parse '15-10-2026', '15/10/2026', '15 oktober 2026' or '15 okt. 2026' (day first)."""
    cleaned = text.strip().lower()
    numeric = _NUMERIC_DATE_PATTERN.match(cleaned)
    if numeric:
        day, month, year = (int(part) for part in numeric.groups())
        return date(year, month, day)
    long = _LONG_DATE_PATTERN.match(cleaned)
    if long and long.group(2) in _MONTH_NUMBERS:
        return date(int(long.group(3)), _MONTH_NUMBERS[long.group(2)], int(long.group(1)))
    raise ValueError(f"not a Dutch-formatted date: {text!r}")


def format_dutch_date(value: date) -> str:
    """Format as '15-10-2026'."""
    return f"{value.day:02d}-{value.month:02d}-{value.year}"


def format_dutch_date_long(value: date) -> str:
    """Format as '15 oktober 2026'."""
    return f"{value.day} {MONTHS[value.month - 1]} {value.year}"
