"""Who may do what to a chore — decided here and nowhere else.

The rules, agreed on 2026-09-30 (ADR 0011):

- **See:** both of you see both lists (the other's behind a toggle).
- **Complete:** either of you may mark either's chore done — the "I took the
  trash out for you" case. The occurrence records who actually did it. The
  screen asks for confirmation first when it is the other person's chore;
  that dialog is courtesy, not a guard, so it is not checked here.
- **Manage** (edit, skip, pause, delete): the owner, or anyone when the owner
  has ticked "let the other person manage this". Household-owned chores —
  shared work, and later maintenance and project tasks — are manageable by
  both, always.
- **Undo:** whoever marked it done, or anyone who could manage it.

Everything here assumes the caller already passed the household gate; an
outsider never gets this far.
"""


def can_view(user, chore):
    return True


def can_complete(user, chore):
    return True


def can_manage(user, chore):
    return chore.owner_id is None or chore.owner_id == user.pk or chore.others_can_manage


def can_undo(user, occurrence):
    return occurrence.completed_by_id == user.pk or can_manage(user, occurrence.chore)


def needs_confirmation(user, chore):
    """Completing this puts a tick on someone else's checklist."""
    return chore.assignee_id is not None and chore.assignee_id != user.pk
