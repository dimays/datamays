# 0011 — Chores are owner-managed; either person may mark one done

**Status:** accepted
**Reverse cost:** low — one module decides, one table test checks

## Context

The ask: per-person checklists, visible to both "under a toggle", where
"each user can only manage their own chores unless granted explicit
permission". Two questions were left open and settled with David on
2026-09-30:

1. Does marking the other person's chore done count as managing it?
2. What about shared household work — maintenance, project tasks?

## Decision

- **Seeing** is open to both, with the other person's list behind a
  remembered toggle.
- **Marking done** is open to both — "I took the trash out for you" — with a
  confirmation dialog when the chore is on the other person's list. The
  occurrence records who actually did it.
- **Managing** (edit, skip, pause, delete) belongs to the owner, or to both
  when the owner ticks a per-chore grant. Each person picks a default for
  new chores.
- **Household-owned chores** have no owner and are managed by both, always.
- **Undo** belongs to whoever did it, or to anyone who could manage it.

All of it lives in `household/services/permissions.py`.

## Why a per-chore grant rather than a per-person one

A blanket "Maddie can manage all my chores" is expressible as a default for
new chores, and a per-chore flag still lets one chore be private. The
reverse — a blanket grant with per-chore exceptions — is the same power with
a more confusing model.

## Why the confirmation is not enforced on the server

Completing someone else's chore is *allowed*; the dialog exists to catch a
mis-tap on a phone, not to stop anyone. Requiring a server-side "confirmed"
token would add a failure mode (a stale page, a disabled script) without
protecting anything.

## Consequences

- `tests/test_permissions.py` checks every action against every case through
  the real endpoints.
- Buttons a person can't use aren't drawn, but every endpoint still asks the
  service; the template is a convenience, the service is the rule.
