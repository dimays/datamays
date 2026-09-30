"""Project budgets, and the link rows that tie household records to finance.

Finance's tables are never altered for household features (ADR 0009). A
transaction "belonging" to a project is a household-side row pointing at it:
`ProjectExpense` for projects, `Occurrence.transaction` for maintenance.
Everything read back through them follows finance's sign convention (ADR
0003) — money leaving is negative — and household code turns that into
"spent" at exactly one place, `integrations/finance.py`.
"""

from django.core.validators import MinValueValidator
from django.db import models

from .base import TimestampedModel, money_field


class BudgetLine(TimestampedModel):
    """One planned cost in a project: "Tile", "Paint", "Contractor"."""

    project = models.ForeignKey("household.Project", on_delete=models.CASCADE, related_name="budget_lines")
    label = models.CharField(max_length=120)
    estimated = money_field(validators=[MinValueValidator(0)], help_text="As a positive number.")

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return self.label


class ProjectExpense(TimestampedModel):
    """A finance transaction counted toward a project, optionally a line."""

    project = models.ForeignKey("household.Project", on_delete=models.CASCADE, related_name="expenses")
    budget_line = models.ForeignKey(
        BudgetLine, on_delete=models.SET_NULL, null=True, blank=True, related_name="expenses"
    )
    transaction = models.ForeignKey(
        "finance.Transaction", on_delete=models.CASCADE, related_name="+",
        help_text="Deleted with the transaction: an expense that no longer exists isn't spending.",
    )

    class Meta:
        ordering = ["-transaction__posted_on", "-id"]
        constraints = [
            # Counting one purchase twice in the same project would overstate
            # its spend; the same purchase split across two projects is fine.
            models.UniqueConstraint(fields=["project", "transaction"], name="one_link_per_project_transaction"),
        ]

    def __str__(self):
        return f"{self.transaction} → {self.project}"
