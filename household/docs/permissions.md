# Permissions

Who may do what to a chore. Decided in one module,
`household/services/permissions.py`; every view and every htmx endpoint
asks it. The decision record is
[ADR 0011](../../docs/architecture/decisions/0011-chore-permissions.md).

Everything below assumes the visitor already passed the household gate
(signed in, a member, second factor cleared). An outsider never reaches a
chore at all — see [architecture.md](architecture.md#sign-in-and-the-access-gate).

## The matrix

| Action | Owner | Other person | Other person, owner granted | Household-owned chore |
|---|---|---|---|---|
| See it | ✓ | ✓ (behind the toggle) | ✓ | ✓ |
| Mark it done | ✓ | ✓ **after a confirmation** | ✓ after a confirmation | ✓ |
| Skip it | ✓ | — | ✓ | ✓ |
| Edit, pause | ✓ | — | ✓ | ✓ |
| Delete | ✓ | — | ✓ | ✓ |
| Undo a done/skip | ✓ | only if they did it | ✓ | ✓ |

- **The grant** is the per-chore "Let the other person manage this chore"
  box. Each person sets a default for new chores in preferences.
- **Household-owned** chores (no owner — "Shared household chore" on the
  form, and later maintenance items and project tasks) are shared work:
  either person manages them, always.
- **Marking done** is open to both so that "I took the trash out for you" is
  one tap. The occurrence records who actually did it.

## The confirmation is courtesy, not a guard

A row on someone else's checklist carries `hx-confirm`, and the app's
dialog (`household/base.html`) asks "Mark Maddie's 'Walk the dog' as
done?" before sending. The server does not check that the question was
asked — completing is allowed either way. It is there to prevent a
mistaken tap, not to enforce anything.

"Someone else's" means the chore's **assignee** is the other person, whoever
owns it: a household chore assigned to Maddie asks David first; one assigned
to "either of us" does not.

## Seeing each other's lists

Your checklist and Today show your chores and the shared ones. "Show
Maddie's chores" (a switch on both screens, remembered per person in
`HouseholdPreference.show_partner_chores`) adds hers — on the checklist in
full, on Today just her overdue and due-today items.

## Tested as a table

`tests/test_permissions.py` drives every action × case above through the
real endpoints, so a view that forgets to ask the service fails even though
the service itself is right. Refused actions return 403 and change nothing.
