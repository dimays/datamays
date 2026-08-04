"""Settings and per-user preferences.

Settings are household-wide — connections, accounts, categories, rules. They
affect the ledger, so both people see the same thing.

Preferences are personal — which widgets, which filters. They affect only how
one person sees that ledger, so they never touch shared data.
"""

from django import forms
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse, reverse_lazy
from django.views.generic import FormView, ListView, TemplateView, UpdateView

from .access import FinanceAccessMixin
from .models import (
    Account,
    AccountConnection,
    AccountType,
    Budget,
    CategoryRule,
    ConnectionStatus,
    Institution,
    Provider,
    SyncRun,
    SyncTrigger,
    UserPreference,
)
from .providers.base import ProviderError
from .providers.simplefin import claim_access_url
from .services.sync import sync_connection
from .services.widgets import WIDGET_CHOICES
from .views import FinanceView

FIELD_CLASSES = (
    "w-full rounded-button border border-border bg-background px-3 py-2 text-sm "
    "text-text-primary focus:outline-none focus:ring-2 focus:ring-primary"
)

CHECKBOX_CLASSES = (
    "h-4 w-4 rounded border-border bg-background text-primary focus:ring-primary"
)


class SettingsHomeView(FinanceView):
    template_name = "finance/settings/index.html"
    page_title = "Settings"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)

        context.update(
            {
                "connections": AccountConnection.objects.select_related("institution").defer("access_secret"),
                "accounts": Account.objects.select_related("institution"),
                "budget_count": Budget.objects.count(),
                "rule_count": CategoryRule.objects.count(),
                "needs_attention": AccountConnection.objects.filter(
                    status__in=[ConnectionStatus.NEEDS_REAUTH, ConnectionStatus.ERROR]
                ).defer("access_secret"),
                "recent_runs": SyncRun.objects.select_related("connection")[:5],
            }
        )

        return context


class ConnectionForm(forms.Form):
    """Step one of adding an integration: authenticate."""

    institution_name = forms.CharField(
        label="Institution",
        max_length=120,
        widget=forms.TextInput(
            attrs={"class": FIELD_CLASSES, "placeholder": "Byline Bank"}
        ),
    )
    label = forms.CharField(
        label="Name this connection",
        max_length=120,
        required=False,
        widget=forms.TextInput(
            attrs={"class": FIELD_CLASSES, "placeholder": "Byline (joint)"}
        ),
    )
    setup_token = forms.CharField(
        label="SimpleFIN setup token",
        widget=forms.Textarea(
            attrs={
                "class": FIELD_CLASSES,
                "rows": 4,
                "placeholder": "Paste the token from bridge.simplefin.org",
                # Never let a browser or password manager retain a bearer
                # credential from this box.
                "autocomplete": "off",
                "spellcheck": "false",
            }
        ),
        help_text="Single use — SimpleFIN will refuse a token that has already been claimed.",
    )


class ConnectionCreateView(FinanceAccessMixin, FormView):
    """Authenticate, exchange the token, then test by syncing immediately."""

    template_name = "finance/settings/connection_form.html"
    form_class = ConnectionForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Connect an institution"
        return context

    def form_valid(self, form):
        from django.utils.text import slugify

        try:
            access_url = claim_access_url(form.cleaned_data["setup_token"])
        except ProviderError as exc:
            form.add_error("setup_token", str(exc))
            return self.form_invalid(form)

        name = form.cleaned_data["institution_name"].strip()

        institution, _ = Institution.objects.get_or_create(
            name=name,
            defaults={"slug": slugify(name)[:140], "provider": Provider.SIMPLEFIN},
        )

        connection = AccountConnection.objects.create(
            institution=institution,
            label=form.cleaned_data["label"] or f"{name} (SimpleFIN)",
            provider=Provider.SIMPLEFIN,
            access_secret=access_url,
            created_by=self.request.user,
        )

        # Test and deploy in one step: a connection that cannot pull is not
        # really connected, and finding that out now beats finding out when a
        # dashboard is silently empty.
        run = sync_connection(connection, trigger=SyncTrigger.MANUAL)

        if run.status == "success":
            messages.success(
                self.request,
                f"Connected {institution.name}: {run.accounts_synced} accounts, "
                f"{run.transactions_created} transactions.",
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
                "accounts": connection.accounts.all(),
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


class AccountForm(forms.ModelForm):
    class Meta:
        model = Account
        fields = [
            "name", "account_type", "mask", "debt_reported_positive",
            "is_active", "include_in_net_worth", "include_in_spending",
            "sort_order", "notes",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": FIELD_CLASSES}),
            "account_type": forms.Select(attrs={"class": FIELD_CLASSES}),
            "mask": forms.TextInput(attrs={"class": FIELD_CLASSES}),
            "sort_order": forms.NumberInput(attrs={"class": FIELD_CLASSES}),
            "notes": forms.Textarea(attrs={"class": FIELD_CLASSES, "rows": 2}),
            "debt_reported_positive": forms.CheckboxInput(attrs={"class": CHECKBOX_CLASSES}),
            "is_active": forms.CheckboxInput(attrs={"class": CHECKBOX_CLASSES}),
            "include_in_net_worth": forms.CheckboxInput(attrs={"class": CHECKBOX_CLASSES}),
            "include_in_spending": forms.CheckboxInput(attrs={"class": CHECKBOX_CLASSES}),
        }


class AccountUpdateView(FinanceAccessMixin, UpdateView):
    template_name = "finance/settings/account_form.html"
    form_class = AccountForm
    model = Account
    success_url = reverse_lazy("finance:settings")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = f"Edit {self.object.name}"
        return context

    def form_valid(self, form):
        messages.success(self.request, f"Updated {form.instance.name}.")
        return super().form_valid(form)


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


class PreferencesForm(forms.ModelForm):
    widgets_selected = forms.MultipleChoiceField(
        label="Homepage widgets",
        choices=WIDGET_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={"class": CHECKBOX_CLASSES}),
    )
    accounts_selected = forms.ModelMultipleChoiceField(
        label="Accounts to show",
        queryset=Account.objects.filter(is_active=True),
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={"class": CHECKBOX_CLASSES}),
        help_text="Leave all unchecked to show every account.",
    )
    budgets_selected = forms.ModelMultipleChoiceField(
        label="Budgets to show",
        queryset=Budget.objects.filter(is_active=True),
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={"class": CHECKBOX_CLASSES}),
        help_text="Leave all unchecked to show every active budget.",
    )

    class Meta:
        model = UserPreference
        fields = ["recent_transaction_count"]
        widgets = {
            "recent_transaction_count": forms.NumberInput(
                attrs={"class": FIELD_CLASSES, "min": 1, "max": 50}
            )
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        if self.instance.pk:
            self.fields["widgets_selected"].initial = self.instance.widgets
            self.fields["accounts_selected"].initial = self.instance.homepage_account_ids
            self.fields["budgets_selected"].initial = self.instance.homepage_budget_ids

    def save(self, commit=True):
        preference = super().save(commit=False)

        # Stored in the order WIDGET_CHOICES declares, so the homepage reads
        # the same way every time rather than in checkbox-click order.
        chosen = set(self.cleaned_data["widgets_selected"])
        preference.homepage_widgets = [
            slug for slug, _ in WIDGET_CHOICES if slug in chosen
        ]

        preference.homepage_account_ids = [
            account.pk for account in self.cleaned_data["accounts_selected"]
        ]
        preference.homepage_budget_ids = [
            budget.pk for budget in self.cleaned_data["budgets_selected"]
        ]

        if commit:
            preference.save()

        return preference


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
