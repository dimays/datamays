"""The activity list and the review queue.

The review queue is where the classifier's uncertainty gets resolved. Every
confirmation writes a merchant memo, so the same merchant is never asked about
twice — the queue should shrink toward empty rather than becoming a chore.

This view doubles as the landing spot for every "show me what's behind this
number" click elsewhere in the app: a budget row on the homepage, a bar in a
Spend chart. Those pass `budget=`, `start=`/`end=`, or `spend=1` rather than
duplicating filter logic at the call site, so the definition of "what counts"
stays in one place (services.rollups.expand_categories,
services.analytics.spend_filter).

Accounts, categories, and budgets are all multi-select, and combine the way
faceted filters normally do: choices *within* one filter are OR'd together
("Checking or Savings"), and the different filters are AND'd against each
other ("(Checking or Savings) and (Groceries)"). Selecting a budget and a
category that budget doesn't include is a legitimate thing to ask for — it
just means "transactions in that category, restricted to what this budget
would count" — and if that combination matches nothing, the empty state below
says so explicitly rather than looking indistinguishable from "no
transactions at all".
"""

from datetime import date

from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import ListView

from .access import FinanceAccessMixin
from .categories_seed import UNCATEGORIZED_SLUG
from .models import Account, Budget, Category, CategorySource, Transaction
from .redirects import safe_next
from .services.analytics import spend_filter
from .services.categorize import confirm_category
from .services.rollups import expand_categories


