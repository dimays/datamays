"""Forms owned by the household shell.

`StyledFormMixin` gives every form in every section the same field styling;
finance's forms use it too. The sign-in forms live here because sign-in
belongs to the shell (ADR 0008).
"""

from .auth import LoginForm, OTPTokenForm
from .base import StyledFormMixin, style_widget
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
    "LoginForm",
    "OTPTokenForm",
    "StyledFormMixin",
    "style_widget",
]
