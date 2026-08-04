"""Admin registrations.

A deliberate safety net rather than the primary interface: when a sync goes
sideways or a category needs surgery, this is where it gets fixed. Money
fields are read-only where a stray edit would silently corrupt history.
"""

from django.contrib import admin

from .models import (
    Account,
    AccountBalanceSnapshot,
    AccountConnection,
    Alert,
    AlertEvent,
    Budget,
    BudgetPeriod,
    Category,
    CategoryRule,
    ImportBatch,
    ImportMapping,
    ImportRow,
    Institution,
    MerchantCategoryMemo,
    Paycheck,
    PaycheckDeduction,
    QuarterlyReport,
    ScheduledReport,
    SyncRun,
    Transaction,
    UserPreference,
)


@admin.register(Institution)
class InstitutionAdmin(admin.ModelAdmin):
    list_display = ["name", "provider", "owner", "is_active"]
    list_filter = ["provider", "owner", "is_active"]
    search_fields = ["name"]
    prepopulated_fields = {"slug": ["name"]}


@admin.register(AccountConnection)
class AccountConnectionAdmin(admin.ModelAdmin):
    list_display = ["label", "institution", "status", "last_synced_at"]
    list_filter = ["status", "provider", "institution"]
    # access_secret is deliberately absent from every list, form, and search:
    # it decrypts on access, and the admin is not a place to render credentials.
    exclude = ["access_secret"]
    readonly_fields = ["last_synced_at", "last_error", "created_at", "updated_at"]


@admin.register(SyncRun)
class SyncRunAdmin(admin.ModelAdmin):
    list_display = [
        "started_at",
        "connection",
        "status",
        "accounts_synced",
        "transactions_created",
        "transactions_updated",
    ]
    list_filter = ["status", "trigger"]
    readonly_fields = [field.name for field in SyncRun._meta.fields]
    date_hierarchy = "started_at"

    def has_add_permission(self, request):
        return False


class BalanceSnapshotInline(admin.TabularInline):
    model = AccountBalanceSnapshot
    extra = 0
    max_num = 10
    ordering = ["-as_of"]
    readonly_fields = ["created_at"]


@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display = [
        "name",
        "institution",
        "account_type",
        "owner",
        "mask",
        "current_balance",
        "is_active",
    ]
    list_filter = ["account_type", "owner", "institution", "is_active", "include_in_net_worth"]
    search_fields = ["name", "official_name", "mask"]
    readonly_fields = ["balance_as_of", "created_at", "updated_at"]
    inlines = [BalanceSnapshotInline]


@admin.register(AccountBalanceSnapshot)
class AccountBalanceSnapshotAdmin(admin.ModelAdmin):
    list_display = ["account", "as_of", "current", "available", "source"]
    list_filter = ["source", "account"]
    date_hierarchy = "as_of"


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ["full_path", "kind", "is_system", "is_active", "sort_order"]
    list_filter = ["kind", "is_system", "is_active"]
    search_fields = ["name", "slug"]
    prepopulated_fields = {"slug": ["name"]}

    def has_delete_permission(self, request, obj=None):
        # System categories are referenced by slug in code.
        return not (obj and obj.is_system)


@admin.register(CategoryRule)
class CategoryRuleAdmin(admin.ModelAdmin):
    list_display = ["pattern", "match_type", "category", "account", "priority", "is_active"]
    list_filter = ["match_type", "is_active", "category"]
    search_fields = ["pattern", "notes"]


@admin.register(MerchantCategoryMemo)
class MerchantCategoryMemoAdmin(admin.ModelAdmin):
    list_display = ["merchant_key", "category", "hit_count", "last_used_at"]
    search_fields = ["merchant_key"]
    list_filter = ["category"]