class TransactionListView(FinanceAccessMixin, ListView):
    template_name = "finance/transactions/list.html"
    context_object_name = "transactions"
    paginate_by = 50

    def get_queryset(self):
        queryset = Transaction.objects.select_related("account", "category")

        if self.request.GET.get("review") == "1":
            queryset = queryset.filter(needs_review=True)

        if self.selected_accounts:
            queryset = queryset.filter(account_id__in=self.selected_accounts)

        if self.selected_categories:
            queryset = queryset.filter(category_id__in=self.selected_categories)

        budgets = self.filtered_budgets()
        if budgets:
            # No amount__lt=0 here — a refund against one of the budget's own
            # categories is part of "what counts toward it" too, the same
            # definition services.rollups.spend_for() sums.
            queryset = queryset.filter(self._budgets_q(budgets), is_transfer=False)

        if self.request.GET.get("spend") == "1":
            # Independent of budget — a chart click and a budget click-through
            # can both land here (e.g. a stale link), and both narrowing the
            # result is the correct, unsurprising behavior rather than one
            # silently overriding the other.
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

    @staticmethod
    def _budgets_q(budgets):
        """OR across budgets, each with its own category (and, if it has one,
        account) restriction — "everything that counts toward any of these
        budgets", which is what picking more than one budget should mean."""
        combined = Q(pk__in=[])  # false until a budget contributes to it

        for budget in budgets:
            clause = Q(category_id__in=expand_categories(budget.categories.all()))

            account_ids = list(budget.accounts.values_list("pk", flat=True))
            if account_ids:
                clause &= Q(account_id__in=account_ids)

            combined |= clause

        return combined

    @property
    def selected_accounts(self):
        # The "All accounts" option in the filter always submits value="" —
        # drop blanks so re-submitting with nothing chosen doesn't try to
        # filter account_id__in=[''].
        if not hasattr(self, "_selected_accounts"):
            self._selected_accounts = [v for v in self.request.GET.getlist("account") if v]
        return self._selected_accounts

    @property
    def selected_categories(self):
        if not hasattr(self, "_selected_categories"):
            self._selected_categories = [v for v in self.request.GET.getlist("category") if v]
        return self._selected_categories

    def filtered_budgets(self):
        if not hasattr(self, "_filtered_budgets"):
            budget_ids = [
                v for v in self.request.GET.getlist("budget") if v and v.isdigit()
            ]
            # Invalid or stale ids just drop out rather than erroring — these
            # are query params on a list view, not a resource lookup.
            self._filtered_budgets = list(
                Budget.objects.filter(pk__in=budget_ids).prefetch_related(
                    "categories", "accounts"
                )
            ) if budget_ids else []
        return self._filtered_budgets

    @staticmethod
    def parse_date(value):
        if not value:
            return None

        try:
            return date.fromisoformat(value)
        except ValueError:
            return None

    def has_active_filters(self):
        return bool(
            self.selected_accounts
            or self.selected_categories
            or self.filtered_budgets()
            or self.request.GET.get("start")
            or self.request.GET.get("end")
            or self.request.GET.get("q")
            or self.request.GET.get("spend") == "1"
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        all_accounts = Account.objects.filter(is_active=True)
        all_categories = Category.objects.filter(
            is_active=True, children__isnull=True
        ).select_related("parent").alphabetical()
        filtered_budgets = self.filtered_budgets()

        context["page_title"] = "Activity"
        context["accounts"] = all_accounts
        context["categories"] = all_categories
        # Archived categories stay assignable — just tucked into their own
        # section at the bottom of the picker, so old data stays readable
        # without cluttering the choices for new transactions.
        context["archived_categories"] = Category.objects.filter(
            is_active=False, children__isnull=True
        ).select_related("parent").alphabetical()
        context["budgets"] = Budget.objects.filter(is_active=True).order_by("name")
        context["review_only"] = self.request.GET.get("review") == "1"
        context["review_count"] = Transaction.objects.filter(needs_review=True).count()
        context["filtered_budgets"] = filtered_budgets
        context["has_active_filters"] = self.has_active_filters()
        # Precomputed for the "showing: ..." banner, so the template doesn't
        # have to cross-reference id lists against the full dropdown options.
        context["selected_account_names"] = [
            a.name for a in all_accounts if str(a.pk) in self.selected_accounts
        ]
        context["selected_category_names"] = [
            c.full_path for c in all_categories if str(c.pk) in self.selected_categories
        ]
        context["selected_budget_names"] = [budget.name for budget in filtered_budgets]
        context["filters"] = {
            "accounts": self.selected_accounts,
            "categories": self.selected_categories,
            "budgets": [str(budget.pk) for budget in filtered_budgets],
            "q": self.request.GET.get("q", ""),
            "start": self.request.GET.get("start", ""),
            "end": self.request.GET.get("end", ""),
        }

        page_obj = context.get("page_obj")
        if page_obj is not None:
            # Bare "?page=N" would drop every other active filter (review=1
            # included) — a page-2 link must carry the rest of the query
            # string forward, not just replace it.
            context["previous_page_url"] = (
                self._page_url(page_obj.previous_page_number())
                if page_obj.has_previous()
                else None
            )
            context["next_page_url"] = (
                self._page_url(page_obj.next_page_number())
                if page_obj.has_next()
                else None
            )

        return context

    def _page_url(self, page_number):
        query = self.request.GET.copy()
        query["page"] = page_number
        return f"{self.request.path}?{query.urlencode()}"

    def post(self, request, *args, **kwargs):
        """Confirm a category from the list, or apply one in bulk.

        Standing rules are created from Settings > Category rules instead,
        with the full pattern-matching system available there — not folded
        into this save.
        """
        if request.POST.get("action") == "bulk_categorize":
            return self._bulk_categorize(request)

        transaction = get_object_or_404(Transaction, pk=request.POST.get("transaction"))
        category = get_object_or_404(Category, pk=request.POST.get("category"))

        confirm_category(transaction, category, request.user)

        return redirect(safe_next(request, default=request.get_full_path()))

    def _bulk_categorize(self, request):
        """Set one category on many transactions at once — either an
        explicit id list, or every transaction matching the page's current
        filters (self.get_queryset() reads request.GET, which is populated
        from the URL regardless of this being a POST, so it sees the exact
        same filters the page was rendered with).

        Bypasses confirm_category(): that writes a MerchantCategoryMemo per
        merchant, which doesn't make sense for an arbitrary bulk selection
        that may span many unrelated merchants."""
        category = get_object_or_404(Category, pk=request.POST.get("category"))

        if request.POST.get("apply_to_all_filtered") == "1":
            queryset = self.get_queryset()
        else:
            queryset = Transaction.objects.filter(
                pk__in=request.POST.getlist("transaction_ids")
            )

        if category.slug == UNCATEGORIZED_SLUG:
            # Matches services.categorize._assign_uncategorized: parked for
            # review rather than treated as a confirmed decision.
            count = queryset.update(
                category=category,
                category_source="",
                category_confidence=0.0,
                needs_review=True,
            )
        else:
            count = queryset.update(
                category=category,
                category_source=CategorySource.MANUAL,
                category_confidence=1.0,
                needs_review=False,
            )

        messages.success(
            request,
            f"Set {count} transaction{'s' if count != 1 else ''} to {category.full_path}.",
        )
        return redirect(safe_next(request, default=request.get_full_path()))
