# Screens

Every household URL, its view, and its template. `household/urls.py` is the
truth if this drifts. Paths are relative to `/household/`; templates to
`household/templates/household/`.

## Sign-in

| Path | View | Template | Gate |
|---|---|---|---|
| `login/` | `HouseholdLoginView` | `login.html` | none |
| `logout/` | `HouseholdLogoutView` | — POST only, then the public site | none |
| `two-factor/setup/` | `OTPSetupView` | `otp_setup.html` | member, not yet verified |
| `two-factor/` | `OTPVerifyView` | `otp_verify.html` | member, not yet verified |

The two TOTP screens use `PageTitleMixin` + `HouseholdMemberMixin` rather
than the full gate — they need a title but cannot require a cleared second
factor, since they are how you clear it.

The pre-shell paths `/finance/login/`, `/finance/two-factor/`, and
`/finance/two-factor/setup/` redirect here, keeping any `?next=`.

## Sections

| Path | View | Template |
|---|---|---|
| `` (root) | `TodayView` | `today.html` |

Everything below this line is behind the full gate.

## Shared templates

| Template | Used for |
|---|---|
| `base.html` | Page chrome for every private page, finance included |
| `base_auth.html` | The signed-out screens: sign-in, 403, lockout |
| `403.html` | The one 403 for `/household` and `/finance` |
| `lockout.html` | Shown by django-axes after repeated failed sign-ins |
| `partials/header.html` | Brand, section links, account menu |
| `partials/nav_bottom.html` | The phone's section tab bar |
| `partials/section_nav.html` | A section's own screens as a pill strip |
| `partials/messages.html` | Flash messages |
