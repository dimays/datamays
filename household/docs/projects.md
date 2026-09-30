# Projects

Longer-term shared house projects: a kitchen refresh, a garden, a
basement. The Projects section in the nav.

## What a project holds

| | |
|---|---|
| **Status** | In progress, Planned, Idea, On hold, Done. The list groups by it, in that order. |
| **Dates** | An optional start and target. |
| **Budget** | An overall figure for now; budget lines and spending linked from finance arrive with the finance bridge. |
| **Milestones** | Named steps with an optional target date, ticked done in place. |
| **Links** | Documents that live elsewhere — a Drive folder, a quote, a mood board. Only `http`, `https`, or `ftp` addresses are accepted, because each is rendered as a clickable link. |
| **Notes & decisions** | A running log, newest first. Only a note's author can remove it: the log is shared, the words are theirs. |
| **Tasks** | Chores — see below. |

Everything in a project is shared: both of you manage it all (ADR 0011).

## Tasks are chores

A task is a `Chore` with `project` set (and optionally `milestone`). It is
household-owned, so both of you manage it; its **assignee decides whose
checklist it lands on**. That is the entire mechanism behind "assigned
tasks become chores" — a task appears on the assignee's checklist, on
Today, and in the overdue badge exactly like any other chore, with every
scheduling rule available (most tasks are one-offs; "water the seedlings
daily for two weeks" works too).

A task is created and edited from its project (`projects/<pk>/tasks/…`),
where the milestone choice lives; the generic chore edit page redirects
there. Its detail page is the ordinary chore page, which names the project.

A milestone must belong to the task's own project (`Chore.clean`).
Deleting a milestone keeps its tasks in the project; deleting a project
deletes its tasks, taking them off every checklist.

## Progress

Counted two ways, because a project may have either:

- **milestones done / milestones set**, and
- **tasks done / tasks created**, where a task is done when nothing is left
  open and at least one occurrence was done — a finished one-off, or a
  repeating task whose run has ended. A repeating task still running is not
  done.

The bar shows milestones when there are any (they are the plan), tasks
otherwise. Both counts are computed in the same query as the project list
(`services/projects.py::with_progress`), so the list and Today cost the same
however many projects and tasks exist — tested.

## The timeline

`services/projects.py::timeline` — the start, each dated milestone, today,
and the target, in date order, as a vertical line that reads on a phone at
any length. A milestone past its date and not done is **late** (red); so is
the target of a project not marked Done. Today is placed only on a timeline
it falls inside. Undated milestones follow under "No date yet" rather than
being left off.

## On Today

Projects in progress appear on Today above the budget widget: each with its
next milestone — or, louder, how many milestones are past their date — and
its progress bar.
