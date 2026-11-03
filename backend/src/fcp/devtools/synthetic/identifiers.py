"""Fictional identifiers that are realistic in format but provably invalid.

- Cyprus VAT/TIN numbers use the correct format with a **wrong check letter**.
- IBANs use the Cyprus format with **wrong check digits** (mod-97 != 1).
- Organisation names carry a "(Demo)" marker; e-mail domains use the reserved ``.example`` TLD
  (RFC 2606).
So generated data can never be mistaken for, or collide with, a real registered identifier.
"""

import random
import string

_CY_VAT_ODD = {"0": 1, "1": 0, "2": 5, "3": 7, "4": 9, "5": 13, "6": 15, "7": 17, "8": 19, "9": 21}
_LETTERS = string.ascii_uppercase


def cy_vat_check_letter(digits: str) -> str:
    """The valid check letter for 8 Cyprus VAT/TIN digits."""
    total = sum(_CY_VAT_ODD[d] for d in digits[0::2]) + sum(int(d) for d in digits[1::2])
    return _LETTERS[total % 26]


def fictional_cy_vat(rng: random.Random) -> str:
    """'CY' + 8 digits + a deliberately invalid check letter."""
    first = rng.choice("01345")  # valid leading digits (and never the '12' prefix)
    digits = first + "".join(rng.choice(string.digits) for _ in range(7))
    valid = cy_vat_check_letter(digits)
    wrong = _LETTERS[(_LETTERS.index(valid) + rng.randint(1, 25)) % 26]
    return f"CY{digits}{wrong}"


def iban_mod97(iban: str) -> int:
    """ISO 13616 mod-97 of an IBAN (1 for a valid IBAN)."""
    rearranged = iban[4:] + iban[:4]
    numeric = "".join(str(int(c, 36)) for c in rearranged)
    return int(numeric) % 97


def fictional_cy_iban(rng: random.Random) -> str:
    """A Cyprus-format IBAN (28 characters) with deliberately invalid check digits."""
    bban = "".join(rng.choice(string.digits) for _ in range(24))
    valid_check = 98 - iban_mod97(f"CY00{bban}")
    wrong_check = (valid_check + rng.randint(1, 96)) % 97 + 2  # always 02..98 and != valid
    if wrong_check == valid_check:
        wrong_check = 2 if valid_check != 2 else 3
    return f"CY{wrong_check:02d}{bban}"


_NAME_PREFIXES = (
    "Aster",
    "Halcyon",
    "Cedar",
    "Meridian",
    "Coral",
    "Saffron",
    "Juniper",
    "Azure",
    "Laurel",
    "Quarry",
    "Harbour",
    "Orchard",
    "Beacon",
    "Granite",
    "Tamarisk",
    "Zephyr",
)
_NAME_SECTORS = (
    "Marine",
    "Trading",
    "Foods",
    "Logistics",
    "Consulting",
    "Hospitality",
    "Interiors",
    "Engineering",
    "Software",
    "Wholesale",
    "Print",
    "Textiles",
    "Packaging",
    "Supplies",
)


def fictional_company_name(rng: random.Random, used: set[str]) -> str:
    """A unique, clearly fictional company name such as 'Coral Logistics Ltd (Demo)'."""
    for _ in range(1000):
        name = f"{rng.choice(_NAME_PREFIXES)} {rng.choice(_NAME_SECTORS)} Ltd (Demo)"
        if name not in used:
            used.add(name)
            return name
    name = f"Demo Company {len(used) + 1} Ltd (Demo)"
    used.add(name)
    return name


def email_for(name: str) -> str:
    slug = "".join(c for c in name.lower().replace("(demo)", "") if c.isalnum() or c == " ")
    return f"accounts@{'-'.join(slug.split())}.example"
