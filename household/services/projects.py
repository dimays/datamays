"""Projects: the list, a project's page, and what Today shows.

Progress is counted two ways, because a project may have either: milestones
done of milestones set, and tasks done of tasks created. A task is done when
its chore has no open occurrence and at least one done — a finished one-off,
or a repeating task whose run has ended.
"""

from dataclasses import dataclass
from datetime import date

from django.db.models import Count, Exists, OuterRef, Prefetch, Q

from ..dates import household_today
from ..models import Chore, Milestone, Occurrence, OccurrenceStatus, Project, ProjectStatus
from ..models.projects import STATUS_ORDER
from . import checklist, occurrences


def with_progress(projects):
    """Annotate task counts and prefetch milestones — a fixed query count."""
    open_occurrence = Occurrence.objects.filter(chore=OuterRef("pk"), status=OccurrenceStatus.OPEN)
    done_occurrence = Occurrence.objects.filter(chore=OuterRef("pk"), status=OccurrenceStatus.DONE)
    # Paused tasks aren't done, whatever their history — found in review:
    # pausing a repeating task (which removes its open occurrence) made it
    # count as finished.
    finished_tasks = Chore.objects.filter(project=OuterRef("pk"), is_active=True).filter(
        ~Exists(open_occurrence), Exists(done_occurrence)
    )

    return projects.annotate(
        task_count=Count("tasks", distinct=True),
        tasks_done=Count("tasks", filter=Q(tasks__in=finished_tasks.values("pk")), distinct=True),
    ).prefetch_related(Prefetch("milestones", queryset=Milestone.objects.all()))


@dataclass
class Progress:
    milestones_done: int
    milestone_count: int
    tasks_done: int
    task_count: int

    @property
    def percent(self):
        """Milestones when there are any — they are the plan — else tasks."""
        done, total = (
            (self.milestones_done, self.milestone_count)
            if self.milestone_count
            else (self.tasks_done, self.task_count)
        )
        return round(100 * done / total) if total else 0


def progress(project):
    milestones = list(project.milestones.all())
    return Progress(
        milestones_done=sum(1 for milestone in milestones if milestone.is_done),
        milestone_count=len(milestones),
        tasks_done=getattr(project, "tasks_done", 0),
        task_count=getattr(project, "task_count", 0),
    )


def next_milestone(project):
    """The earliest dated milestone not yet done, else the first undated one."""
    remaining = [milestone for milestone in project.milestones.all() if not milestone.is_done]
    dated = sorted((m for m in remaining if m.target_on), key=lambda m: m.target_on)
    return dated[0] if dated else (remaining[0] if remaining else None)


def project_list(today=None):
    today = today or household_today()
    projects = list(with_progress(Project.objects.all()))
    for project in projects:
        project.progress = progress(project)
        project.next = next_milestone(project)
        project.late_milestones = [m for m in project.milestones.all() if m.is_late(today)]

    return [
        (status, ProjectStatus(status).label, [p for p in projects if p.status == status])
        for status in STATUS_ORDER
        if any(p.status == status for p in projects)
    ]


def active_for_today(today=None):
    """Projects in progress, each with its next milestone and any late ones."""
    today = today or household_today()
    projects = list(with_progress(Project.objects.filter(status=ProjectStatus.ACTIVE)))
    for project in projects:
        project.progress = progress(project)
        project.next = next_milestone(project)
        project.late_milestones = [m for m in project.milestones.all() if m.is_late(today)]
    return projects


@dataclass
class TimelineEntry:
    day: date | None
    label: str
    kind: str  # "start", "milestone", "target", "today"
    milestone: Milestone | None = None
    done: bool = False
    late: bool = False


def timeline(project, today):
    """The project start, its milestones, its target, and today, in date order.

    Undated milestones come last, under "no date yet", rather than being
    left off: a plan with gaps is still a plan.
    """
    milestones = list(project.milestones.all())
    entries = []
    if project.start_on:
        entries.append(TimelineEntry(project.start_on, "Start", "start", done=project.start_on <= today))
    for milestone in milestones:
        if milestone.target_on:
            entries.append(TimelineEntry(
                milestone.target_on, milestone.name, "milestone", milestone,
                done=milestone.is_done, late=milestone.is_late(today),
            ))
    if project.target_on:
        entries.append(TimelineEntry(project.target_on, "Target", "target",
                                     late=project.target_on < today and project.status != ProjectStatus.DONE))

    # Today goes where it falls — but only on a timeline it lands inside.
    dated = [entry.day for entry in entries]
    if dated and min(dated) <= today <= max(dated):
        entries.append(TimelineEntry(today, "Today", "today"))

    kind_order = {"start": 0, "milestone": 1, "today": 2, "target": 3}
    entries.sort(key=lambda entry: (entry.day, kind_order[entry.kind]))
    undated = [
        TimelineEntry(None, m.name, "milestone", m, done=m.is_done)
        for m in milestones if not m.target_on
    ]
    return entries, undated


def tasks(project, user, today):
    """Open tasks as checklist rows, and every other task with its state.

    Every task lands in exactly one of the two lists. The states match
    `with_progress`: a task is "done" only when nothing is left open and one
    was done — so a skipped one-off reads "skipped" here, and doesn't count
    as done in the progress bar either. A paused task is "paused" whether
    or not it still holds an open occurrence (a paused one-off does).
    """
    done_occurrence = Occurrence.objects.filter(chore=OuterRef("pk"), status=OccurrenceStatus.DONE)
    skipped_occurrence = Occurrence.objects.filter(chore=OuterRef("pk"), status=OccurrenceStatus.SKIPPED)
    chores = list(
        occurrences.with_open_occurrence(
            project.tasks.select_related("owner", "assignee", "milestone", "maintenance_item")
            .annotate(has_done=Exists(done_occurrence), has_skipped=Exists(skipped_occurrence))
        )
    )
    occurrences.refresh(chores, today)

    active_open = [c for c in chores if c.is_active and c.open_occurrences]
    others = [c for c in chores if c not in active_open]
    for chore in others:
        if not chore.is_active:
            chore.state = "paused"
        elif chore.has_done:
            chore.state = "done"
        elif chore.has_skipped:
            chore.state = "skipped"
        else:
            # Its schedule ran out before anything was done (an end date or
            # count already passed).
            chore.state = "ended"
    return checklist.rows_for(user, active_open, today), others
