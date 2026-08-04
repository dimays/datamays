"""The activity list and the review queue.

The review queue is where the classifier's uncertainty gets resolved. Every
confirmation writes a merchant memo, so the same merchant is never asked about
twice — the queue should shrink toward empty rather than becoming a chore.
"""

from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect
from django.views.generic import ListView

from .access import FinanceAccessMixin
from .models import Account, Category, CategoryRule, MatchType, Transaction
from .redirects import safe_next
from .services.categorize import confirm_category
from .services.merchants import normalise_merchant


class TransactionListView(FinanceAccessMixin, ListView):
    template_name = "finance/transactions/list.html"
    context_object_name = "transactions"
    paginate_by = 50

    def get_queryset(self):
        queryset = Transaction.objects.select_related("account", "category")

        if self.request.GET.get("review") == "1":
            queryset = queryset.filter(needs_review=True)

        account = self.request.GET.get("account")
        if account:
            queryset = queryset.filter(account_id=account)

        category = self.request.GET.get("category")
        if category:
            queryset = queryset.filter(category_id=category)

        search = self.request.GET.get("q", "").strip()
        if search:
            queryset = queryset.filter(
                Q(description_raw__icontains=search) | Q(merchant__icontains=search)
            )

        return queryset

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context["page_title"] = "Activity"
        context["accounts"] = Account.objects.filter(is_active=True)
        context["categories"] = Category.objects.filter(
            is_active=True, children__isnull=True
        ).select_related("parent")
        context["review_only"] = self.request.GET.get("review") == "1"
        context["review_count"] = Transaction.objects.filter(needs_review=True).count()
        context["filters"] = {
            "account": self.request.GET.get("account", ""),
            "category": self.request.GET.get("category", ""),
            "q": self.request.GET.get("q", ""),
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
