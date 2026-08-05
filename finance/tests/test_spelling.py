"""US spelling is the house style, enforced rather than remembered.

This has been asked for three separate times — "categorise" once, then
"customise", then a round that turned up `normalise_balance()` and friends
sitting in actual function names. Each time the fix was mechanical and each
time a few instances survived it, because nothing was checking.

So: check. The stems below are the ones that have actually shown up in this
repo, not a general British-English dictionary — a word only earns a place
here after it has slipped in at least once.
"""

import re
from pathlib import Path

from django.test import SimpleTestCase

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# Directories whose contents this repo does not author.
EXCLUDED_DIRS = {
    ".git", ".venv", "node_modules", "staticfiles", "__pycache__",
    "migrations", ".devcontainer", "assets",
}

CHECKED_SUFFIXES = {".py", ".html", ".js", ".md"}

# Stem → the US spelling to use instead. Matched case-insensitively as a
# substring, so "normalis" catches normalise/normalised/normalising and
# Normalise/NORMALISE alike.
BRITISH_STEMS = {
    "normalis": "normaliz",
    "categoris": "categoriz",
    "customis": "customiz",
    "recognis": "recogniz",
    "organis": "organiz",
    "alphabetis": "alphabetiz",
    "initialis": "initializ",
    "materialis": "materializ",
    "quantis": "quantiz",
    "summaris": "summariz",
    "serialis": "serializ",
    "prioritis": "prioritiz",
    "synchronis": "synchroniz",
    "behaviour": "behavior",
    "colour": "color",
    "licence": "license",
}

PATTERN = re.compile("|".join(BRITISH_STEMS), re.IGNORECASE)

# A line carrying this marker is skipped. For the rare legitimate case: a
# style guide showing the wrong spelling as a counter-example, or a quotation
# from an external source. Opting a line out beats deleting the check.
OPT_OUT = "spelling-check: ignore"


def _checked_files():
    for path in REPO_ROOT.rglob("*"):
        if path.suffix not in CHECKED_SUFFIXES:
            continue
        if EXCLUDED_DIRS.intersection(path.parts):
            continue
        yield path


class SpellingTests(SimpleTestCase):
    def test_no_british_spellings_anywhere_in_the_repo(self):
        offenders = []

        for path in _checked_files():
            # This file names every stem it forbids; exempting it is what
            # lets the check describe itself.
            if path.name == Path(__file__).name:
                continue

            try:
                lines = path.read_text(encoding="utf-8").splitlines()
            except UnicodeDecodeError:
                continue

            for number, line in enumerate(lines, start=1):
                if OPT_OUT in line:
                    continue

                for match in PATTERN.finditer(line):
                    british = match.group(0)
                    american = BRITISH_STEMS[british.lower()]
                    offenders.append(
                        f"{path.relative_to(REPO_ROOT)}:{number}: "
                        f"“{british}” → use “{american}”"
                    )

        self.assertEqual(
            offenders,
            [],
            "US spelling is the house style. Found British spellings:\n"
            + "\n".join(offenders),
        )
