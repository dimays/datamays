"""Settings and per-user preferences.

Settings are household-wide — connections, accounts, categories, rules. They
affect the ledger, so both people see the same thing.

Preferences are personal — which widgets, which filters. They affect only how
one person sees that ledger, so they never touch shared data.
"""

from django import forms
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse_lazy
from django.utils.text import slugify
from django.views.generic import CreateView, FormView, ListView, TemplateView, UpdateView

from .access import FinanceAccessMixin
from .models import (
    Account,
    AccountConnection,
    Budget,
    CategoryRule,
    ConnectionStatus,
    Institution,
    Provider,
    SyncRun,
    SyncStatus,
    SyncTrigger,
    UserPreference,
)
from .providers.base import ProviderError
from .providers.simplefin import claim_access_url
from .services.sync import sync_connection
from .services.widgets import WIDGET_CHOICES
from .views import FinanceView
from .views_dashboards import CHART_SECTION_CHOICES

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
                "institution_count": Institution.objects.count(),
                "budget_count": Budget.objects.count(),
                "rule_count": CategoryRule.objects.count(),
                "needs_attention": AccountConnection.objects.filter(
                    status__in=[ConnectionStatus.NEEDS_REAUTH, ConnectionStatus.ERROR]
                ).defer("access_secret"),
                "recent_runs": SyncRun.objects.select_related("connection")[:5],
            }
        )

        return context


class InstitutionForm(forms.ModelForm):
    """Every institution goes through here, whether it ends up connected via
    SimpleFIN or only ever fed by hand-uploaded statements — CSV import and
    manual accounts both need an Institution to attach to, and until now the
    only way to create one was the side effect of connecting a SimpleFIN
    integration."""

    class Meta:
        model = Institution
        fields = ["name", "provider", "owner", "website", "notes", "is_active"]
        widgets = {
            "name": forms.TextInput(attrs={"class": FIELD_CLASSES, "placeholder": "Northwestern Mutual"}),
            "provider": forms.Select(attrs={"class": FIELD_CLASSES}),
            "owner": forms.Select(attrs={"class": FIELD_CLASSES}),
            "website": forms.URLInput(attrs={"class": FIELD_CLASSES}),
            "notes": forms.Textarea(attrs={"class": FIELD_CLASSES, "rows": 3}),
            "is_active": forms.CheckboxInput(attrs={"class": CHECKBOX_CLASSES}),
        }
        help_texts = {
            "provider": "How data from here normally arrives — SimpleFIN connects "
            "automatically; CSV/manual means you'll keep it current by hand.",
        }

    def save(self, commit=True):
        institution = super().save(commit=False)

        if not institution.slug:
            institution.slug = slugify(institution.name)[:140]

        if commit:
            institution.save()

        return institution


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


