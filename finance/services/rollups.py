"""Computing budget actuals.

Materialised rather than derived on page load: the homepage shows every active
budget at once, and doing that live would be one aggregate query per budget on
every request from a phone.

Two rules that shape the arithmetic:

- **Transfers never count.** Moving money between our own accounts is not
  spending, and counting it would make every budget look blown.
- **Selecting a parent category includes its children.** Budgeting "Food"
  should cover groceries and restaurants without listing each leaf, which is
  how a person means it.
"""

from decimal import Decimal

from django.db.models import Q, Sum

from ..dates import household_today
from ..models import Budget, BudgetPeriod, Category, Transaction
from ..periods import previous_period


def expand_categories(categories):
    """A category selection plus every descendant, to the depth cap."""
    selected = list(categories)

    if not selected:
        return []

    ids = {category.pk for category in selected}

    children = Category.objects.filter(parent_id__in=ids)
    ids.update(child.pk for child in children)

    grandchildren = Category.objects.filter(parent_id__in=[c.pk for c in children])
    ids.update(grandchild.pk for grandchild in grandchildren)

    return list(ids)


def spend_for(budget: Budget, start, end) -> Decimal:
    """Total outflow against a budget in a window, as a positive number."""
    category_ids = expand_categories(budget.categories.all())

    if not category_ids:
        return Decimal("0")

    filters = Q(
        category_id__in=category_ids,
        posted_on__gte=start,
        posted_on__lte=end,
        is_transfer=False,
        # Only money leaving. A refund reduces the total, which is why this
        # sums signed amounts rather than counting rows.
        amount__lt=0,
    )

    account_ids = list(budget.accounts.values_list("pk", flat=True))

    if account_ids:
        filters &= Q(account_id__in=account_ids)

    total = Transaction.objects.filter(filters).aggregate(total=Sum("amount"))["total"]

    return -(total or Decimal("0"))


def rollover_for(budget: Budget, start) -> Decimal:
    """What last period's under- or overspend carries into this one."""
    if not budget.rollover:
        return Decimal("0")

    previous_start, _ = previous_period(budget.period_type, budget.anchor_date, start)
    previous = budget.budget_periods.filter(period_start=previous_start).first()

    if previous is None:
        return Decimal("0")

    return previous.target_amount - previous.actual_amount


def roll_up_budget(budget: Budget, on_date=None) -> BudgetPeriod:
    """Recompute one budget's current period."""
    on_date = on_date or household_today()
    start, end = budget.period_for(on_date)

    rollover = rollover_for(budget, start)

    period, _ = BudgetPeriod.objects.update_or_create(
        budget=budget,
        period_start=start,
        defaults={
            "period_end": end,
            "target_amount": budget.amount + rollover,
            "actual_amount": spend_for(budget, start, end),
            "rollover_amount": rollover,
        },
    )

    return period


def roll_up_all(on_date=None, *, include_inactive=False):
    budgets = Budget.objects.prefetch_related("categories", "accounts")

    if not include_inactive:
        budgets = budgets.filter(is_active=True)

    return [roll_up_budget(budget, on_date) for budget in budgets]


def backfill_budget(budget: Budget, periods_back: int = 12, on_date=None):
    """Recompute recent history, so a new budget has a chart from day one."""
    on_date = on_date or household_today()
    start, _ = budget.period_for(on_date)

    boundaries = [start]

    for _ in range(periods_back):
        start, _ = previous_period(budget.period_type, budget.anchor_date, start)
        boundaries.append(start)

    # Oldest first, so each period's rollover sees a computed predecessor.
    return [roll_up_budget(budget, boundary) for boundary in reversed(boundaries)]
