"""The Charts tab's sections, declared once.

Both the Charts page and the Preferences page need to know what sections
exist, what to call them, and what order they come in. Keeping the list here
rather than in either view means neither has to import the other — Preferences
used to reach into the dashboards view module for it, which had forms
depending on views for no reason beyond where the constant happened to live.

The title and the one-line blurb live here too, not in the templates. Each
section's card is drawn by `dashboards/_section.html` from this data, so a
section template contains only what is actually specific to it: its controls
and its chart. Retitling a section is a one-line edit here rather than a hunt
through nine near-identical partials.

Each slug maps to a template partial at
`finance/dashboards/sections/<slug>.html`, and to a key in the view's
`section_has_data` map, which decides whether the section renders at all.
"""

from typing import NamedTuple


class ChartSection(NamedTuple):
    slug: str
    label: str
    blurb: str = ""


CHART_SECTIONS = [
    ChartSection(
        "spend_over_time",
        "Spend over time",
        "Total outflow per period. Switch the view to split it by category, "
        "or to drill into one category's subcategories.",
    ),
    ChartSection(
        "spend_by_category_trend",
        "Spend by category, over time",
        "Each line is a category, so a trend jumps out.",
    ),
    ChartSection(
        "spend_by_category",
        "Spend by category",
        "Every category, largest first. Break it out to see the subcategories "
        "beneath each one.",
    ),
    ChartSection(
        "large_transactions",
        "Largest transactions",
        "The biggest one-off outflows in this window — worth a second look.",
    ),
    ChartSection(
        "budget_attainment",
        "Budget attainment",
        "Actual against target, period by period, for each active budget.",
    ),
    ChartSection(
        "net_income",
        "Net income",
        "Every deposit categorized as income, whether or not a payslip was "
        "imported for it.",
    ),
    ChartSection(
        "net_cash_flow",
        "Net cash flow",
        "Income minus spend, per period — above zero is cash building up.",
    ),
    ChartSection(
        "net_worth",
        "Net worth",
        "Everything you own minus everything you owe, day by day.",
    ),
    ChartSection(
        "balances_over_time",
        "Balances over time",
        "Every account, signed the same way it reads everywhere else — a debt "
        "is negative.",
    ),
]

CHART_SECTIONS_BY_SLUG = {section.slug: section for section in CHART_SECTIONS}

CHART_SECTION_SLUGS = [section.slug for section in CHART_SECTIONS]

# What the Preferences form's checkbox list is built from.
CHART_SECTION_CHOICES = [(section.slug, section.label) for section in CHART_SECTIONS]
