"""Access control for the finance app.

Every finance view must inherit from FinanceAccessMixin. The gate is
deliberately a hard PermissionDenied rather than a redirect to a login page:
an unauthenticated visitor should not learn that a login form exists here, let
alone what it protects.

The finance/auth branch replaces the stock 403 with the household's own page
and adds group membership plus TOTP checks.
"""

from django.core.exceptions import PermissionDenied


class FinanceAccessMixin:
    def dispatch(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            raise PermissionDenied

        return super().dispatch(request, *args, **kwargs)
