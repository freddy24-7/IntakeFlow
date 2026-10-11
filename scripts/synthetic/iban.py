"""IBAN check digits (ISO 13616, mod 97), used to make valid and deliberately wrong IBANs."""


def _mod97(iban: str) -> int:
    rearranged = iban[4:] + iban[:4]
    return int("".join(str(int(character, 36)) for character in rearranged)) % 97


def with_check_digits(country: str, bban: str) -> str:
    check = 98 - _mod97(f"{country}00{bban}")
    return f"{country}{check:02d}{bban}"


def is_valid_iban(iban: str) -> bool:
    compact = iban.replace(" ", "")
    return len(compact) > 4 and compact.isalnum() and _mod97(compact) == 1
