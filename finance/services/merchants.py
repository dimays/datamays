"""Reducing a bank description to a stable merchant key.

Bank descriptions are noisy in predictable ways: store numbers, cities, card
suffixes, dates, reference numbers, and processor prefixes. Stripping them
turns

    SQ *BLUE BOTTLE COFFEE 4471 CHICAGO IL 04/15
    SQ *BLUE BOTTLE COFFEE 9920 EVANSTON IL 05/02

into the same key, which is what lets one confirmed decision cover every
future visit — and is the main reason the classifier is nearly free to run.
"""

import re

# Payment processors and channel markers that prefix the real merchant name.
PREFIXES = [
    r"^sq\s*\*", r"^tst\*", r"^sp\s+", r"^pp\*", r"^paypal\s*\*",
    r"^dd\s*\*", r"^doordash\s*\*", r"^ach\s+(debit|credit)\s+",
    r"^pos\s+(debit|purchase)\s+", r"^debit\s+card\s+purchase\s+",
    r"^recurring\s+", r"^purchase\s+authorized\s+on\s+",
    r"^checkcard\s+\d*\s*", r"^visa\s+(debit|purchase)\s+",
]

NOISE_PATTERNS = [
    r"\b\d{1,2}/\d{1,2}(/\d{2,4})?\b",       # embedded dates
    r"\bx{2,}\d+\b",                          # masked card numbers
    r"\b\d{4,}\b",                            # store / reference numbers
    r"#\s*\d+",                               # "#1234" — no \b, since # is not a word char
    r"\bcard\s*\d+\b",
    r"\b(id|ref|inv|auth|trace)[:#]?\s*\w+\b",
]

WHITESPACE = re.compile(r"\s+")
PUNCTUATION = re.compile(r"[^a-z0-9&\s]")

US_STATES = frozenset(
    """al ak az ar ca co ct de fl ga hi id il in ia ks ky la me md ma mi mn ms mo
    mt ne nv nh nj nm ny nc nd oh ok or pa ri sc sd tn tx ut vt va wa wv wi wy dc""".split()
)


def _drop_bare_numbers(tokens):
    """Remove standalone numeric tokens — short store numbers, mostly.

    The first token is spared, because a leading number is sometimes the name
    itself ("7 eleven", "76").
    """
    return [
        token
        for index, token in enumerate(tokens)
        if index == 0 or not token.isdigit()
    ]


def _strip_trailing_location(tokens):
    """Drop a trailing "CITY ST" when a state code anchors it.

    A trailing two-letter state code is strong evidence the token before it is
    a city, which is what makes two branches of the same shop collapse to one
    key. Only one city token is dropped: a two-word city leaves a residue and
    costs one extra classification, whereas stripping too eagerly would merge
    genuinely different merchants — much the worse error.
    """
    if len(tokens) >= 3 and tokens[-1] in US_STATES:
        return tokens[:-2]

    return tokens


def normalize_merchant(description: str) -> str:
    """A lowercase, punctuation-free merchant key. Empty if nothing survives."""
    text = (description or "").casefold().strip()

    if not text:
        return ""

    for prefix in PREFIXES:
        text = re.sub(prefix, "", text)

    for pattern in NOISE_PATTERNS:
        text = re.sub(pattern, " ", text)

    text = PUNCTUATION.sub(" ", text)
    text = WHITESPACE.sub(" ", text).strip()
    text = " ".join(_drop_bare_numbers(_strip_trailing_location(text.split())))

    # Very short remnants are not a merchant, they are leftovers.
    if len(text) < 3:
        return ""

    return text[:160]
