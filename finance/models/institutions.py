from django.conf import settings
from django.db import models
from django.utils import timezone

from ..crypto import EncryptedTextField
from .base import TimestampedModel


class Provider(models.TextChoices):
    SIMPLEFIN = "simplefin", "SimpleFIN Bridge"
    CSV = "csv", "CSV import"
    MANUAL = "manual", "Manual entry"


class Institution(TimestampedModel):
    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=140, unique=True)
    provider = models.CharField(
        max_length=20,
        choices=Provider.choices,
        default=Provider.SIMPLEFIN,
        help_text="How data from this institution normally arrives.",
    )
    website = models.URLField(blank=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(
        blank=True,
        help_text="Anything worth remembering — statement quirks, login oddities.",
    )

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class ConnectionStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    NEEDS_REAUTH = "needs_reauth", "Needs re-authorization"
    ERROR = "error", "Error"
    DISABLED = "disabled", "Disabled"


class AccountConnection(TimestampedModel):
    """An authorized link to an institution.

    For SimpleFIN, `access_secret` holds the Access URL, which embeds HTTP
    Basic credentials — hence the encrypted field. It is read-only by
    construction: the credential cannot move money, only list accounts and
    transactions.
    """

    institution = models.ForeignKey(
        Institution, on_delete=models.CASCADE, related_name="connections"
    )
    label = models.CharField(
        max_length=120,
        help_text="How this connection appears in settings, e.g. 'Byline (joint)'.",
    )
    provider = models.CharField(
        max_length=20, choices=Provider.choices, default=Provider.SIMPLEFIN
    )

    access_secret = EncryptedTextField(
        blank=True,
        help_text="Encrypted at rest. Never rendered in full, never logged.",
    )

    status = models.CharField(
        max_length=20, choices=ConnectionStatus.choices, default=ConnectionStatus.ACTIVE
    )
    last_synced_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="finance_connections",
    )

    class Meta:
        ordering = ["institution__name", "label"]

    def __str__(self):
        return f"{self.institution.name} — {self.label}"

    @property
    def is_syncable(self):
        # ERROR is included deliberately: it usually means a timeout or a
        # provider blip, and refusing to retry would strand the connection
        # permanently after one bad night. NEEDS_REAUTH and DISABLED are
        # excluded because both genuinely require a person.
        return (
            self.status in {ConnectionStatus.ACTIVE, ConnectionStatus.ERROR}
            and self.provider == Provider.SIMPLEFIN
            and bool(self.access_secret)
        )

    def mark_synced(self):
        self.last_synced_at = timezone.now()
        self.last_error = ""
        self.status = ConnectionStatus.ACTIVE
        self.save(update_fields=["last_synced_at", "last_error", "status", "updated_at"])

    def mark_failed(self, message, *, needs_reauth=False):
        self.last_error = str(message)[:2000]
        self.status = (
            ConnectionStatus.NEEDS_REAUTH if needs_reauth else ConnectionStatus.ERROR
        )
        self.save(update_fields=["last_error", "status", "updated_at"])


class SyncStatus(models.TextChoices):
    RUNNING = "running", "Running"
    SUCCESS = "success", "Success"
    PARTIAL = "partial", "Partial"
    FAILED = "failed", "Failed"


class SyncTrigger(models.TextChoices):
    SCHEDULE = "schedule", "Scheduled"
    MANUAL = "manual", "Manual"


class SyncRun(models.Model):
    """One attempt at pulling data, kept so failures are visible after the fact.

    Without this the scheduler fails silently and the dashboards quietly go
    stale, which is the worst way for a finance app to be wrong.
    """

    connection = models.ForeignKey(
        AccountConnection,
        on_delete=models.CASCADE,
        related_name="sync_runs",
        null=True,
        blank=True,
    )
    trigger = models.CharField(
        max_length=20, choices=SyncTrigger.choices, default=SyncTrigger.SCHEDULE
    )
    status = models.CharField(
        max_length=20, choices=SyncStatus.choices, default=SyncStatus.RUNNING
    )

    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)

    accounts_synced = models.PositiveIntegerField(default=0)
    transactions_created = models.PositiveIntegerField(default=0)
    transactions_updated = models.PositiveIntegerField(default=0)

    error_message = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at"]
        indexes = [models.Index(fields=["-started_at"])]

    def __str__(self):
        target = self.connection or "all connections"
        return f"{target} @ {self.started_at:%Y-%m-%d %H:%M} ({self.status})"

    @property
    def duration_seconds(self):
        if not self.finished_at:
            return None
        return (self.finished_at - self.started_at).total_seconds()

    def finish(self, status, *, error=""):
        self.status = status
        self.error_message = str(error)[:2000]
        self.finished_at = timezone.now()
        self.save(
            update_fields=[
                "status",
                "error_message",
                "finished_at",
                "accounts_synced",
                "transactions_created",
                "transactions_updated",
            ]
        )
