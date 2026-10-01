"""Who may do what to a chore, as a table (ADR 0011).

Driven through the real endpoints rather than the service alone: a rule that
holds in `permissions.py` but that one view forgot to ask about would pass a
service-only test and still let the wrong person edit a chore.
"""

from datetime import date

from django.test import TestCase
from django.urls import reverse

from household.models import Chore, OccurrenceStatus
from household.scheduling import Frequency
from household.services import occurrences, permissions

from .factories import make_chore, make_member, sign_in

TODAY = date(2026, 9, 30)

# Who is acting, relative to the chore: its owner, the other person with or
# without the owner's grant, or either person on a household-owned chore.
OWNER, PARTNER, PARTNER_GRANTED, HOUSEHOLD = "owner", "partner", "partner granted", "household"

# action → the cases allowed to do it. Anything not listed must be refused.
ALLOWED = {
    "view": {OWNER, PARTNER, PARTNER_GRANTED, HOUSEHOLD},
    "complete": {OWNER, PARTNER, PARTNER_GRANTED, HOUSEHOLD},
    "skip": {OWNER, PARTNER_GRANTED, HOUSEHOLD},
    "edit": {OWNER, PARTNER_GRANTED, HOUSEHOLD},
    "delete": {OWNER, PARTNER_GRANTED, HOUSEHOLD},
}


class PermissionMatrixTests(TestCase):
    def setUp(self):
        self.david = make_member("david", first_name="David")
        self.maddie = make_member("maddie", first_name="Maddie")

    def case(self, name):
        """(actor, chore) for one row of the table."""
        if name == HOUSEHOLD:
            chore = make_chore(None, title="Shared", frequency=Frequency.WEEKLY, starts_on=TODAY)
            return self.maddie, chore

        chore = make_chore(
            self.david, frequency=Frequency.WEEKLY, starts_on=TODAY,
            others_can_manage=(name == PARTNER_GRANTED),
        )
        return (self.david if name == OWNER else self.maddie), chore

    def attempt(self, action, chore):
        current = chore.occurrences.get(status=OccurrenceStatus.OPEN)
        if action == "view":
            return self.client.get(reverse("household:chore_detail", args=[chore.pk]))
        if action in ("complete", "skip"):
            return self.client.post(reverse("household:occurrence_action", args=[current.pk, action]))
        if action == "edit":
            return self.client.get(reverse("household:chore_edit", args=[chore.pk]))
        return self.client.post(reverse("household:chore_delete", args=[chore.pk]))

    def test_the_table(self):
        for action, allowed in ALLOWED.items():
            for name in (OWNER, PARTNER, PARTNER_GRANTED, HOUSEHOLD):
                with self.subTest(action=action, case=name):
                    actor, chore = self.case(name)
                    sign_in(self.client, actor)

                    response = self.attempt(action, chore)

                    if name in allowed:
                        self.assertIn(response.status_code, (200, 302), response.status_code)
                    else:
                        self.assertEqual(response.status_code, 403)
                    Chore.objects.all().delete()

    def test_a_refused_skip_changes_nothing(self):
        actor, chore = self.case(PARTNER)
        sign_in(self.client, actor)
        current = chore.occurrences.get(status=OccurrenceStatus.OPEN)

        self.client.post(reverse("household:occurrence_action", args=[current.pk, "skip"]))

        current.refresh_from_db()
        self.assertEqual(current.status, OccurrenceStatus.OPEN)

    def test_a_refused_edit_post_changes_nothing(self):
        actor, chore = self.case(PARTNER)
        sign_in(self.client, actor)

        self.client.post(reverse("household:chore_edit", args=[chore.pk]), {"title": "Hijacked"})

        chore.refresh_from_db()
        self.assertEqual(chore.title, "Take out the bins")

    def test_undo_belongs_to_whoever_did_it_or_a_manager(self):
        _, chore = self.case(PARTNER)
        current = chore.occurrences.get(status=OccurrenceStatus.OPEN)
        occurrences.complete(current, by=self.maddie)
        current.refresh_from_db()

        self.assertTrue(permissions.can_undo(self.maddie, current))  # she did it
        self.assertTrue(permissions.can_undo(self.david, current))  # he owns it

        # Done by David, on David's own chore: Maddie did neither.
        chore.occurrences.filter(status=OccurrenceStatus.OPEN).delete()
        occurrences.reopen(current)
        occurrences.complete(current, by=self.david)
        current.refresh_from_db()
        self.assertFalse(permissions.can_undo(self.maddie, current))

    def test_an_unknown_action_is_refused(self):
        actor, chore = self.case(OWNER)
        sign_in(self.client, actor)
        current = chore.occurrences.get(status=OccurrenceStatus.OPEN)

        response = self.client.post(reverse("household:occurrence_action", args=[current.pk, "delete"]))

        self.assertEqual(response.status_code, 403)

    def test_actions_are_post_only(self):
        actor, chore = self.case(OWNER)
        sign_in(self.client, actor)
        current = chore.occurrences.get(status=OccurrenceStatus.OPEN)

        response = self.client.get(reverse("household:occurrence_action", args=[current.pk, "complete"]))

        self.assertEqual(response.status_code, 405)
        current.refresh_from_db()
        self.assertTrue(current.is_open)


class ConfirmationTests(TestCase):
    """The dialog is courtesy, not a guard — but it must appear on the right rows."""

    def setUp(self):
        self.david = make_member("david", first_name="David")
        self.maddie = make_member("maddie", first_name="Maddie")

    def test_only_someone_elses_list_asks_first(self):
        mine = make_chore(self.david)
        hers = make_chore(self.maddie)
        shared_unassigned = make_chore(None)
        shared_to_her = make_chore(None, assignee=self.maddie)

        self.assertFalse(permissions.needs_confirmation(self.david, mine))
        self.assertTrue(permissions.needs_confirmation(self.david, hers))
        self.assertFalse(permissions.needs_confirmation(self.david, shared_unassigned))
        self.assertTrue(permissions.needs_confirmation(self.david, shared_to_her))

    def test_the_row_carries_the_question(self):
        hers = make_chore(self.maddie, title="Walk the dog", starts_on=TODAY)
        sign_in(self.client, self.david)
        self.client.post(reverse("household:chores_partner_toggle"))

        response = self.client.get(reverse("household:chores"))

        self.assertContains(response, "hx-confirm=\"Mark Maddie’s “Walk the dog” as done?\"")
        self.assertIn(hers.title, response.content.decode())
