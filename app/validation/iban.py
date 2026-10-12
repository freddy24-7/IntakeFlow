"""IBAN check (ISO 13616): country-specific length where known, then mod 97."""

import re

_SHAPE = re.compile(r"^[A-Z]{2}\d{2}[A-Z0-9]{11,30}$")
_LENGTHS = {"NL": 18, "BE": 16, "DE": 22, "FR": 27, "GB": 22, "LU": 20}


def is_valid_iban(iban: str) -> bool:
    if not _SHAPE.match(iban):
        return False
    expected_length = _LENGTHS.get(iban[:2])
    if expected_length is not None and len(iban) != expected_length:
        return False
    rearranged = iban[4:] + iban[:4]
    return int("".join(str(int(character, 36)) for character in rearranged)) % 97 == 1