class ConnectionForm(forms.Form):
    """Step one of adding an integration: authenticate.

    No institution field — a single SimpleFIN setup token can cover more than
    one real institution (that's how SimpleFIN Bridge itself works), so which
    institution each discovered account belongs to is resolved automatically
    during sync from the provider's own data, not chosen up front here.
    """

    label = forms.CharField(
        label="Name this connection",
        max_length=120,
        required=False,
        widget=forms.TextInput(
            attrs={"class": FIELD_CLASSES, "placeholder": "Byline + Capital One (joint)"}
        ),
        help_text="However you want to recognise this in Settings — it can cover more than one institution.",
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


class AccountForm(forms.ModelForm):
    class Meta:
        model = Account
        fields = [
            "name", "account_type", "owner", "mask", "debt_reported_positive",
            "is_active", "include_in_net_worth", "include_in_spending",
            "sort_order", "notes",
        ]
        widgets = {
            "name": forms.TextInput(attrs={"class": FIELD_CLASSES}),
            "account_type": forms.Select(attrs={"class": FIELD_CLASSES}),
            "owner": forms.Select(attrs={"class": FIELD_CLASSES}),
            "mask": forms.TextInput(attrs={"class": FIELD_CLASSES}),
            "sort_order": forms.NumberInput(attrs={"class": FIELD_CLASSES}),
            "notes": forms.Textarea(attrs={"class": FIELD_CLASSES, "rows": 2}),
            "debt_reported_positive": forms.CheckboxInput(attrs={"class": CHECKBOX_CLASSES}),
            "is_active": forms.CheckboxInput(attrs={"class": CHECKBOX_CLASSES}),
            "include_in_net_worth": forms.CheckboxInput(attrs={"class": CHECKBOX_CLASSES}),
            "include_in_spending": forms.CheckboxInput(attrs={"class": CHECKBOX_CLASSES}),
        }


class ManualAccountForm(forms.ModelForm):
    """For an account with no connection — the mortgage, the 401(k), anything
    only ever kept current by a CSV import or by hand. A connected account's
    institution is set by the sync that discovered it, so this form (and its
    institution field) is create-only; editing an existing account goes
    through AccountForm instead."""

    class Meta:
        model = Account
        fields = [
            "institution", "name", "account_type", "owner", "mask",
            "current_balance", "balance_as_of",
            "debt_reported_positive", "include_in_net_worth", "include_in_spending",
            "notes",
        ]
        widgets = {
            "institution": forms.Select(attrs={"class": FIELD_CLASSES}),
            "name": forms.TextInput(attrs={"class": FIELD_CLASSES, "placeholder": "401(k)"}),
            "account_type": forms.Select(attrs={"class": FIELD_CLASSES}),
            "owner": forms.Select(attrs={"class": FIELD_CLASSES}),
            "mask": forms.TextInput(attrs={"class": FIELD_CLASSES}),
            "current_balance": forms.NumberInput(attrs={"class": FIELD_CLASSES, "step": "0.01"}),
            "balance_as_of": forms.DateTimeInput(attrs={"class": FIELD_CLASSES, "type": "datetime-local"}),
            "notes": forms.Textarea(attrs={"class": FIELD_CLASSES, "rows": 2}),
            "debt_reported_positive": forms.CheckboxInput(attrs={"class": CHECKBOX_CLASSES}),
            "include_in_net_worth": forms.CheckboxInput(attrs={"class": CHECKBOX_CLASSES}),
            "include_in_spending": forms.CheckboxInput(attrs={"class": CHECKBOX_CLASSES}),
        }
        help_texts = {
            "current_balance": "Optional — leave blank and set it later with a CSV "
            "balance import if you don't have a figure handy right now.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["institution"].queryset = Institution.objects.filter(is_active=True)
        self.fields["current_balance"].required = False
        self.fields["balance_as_of"].required = False


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
        return context

    def form_valid(self, form):
        # current_balance is normalised (services.sync.normalise_balance) only
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


class PreferencesForm(forms.ModelForm):
    widgets_selected = forms.MultipleChoiceField(
        label="Homepage widgets",
        choices=WIDGET_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={"class": CHECKBOX_CLASSES}),
    )
    # Populated by the drag-and-drop reorder script (finance/js/widget-reorder.js)
    # as a comma-separated slug list reflecting the on-screen row order —
    # every WIDGET_CHOICES slug, not just the checked ones, so unchecking and
    # rechecking a widget doesn't lose its place in the list.
    widget_order = forms.CharField(required=False, widget=forms.HiddenInput())
    chart_sections_selected = forms.MultipleChoiceField(
        label="Charts tab sections",
        choices=CHART_SECTION_CHOICES,
        required=False,
        widget=forms.CheckboxSelectMultiple(attrs={"class": CHECKBOX_CLASSES}),
    )
    # Same reorder pattern as widget_order, one section down.
    chart_section_order_input = forms.CharField(required=False, widget=forms.HiddenInput())
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

        all_slugs = [slug for slug, _ in WIDGET_CHOICES]
        all_section_slugs = [slug for slug, _ in CHART_SECTION_CHOICES]

        if self.instance.pk:
            self.fields["widgets_selected"].initial = self.instance.widgets
            self.fields["accounts_selected"].initial = self.instance.homepage_account_ids
            self.fields["budgets_selected"].initial = self.instance.homepage_budget_ids
            # The chosen widgets first, in the order the person last arranged
            # them, then anything not yet chosen — so a widget shipped after
            # they last saved still shows up, at the end rather than nowhere.
            ordered = list(self.instance.widgets) + [
                slug for slug in all_slugs if slug not in self.instance.widgets
            ]
            self.fields["chart_sections_selected"].initial = self.instance.chart_section_order
            ordered_sections = list(self.instance.chart_section_order) + [
                slug for slug in all_section_slugs if slug not in self.instance.chart_section_order
            ]
        else:
            ordered = all_slugs
            ordered_sections = all_section_slugs

        self.fields["widget_order"].initial = ",".join(ordered)
        self._ordered_slugs = ordered

        self.fields["chart_section_order_input"].initial = ",".join(ordered_sections)
        self._ordered_section_slugs = ordered_sections

    def ordered_widget_rows(self):
        """(slug, label, checked) in the order the reorder UI should render them."""
        checked = set(self.fields["widgets_selected"].initial or [])
        labels = dict(WIDGET_CHOICES)

        return [(slug, labels[slug], slug in checked) for slug in self._ordered_slugs]

    def ordered_chart_section_rows(self):
        """(slug, label, checked) for the Charts tab section reorder UI."""
        checked = set(self.fields["chart_sections_selected"].initial or [])
        labels = dict(CHART_SECTION_CHOICES)

        return [
            (slug, labels[slug], slug in checked) for slug in self._ordered_section_slugs
        ]

    def save(self, commit=True):
        preference = super().save(commit=False)

        # The hidden field carries the drag-and-drop order for every known
        # widget; filtering it down to what's checked (rather than reading
        # WIDGET_CHOICES' fixed order) is what lets a person actually control
        # placement instead of always getting it reset to the declared order.
        chosen = set(self.cleaned_data["widgets_selected"])
        known_slugs = {slug for slug, _ in WIDGET_CHOICES}
        ordered_slugs = [
            slug
            for slug in self.cleaned_data["widget_order"].split(",")
            if slug in known_slugs
        ]
        # A missing or corrupted order (JS disabled, stale form) falls back
        # to the declared order rather than dropping every widget.
        if not ordered_slugs:
            ordered_slugs = [slug for slug, _ in WIDGET_CHOICES]

        preference.homepage_widgets = [slug for slug in ordered_slugs if slug in chosen]

        chosen_sections = set(self.cleaned_data["chart_sections_selected"])
        known_section_slugs = {slug for slug, _ in CHART_SECTION_CHOICES}
        ordered_section_slugs = [
            slug
            for slug in self.cleaned_data["chart_section_order_input"].split(",")
            if slug in known_section_slugs
        ]
        if not ordered_section_slugs:
            ordered_section_slugs = [slug for slug, _ in CHART_SECTION_CHOICES]

        preference.chart_sections = [
            slug for slug in ordered_section_slugs if slug in chosen_sections
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