@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = [
        "posted_on",
        "account",
        "description_raw",
        "amount",
        "category",
        "category_source",
        "needs_review",
        "is_transfer",
    ]
    list_filter = [
        "needs_review",
        "is_transfer",
        "category_source",
        "source",
        "account",
        "category",
    ]
    search_fields = ["description_raw", "merchant", "provider_txn_id"]
    date_hierarchy = "posted_on"
    list_select_related = ["account", "category"]
    # Identity fields: editing these would break deduplication on the next sync.
    readonly_fields = ["fingerprint", "provider_txn_id", "created_at", "updated_at"]
    raw_id_fields = ["transfer_pair", "import_batch"]


class BudgetPeriodInline(admin.TabularInline):
    model = BudgetPeriod
    extra = 0
    max_num = 12
    ordering = ["-period_start"]
    readonly_fields = ["computed_at"]


@admin.register(Budget)
class BudgetAdmin(admin.ModelAdmin):
    list_display = ["name", "amount", "period_type", "owner", "is_active"]
    list_filter = ["period_type", "is_active", "owner"]
    filter_horizontal = ["categories", "accounts"]
    inlines = [BudgetPeriodInline]


@admin.register(BudgetPeriod)
class BudgetPeriodAdmin(admin.ModelAdmin):
    list_display = [
        "budget",
        "period_start",
        "period_end",
        "target_amount",
        "actual_amount",
    ]
    list_filter = ["budget"]
    date_hierarchy = "period_start"


class PaycheckDeductionInline(admin.TabularInline):
    model = PaycheckDeduction
    extra = 1


@admin.register(Paycheck)
class PaycheckAdmin(admin.ModelAdmin):
    list_display = ["pay_date", "user", "employer", "gross", "net", "reconciles"]
    list_filter = ["user", "employer"]
    date_hierarchy = "pay_date"
    inlines = [PaycheckDeductionInline]

    @admin.display(boolean=True, description="Balances")
    def reconciles(self, obj):
        return obj.reconciles


@admin.register(ImportMapping)
class ImportMappingAdmin(admin.ModelAdmin):
    list_display = ["name", "institution", "record_type", "times_used", "last_used_at"]
    list_filter = ["record_type", "institution"]


class ImportRowInline(admin.TabularInline):
    model = ImportRow
    extra = 0
    max_num = 25
    readonly_fields = ["row_number", "raw", "parsed", "status", "error_message"]

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(ImportBatch)
class ImportBatchAdmin(admin.ModelAdmin):
    list_display = [
        "original_filename",
        "institution",
        "record_type",
        "status",
        "row_count",
        "created_count",
        "duplicate_count",
        "error_count",
        "created_at",
    ]
    list_filter = ["status", "record_type", "institution"]
    readonly_fields = ["detected_headers", "sample_rows", "suggested_map", "raw_content", "created_at"]
    inlines = [ImportRowInline]


@admin.register(UserPreference)
class UserPreferenceAdmin(admin.ModelAdmin):
    list_display = ["user", "recent_transaction_count"]


class AlertEventInline(admin.TabularInline):
    model = AlertEvent
    extra = 0
    max_num = 20
    readonly_fields = ["triggered_at", "observed_value", "message", "was_delivered"]

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Alert)
class AlertAdmin(admin.ModelAdmin):
    list_display = ["name", "user", "kind", "comparison", "threshold", "is_active", "last_triggered_at"]
    list_filter = ["kind", "is_active", "user"]
    inlines = [AlertEventInline]


@admin.register(ScheduledReport)
class ScheduledReportAdmin(admin.ModelAdmin):
    list_display = ["name", "user", "cadence", "send_day", "is_active", "last_sent_at"]
    list_filter = ["cadence", "is_active", "user"]


@admin.register(QuarterlyReport)
class QuarterlyReportAdmin(admin.ModelAdmin):
    list_display = ["label", "period_start", "period_end", "narrator", "generated_at"]
    list_filter = ["year", "narrator"]
    # Generated by the management command, not hand-edited — metrics and
    # comparisons in particular would be misleading if tweaked without
    # regenerating the narrative that was written to match them.
    readonly_fields = [
        "year", "quarter", "period_start", "period_end", "metrics",
        "comparisons", "narrator", "generated_at",
    ]

    def has_add_permission(self, request):
        return False
