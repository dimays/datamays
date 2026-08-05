"""Settings and per-user preferences.

Settings are household-wide — connections, accounts, categories, rules. They
affect the ledger, so both people see the same thing.

Preferences are personal — which widgets, which filters. They affect only how
one person sees that ledger, so they never touch shared data.

The forms these views render live in `finance/forms/`, not here.
"""

from django.contrib import messages
from django.db import transaction as db_transaction
from django.db.models import Count
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import CreateView, FormView, ListView, TemplateView, UpdateView

from .access import FinanceAccessMixin
from .categories_seed import UNCATEGORIZED_SLUG
from .dates import household_today
from .forms import (
    AccountForm,
    BalanceUpdateForm,
    CategoryForm,
    ConnectionForm,
    InstitutionForm,
    ManualAccountForm,
    PreferencesForm,
    RuleForm,
)
from .models import (
    Account,
    AccountConnection,
    BalanceSource,
    Budget,
    Category,
    CategoryRule,
    CategorySource,
    ConnectionStatus,
    Institution,
    Provider,
    SyncRun,
    SyncStatus,
    SyncTrigger,
    Transaction,
    UserPreference,
)
from .providers.base import ProviderError
from .providers.simplefin import claim_access_url
from .services.categorize import categorize_transactions
from .services.sync import record_balance_snapshot, sync_connection
from .views import FinanceView


class SettingsHomeView(FinanceView):
    template_name = "finance/settings/index.html"
    page_title = "Settings"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context.update(
            {
                "connections": AccountConnection.objects.select_related("institution").defer("access_secret"),
                "accounts": Account.objects.select_related("institution"),
                "institution_count": Institution.objects.count(),
                "budget_count": Budget.objects.count(),
                "rule_count": CategoryRule.objects.count(),
                "category_count": Category.objects.count(),
                "needs_attention": AccountConnection.objects.filter(
                    status__in=[ConnectionStatus.NEEDS_REAUTH, ConnectionStatus.ERROR]
                ).defer("access_secret"),
                "recent_runs": SyncRun.objects.select_related("connection")[:5],
                # Mirrors categorize_transactions()'s own default queryset, so
                # this number is exactly what the button below would act on.
                "uncategorized_count": Transaction.objects.filter(
                    category__isnull=True, is_transfer=False
                ).count(),
            }
        )

        return context

    def post(self, request, *args, **kwargs):
        if request.POST.get("action") == "categorize":
            summary = categorize_transactions()
            messages.success(
                request,
                f"Transfers paired: {summary.transfers} · by rule: {summary.by_rule} · "
                f"remembered: {summary.by_memo} · classified: {summary.by_classifier} · "
                f"needs review: {summary.needs_review} · unmatched: {summary.unmatched}",
            )

        return redirect("finance:settings")


class InstitutionListView(FinanceAccessMixin, ListView):
    template_name = "finance/settings/institutions.html"
    context_object_name = "institutions"

    def get_queryset(self):
        return Institution.objects.prefetch_related("accounts", "connections")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Institutions"
        return context


class InstitutionCreateView(FinanceAccessMixin, CreateView):
    template_name = "finance/settings/institution_form.html"
    form_class = InstitutionForm
    success_url = reverse_lazy("finance:institutions")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "New institution"
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"Added {self.object.name}.")
        return response


class InstitutionUpdateView(FinanceAccessMixin, UpdateView):
    template_name = "finance/settings/institution_form.html"
    form_class = InstitutionForm
    model = Institution
    success_url = reverse_lazy("finance:institutions")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = f"Edit {self.object.name}"
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"Updated {self.object.name}.")
        return response


class ConnectionCreateView(FinanceAccessMixin, FormView):
    """Authenticate, exchange the token, then test by syncing immediately."""

    template_name = "finance/settings/connection_form.html"
    form_class = ConnectionForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Connect an institution"
        return context

    def form_valid(self, form):
        try:
            access_url = claim_access_url(form.cleaned_data["setup_token"])
        except ProviderError as exc:
            form.add_error("setup_token", str(exc))
            return self.form_invalid(form)

        connection = AccountConnection.objects.create(
            label=form.cleaned_data["label"] or "SimpleFIN",
            provider=Provider.SIMPLEFIN,
            access_secret=access_url,
            created_by=self.request.user,
        )

        # Test and deploy in one step: a connection that cannot pull is not
        # really connected, and finding that out now beats finding out when a
        # dashboard is silently empty.
        run = sync_connection(connection, trigger=SyncTrigger.MANUAL)

        if run.status == SyncStatus.SUCCESS:
            institution_count = (
                connection.accounts.values("institution").distinct().count()
            )
            messages.success(
                self.request,
                f"Connected: {institution_count} institution"
                f"{'s' if institution_count != 1 else ''}, {run.accounts_synced} "
                f"accounts, {run.transactions_created} transactions.",
            )
        else:
            messages.warning(
                self.request,
                f"Saved the connection, but the first sync reported: {run.error_message}",
            )

        return redirect("finance:settings")


