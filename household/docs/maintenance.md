# Maintenance ("Upkeep")

Shared home maintenance: filters, detectors, the outdoor faucets before a
freeze, deep cleans. The Upkeep section in the nav.

## How it is built

A **maintenance item** (`models/maintenance.py`) is the definition — area,
location, instructions, supplies, where to buy them, what it usually costs.
It **owns one household chore** (a one-to-one), and that chore carries
everything else: the name, the schedule, whose list it lands on, and the
history.

That split is the whole design. Because maintenance *is* a chore:

- it appears on Today, the checklists, and the Chores badge with no
  special-casing;
- every scheduling rule — fixed vs. after-completion, missed vs. overdue,
  seasons, deadlines — is the chores' rule
  ([scheduling.md](scheduling.md));
- permissions are the household-chore rule: both of you manage every item
  ([permissions.md](permissions.md)).

The chore's own pages (`/household/chores/<pk>/…`) redirect a maintenance
chore to its Upkeep pages, where the instructions and costs live alongside
the schedule. A row on any checklist links there directly
(`Chore.get_absolute_url`).

## Logging a job

The item page's **Mark done** posts to the same occurrence endpoint as a
checklist tick, with two extra fields: what it cost and a note. The cost is
validated as money (`forms/maintenance.py::LogCompletionForm`, the same form
the endpoint uses for every completion) and stored on the occurrence
(`Occurrence.cost`, a `Decimal`, positive). A bad amount changes nothing and
says so.

The history lists each time with who did it, the cost, and the note, and
totals spend by *household* year — a job done at 10:30pm on New Year's Eve
in Chicago counts for the old year.

Linking a logged cost to the real finance transaction, and projecting
upcoming maintenance costs, arrive with the finance-bridge phase.

## The starter list

`household/maintenance_library.py` — eleven common, generic jobs to adopt
with one tap and adjust afterwards. Short on purpose (the decision was to
start simple) and generic on purpose (the repository is public; this house's
details belong in the database).

Adopting an entry (`services/maintenance.py::adopt`) creates the chore and
the item and opens the first occurrence. Dates are month/day pairs resolved
to the **soonest date in the cycle** from today: "every six months from
April 30", adopted in September, starts October 30. An entry disappears from
the list once an item with its name exists.

To add an entry: append a `LibraryEntry`. `tests/test_maintenance.py`
adopts every entry and validates the resulting schedule, so a bad one fails
the suite.

## Screens

See [screens.md](screens.md#upkeep). The list shows everything overdue or
due in the next 30 days first — overdue first, then by due date — then every
item grouped by area.
