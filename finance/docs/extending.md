# Making changes

Step-by-step for the changes most likely to come up. Each is written as "these
are the files you touch," because the hard part is usually knowing that rather
than the code itself.

Run the suite with `--settings=datamays.settings_test` after each. Always.

---

## Add a chart to the Charts tab

1. **Write the aggregation** in `services/analytics.py`. Return a plain dict of
   labels and series — no rendering, no request. This is the part that gets
   tested.

2. **Register the section** in `finance/chart_sections.py`:

   ```python
   ChartSection("my_slug", "My chart", "One line saying what it shows."),
   ```

   Title and blurb live here, not in the template.

3. **Add the template** at `templates/finance/dashboards/sections/my_slug.html`:

   ```
   {% extends "finance/dashboards/_section.html" %}

   {% block body %}
     <div class="mt-4 h-64">
       <canvas data-chart="bar" data-source="my-data"></canvas>
     </div>
     {{ my_data_json|json_script:"my-data" }}
   {% endblock %}
   ```

   Do **not** add a top margin — the container owns spacing between sections,
   because they are user-reorderable. Do **not** add an `{% if %}` guard — step
   5 handles that.

   Use `{% block controls %}` for anything that belongs next to "Hide chart".

4. **Feed the context** from `views/dashboards.py`, in the relevant
   `_*_context()` method.

5. **Add the data flag** to `section_has_data` in `ChartsView.get_context_data`.
   This is the single place that decides whether the section renders.

6. **Tests** in `tests/test_dashboards.py` — the analytics function directly,
   plus one assertion that the section appears.

New chart *types* go in `static/js/finance-charts.js`, registered in
`BUILDERS`. Re-run `npm run tailwind:build` if the template uses new classes.

---

## Add an alert kind

`Alert` is one model with a `kind` discriminator. Adding a fifth kind means
exactly three places:

1. A case in `services/alerts.py::observed_value()` — what number this kind
   watches.
2. A case in `build_message()` — how it reads in an email.
3. A validation branch in `Alert.clean()` **only if** the new kind needs its
   own required fields.

`is_breached()` and the cooldown logic are generic. If you find yourself
special-casing either, the new kind probably wants to be expressed differently.

Add the kind to `AlertKind` in `models/prefs.py` and write a migration.

---

## Add a data provider

The point of `providers/` is that this does not touch the sync service.

1. **Write the adapter** in `providers/`, implementing `ProviderAdapter` from
   `base.py`: one method, `fetch()`, returning normalized `AccountPayload` and
   `TransactionPayload` objects.
2. **Normalize signs in the adapter**, not downstream. Money out negative,
   liabilities negative. See
   [ADR 0003](../../docs/architecture/decisions/0003-household-sign-convention.md).
3. **Register it** in `providers/registry.py`.
4. **Add the choice** to `Provider` in `models/institutions.py`, with a
   migration.
5. **Test against mocked HTTP.** No test may reach a real institution.

Nothing in `services/sync.py` should need to change. If it does, the adapter
interface is leaking and that is the thing to fix.

**Read [ADR 0001](../../docs/architecture/decisions/0001-no-stored-bank-credentials.md)
first.** A provider that requires storing a bank username and password is not
an option, regardless of how good its coverage is.

---

## Add a CSV record type

The three record types (transactions, balances, paycheck) are parsed by fixed
logic, not configuration. Adding a fourth:

1. `RecordType` in `models/imports.py`, plus a migration.
2. `REQUIRED_FIELDS`, `OPTIONAL_FIELDS`, `FIELD_LABELS` and
   `RECORD_TYPE_GRAIN` in `views/imports.py`. `RECORD_TYPE_GRAIN` is what the
   `/imports/schemas/` page shows, so a new type documents itself.
3. Parsing and commit branches in `services/importer.py`.
4. Header-detection hints in `services/detection.py` if the columns are not
   obvious.
5. Tests in `tests/test_csv_import.py`, including a malformed file.

---

## Add a homepage widget

1. A builder function in `services/widgets.py`.
2. An entry in `WIDGET_CHOICES` — the slug maps to
   `templates/finance/widgets/<slug>.html`.
3. The template.
4. Add the slug to `DEFAULT_WIDGETS` in `models/prefs.py` if it should be on
   by default.

**Watch out:** `models/prefs.py` holds a second, independent list of default
sections and widgets. A slug added to the choice list but not there — or
retired from one and not the other — is a real bug that has happened before.
`views/settings.py` filters saved preferences down to known slugs
defensively, which is why a retired slug no longer 500s the Preferences page.

---

## Change the category tree

Edit `categories_seed.py`, then:

```bash
uv run python manage.py seed_finance_categories --settings=datamays.settings_test
```

Safe to re-run: matches on slug, never deletes.

**Never change or remove these slugs** — they are referenced directly in code:
`uncategorized`, `transfer-internal`, `transfer-card-payment`.

Deleting a category in production cascades to its rules and memos and unfiles
its transactions. Read the table in [`data-model.md`](data-model.md), and dry-
run the selection before deleting anything.
