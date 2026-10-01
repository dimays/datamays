"""Money on the household side: project budgets, linked spending, and what
maintenance is expected to cost.

Every transaction read goes through `integrations/finance.py` (ADR 0009),
and every amount is a `Decimal` (ADR 0002). "Spent" is always positive for a
purchase; a refund linked to the same project nets against it.
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import timedelta
from decimal import Decimal

from django.db import IntegrityError, transaction

from .. import scheduling
from ..dates import to_household_date
from ..integrations import finance
from ..models import Occurrence, OccurrenceStatus, ProjectExpense

ZERO = Decimal("0")


def as_id(value):
    """A posted id as an int, or None. A non-numeric id is "not found",
    not a 500."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None

# How far around a date to look for the purchase behind it.
PROJECT_LEAD_DAYS = 30
JOB_WINDOW_DAYS = 14


# --- project budgets ---------------------------------------------------------


@dataclass
class LineRow:
    line: object
    actual: Decimal

    @property
    def remaining(self):
        return self.line.estimated - self.actual

    @property
    def is_over(self):
        return self.actual > self.line.estimated


@dataclass
class BudgetSummary:
    budget: Decimal | None  # the project's overall figure, if set
    estimated: Decimal  # the sum of its lines
    actual: Decimal
    lines: list = field(default_factory=list)
    unassigned: Decimal = ZERO  # linked spending not put against a line
    expenses: list = field(default_factory=list)

    @property
    def target(self):
        """What "over budget" is measured against: the overall budget if
        one is set, otherwise the lines' estimates."""
        return self.budget if self.budget is not None else (self.estimated or None)

    @property
    def remaining(self):
        return None if self.target is None else self.target - self.actual

    @property
    def is_over(self):
        return self.target is not None and self.actual > self.target

    @property
    def percent(self):
        if not self.target:
            return 0
        # Clamped both ways: a project with only a refund linked has negative
        # spend, which rendered a "-5%" bar. Found in review.
        return max(0, min(100, round(100 * self.actual / self.target)))


def budget_summary(project):
    """A project's budget against what was actually spent. Two queries."""
    lines = list(project.budget_lines.all())
    expenses = list(
        project.expenses.select_related("transaction", "transaction__account", "transaction__category", "budget_line")
    )

    # Re-checked on every read, not only when linked: if finance later marks
    # a linked purchase as a transfer or recategorizes it as income, it stops
    # counting here too, as it has in finance's own reports. Found in review.
    counting = finance.still_spending({expense.transaction_id for expense in expenses})

    by_line = defaultdict(lambda: ZERO)
    for expense in expenses:
        expense.spent = finance.spent(expense.transaction)
        expense.counts = expense.transaction_id in counting
        if expense.counts:
            by_line[expense.budget_line_id] += expense.spent

    return BudgetSummary(
        budget=project.budget_total,
        estimated=sum((line.estimated for line in lines), ZERO),
        actual=finance.total_spent(expense.transaction for expense in expenses if expense.counts),
        lines=[LineRow(line, by_line[line.pk]) for line in lines],
        unassigned=by_line[None],
        expenses=expenses,
    )


def project_window(project, today):
    """Where to look for a project's spending: from a month before it
    started (deposits, early purchases) through today."""
    start = (project.start_on or today - timedelta(days=90)) - timedelta(days=PROJECT_LEAD_DAYS)
    return start, today


def project_candidates(project, today, query=""):
    start, end = project_window(project, today)
    if query:
        # A search reaches further back: the receipt may predate the plan.
        start = start - timedelta(days=365)
    linked = project.expenses.values_list("transaction_id", flat=True)
    return finance.spending_candidates(start=start, end=end, query=query, exclude_ids=linked)


