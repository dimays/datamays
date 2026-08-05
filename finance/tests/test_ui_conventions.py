"""The shared UI vocabulary, enforced rather than remembered.

Three patterns were being retyped instead of reused, and each had drifted
into more than one variant purely by whoever wrote it last — the empty state
in two paddings, the page subtitle in three different max-widths, the page
title in twenty copies of one class string.

Naming them in `assets/css/input.css` fixed the drift. These tests keep it
fixed: a template that retypes the raw utilities instead of using the
component class will fail here rather than quietly reintroducing a variant.
"""

from pathlib import Path

from django.test import SimpleTestCase

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
TEMPLATES = REPO_ROOT / "finance" / "templates"
INPUT_CSS = REPO_ROOT / "assets" / "css" / "input.css"
BUILT_CSS = REPO_ROOT / "static" / "css" / "tailwind.css"

# Raw utility strings that now have a component class. Substring match, so a
# template combining them with other utilities is caught too.
RETIRED_PATTERNS = {
    "text-2xl font-extrabold tracking-tight md:text-3xl": "page-title",
    "border-dashed border-border bg-surface/50": "empty-state",
}


def _templates():
    return sorted(TEMPLATES.rglob("*.html"))


class ComponentClassTests(SimpleTestCase):
    def test_no_template_retypes_a_retired_utility_string(self):
        offenders = []

        for path in _templates():
            body = path.read_text()

            for raw, replacement in RETIRED_PATTERNS.items():
                if raw in body:
                    offenders.append(
                        f"{path.relative_to(REPO_ROOT)}: “{raw}” → use “{replacement}”"
                    )

        self.assertEqual(
            offenders, [], "Use the component class:\n" + "\n".join(offenders)
        )

    def test_the_component_classes_are_defined(self):
        source = INPUT_CSS.read_text()

        for name in ("page-title", "page-subtitle", "empty-state"):
            self.assertIn(f".{name}", source)

    def test_the_committed_css_is_current(self):
        """static/css/tailwind.css is a build artifact — Heroku runs no Node,
        so a template change that adds a class is only live if the build was
        re-run and committed."""
        built = BUILT_CSS.read_text()

        for name in ("page-title", "page-subtitle", "empty-state"):
            self.assertIn(f".{name}", built, f".{name} missing — run npm run tailwind:build")


class DarkThemeControlTests(SimpleTestCase):
    """Native controls the browser draws itself, not Tailwind."""

    def test_the_page_declares_a_dark_color_scheme(self):
        """Without this a <select> opens a white panel over a near-black
        page — the most obvious 'unfinished' tell on a dark theme."""
        self.assertIn("color-scheme: dark", INPUT_CSS.read_text())
        self.assertIn("color-scheme: dark", BUILT_CSS.read_text())

    def test_checkboxes_use_the_theme_accent(self):
        """Native checkboxes ignore Tailwind's text-* color, so every
        checkbox rendered in the browser's default blue against an indigo
        and teal palette. accent-color is what actually recolors them."""
        self.assertIn("accent-color", INPUT_CSS.read_text())
        self.assertIn("accent-color: #4F46E5", BUILT_CSS.read_text())
