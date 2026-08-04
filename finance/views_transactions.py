"""The activity list and the review queue.

The review queue is where the classifier's uncertainty gets resolved. Every
confirmation writes a merchant memo, so the same merchant is never asked about
twice — the queue should shrink toward empty rather than becoming a chore.

This view doubles as the landing spot for every "show me what's behind this
number" click elsewhere in the app: a budget row on the homepage, a bar in a
Spend chart. Those pass `budget=`, `start=`/`end=`, or `spend=1` rather than
duplicating filter logic at the call site, so the definition of "what counts"
stays in one place (services.rollups.expand_categories,
services.analytics.spend_transactions).
"""

from datetime import date

from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import ListView

from .access import FinanceAccessMixin
from .models import Account, Budget, Category, CategoryRule, MatchType, Transaction
from .redirects import safe_next
from .services.analytics import spend_filter
from .services.categorize import confirm_category
from .services.merchants import normalise_merchant
from .services.rollups import expand_categories


class TransactionListView(FinanceAccessMixin, ListView):
    template_name = "finance/transactions/list.html"
    context_object_name = "transactions"
    paginate_by = 50

    def get_queryset(self):
        queryset = Transaction.objects.select_related("account", "category")

        if self.request.GET.get("review") == "1":
            queryset = queryset.filter(needs_review=True)

        # Multi-value: a chart click carries forward whatever accounts were
        # already selected on the dashboard it came from, which may be more
        # than one. A single `?account=` still works the same as before.
        # The filter <select> always submits an "All accounts" option with
        # value="" — drop blanks so re-submitting the form with nothing
        # chosen doesn't try to filter account_id__in=[''].
        accounts = [value for value in self.request.GET.getlist("account") if value]
        if accounts:
            queryset = queryset.filter(account_id__in=accounts)

        category = self.request.GET.get("category")
        if category:
            queryset = queryset.filter(category_id=category)

        budget = self.filtered_budget()
        if budget is not None:
            # The exact definition budgets use for "actual" (services.rollups
            # .spend_for) — so a budget click-through shows precisely the rows
            # behind its number, not a looser approximation.
            queryset = queryset.filter(
                category_id__in=expand_categories(budget.categories.all()),
                is_transfer=False,
                amount__lt=0,
            )
            account_ids = list(budget.accounts.values_list("pk", flat=True))
            if account_ids:
                queryset = queryset.filter(account_id__in=account_ids)
        elif self.request.GET.get("spend") == "1":
            # Same idea for a Spend-chart bar: only what that chart counted.
            queryset = queryset.filter(spend_filter())

        start = self.parse_date(self.request.GET.get("start"))
        if start:
            queryset = queryset.filter(posted_on__gte=start)

        end = self.parse_date(self.request.GET.get("end"))
        if end:
            queryset = queryset.filter(posted_on__lte=end)

        search = self.request.GET.get("q", "").strip()
        if search:
            queryset = queryset.filter(
                Q(description_raw__icontains=search) | Q(merchant__icontains=search)
            )

        return queryset

    def filtered_budget(self):
        budget_id = self.request.GET.get("budget")

        if not budget_id or not budget_id.isdigit():
            return None

        # An invalid or stale id degrades to "no budget filter" rather than a
        # 404 — this is a query param on a list view, not a resource lookup.
        return Budget.objects.filter(pk=budget_id).prefetch_related(
            "categories", "accounts"
        ).first()

    @staticmethod
    def parse_date(value):
        if not value:
            return None

        try:
            return date.fromisoformat(value)
        except ValueError:
            return None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["page_title"] = "Activity"
        context["accounts"] = Account.objects.filter(is_active=True)
        context["categories"] = Category.objects.filter(
            is_active=True, children__isnull=True
        ).select_related("parent").alphabetical()
        context["budgets"] = Budget.objects.filter(is_active=True).order_by("name")
        context["review_only"] = self.request.GET.get("review") == "1"
        context["review_count"] = Transaction.objects.filter(needs_review=True).count()
        context["filtered_budget"] = self.filtered_budget()
        context["filters"] = {
            "account": self.request.GET.get("account", ""),
            "category": self.request.GET.get("category", ""),
            "budget": self.request.GET.get("budget", ""),
            "q": self.request.GET.get("q", ""),
            "start": self.request.GET.get("start", ""),
            "end": self.request.GET.get("end", ""),
        }

        return context

    def post(self, request, *args, **kwargs):
        """Confirm a category from the list, optionally as a standing rule."""
        transaction = get_object_or_404(Transaction, pk=request.POST.get("transaction"))
        category = get_object_or_404(Category, pk=request.POST.get("category"))

        confirm_category(transaction, category, request.user)

        if request.POST.get("create_rule"):
            self._create_rule(request, transaction, category)

        return redirect(safe_next(request, default=request.get_full_path()))

    def _create_rule(self, request, transaction, category):
        pattern = normalise_merchant(transaction.description_raw)

        if not pattern:
            messages.warning(
                request,
                "That description was too noisy to turn into a rule, but the "
                "merchant has been remembered.",
            )
            return

        rule, created = CategoryRule.objects.get_or_create(
            pattern=pattern,
            match_type=MatchType.CONTAINS,
            defaults={"category": category, "notes": "Created from the review queue."},
        )

        if not created:
            rule.category = category
            rule.save(update_fields=["category", "updated_at"])

        messages.success(request, f"Anything matching “{pattern}” now goes to {category}.")
