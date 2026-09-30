"""Projects: progress, the timeline, tasks as chores, and the small actions."""

from datetime import date, timedelta
from decimal import Decimal

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from household.dates import household_today
from household.models import Chore, Milestone, Occurrence, OccurrenceStatus, Project, ProjectLink, ProjectNote, ProjectStatus
from household.scheduling import Anchor, Frequency
from household.services import checklist, occurrences, projects

from .factories import make_member, sign_in

TODAY = date(2026, 9, 30)


def make_project(name="Kitchen refresh", **fields):
    fields.setdefault("status", ProjectStatus.ACTIVE)
    return Project.objects.create(name=name, **fields)


def make_task(project, title="Buy paint", *, assignee=None, milestone=None, today=TODAY, **fields):
    chore = Chore.objects.create(title=title, owner=None, assignee=assignee, project=project,
                                 milestone=milestone, **fields)
    occurrences.reschedule(chore, today=today)
    return chore


def task_form(**overrides):
    data = {
        "title": "Get backsplash quotes",
        "frequency": Frequency.ONCE,
        "starts_on": "",
        "interval": 1,
        "monthly_mode": "day",
        "anchor": Anchor.FIXED,
        "is_active": "on",
        "notes": "",
    }
    data.update(overrides)
    return data


class ProgressTests(TestCase):
    def setUp(self):
        self.david = make_member("david")
        self.project = make_project()

    def annotated(self):
        return projects.with_progress(Project.objects.filter(pk=self.project.pk)).get()

    def test_tasks_count_as_done_only_when_nothing_is_left_open(self):
        done = make_task(self.project, "Done one-off", starts_on=TODAY)
        occurrences.complete(done.occurrences.get(status=OccurrenceStatus.OPEN), by=self.david)
        make_task(self.project, "Still open", starts_on=TODAY)
        # A repeating task that has done one and opened the next isn't done.
        weekly = make_task(self.project, "Water the seedlings", frequency=Frequency.WEEKLY, starts_on=TODAY)
        occurrences.complete(weekly.occurrences.get(status=OccurrenceStatus.OPEN), by=self.david)

        progress = projects.progress(self.annotated())

        self.assertEqual((progress.tasks_done, progress.task_count), (1, 3))

    def test_milestones_drive_the_percentage_when_there_are_any(self):
        Milestone.objects.create(project=self.project, name="A", completed_on=TODAY)
        Milestone.objects.create(project=self.project, name="B")
        Milestone.objects.create(project=self.project, name="C")
        Milestone.objects.create(project=self.project, name="D")
        make_task(self.project, starts_on=TODAY)

        self.assertEqual(projects.progress(self.annotated()).percent, 25)

    def test_without_milestones_tasks_drive_it(self):
        done = make_task(self.project, starts_on=TODAY)
        occurrences.complete(done.occurrences.get(status=OccurrenceStatus.OPEN), by=self.david)
        make_task(self.project, "Other", starts_on=TODAY)

        self.assertEqual(projects.progress(self.annotated()).percent, 50)
        self.assertEqual(projects.progress(make_project("Empty")).percent, 0)

    def test_next_milestone_is_the_earliest_dated_one_not_done(self):
        Milestone.objects.create(project=self.project, name="Undated")
        Milestone.objects.create(project=self.project, name="Done", target_on=TODAY, completed_on=TODAY)
        Milestone.objects.create(project=self.project, name="Later", target_on=TODAY + timedelta(days=20))
        Milestone.objects.create(project=self.project, name="Sooner", target_on=TODAY + timedelta(days=5))

        self.assertEqual(projects.next_milestone(self.project).name, "Sooner")

    def test_with_only_undated_left_it_is_the_first_of_those(self):
        Milestone.objects.create(project=self.project, name="First undated")
        Milestone.objects.create(project=self.project, name="Second undated")

        self.assertEqual(projects.next_milestone(self.project).name, "First undated")


class TimelineTests(TestCase):
    def test_order_today_and_lateness(self):
        project = make_project(start_on=TODAY - timedelta(days=30), target_on=TODAY + timedelta(days=60))
        Milestone.objects.create(project=project, name="Late", target_on=TODAY - timedelta(days=2))
        Milestone.objects.create(project=project, name="Done early", target_on=TODAY - timedelta(days=10),
                                 completed_on=TODAY - timedelta(days=12))
        Milestone.objects.create(project=project, name="Soon", target_on=TODAY + timedelta(days=5))
        Milestone.objects.create(project=project, name="Someday")

        entries, undated = projects.timeline(project, TODAY)

        self.assertEqual(
            [(entry.label, entry.late, entry.done) for entry in entries],
            [
                ("Start", False, True),
                ("Done early", False, True),
                ("Late", True, False),
                ("Today", False, False),
                ("Soon", False, False),
                ("Target", False, False),
            ],
        )
        self.assertEqual([entry.label for entry in undated], ["Someday"])

    def test_today_is_left_off_a_timeline_it_falls_outside(self):
        project = make_project(start_on=TODAY + timedelta(days=10), target_on=TODAY + timedelta(days=40))

        entries, _ = projects.timeline(project, TODAY)

        self.assertNotIn("Today", [entry.label for entry in entries])

    def test_a_done_project_is_never_late(self):
        project = make_project(status=ProjectStatus.DONE, target_on=TODAY - timedelta(days=1))

        [target], _ = projects.timeline(project, TODAY)

        self.assertFalse(target.late)