class ConnectionDetailView(FinanceAccessMixin, TemplateView):
    template_name = "finance/settings/connection_detail.html"

    def get_connection(self, *, with_secret=False):
        queryset = AccountConnection.objects.all()

        # The detail page only ever displays metadata; decrypting to render it
        # would be both wasteful and a needless failure mode.
        if not with_secret:
            queryset = queryset.defer("access_secret")

        return get_object_or_404(queryset, pk=self.kwargs["pk"])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        connection = self.get_connection()

        context.update(
            {
                "page_title": connection.label,
                "connection": connection,
                "accounts": connection.accounts.select_related("institution"),
                "runs": connection.sync_runs.all()[:20],
            }
        )

        return context

    def post(self, request, *args, **kwargs):
        connection = self.get_connection()
        action = request.POST.get("action")

        if action == "sync":
            run = sync_connection(
                self.get_connection(with_secret=True), trigger=SyncTrigger.MANUAL
            )
            messages.info(
                request,
                f"Sync {run.status}: {run.accounts_synced} accounts, "
                f"{run.transactions_created} new, {run.transactions_updated} updated.",
            )
        elif action == "disable":
            connection.status = ConnectionStatus.DISABLED
            connection.save(update_fields=["status", "updated_at"])
            messages.info(request, "Connection disabled. It will be skipped by the scheduler.")
        elif action == "enable":
            connection.status = ConnectionStatus.ACTIVE
            connection.save(update_fields=["status", "updated_at"])
            messages.success(request, "Connection re-enabled.")
        elif action == "forget":
            # Clearing the secret is the point: revoking on SimpleFIN's side
            # is a separate step, but nothing usable should linger here.
            connection.access_secret = ""
            connection.status = ConnectionStatus.DISABLED
            connection.save(update_fields=["access_secret", "status", "updated_at"])
            messages.warning(
                request,
                "Stored credential erased. Revoke it at bridge.simplefin.org too.",
            )

        return redirect("finance:connection_detail", pk=connection.pk)


class AccountCreateView(FinanceAccessMixin, CreateView):
    template_name = "finance/settings/account_form.html"
    form_class = ManualAccountForm
    success_url = reverse_lazy("finance:settings")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "New manual account"
        return context

    def form_valid(self, form):
        messages.success(self.request, f"Added {form.instance.name}.")
        return super().form_valid(form)


class AccountUpdateView(FinanceAccessMixin, UpdateView):
    template_name = "finance/settings/account_form.html"
    form_class = AccountForm
    model = Account
    success_url = reverse_lazy("finance:settings")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = f"Edit {self.object.name}"
        context.setdefault(
            "balance_form",
            BalanceUpdateForm(initial={"as_of": household_today()}),
        )
        return context

    def post(self, request, *args, **kwargs):
        self.object = self.get_object()

        if request.POST.get("action") == "update_balance":
            return self._update_balance(request)

        return super().post(request, *args, **kwargs)

    def _update_balance(self, request):
        """A one-off manual reading — the lightweight alternative to a CSV
        balances import for a single account, connected or not. For a
        connected account this is only as durable as the next sync, which
        will overwrite it with whatever the provider reports."""
        account = self.object
        balance_form = BalanceUpdateForm(request.POST)

        if not balance_form.is_valid():
            context = self.get_context_data(
                form=AccountForm(instance=account), balance_form=balance_form
            )
            return self.render_to_response(context)

        account.current_balance = balance_form.cleaned_data["current_balance"]
        account.available_balance = balance_form.cleaned_data["available_balance"]
        account.balance_as_of = timezone.now()
        account.save(update_fields=["current_balance", "available_balance", "balance_as_of", "updated_at"])

        record_balance_snapshot(
            account,
            as_of=balance_form.cleaned_data["as_of"],
            current=account.current_balance,
            available=account.available_balance,
            source=BalanceSource.MANUAL,
        )

        messages.success(request, f"Updated {account.name}'s balance.")
        return redirect(self.get_success_url())

    def form_valid(self, form):
        # current_balance is normalized (services.sync.normalize_balance) only
        # at sync time, so flipping this checkbox alone leaves the stored
        # balance untouched until the next sync happens to run — which can be
        # up to an hour away, and silently never for a manual account. Since
        # the sign flip is self-inverse, apply it here immediately rather
        # than make the household total wait on a background job to notice.
        sign_flip_needed = (
            "debt_reported_positive" in form.changed_data
            and form.instance.is_liability
        )

        account = form.save(commit=False)

        if sign_flip_needed:
            if account.current_balance is not None:
                account.current_balance = -account.current_balance
            if account.available_balance is not None:
                account.available_balance = -account.available_balance

        account.save()
        self.object = account

        messages.success(self.request, f"Updated {account.name}.")
        return redirect(self.get_success_url())


class RuleListView(FinanceAccessMixin, ListView):
    template_name = "finance/settings/rules.html"
    context_object_name = "rules"

    def get_queryset(self):
        return CategoryRule.objects.select_related("category", "account")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Category rules"
        return context

    def post(self, request, *args, **kwargs):
        rule = get_object_or_404(CategoryRule, pk=request.POST.get("rule"))

        if request.POST.get("action") == "delete":
            rule.delete()
            messages.info(request, "Rule removed.")
        else:
            rule.is_active = not rule.is_active
            rule.save(update_fields=["is_active", "updated_at"])

        return redirect("finance:rules")


