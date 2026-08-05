"""The Charts tab's sections, declared once.

Both the Charts page and the Preferences page need to know what sections
exist, what to call them, and what order they come in. Keeping the list here
rather than in either view means neither has to import the other — Preferences
used to reach into `views_dashboards` for it, which had forms depending on
views for no reason other than where the constant happened to live.

Each slug maps to a template partial at
`finance/dashboards/sections/<slug>.html`.
"""

CHART_SECTION_CHOICES = [
    ("spend_over_time", "Spend over time"),
    ("spend_by_category_trend", "Spend by category, over time"),
    ("spend_by_category", "Spend by category"),
    ("large_transactions", "Largest transactions"),
    ("budget_attainment", "Budget attainment"),
    ("net_income", "Net income"),
    ("net_cash_flow", "Net cash flow"),
    ("net_worth", "Net worth"),
    ("balances_over_time", "Balances over time"),
]

CHART_SECTION_SLUGS = [slug for slug, _ in CHART_SECTION_CHOICES]