class TaskTests(TestCase):
    def setUp(self):
        self.david = make_member("david", first_name="David")
        self.maddie = make_member("maddie", first_name="Maddie")
        sign_in(self.client, self.david)
        self.project = make_project()
        self.milestone = Milestone.objects.create(project=self.project, name="Backsplash")

    def test_a_task_is_a_shared_chore_on_the_assignees_checklist(self):
        response = self.client.post(
            reverse("household:project_task_create", args=[self.project.pk]),
            task_form(assignee=self.maddie.pk, milestone=self.milestone.pk,
                      starts_on=household_today().isoformat()),
        )

        task = Chore.objects.get()
        self.assertRedirects(response, reverse("household:project_detail", args=[self.project.pk]) + "#tasks",
                             fetch_redirect_response=False)
        self.assertEqual((task.project, task.milestone, task.owner, task.assignee),
                         (self.project, self.milestone, None, self.maddie))

        hers = checklist.checklist(self.maddie, include_partner=False)
        self.assertIn("Get backsplash quotes", [row.chore.title for _, _, rows in hers["mine"] for row in rows])

    def test_another_projects_milestone_is_refused(self):
        other = Milestone.objects.create(project=make_project("Garden"), name="Dig beds")

        response = self.client.post(
            reverse("household:project_task_create", args=[self.project.pk]),
            task_form(milestone=other.pk),
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("milestone", response.context["form"].errors)
        self.assertFalse(Chore.objects.exists())

    def test_the_chore_edit_page_sends_a_task_to_its_project(self):
        task = make_task(self.project)

        response = self.client.get(reverse("household:chore_edit", args=[task.pk]))

        self.assertRedirects(response, reverse("household:project_task_edit", args=[self.project.pk, task.pk]))

    def test_a_task_from_another_project_is_a_404(self):
        task = make_task(make_project("Garden"))

        response = self.client.get(reverse("household:project_task_edit", args=[self.project.pk, task.pk]))

        self.assertEqual(response.status_code, 404)

    def test_deleting_a_milestone_keeps_its_tasks(self):
        task = make_task(self.project, milestone=self.milestone)

        self.client.post(reverse("household:milestone_delete", args=[self.project.pk, self.milestone.pk]))

        task.refresh_from_db()
        self.assertIsNone(task.milestone)

    def test_deleting_the_project_takes_its_tasks_off_every_list(self):
        make_task(self.project, starts_on=TODAY)

        self.client.post(reverse("household:project_delete", args=[self.project.pk]))

        self.assertFalse(Chore.objects.exists())
        self.assertFalse(Occurrence.objects.exists())


class ActionTests(TestCase):
    def setUp(self):
        self.david = make_member("david", first_name="David")
        self.maddie = make_member("maddie", first_name="Maddie")
        sign_in(self.client, self.david)
        self.project = make_project()
        self.detail = reverse("household:project_detail", args=[self.project.pk])

    def test_milestones_are_added_and_ticked(self):
        self.client.post(reverse("household:milestone_create", args=[self.project.pk]),
                         {"milestone-name": "Paint", "milestone-target_on": "2026-10-20"})
        milestone = Milestone.objects.get()

        self.client.post(reverse("household:milestone_toggle", args=[self.project.pk, milestone.pk]))
        milestone.refresh_from_db()
        self.assertEqual(milestone.completed_on, household_today())

        self.client.post(reverse("household:milestone_toggle", args=[self.project.pk, milestone.pk]))
        milestone.refresh_from_db()
        self.assertIsNone(milestone.completed_on)

    def test_a_bad_milestone_says_why_and_saves_nothing(self):
        response = self.client.post(reverse("household:milestone_create", args=[self.project.pk]),
                                    {"milestone-name": ""}, follow=True)

        self.assertFalse(Milestone.objects.exists())
        self.assertContains(response, "Not saved")

    def test_links_must_be_web_addresses(self):
        """A link is rendered as an href, so a javascript: URL must never get in."""
        for url in ["javascript:alert(1)", "not a url", "data:text/html,hi"]:
            with self.subTest(url=url):
                self.client.post(reverse("household:link_create", args=[self.project.pk]),
                                 {"link-title": "Bad", "link-url": url})
                self.assertFalse(ProjectLink.objects.exists())

        self.client.post(reverse("household:link_create", args=[self.project.pk]),
                         {"link-title": "Design board", "link-url": "https://docs.google.com/document/d/x"})
        self.assertContains(self.client.get(self.detail), "https://docs.google.com/document/d/x")

    def test_a_note_is_removable_only_by_its_author(self):
        mine = ProjectNote.objects.create(project=self.project, author=self.david, body="Mine")
        hers = ProjectNote.objects.create(project=self.project, author=self.maddie, body="Hers")

        refused = self.client.post(reverse("household:note_delete", args=[self.project.pk, hers.pk]))
        self.client.post(reverse("household:note_delete", args=[self.project.pk, mine.pk]))

        self.assertEqual(refused.status_code, 403)
        self.assertEqual(list(ProjectNote.objects.values_list("body", flat=True)), ["Hers"])

    def test_child_rows_are_scoped_to_their_project(self):
        other = make_project("Garden")
        link = ProjectLink.objects.create(project=other, title="x", url="https://example.com")

        response = self.client.post(reverse("household:link_delete", args=[self.project.pk, link.pk]))

        self.assertEqual(response.status_code, 404)
        self.assertTrue(ProjectLink.objects.exists())


class PageTests(TestCase):
    def setUp(self):
        self.david = make_member("david", first_name="David")
        sign_in(self.client, self.david)

    def test_the_list_groups_by_status_in_order(self):
        make_project("Someday", status=ProjectStatus.IDEA)
        make_project("Now", status=ProjectStatus.ACTIVE)
        make_project("Finished", status=ProjectStatus.DONE)

        groups = [label for _, label, _ in projects.project_list(TODAY)]

        self.assertEqual(groups, ["In progress", "Idea", "Done"])

    def test_today_shows_only_projects_in_progress(self):
        make_project("Now", status=ProjectStatus.ACTIVE)
        make_project("Later", status=ProjectStatus.PLANNED)

        response = self.client.get(reverse("household:today"))

        self.assertEqual([p.name for p in response.context["projects"]], ["Now"])

    def test_query_counts_do_not_grow_with_projects_or_tasks(self):
        def count(url):
            with CaptureQueriesContext(connection) as queries:
                self.client.get(url)
            return len(queries)

        project = make_project("First", budget_total=Decimal("100"))
        # At least one task in the baseline: with none, Django skips the
        # open-occurrence prefetch entirely and the baseline reads one low.
        make_task(project, "Baseline task", starts_on=TODAY)
        for url in (reverse("household:projects"), reverse("household:today"),
                    reverse("household:project_detail", args=[project.pk])):
            count(url)
        baseline = {
            "list": count(reverse("household:projects")),
            "today": count(reverse("household:today")),
            "detail": count(reverse("household:project_detail", args=[project.pk])),
        }

        for index in range(6):
            extra = make_project(f"Project {index}")
            Milestone.objects.create(project=extra, name="m", target_on=TODAY)
            make_task(extra, starts_on=TODAY)
        for index in range(8):
            make_task(project, f"Task {index}", starts_on=TODAY,
                      milestone=Milestone.objects.create(project=project, name=f"m{index}"))

        self.assertEqual(count(reverse("household:projects")), baseline["list"])
        self.assertEqual(count(reverse("household:today")), baseline["today"])
        self.assertEqual(count(reverse("household:project_detail", args=[project.pk])), baseline["detail"])


class TaskStateTests(TestCase):
    """Found in review: a paused one-off vanished from its project page, and a
    skipped task read "done" while the progress bar didn't count it."""

    def test_every_task_appears_once_with_a_state_matching_progress(self):
        david = make_member("david")
        project = make_project()
        done = make_task(project, "Done", starts_on=TODAY)
        occurrences.complete(done.occurrences.get(status=OccurrenceStatus.OPEN), by=david)
        skipped = make_task(project, "Skipped", starts_on=TODAY)
        occurrences.skip(skipped.occurrences.get(status=OccurrenceStatus.OPEN), by=david)
        make_task(project, "Open", starts_on=TODAY)
        paused = make_task(project, "Paused one-off", starts_on=TODAY)
        paused.is_active = False
        paused.save()
        occurrences.reschedule(paused, today=TODAY)  # a paused one-off keeps its open occurrence

        open_rows, others = projects.tasks(project, david, TODAY)

        self.assertEqual([row.chore.title for row in open_rows], ["Open"])
        self.assertEqual({c.title: c.state for c in others},
                         {"Done": "done", "Skipped": "skipped", "Paused one-off": "paused"})
        progress = projects.progress(projects.with_progress(Project.objects.filter(pk=project.pk)).get())
        self.assertEqual((progress.tasks_done, progress.task_count), (1, 4))

    def test_a_non_numeric_milestone_in_the_url_is_ignored(self):
        sign_in(self.client, make_member("david"))
        project = make_project()

        response = self.client.get(reverse("household:project_task_create", args=[project.pk]) + "?milestone=abc")

        self.assertEqual(response.status_code, 200)