class RuleCreateView(FinanceAccessMixin, CreateView):
    template_name = "finance/settings/rule_form.html"
    form_class = RuleForm
    success_url = reverse_lazy("finance:rules")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "New category rule"
        return context

    def form_valid(self, form):
        rule = form.instance
        messages.success(
            self.request,
            f"Anything that {rule.get_match_type_display().lower()} "
            f"“{rule.pattern}” now goes to {rule.category}.",
        )
        return super().form_valid(form)


class CategoryListView(FinanceAccessMixin, ListView):
    template_name = "finance/settings/categories.html"
    context_object_name = "categories"

    def get_queryset(self):
        return (
            Category.objects.select_related("parent")
            .annotate(transaction_count=Count("transactions", distinct=True))
            .alphabetical()
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Categories"
        return context

    def post(self, request, *args, **kwargs):
        category = get_object_or_404(Category, pk=request.POST.get("category"))

        if category.is_system:
            messages.error(request, "This category is built into the app and can't be archived.")
            return redirect("finance:categories")

        category.is_active = not category.is_active
        category.save(update_fields=["is_active", "updated_at"])

        messages.info(
            request,
            f"{category.full_path} {'archived' if not category.is_active else 'unarchived'}.",
        )
        return redirect("finance:categories")


class CategoryCreateView(FinanceAccessMixin, CreateView):
    template_name = "finance/settings/category_form.html"
    form_class = CategoryForm
    success_url = reverse_lazy("finance:categories")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "New category"
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"Added {self.object.full_path}.")
        return response


class CategoryUpdateView(FinanceAccessMixin, UpdateView):
    template_name = "finance/settings/category_form.html"
    form_class = CategoryForm
    model = Category
    success_url = reverse_lazy("finance:categories")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = f"Edit {self.object.full_path}"
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"Updated {self.object.full_path}.")
        return response


class CategoryDeleteView(FinanceAccessMixin, TemplateView):
    """Deleting a category cascades to its CategoryRules and
    MerchantCategoryMemos (both FK on_delete=CASCADE), and would otherwise
    silently null out every transaction currently filed under it
    (Transaction.category is on_delete=SET_NULL). Reassigning those
    transactions to a chosen category first — defaulting to Uncategorized —
    keeps that from happening quietly."""

    template_name = "finance/settings/category_delete.html"

    def get_category(self):
        return get_object_or_404(Category, pk=self.kwargs["pk"])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        category = self.get_category()
        default_reassign = Category.objects.filter(slug=UNCATEGORIZED_SLUG).first()

        context.update(
            {
                "page_title": f"Delete {category.full_path}",
                "category": category,
                "transaction_count": category.transactions.count(),
                "rule_count": category.rules.count(),
                "memo_count": category.merchant_memos.count(),
                "child_count": category.children.count(),
                "reassign_choices": Category.objects.filter(is_active=True)
                .exclude(pk=category.pk)
                .select_related("parent")
                .alphabetical(),
                "default_reassign": default_reassign,
            }
        )
        return context

    def post(self, request, *args, **kwargs):
        category = self.get_category()

        if category.is_system:
            messages.error(request, "This category is built into the app and can't be deleted.")
            return redirect("finance:categories")

        if category.children.exists():
            messages.error(
                request,
                f"{category.full_path} has subcategories — delete or reassign those first.",
            )
            return redirect("finance:category_delete", pk=category.pk)

        reassign_to = (
            Category.objects.filter(pk=request.POST.get("reassign_to"), is_active=True)
            .exclude(pk=category.pk)
            .first()
        )

        if reassign_to is None:
            messages.error(request, "Pick a category for the existing transactions to move to.")
            return redirect("finance:category_delete", pk=category.pk)

        with db_transaction.atomic():
            moved = category.transactions.count()

            if reassign_to.slug == UNCATEGORIZED_SLUG:
                # Matches services.categorize._assign_uncategorized: parked
                # for review rather than treated as a confirmed decision.
                category.transactions.update(
                    category=reassign_to,
                    category_source="",
                    category_confidence=0.0,
                    needs_review=True,
                )
            else:
                category.transactions.update(
                    category=reassign_to,
                    category_source=CategorySource.MANUAL,
                    category_confidence=1.0,
                    needs_review=False,
                )

            name = category.full_path
            category.delete()

        messages.success(
            request,
            f"Deleted {name}. {moved} transaction{'s' if moved != 1 else ''} moved to {reassign_to.full_path}.",
        )
        return redirect("finance:categories")


class PreferencesView(FinanceAccessMixin, UpdateView):
    template_name = "finance/settings/preferences.html"
    form_class = PreferencesForm
    success_url = reverse_lazy("finance:preferences")

    def get_object(self, queryset=None):
        # Personal, always — never another person's row, whatever is in the URL.
        return UserPreference.for_user(self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Preferences"
        return context

    def form_valid(self, form):
        messages.success(self.request, "Preferences saved.")
        return super().form_valid(form)
