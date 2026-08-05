# Screens

Every URL in the app, its view, and its template. Generated from
`finance/urls.py` — if this drifts, that file is the truth.

All paths are relative to `/finance/`. Every view is gated (authenticated →
`finance` group → TOTP verified) except the auth screens themselves.

## Daily use

| Path | View | Template |
|---|---|---|
| `/` | `HomeView` | `home.html` |
| `transactions/` | `TransactionListView` | `transactions/list.html` |
| `charts/` | `ChartsView` | `dashboards/charts.html` |
| `qfrs/` | `QFRListView` | `qfr/list.html` |
| `qfrs/<pk>/` | `QFRDetailView` | `qfr/detail.html` |

**Home** renders whichever widgets the person selected, in the order they
arranged them (`UserPreference`). Widget definitions are in
`services/widgets.py`.

**Activity** is the app's junction box. Every "show me what's behind this
number" click lands here — a budget row on the homepage, a bar in a spend
chart — carrying `budget=`, `start=`/`end=`, or `spend=1` rather than
duplicating filter logic at the call site. Filters combine the way faceted
filters normally do: OR within a filter, AND between them.

**Charts** draws user-selectable, user-reorderable sections. Adding one is
documented in [`extending.md`](extending.md).

## Budgets

| Path | View | Template |
|---|---|---|
| `budgets/` | `BudgetListView` | `budgets/list.html` |
| `budgets/new/` | `BudgetCreateView` | `budgets/form.html` |
| `budgets/<pk>/` | `BudgetUpdateView` | `budgets/form.html` |
| `budgets/<pk>/delete/` | `BudgetDeleteView` | `budgets/confirm_delete.html` |

The list leads with **pace**, not raw attainment: 80% through a grocery budget
is fine on the 25th and alarming on the 8th.

Creating a budget backfills its history, so it arrives with a chart rather than
an empty one. Editing re-rolls the current period, since categories or accounts
may have changed.

## Imports

| Path | View | Template |
|---|---|---|
| `imports/` | `ImportListView` | `imports/list.html` |
| `imports/schemas/` | `ImportSchemaView` | `imports/schemas.html` |
| `imports/new/` | `ImportUploadView` | `imports/upload.html` |
| `imports/<pk>/columns/` | `ImportMapView` | `imports/map.html` |
| `imports/<pk>/review/` | `ImportPreviewView` | `imports/preview.html` |

Three screens rather than one, because the mapping step is the whole point.
`schemas/` is read-only reference: what a file needs to look like per record
type.

## Settings — household-wide

Changes here affect what both people see.

| Path | View | Template |
|---|---|---|
| `settings/` | `SettingsHomeView` | `settings/index.html` |
| `settings/institutions/` | `InstitutionListView` | `settings/institutions.html` |
| `settings/institutions/new/` | `InstitutionCreateView` | `settings/institution_form.html` |
| `settings/institutions/<pk>/` | `InstitutionUpdateView` | `settings/institution_form.html` |
| `settings/connections/new/` | `ConnectionCreateView` | `settings/connection_form.html` |
| `settings/connections/<pk>/` | `ConnectionDetailView` | `settings/connection_detail.html` |
| `settings/accounts/new/` | `AccountCreateView` | `settings/account_form.html` |
| `settings/accounts/<pk>/` | `AccountUpdateView` | `settings/account_form.html` |
| `settings/rules/` | `RuleListView` | `settings/rules.html` |
| `settings/rules/new/` | `RuleCreateView` | `settings/rule_form.html` |
| `settings/categories/` | `CategoryListView` | `settings/categories.html` |
| `settings/categories/new/` | `CategoryCreateView` | `settings/category_form.html` |
| `settings/categories/<pk>/` | `CategoryUpdateView` | `settings/category_form.html` |
| `settings/categories/<pk>/delete/` | `CategoryDeleteView` | `settings/category_delete.html` |

**Connecting** authenticates and immediately test-syncs — a connection that
cannot pull is not really connected, and finding out now beats finding out when
a dashboard is silently empty.

**Deleting a category** requires choosing where its transactions go. See the
cascade table in [`data-model.md`](data-model.md).

## Personal — one household member only

| Path | View | Template |
|---|---|---|
| `preferences/` | `PreferencesView` | `settings/preferences.html` |
| `alerts/` | `AlertListView` | `alerts/list.html` |
| `alerts/new/` | `AlertCreateView` | `alerts/form.html` |
| `alerts/<pk>/` | `AlertUpdateView` | `alerts/form.html` |
| `alerts/<pk>/delete/` | `AlertDeleteView` | `alerts/confirm_delete.html` |
| `reports/new/` | `ReportCreateView` | `alerts/report_form.html` |
| `reports/<pk>/` | `ReportUpdateView` | `alerts/report_form.html` |

Every one of these uses `PersonalObjectMixin`. Neither person ever sees the
other's thresholds.

## Auth and help

| Path | View | Template |
|---|---|---|
| `login/` | `FinanceLoginView` | `login.html` |
| `logout/` | `FinanceLogoutView` | — redirects to the public site |
| `two-factor/setup/` | `OTPSetupView` | `otp_setup.html` |
| `two-factor/` | `OTPVerifyView` | `otp_verify.html` |
| `help/` | `HelpView` | `help.html` |

The two TOTP screens use `PageTitleMixin` + `HouseholdMemberMixin` rather than
the full gate — they need a title but must not require a cleared second
factor, since they are how you clear it.

**`help.html` is the user-facing documentation.** When a screen's behavior
changes in a way a user would notice, update it.
