"""Street and house matching for outages by address.

A mirror of server/internal/outages/address.go and the apps' OutageAddressing,
pinned by server/internal/outages/testdata/address_cases.json. No Home
Assistant imports, so the tests can load it without one.
"""
from __future__ import annotations

import re
import unicodedata

MATCH_EXACT = "exact"
MATCH_STREET = "street"
MATCH_POSSIBLE = "possible"

_TYPE_PREFIXES = [
    "вулиця", "вул.", "вул", "провулок", "пров.", "пров", "проспект", "просп.", "пр-т",
    "площа", "пл.", "бульвар", "бульв.", "б-р", "тупик", "туп.", "проїзд", "пр.",
    "місто", "м.", "село", "с.", "селище", "с-ще", "смт.", "смт", "сел.",
]
_LATIN = str.maketrans("abcehikmoptxy", "авсенікмортху")
_SPACES = {" ": " ", " ": " ", " ": " ", "​": ""}
_DASHES = {c: "-" for c in "‒–—―−"}
_APOSTROPHES = {c: "'" for c in "’ʼ‘`"}


def normalize_text(s: str) -> str:
    """NFC, dashes, apostrophes, odd spaces; whitespace collapsed."""
    s = unicodedata.normalize("NFC", s)
    s = "".join(_SPACES.get(c, _DASHES.get(c, _APOSTROPHES.get(c, c))) for c in s)
    return " ".join(s.split())


def normalize_name(value: str) -> str:
    s = normalize_text(value).lower().translate(_LATIN)
    changed = True
    while changed:
        changed = False
        for prefix in _TYPE_PREFIXES:
            if not s.startswith(prefix):
                continue
            rest = s[len(prefix):]
            # "вул.Шевченка" and "вул. Шевченка" both count; "вулична" does not.
            if prefix.endswith(".") or rest.startswith(" "):
                s = rest.strip()
                changed = True
                break
    return s


_INITIALS = re.compile(r"^([^\W\d_]\.\s*)+")


def same_street(a: str, b: str) -> bool:
    na, nb = normalize_name(a), normalize_name(b)
    if not na or not nb:
        return False
    return na == nb or _INITIALS.sub("", na).strip() == _INITIALS.sub("", nb).strip()


_SLASH_LETTER = re.compile(r"(\d)/([а-яіїєґ])$")
_APARTMENT = re.compile(r"\s*кв\.?\s*\d+.*$")
_HOUSE_PREFIX = re.compile(r"^(буд\.?|б\.?)\s*")
_KORPUS = re.compile(r"\s*(корпус|корп\.?|к\.)\s*")
_LETTER_DASH = re.compile(r"(\d)[-\s]+([а-яіїєґ]{1,2})$")
_LEADING_ZEROS = re.compile(r"(^|/)0+(\d)")
_HOUSE_RANGE = re.compile(r"^(\d+)-(\d+)$")


def normalize_house(value: str) -> str:
    """'49 А' -> '49а', '188 корп. А' -> '188ка', '38-1' -> '38/1', '004' -> '4'."""
    s = normalize_text(value).lower().translate(_LATIN)
    s = s.replace("\\", "/").replace("..", "-")
    for ch in "\"«»":
        s = s.replace(ch, "")
    s = _SLASH_LETTER.sub(r"\1\2", s)
    s = _APARTMENT.sub("", s)
    s = _HOUSE_PREFIX.sub("", s)
    s = s.strip(" .*+-/")
    s = _KORPUS.sub("к", s)
    s = _LETTER_DASH.sub(r"\1\2", s)
    s = s.replace(" ", "").strip(".")
    s = _LEADING_ZEROS.sub(r"\1\2", s)
    m = _HOUSE_RANGE.fullmatch(s)
    if m and int(m.group(2)) <= int(m.group(1)):
        s = f"{int(m.group(1))}/{int(m.group(2))}"
    return s


def match(
    street: str,
    tokens: list[str],
    houses_parsed: bool,
    whole_street: bool,
    user_street: str | None,
    user_house: str | None,
) -> str | None:
    """How a row concerns the address: exact / street / possible, or None."""
    wanted = (user_street or "").strip()
    if not wanted:
        return MATCH_STREET
    row_street = street.strip()
    if row_street and not same_street(row_street, wanted):
        return None
    house = normalize_house(user_house or "")
    if not house or whole_street or not row_street:
        return MATCH_STREET
    number = int(house) if house.isdigit() else None
    for token in tokens:
        if token == house:
            return MATCH_EXACT
        r = _HOUSE_RANGE.fullmatch(token)
        if r and number is not None and int(r.group(1)) <= number <= int(r.group(2)):
            return MATCH_EXACT
    return None if houses_parsed else MATCH_POSSIBLE
