"""The morning digest: one email per person, per household morning.

Opt-in (`HouseholdPreference.morning_digest`). It says what Today would say
— overdue, today, the week's easy-to-forget chores — plus project milestones
coming up or late, so a busy morning doesn't need the app opened to know
what matters. A morning with nothing to say sends nothing.

**When.** The hourly chain calls `send_due_digests()`; a digest goes out on
the first run at or after `DIGEST_HOUR` household time, and
`last_digest_on` keeps it to one a day. Driven by the household clock, not a
fixed UTC cron time, so it lands at the same local hour on both sides of a
daylight-saving change.

**Sending never happens inside a database transaction** (the repo-wide rule;
see finance's architecture doc). The day is claimed first, in one
conditional UPDATE, so overlapping runs can't both send; then everything is
read and the mail goes out with nothing open. Any failure after the claim
releases it, so the next hourly run tries again.
"""

import logging
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse
from django.utils import timezone

from ..access import HOUSEHOLD_GROUP
from ..dates import household_timezone
from ..models import HouseholdPreference, ProjectStatus
from ..models.projects import Milestone
from . import checklist
from .wording import due_words

logger = logging.getLogger(__name__)

DIGEST_HOUR = 7
MILESTONE_DAYS = 14


def _link(path):
    return settings.REDIRECT_DOMAIN.rstrip("/") + path


def _row_line(row, today):
    whose = "" if row.chore.assignee_id else " (either of us)"
    return f"  - {row.chore.title}{whose} — {due_words(row.occurrence, today)}"


def build_digest(user, today):
    """The digest's sections as [(title, [lines])], or [] when there's nothing."""
    summary = checklist.today_summary(user, include_partner=False, today=today)
    sections = []

    if summary["overdue"]:
        sections.append(("Overdue", [_row_line(row, today) for row in summary["overdue"]]))
    if summary["due_today"]:
        sections.append(("Today", [_row_line(row, today) for row in summary["due_today"]]))
    if summary["coming_up"]:
        sections.append(("Coming up this week", [_row_line(row, today) for row in summary["coming_up"]]))

    milestones = (
        Milestone.objects.filter(
            project__status=ProjectStatus.ACTIVE,
            completed_on__isnull=True,
            target_on__lte=today + timedelta(days=MILESTONE_DAYS),
        )
        .select_related("project")
        .order_by("target_on")
    )
    lines = []
    for milestone in milestones:
        when = "late" if milestone.target_on < today else f"{milestone.target_on:%a %b} {milestone.target_on.day}"
        lines.append(f"  - {milestone.project.name}: {milestone.name} — {when}")
    if lines:
        sections.append(("Project milestones", lines))

    return sections


def render_digest(user, today, sections):
    body = [f"Good morning{', ' + user.first_name if user.first_name else ''} — {today:%A, %B} {today.day}", ""]
    for title, lines in sections:
        body.extend([title.upper(), *lines, ""])
    body.extend([
        f"Open Today: {_link(reverse('household:today'))}",
        f"Turn these off: {_link(reverse('household:preferences'))}",
    ])
    return "\n".join(body)


def is_due(preference, now):
    local = now.astimezone(household_timezone())
    return (
        preference.morning_digest
        and local.hour >= DIGEST_HOUR
        and preference.last_digest_on != local.date()
    )


def send_digest(preference, now):
    """Build, send, and record one person's digest. True if one went out."""
    user = preference.user
    today = now.astimezone(household_timezone()).date()

    if not user.email:
        logger.warning("Digest for %s skipped: no email address", user.pk)
        return False

    # Claim the day before sending, in one conditional UPDATE: if two hourly
    # runs overlap (Heroku Scheduler doesn't promise it won't), only one wins
    # the claim and only one email goes out. Found in review.
    previous = preference.last_digest_on
    claimed = (
        HouseholdPreference.objects.filter(pk=preference.pk)
        .exclude(last_digest_on=today)
        .update(last_digest_on=today, updated_at=timezone.now())
    )
    if not claimed:
        return False

    try:
        sections = build_digest(user, today)
        if not sections:
            # The claim stands for an empty morning, so the next hour doesn't
            # rebuild it.
            return False
        send_mail(
            subject=f"[Mays Household] {today:%A}: {_subject_summary(sections)}",
            message=render_digest(user, today, sections),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            fail_silently=False,
        )
    except Exception:  # noqa: BLE001
        # Building or sending failed: release the claim so the next hourly
        # run tries again. (Found in review: a build failure kept the claim,
        # and that morning's digest never came.)
        logger.exception("Could not send the digest to %s", user.pk)
        HouseholdPreference.objects.filter(pk=preference.pk, last_digest_on=today).update(last_digest_on=previous)
        return False
    return True


def _subject_summary(sections):
    counts = {title: len(lines) for title, lines in sections}
    parts = []
    if counts.get("Overdue"):
        parts.append(f"{counts['Overdue']} overdue")
    if counts.get("Today"):
        parts.append(f"{counts['Today']} today")
    if counts.get("Coming up this week"):
        parts.append(f"{counts['Coming up this week']} this week")
    if counts.get("Project milestones"):
        parts.append(f"{counts['Project milestones']} milestone{'s' if counts['Project milestones'] != 1 else ''}")
    return ", ".join(parts)


def send_due_digests(now=None):
    """Every digest due this hour. Returns how many were sent."""
    now = now or timezone.now()
    # Current members only: someone removed from the household (or
    # deactivated) must stop getting shared chores and milestones by email —
    # and could no longer reach the preference to turn it off.
    preferences = HouseholdPreference.objects.filter(
        morning_digest=True, user__is_active=True, user__groups__name=HOUSEHOLD_GROUP
    ).select_related("user")
    return sum(1 for preference in preferences if is_due(preference, now) and send_digest(preference, now))
