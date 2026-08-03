"""The CSV import wizard: upload → confirm mapping → preview → commit.

Three screens rather than one, because the mapping step is the whole point.
Auto-detection is good enough to be right most of the time and confident
enough to be dangerous when it isn't, so nothing is written until a person has
looked at the proposed columns and the resulting preview.
"""

from django import forms
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.generic import DetailView, FormView, ListView

from .access import FinanceAccessMixin
from .models import (
    Account,
    AmountConvention,
    ImportBatch,
    ImportMapping,
    ImportStatus,
    Institution,
    RecordType,
    RowStatus,
)
from .services.importer import ImportError_, commit_batch, parse_batch, stage_upload

FIELD_CLASSES = (
    "w-full rounded-button border border-border bg-background px-3 py-2 text-sm "
    "text-text-primary focus:outline-none focus:ring-2 focus:ring-primary"
)

# Target fields per record type, and whether the import can proceed without them.
REQUIRED_FIELDS = {
    RecordType.TRANSACTIONS: ["posted_on", "description"],
    RecordType.BALANCES: ["as_of", "current"],
    RecordType.PAYCHECK: ["pay_date", "gross", "net"],
}

OPTIONAL_FIELDS = {
    RecordType.TRANSACTIONS: ["amount", "debit", "credit", "merchant"],
    RecordType.BALANCES: ["available"],
    RecordType.PAYCHECK: [
        "employer",
        "deduction:federal_tax",
        "deduction:state_tax",
        "deduction:fica",
        "deduction:retirement",
        "deduction:hsa",
        "deduction:insurance",
    ],
}

FIELD_LABELS = {
    "posted_on": "Transaction date",
    "description": "Description",
    "amount": "Amount (single signed column)",
    "debit": "Debit column",
    "credit": "Credit column",
    "merchant": "Merchant",
    "as_of": "Balance date",
    "current": "Balance",
    "available": "Available balance",
    "pay_date": "Pay date",
    "employer": "Employer",
    "gross": "Gross pay",
    "net": "Net pay",
    "deduction:federal_tax": "Federal tax withheld",
    "deduction:state_tax": "State tax withheld",
    "deduction:fica": "Social Security & Medicare",
    "deduction:retirement": "Retirement contribution",
    "deduction:hsa": "HSA / FSA",
    "deduction:insurance": "Insurance premium",
}


class UploadForm(forms.Form):
    institution = forms.ModelChoiceField(
        queryset=Institution.objects.filter(is_active=True),
        widget=forms.Select(attrs={"class": FIELD_CLASSES}),
    )
    account = forms.ModelChoiceField(
        queryset=Account.objects.filter(is_active=True),
        required=False,
        help_text="Required for transactions and balances.",
        widget=forms.Select(attrs={"class": FIELD_CLASSES}),
    )
    record_type = forms.ChoiceField(
        choices=RecordType.choices,
        widget=forms.Select(attrs={"class": FIELD_CLASSES}),
    )
    csv_file = forms.FileField(
        widget=forms.ClearableFileInput(attrs={"class": FIELD_CLASSES, "accept": ".csv,text/csv"})
    )

    def clean(self):
        cleaned = super().clean()

        if cleaned.get("record_type") in {RecordType.TRANSACTIONS, RecordType.BALANCES} and not cleaned.get("account"):
            raise forms.ValidationError(
                "Pick the account these rows belong to — transactions and "
                "balances cannot be filed without one."
            )

        return cleaned


class ImportListView(FinanceAccessMixin, ListView):
    template_name = "finance/imports/list.html"
    context_object_name = "batches"
    paginate_by = 20

    def get_queryset(self):
        return ImportBatch.objects.select_related("institution", "account")

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Imports"
        return context


class ImportUploadView(FinanceAccessMixin, FormView):
    template_name = "finance/imports/upload.html"
    form_class = UploadForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Import a file"
        return context

    def form_valid(self, form):
        upload = form.cleaned_data["csv_file"]

        batch = ImportBatch.objects.create(
            uploaded_by=self.request.user,
            institution=form.cleaned_data["institution"],
            account=form.cleaned_data["account"],
            record_type=form.cleaned_data["record_type"],
            original_filename=upload.name[:255],
            raw_content=upload.read().decode("utf-8-sig", errors="replace"),
        )

        try:
            stage_upload(batch)
        except ImportError_ as exc:
            messages.error(self.request, str(exc))
            return redirect("finance:import_upload")

        return redirect("finance:import_map", pk=batch.pk)


