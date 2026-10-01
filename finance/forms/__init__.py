"""Every form in the finance app.

One module per subject rather than forms living inside the view modules that
happen to render them: a form is reusable and independently testable, and
several of these (AccountForm, CategoryForm) are used by more than one view.

Re-exported here so callers import from `finance.forms` regardless of which
module a form lives in. The shared field styling (`StyledFormMixin`) and the
sign-in forms belong to the household shell, in `household/forms/`.
"""

from .accounts import AccountForm, BalanceUpdateForm, ManualAccountForm
from .alerts import AlertForm, ReportForm
from .budgets import BudgetForm
from .categories import CategoryForm
from .connections import ConnectionForm
from .imports import UploadForm
from .institutions import InstitutionForm
from .preferences import PreferencesForm
from .rules import RuleForm

__all__ = [
    "AccountForm",
    "AlertForm",
    "BalanceUpdateForm",
    "BudgetForm",
    "CategoryForm",
    "ConnectionForm",
    "InstitutionForm",
    "ManualAccountForm",
    "PreferencesForm",
    "ReportForm",
    "RuleForm",
    "UploadForm",
]
