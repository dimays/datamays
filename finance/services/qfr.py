"""Quarterly Finance Reports: metrics, comparisons, and the narrative.

Three layers, deliberately separable:

1. **Metrics** — plain numbers, computed by re-reading the ledger. Fully
   testable without a network call.
2. **Comparisons** — the same metrics for the previous quarter and the same
   quarter a year ago, computed on demand rather than requiring those
   reports to already exist. A gap in the backfill should never block a
   later quarter from generating.
3. **Narrative** — an LLM turns (1) and (2) into the four fixed sections a
   QFR shows. Optional: a report with no OPENAI_API_KEY is still a complete,
   useful report, just without prose.

Generation writes nothing until the metrics are fully computed, and makes the
narrator call — the one network round trip in this module — with no database
transaction open around it, for the same reason services.categorize does:
holding a transaction across a call to a third party pins a connection for as
long as that party takes to answer.
"""

import json
import logging
from datetime import date, timedelta
from decimal import Decimal

from django.conf import settings
from django.db.models import Sum
from django.utils import timezone

from ..dates import household_today
from ..models import (
    DEBT_TYPES,
    SAVINGS_TYPES,
    Account,
    BudgetPeriod,
    QuarterlyReport,
    Transaction,
)
from ..periods import previous_quarter, quarter_bounds, quarter_containing
from . import analytics

logger = logging.getLogger(__name__)

BATCH_SIZE_CATEGORIES = 8

SYSTEM_PROMPT = """You write a household's Quarterly Finance Report from numbers you are given.

Respond with a JSON object with exactly these four string keys:
- "summary": 2-4 sentences, the headline of the quarter.
- "key_trends": 2-4 sentences on what moved and in what direction, referencing
  the comparison figures where they're informative.
- "major_events": 1-3 sentences on anything that stands out as a one-off
  rather than a trend — a large single purchase, a paycheck change, a new
  account. If nothing stands out, say so plainly rather than inventing one.
- "risk_areas": 1-3 sentences on what's worth keeping an eye on next quarter —
  budgets running over, debt growing, savings rate falling. If nothing looks
  concerning, say so plainly.

Ground every claim in the numbers provided. Never invent a transaction, a
merchant, or an event that isn't implied by the data. Write for two people who
already know their own finances — skip generic budgeting advice."""


def quarter_is_complete(year: int, quarter: int, *, today=None) -> bool:
    _, end = quarter_bounds(year, quarter)
    return end < (today or household_today())


def compute_metrics(start: date, end: date) -> dict:
    """The quarter's own numbers — no comparison, no narrative."""
    day_before = start - timedelta(days=1)

    net_worth_start = analytics.net_worth_as_of(day_before)
    net_worth_end = analytics.net_worth_as_of(end)

    spend_total = Transaction.objects.filter(
        analytics.spend_filter(), posted_on__gte=start, posted_on__lte=end
    ).aggregate(total=Sum("amount"))["total"]

    net_income = analytics.net_income_over_time(start, end, grain="monthly")
    # Gross is optional supplementary detail (see analytics.income_over_time)
    # and only ever reflects pay periods with an imported payslip — it can
    # legitimately read lower than total_income_net for a household member
    # whose pay is tracked from deposits alone.
    payslip_detail = analytics.income_over_time(start, end, grain="monthly")
    by_category = analytics.spend_by_category(start, end, limit=BATCH_SIZE_CATEGORIES)

    savings_start = _type_balance_as_of(SAVINGS_TYPES, day_before)
    savings_end = _type_balance_as_of(SAVINGS_TYPES, end)
    # Negated here, once, so every downstream read (including the delta) sees
    # amounts owed on a consistent None-means-no-data footing — a $0 balance
    # (a card paid off exactly) must not be mistaken for "nothing reported yet".
    debt_owed_start = _negate(_type_balance_as_of(DEBT_TYPES, day_before))
    debt_owed_end = _negate(_type_balance_as_of(DEBT_TYPES, end))

    return {
        "period_start": start.isoformat(),
        "period_end": end.isoformat(),
        "net_worth_start": _f(net_worth_start),
        "net_worth_end": _f(net_worth_end),
        "net_worth_change": _f(_delta(net_worth_start, net_worth_end)),
        # Floored at 0 for the same reason spend_by_category floors each
        # category: a quarter refunded more than it spent nets to a positive
        # raw total, which would otherwise report as negative spend.
        "total_spend": max(0.0, _f(-spend_total)) if spend_total else 0.0,
        "spend_by_category": dict(zip(by_category["labels"], by_category["values"])),
        "total_income_gross": round(sum(payslip_detail["gross"]), 2),
        "total_income_net": round(sum(net_income["values"]), 2),
        # Stored as amounts owed (positive), so "debt_change" being negative
        # always reads as "debt went down" — the way a person expects it to.
        "savings_balance_start": _f(savings_start),
        "savings_balance_end": _f(savings_end),
        "savings_change": _f(_delta(savings_start, savings_end)),
        "debt_balance_start": _f(debt_owed_start) if debt_owed_start is not None else 0.0,
        "debt_balance_end": _f(debt_owed_end) if debt_owed_end is not None else 0.0,
        "debt_change": _f(_delta(debt_owed_start, debt_owed_end)),
        "budgets": _budget_summary(start, end),
    }


def _type_balance_as_of(account_types, when):
    total = None

    for account in Account.objects.filter(
        is_active=True, account_type__in=account_types
    ):
        snapshot = (
            account.balance_snapshots.filter(as_of__lte=when).order_by("-as_of").first()
        )
        if snapshot is None:
            continue
        total = (total or Decimal("0")) + snapshot.current

    return total


def _negate(value):
    return None if value is None else -value


