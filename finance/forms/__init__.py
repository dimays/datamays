"""Every form in the finance app.

One module per subject rather than forms living inside the view modules that
happen to render them: a form is reusable and independently testable, and
several of these (AccountForm, CategoryForm) are used by more than one view.

Re-exported here so callers import from `finance.forms` regardless of which
module a form lives in.
"""

from .accounts import AccountForm, BalanceUpdateForm, ManualAccountForm
from .alerts import AlertForm, ReportForm
from .auth import FinanceLoginForm, OTPTokenForm
from .base import StyledFormMixin, style_widget
from .budgets import BudgetForm
from .categories import CategoryForm
from .connections import ConnectionForm
from .imports import UploadForm
from .institutions import InstitutionForm
from .preferences import PreferencesForm
from .rules import RuleForm
from .widgets import (
    AUTH_FIELD_CLASSES,
    CHECKBOX_CLASSES,
    FIELD_CLASSES,
    OTP_FIELD_CLASSES,
)

__all__ = [
    "AUTH_FIELD_CLASSES",
    "CHECKBOX_CLASSES",
    "FIELD_CLASSES",
    "OTP_FIELD_CLASSES",
    "AccountForm",
    "AlertForm",
    "BalanceUpdateForm",
    "BudgetForm",
    "CategoryForm",
    "ConnectionForm",
    "FinanceLoginForm",
    "InstitutionForm",
    "ManualAccountForm",
    "OTPTokenForm",
    "PreferencesForm",
    "ReportForm",
    "RuleForm",
    "StyledFormMixin",
    "UploadForm",
    "style_widget",
]