def link_expense(project, transaction_id, budget_line_id=None):
    """Count a transaction toward a project. Returns the link, or None if the
    transaction doesn't exist. Linking the same one twice is a no-op."""
    txn = finance.get_transaction(transaction_id)
    if txn is None:
        return None
    line = project.budget_lines.filter(pk=as_id(budget_line_id)).first() if as_id(budget_line_id) else None

    try:
        with transaction.atomic():
            expense, _ = ProjectExpense.objects.get_or_create(
                project=project, transaction_id=txn.pk, defaults={"budget_line": line}
            )
    except IntegrityError:  # a concurrent double submit
        expense = ProjectExpense.objects.get(project=project, transaction_id=txn.pk)
    return expense


# --- maintenance -------------------------------------------------------------


def job_candidates(occurrence, today, query=""):
    """Purchases near the day a job was done."""
    done_on = to_household_date(occurrence.completed_at) if occurrence.completed_at else today
    start = done_on - timedelta(days=JOB_WINDOW_DAYS)
    end = min(today, done_on + timedelta(days=JOB_WINDOW_DAYS))
    if query:
        start = done_on - timedelta(days=90)
    # A purchase already behind another job isn't offered again: it would
    # count twice in spend by year.
    taken = Occurrence.objects.filter(transaction__isnull=False).exclude(pk=occurrence.pk).values_list("transaction_id", flat=True)
    return finance.spending_candidates(start=start, end=end, query=query, exclude_ids=taken)


def link_job(occurrence, transaction_id):
    """Tie a done job to its purchase, and take its cost from it.

    The transaction is the truth: a cost typed at the time is replaced by
    what was actually spent. Refused: a refund (a job can't have cost a
    negative amount) and a purchase already behind another job (it would
    count twice). Found in review: both were accepted.
    """
    if occurrence.status != OccurrenceStatus.DONE:
        return False
    txn = finance.get_transaction(transaction_id)
    if txn is None or finance.spent(txn) < 0:
        return False
    if Occurrence.objects.filter(transaction=txn).exclude(pk=occurrence.pk).exists():
        return False

    occurrence.transaction = txn
    occurrence.cost = finance.spent(txn)
    occurrence.save(update_fields=["transaction", "cost", "updated_at"])
    return True


def unlink_job(occurrence):
    """Forget the link; the cost it set stays, as the best figure there is."""
    occurrence.transaction = None
    occurrence.save(update_fields=["transaction", "updated_at"])


@dataclass
class Projection:
    item: object
    count: int

    @property
    def total(self):
        return self.item.estimated_cost * self.count


def _due_dates_within(item, today, end):
    """When an item is expected to be due between now and `end`.

    The current occurrence counts once if it falls before `end` — overdue
    included, since it will be done soon. After it: the fixed schedule's
    dates, or for an after-completion schedule, one interval at a time on
    the assumption each is done when due.
    """
    chore, current = item.chore, item.current
    if not chore.is_active or current is None or current.due_on is None or current.due_on > end:
        return 0

    schedule = chore.schedule
    count = 1
    if schedule.is_fixed:
        # fixed_dates() already honors the count and end date; stop at the
        # window's end rather than walking the rest of the schedule.
        for day in scheduling.fixed_dates(schedule):
            if day > end:
                break
            if day > current.due_on:
                count += 1
    elif schedule.repeats:
        # The same rule the lifecycle uses — interval, season, end date, and
        # count — assuming each one is done on the day it's due.
        made = item.occurrence_count
        day = max(current.due_on, today)
        while True:
            day = scheduling.next_after_completion(schedule, day, made)
            if day is None or day > end:
                break
            made += 1
            count += 1
    return count


def projected_costs(items, today, days):
    """What maintenance is expected to cost over the next `days` days, from
    each item's usual cost and its schedule. Items with no usual cost are
    left out rather than guessed at."""
    end = today + timedelta(days=days)
    projections = [
        Projection(item, count)
        for item in items
        if item.estimated_cost
        for count in [_due_dates_within(item, today, end)]
        if count
    ]
    return {
        "days": days,
        "total": sum((p.total for p in projections), ZERO),
        "items": sorted(projections, key=lambda p: p.total, reverse=True),
    }
