"""Sign-in and second-factor forms.

Deliberately not using StyledFormMixin: these are the only screens rendered
signed-out, on an otherwise empty page, and they use the roomier auth sizing
rather than the app's compact in-app fields.
"""

from django import forms
from django.contrib.auth.forms import AuthenticationForm

from .widgets import AUTH_FIELD_CLASSES, OTP_FIELD_CLASSES


class FinanceLoginForm(AuthenticationForm):
    """Styled login form. Authentication behavior is Django's."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["username"].widget.attrs.update(
            {
                "class": AUTH_FIELD_CLASSES,
                "placeholder": "Username",
                "autocomplete": "username",
                "autofocus": True,
            }
        )
        self.fields["password"].widget.attrs.update(
            {
                "class": AUTH_FIELD_CLASSES,
                "placeholder": "Password",
                "autocomplete": "current-password",
            }
        )


class OTPTokenForm(forms.Form):
    """A six-digit TOTP code.

    inputmode="numeric" and autocomplete="one-time-code" are what make this
    bearable on a phone: iOS offers the code from the authenticator app
    directly above the keyboard.
    """

    token = forms.CharField(
        label="Authentication code",
        max_length=6,
        min_length=6,
        widget=forms.TextInput(
            attrs={
                "class": OTP_FIELD_CLASSES,
                "placeholder": "000000",
                "inputmode": "numeric",
                "pattern": "[0-9]*",
                "autocomplete": "one-time-code",
                "autofocus": True,
            }
        ),
    )

    def clean_token(self):
        token = self.cleaned_data["token"].strip().replace(" ", "")

        if not token.isdigit():
            raise forms.ValidationError("Codes are six digits.")

        return token
