"""Connecting an institution through a provider."""

from django import forms

from .base import StyledFormMixin


class ConnectionForm(StyledFormMixin, forms.Form):
    """Step one of adding an integration: authenticate.

    No institution field — a single SimpleFIN setup token can cover more than
    one real institution (that's how SimpleFIN Bridge itself works), so which
    institution each discovered account belongs to is resolved automatically
    during sync from the provider's own data, not chosen up front here.
    """

    label = forms.CharField(
        label="Name this connection",
        max_length=120,
        required=False,
        widget=forms.TextInput(attrs={"placeholder": "Byline + Capital One (joint)"}),
        help_text="However you want to recognize this in Settings — it can cover more than one institution.",
    )
    setup_token = forms.CharField(
        label="SimpleFIN setup token",
        widget=forms.Textarea(
            attrs={
                "rows": 4,
                "placeholder": "Paste the token from bridge.simplefin.org",
                # Never let a browser or password manager retain a bearer
                # credential from this box.
                "autocomplete": "off",
                "spellcheck": "false",
            }
        ),
        help_text="Single use — SimpleFIN will refuse a token that has already been claimed.",
    )
