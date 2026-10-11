"""Turns values as printed or as returned by a model into one canonical text form.

Canonical forms: dates as 2026-10-15, amounts as 1234.56, IBAN and VAT number
in capitals without spaces. Everything downstream (validation, comparison with
Document Intelligence, evaluation) compares canonical forms only.

Number formats are handled explicitly: plain (1234.56), Dutch (1.234,56) and
English (1,234.56). A value that fits none of them is not guessed at.
"""

import re
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

from app.common.dutch import parse_dutch_date, parse_dutch_decimal

_PLAIN_NUMBER = re.compile(r"^-?\d+(\.\d{1,2})?$")
_ENGLISH_NUMBER = re.compile(r"^-?\d{1,3}(,\d{3})+(\.\d+)?$")
_CURRENCY_NOISE = re.compile(r"(€|\$|£|EUR|USD|GBP|%|\s)", re.IGNORECASE)
_ENGLISH_DATE_FORMATS = ("%d %B %Y", "%B %d, %Y", "%d %b %Y", "%b %d, %Y")
_CURRENCY_SYMBOLS = {"€": "EUR", "$": "USD", "£": "GBP"}
CENT = Decimal("0.01")

AMOUNT, DATE, TEXT, IBAN, VAT_NUMBER, CURRENCY = "amount", "date", "text", "iban", "vat", "currency"


def parse_number(text: str) -> Decimal | None:
    cleaned = _CURRENCY_NOISE.sub("", text)
    if _PLAIN_NUMBER.match(cleaned):
        return Decimal(cleaned)
    try:
        return parse_dutch_decimal(cleaned)
    except ValueError:
        pass
    if _ENGLISH_NUMBER.match(cleaned):
        return Decimal(cleaned.replace(",", ""))
    return None


def parse_date(text: str) -> date | None:
    cleaned = " ".join(text.split())
    try:
        return date.fromisoformat(cleaned)
    except ValueError:
        pass
    try:
        return parse_dutch_date(cleaned)
    except ValueError:
        pass
    for date_format in _ENGLISH_DATE_FORMATS:
        try:
            return datetime.strptime(cleaned, date_format).date()
        except ValueError:
            continue
    return None


def number_text(value: Decimal) -> str:
    """Quantities and rates: 2.5 stays 2.5, 21.00 becomes 21."""
    text = format(value.normalize(), "f")
    return "0" if text == "-0" else text


def canonical(kind: str, raw: str | None) -> str | None:
    """The canonical form of `raw`, or None when it is empty or cannot be read."""
    if raw is None or not raw.strip():
        return None
    text = raw.strip()
    if kind == AMOUNT:
        number = parse_number(text)
        return None if number is None else format(number.quantize(CENT, ROUND_HALF_UP), "f")
    if kind == DATE:
        parsed = parse_date(text)
        return None if parsed is None else parsed.isoformat()
    if kind in (IBAN, VAT_NUMBER):
        return re.sub(r"[\s.\-]", "", text).upper()
    if kind == CURRENCY:
        return _CURRENCY_SYMBOLS.get(text, text.upper())
    return " ".join(text.split())


def canonical_number(raw: str | None) -> str | None:
    if raw is None or not raw.strip():
        return None
    number = parse_number(raw)
    return None if number is None else number_text(number)