class ImportMapView(FinanceAccessMixin, DetailView):
    """Confirm which column means what, pre-filled with the detected guess."""

    template_name = "finance/imports/map.html"
    model = ImportBatch
    context_object_name = "batch"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        batch = self.object
        suggested = (batch.suggested_map or {}).get("columns", {})

        context["page_title"] = "Confirm columns"
        context["fields"] = [
            {
                "key": key,
                "label": FIELD_LABELS.get(key, key),
                "required": key in REQUIRED_FIELDS[batch.record_type],
                "suggested": (suggested.get(key) or {}).get("column", ""),
                "confidence": (suggested.get(key) or {}).get("confidence"),
            }
            for key in REQUIRED_FIELDS[batch.record_type] + OPTIONAL_FIELDS[batch.record_type]
        ]
        context["amount_conventions"] = AmountConvention.choices
        context["detected_convention"] = (batch.suggested_map or {}).get(
            "amount_convention", AmountConvention.SIGNED
        )
        context["detected_date_format"] = (batch.suggested_map or {}).get("date_format", "")
        context["saved_mappings"] = ImportMapping.objects.filter(
            institution=batch.institution, record_type=batch.record_type
        )

        return context

    def post(self, request, *args, **kwargs):
        batch = self.get_object()

        column_map = {
            key: value
            for key, value in request.POST.items()
            if key.startswith(("posted_on", "description", "amount", "debit", "credit",
                               "merchant", "as_of", "current", "available", "pay_date",
                               "employer", "gross", "net", "deduction:"))
            and value
        }

        missing = [
            FIELD_LABELS.get(field, field)
            for field in REQUIRED_FIELDS[batch.record_type]
            if not column_map.get(field)
        ]

        if batch.record_type == RecordType.TRANSACTIONS and not (
            column_map.get("amount") or column_map.get("debit") or column_map.get("credit")
        ):
            missing.append("an amount column (or a debit/credit pair)")

        if missing:
            messages.error(request, f"Still need: {', '.join(missing)}.")
            return redirect("finance:import_map", pk=batch.pk)

        convention = request.POST.get("amount_convention") or AmountConvention.SIGNED
        date_format = request.POST.get("date_format", "").strip()

        parse_batch(
            batch,
            column_map=column_map,
            date_format=date_format,
            amount_convention=convention,
        )

        if request.POST.get("save_mapping"):
            self._save_mapping(request, batch, column_map, date_format, convention)

        return redirect("finance:import_preview", pk=batch.pk)

    def _save_mapping(self, request, batch, column_map, date_format, convention):
        name = request.POST.get("mapping_name") or f"{batch.institution.name} default"

        mapping, _ = ImportMapping.objects.update_or_create(
            institution=batch.institution,
            record_type=batch.record_type,
            name=name[:120],
            defaults={
                "column_map": column_map,
                "date_format": date_format,
                "amount_convention": convention,
                "skip_rows": (batch.suggested_map or {}).get("skip_rows", 0),
                "created_by": request.user,
            },
        )

        batch.mapping = mapping
        batch.save(update_fields=["mapping", "updated_at"])

        messages.success(request, f"Saved '{mapping.name}' for next time.")


class ImportPreviewView(FinanceAccessMixin, DetailView):
    """Show what would be written, before anything is."""

    template_name = "finance/imports/preview.html"
    model = ImportBatch
    context_object_name = "batch"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["page_title"] = "Review import"
        context["rows"] = self.object.rows.all()[:100]
        context["problem_rows"] = self.object.rows.filter(status=RowStatus.ERROR)[:25]
        return context

    def post(self, request, *args, **kwargs):
        batch = self.get_object()

        if request.POST.get("action") == "cancel":
            batch.status = ImportStatus.CANCELLED
            batch.save(update_fields=["status", "updated_at"])
            messages.info(request, "Import cancelled. Nothing was written.")
            return redirect("finance:imports")

        try:
            commit_batch(batch)
        except ImportError_ as exc:
            messages.error(request, str(exc))
            return redirect("finance:import_preview", pk=batch.pk)

        messages.success(
            request,
            f"Imported {batch.created_count} rows from {batch.original_filename}. "
            f"{batch.duplicate_count} were already here.",
        )

        return redirect("finance:imports")
