from django import forms
from django.contrib.auth.forms import AuthenticationForm

FIELD_CLASSES = (
    "w-full rounded-button border border-border bg-background px-4 py-3 "
    "text-text-primary placeholder:text-text-muted focus:outline-none "
    "focus:ring-2 focus:ring-primary"
)

OTP_FIELD_CLASSES = (
    "w-full rounded-button border border-border bg-background px-4 py-3 "
    "text-center font-mono text-2xl tracking-[0.4em] text-text-primary "
    "focus:outline-none focus:ring-2 focus:ring-primary"
)


class FinanceLoginForm(AuthenticationForm):
    """Styled login form. Authentication behavior is Django's."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.fields["username"].widget.attrs.update(
            {
                "class": FIELD_CLASSES,
                "placeholder": "Username",
                "autocomplete": "username",
                "autofocus": True,
            }
        )
        self.fields["password"].widget.attrs.update(
            {
                "class": FIELD_CLASSES,
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