def _delta(start, end):
    if start is None or end is None:
        return None
    return end - start


def _f(value):
    return float(value) if value is not None else None


def _budget_summary(start, end):
    """Actual vs. target summed across every period a budget ran within the quarter.

    A weekly budget has ~13 periods inside one quarter; this sums them rather
    than picking one, so "Groceries" in a QFR means the whole quarter's
    grocery spend against the whole quarter's target.
    """
    rows = (
        BudgetPeriod.objects.filter(
            period_start__gte=start, period_start__lte=end
        )
        .values("budget__id", "budget__name")
        .annotate(actual=Sum("actual_amount"), target=Sum("target_amount"))
        .order_by("-actual")
    )

    return [
        {
            "name": row["budget__name"],
            "actual": _f(row["actual"]),
            "target": _f(row["target"]),
        }
        for row in rows
    ]


def historical_comparisons(year: int, quarter: int, current_metrics: dict) -> dict:
    """This quarter against the previous one, and against the same quarter last year.

    Computed fresh rather than read from a stored QuarterlyReport, so a gap in
    the backfill (a quarter nobody generated) never blocks comparisons for a
    later one.
    """
    comparisons = {}

    prev_year, prev_quarter_num = previous_quarter(year, quarter)
    comparisons["previous_quarter"] = _comparison_against(
        current_metrics, prev_year, prev_quarter_num, label=f"Q{prev_quarter_num} {prev_year}"
    )

    comparisons["year_ago_quarter"] = _comparison_against(
        current_metrics, year - 1, quarter, label=f"Q{quarter} {year - 1}"
    )

    return comparisons


def _comparison_against(current_metrics, year, quarter, *, label):
    start, end = quarter_bounds(year, quarter)

    if not quarter_is_complete(year, quarter):
        return None

    other = compute_metrics(start, end)

    return {
        "label": label,
        "net_worth_change_delta": _numeric_delta(
            current_metrics["net_worth_change"], other["net_worth_change"]
        ),
        "total_spend_delta": _numeric_delta(
            current_metrics["total_spend"], other["total_spend"]
        ),
        "total_income_net_delta": _numeric_delta(
            current_metrics["total_income_net"], other["total_income_net"]
        ),
        "metrics": other,
    }


def _numeric_delta(current, other):
    if current is None or other is None:
        return None
    return round(current - other, 2)


class QFRNarrator:
    """Base interface. Subclasses talk to a specific provider, or nothing."""

    def narrate(self, metrics: dict, comparisons: dict) -> dict:
        raise NotImplementedError


class NullNarrator(QFRNarrator):
    """Used with no API key configured. A QFR without prose is still a report."""

    def narrate(self, metrics, comparisons):
        return {}


class OpenAINarrator(QFRNarrator):
    def __init__(self, api_key=None, model=None):
        self.api_key = api_key or getattr(settings, "OPENAI_API_KEY", "")
        self.model = model or getattr(settings, "FINANCE_QFR_MODEL", "gpt-4o-mini")

    def narrate(self, metrics, comparisons):
        if not self.api_key:
            return {}

        try:
            return self._call(metrics, comparisons)
        except Exception:  # noqa: BLE001
            # A narrative failure must not lose the metrics the caller already
            # computed — the report is still generated, just without prose.
            logger.exception("QFR narrative generation failed")
            return {}

    def _call(self, metrics, comparisons):
        from openai import OpenAI

        from .classifier import REQUEST_TIMEOUT_SECONDS

        client = OpenAI(api_key=self.api_key, timeout=REQUEST_TIMEOUT_SECONDS, max_retries=2)

        response = client.chat.completions.create(
            model=self.model,
            temperature=0.3,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps({"metrics": metrics, "comparisons": comparisons}),
                },
            ],
        )

        payload = json.loads(response.choices[0].message.content or "{}")

        return {
            key: str(payload[key]).strip()
            for key in ("summary", "key_trends", "major_events", "risk_areas")
            if payload.get(key)
        }


def get_narrator() -> QFRNarrator:
    if getattr(settings, "OPENAI_API_KEY", ""):
        return OpenAINarrator()

    return NullNarrator()


def generate_qfr(year: int, quarter: int, *, narrator=None, force=False) -> QuarterlyReport:
    """Compute and store one quarter's report.

    Idempotent unless `force`: re-running a backfill after adding more history
    should not silently overwrite a report someone may have already read,
    unless they ask for that explicitly.
    """
    if not quarter_is_complete(year, quarter):
        current_year, current_quarter = quarter_containing(household_today())
        raise ValueError(
            f"Q{quarter} {year} is not finished yet (today is in Q{current_quarter} "
            f"{current_year}). Generate it after the quarter closes."
        )

    existing = QuarterlyReport.objects.filter(year=year, quarter=quarter).first()

    if existing is not None and not force:
        return existing

    start, end = quarter_bounds(year, quarter)

    metrics = compute_metrics(start, end)
    comparisons = historical_comparisons(year, quarter, metrics)

    # No transaction open here: narrate() is a network call, and the metrics
    # above are already fully computed in Python — nothing left to roll back.
    narrator = narrator or get_narrator()
    narrative = narrator.narrate(metrics, comparisons)

    report, _ = QuarterlyReport.objects.update_or_create(
        year=year,
        quarter=quarter,
        defaults={
            "period_start": start,
            "period_end": end,
            "metrics": metrics,
            "comparisons": comparisons,
            "summary": narrative.get("summary", ""),
            "key_trends": narrative.get("key_trends", ""),
            "major_events": narrative.get("major_events", ""),
            "risk_areas": narrative.get("risk_areas", ""),
            "narrator": type(narrator).__name__ if narrative else "",
            "generated_at": timezone.now(),
        },
    )

    return report
