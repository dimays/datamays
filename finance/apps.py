from django.apps import AppConfig


class FinanceConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "finance"
    verbose_name = "Household Finance"

    def ready(self):
        from . import checks  # noqa: F401  (registers system checks)
