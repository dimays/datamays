"""The app's form field styling, in one place.

These class strings used to be copy-pasted into four view modules and then
hand-applied to sixty-eight individual widgets. Both halves of that were a
liability: a styling change meant finding every copy, and a form that forgot
the `attrs={"class": ...}` on one field rendered that field unstyled with
nothing to catch it.

Applying them is `StyledFormMixin`'s job (see base.py) — a form should only
name a widget when it needs a *non-class* attribute.
"""

# The default: every text input, select, textarea, and date picker on a
# settings/CRUD screen.
FIELD_CLASSES = (
    "w-full rounded-button border border-border bg-background px-3 py-2 text-sm "
    "text-text-primary focus:outline-none focus:ring-2 focus:ring-primary"
)

CHECKBOX_CLASSES = (
    "h-4 w-4 rounded border-border bg-background text-primary focus:ring-primary"
)

# Roomier, for the signed-out screens — login and TOTP are a single centred
# card on an otherwise empty page, where the compact in-app sizing reads as
# cramped rather than dense.
AUTH_FIELD_CLASSES = (
    "w-full rounded-button border border-border bg-background px-4 py-3 "
    "text-text-primary placeholder:text-text-muted focus:outline-none "
    "focus:ring-2 focus:ring-primary"
)

# One six-digit code, spaced out so it reads as digits to be checked against
# a phone rather than as ordinary text.
OTP_FIELD_CLASSES = (
    "w-full rounded-button border border-border bg-background px-4 py-3 "
    "text-center font-mono text-2xl tracking-[0.4em] text-text-primary "
    "focus:outline-none focus:ring-2 focus:ring-primary"
)
