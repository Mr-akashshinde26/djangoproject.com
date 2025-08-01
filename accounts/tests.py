import hashlib

from django.contrib.auth.models import AnonymousUser, User
from django.core.cache import cache
from django.test import TestCase, override_settings
from django_hosts.resolvers import reverse

from accounts.forms import DeleteProfileForm
from foundation import models as foundationmodels
from tracdb.models import Revision, Ticket, TicketChange
from tracdb.testutils import TracDBCreateDatabaseMixin


@override_settings(TRAC_URL="https://code.djangoproject.com/")
class UserProfileTests(TracDBCreateDatabaseMixin, TestCase):
    databases = {"default", "trac"}

    @classmethod
    def setUpTestData(cls):
        User.objects.create_user(username="user1", password="password")
        User.objects.create_user(username="user2", password="password")
        cls.user1_url = reverse("user_profile", args=["user1"])
        cls.user2_url = reverse("user_profile", args=["user2"])

    def test_username_is_page_title(self):
        response = self.client.get(self.user1_url)
        self.assertContains(response, "<h1>user1</h1>", html=True)

    def test_stat_commits(self):
        Revision.objects.create(
            author="user1",
            rev="91c879eda595c12477bbfa6f51115e88b75ddf88",
            _time=1731669560,
        )
        Revision.objects.create(
            author="user1",
            rev="da2432cccae841f0d7629f17a5d79ec47ed7b7cb",
            _time=1731669560,
        )
        Revision.objects.create(
            author="user3",
            rev="63dbe30d3363715deaf280214d75b03f6d65a571",
            _time=1731669560,
        )

        user1_response = self.client.get(self.user1_url)
        user2_response = self.client.get(self.user2_url)
        self.assertContains(
            user1_response,
            '<a href="https://github.com/django/django/commits/main/'
            '?author=user1">Commits: 2.</a>',
            html=True,
        )
        self.assertNotContains(user2_response, "Commits")

    def test_stat_tickets(self):
        Ticket.objects.create(status="new", reporter="user1")
        Ticket.objects.create(status="new", reporter="user2")
        Ticket.objects.create(
            status="closed", reporter="user1", owner="user1", resolution="fixed"
        )
        Ticket.objects.create(
            status="closed", reporter="user2", owner="user1", resolution="fixed"
        )
        Ticket.objects.create(
            status="closed", reporter="user2", owner="user2", resolution="fixed"
        )
        Ticket.objects.create(
            status="closed", reporter="user2", owner="user1", resolution="wontfix"
        )

        user1_response = self.client.get(self.user1_url)
        user2_response = self.client.get(self.user2_url)
        self.assertContains(
            user1_response,
            '<a href="https://code.djangoproject.com/query?'
            'owner=user1&resolution=fixed&desc=1&order=changetime">'
            "Tickets fixed: 2.</a>",
            html=True,
        )
        self.assertContains(
            user2_response,
            '<a href="https://code.djangoproject.com/query?'
            'owner=user2&resolution=fixed&desc=1&order=changetime">'
            "Tickets fixed: 1.</a>",
            html=True,
        )
        self.assertContains(
            user1_response,
            '<a href="https://code.djangoproject.com/query?'
            'reporter=user1&desc=1&order=changetime">'
            "Tickets opened: 2.</a>",
            html=True,
        )
        self.assertContains(
            user2_response,
            '<a href="https://code.djangoproject.com/query?'
            'reporter=user2&desc=1&order=changetime">'
            "Tickets opened: 4.</a>",
            html=True,
        )

    def test_stat_tickets_triaged(self):
        # Possible values are from trac.ini in code.djangoproject.com.
        initial_ticket_values = {
            "field": "stage",
            "oldvalue": "Unreviewed",
            "_time": 1731669560,
        }
        TicketChange.objects.create(
            author="user1",
            newvalue="Accepted",
            ticket=Ticket.objects.create(),
            **initial_ticket_values
        )
        TicketChange.objects.create(
            author="user1",
            newvalue="Someday/Maybe",
            ticket=Ticket.objects.create(),
            **initial_ticket_values
        )
        TicketChange.objects.create(
            author="user1",
            newvalue="Ready for checkin",
            ticket=Ticket.objects.create(),
            **initial_ticket_values
        )
        TicketChange.objects.create(
            author="user2",
            newvalue="Accepted",
            ticket=Ticket.objects.create(),
            **initial_ticket_values
        )

        response = self.client.get(self.user1_url)
        self.assertContains(response, "New tickets triaged: 3.")

    def test_stat_tickets_triaged_unaccepted_not_counted(self):
        common_ticket_values = {
            "field": "stage",
            "author": "user1",
            "_time": 1731669560,
        }
        TicketChange.objects.create(
            oldvalue="Unreviewed",
            newvalue="Accepted",
            ticket=Ticket.objects.create(),
            **common_ticket_values
        )
        TicketChange.objects.create(
            oldvalue="Accepted",
            newvalue="Unreviewed",
            ticket=Ticket.objects.create(),
            **common_ticket_values
        )

        response = self.client.get(self.user1_url)
        self.assertContains(response, "New tickets triaged: 1.")

    @override_settings(
        CACHES={
            "default": {
                "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
                "LOCATION": "unique-snowflake",
            }
        }
    )
    def test_caches_trac_stats(self):
        key = "user_vital_status:%s" % hashlib.md5(b"user1").hexdigest()

        self.assertIsNone(cache.get(key))

        self.client.get(self.user1_url)

        self.assertIsNotNone(cache.get(key))


class ViewsTests(TestCase):

    def test_login_redirect(self):
        credentials = {"username": "a-user", "password": "password"}
        User.objects.create_user(**credentials)

        response = self.client.post(reverse("login"), credentials)
        self.assertRedirects(response, "/accounts/edit/")

    def test_profile_view_reversal(self):
        """
        The profile view can be reversed for usernames containing "weird" but
        valid username characters.
        """
        for username in ["asdf", "@asdf", "asd-f", "as.df", "as+df"]:
            reverse("user_profile", host="www", args=[username])


class UserDeletionTests(TestCase):
    def create_user_and_form(self, bound=True, **userkwargs):
        userkwargs.setdefault("username", "test")
        userkwargs.setdefault("email", "test@example.com")
        userkwargs.setdefault("password", "password")

        formkwargs = {"user": User.objects.create_user(**userkwargs)}
        if bound:
            formkwargs["data"] = {}

        return DeleteProfileForm(**formkwargs)

    def test_deletion(self):
        form = self.create_user_and_form()
        self.assertFormError(form, None, [])
        form.delete()
        self.assertQuerySetEqual(User.objects.all(), [])

    def test_anonymous_user_error(self):
        self.assertRaises(TypeError, DeleteProfileForm, user=AnonymousUser)

    def test_deletion_staff_forbidden(self):
        form = self.create_user_and_form(is_staff=True)
        self.assertFormError(form, None, ["Staff users cannot be deleted"])

    def test_user_with_protected_data(self):
        form = self.create_user_and_form()
        form.user.boardmember_set.create(
            office=foundationmodels.Office.objects.create(name="test"),
            term=foundationmodels.Term.objects.create(year=2000),
        )
        form.delete()
        self.assertFormError(
            form, None, ["User has protected data and cannot be deleted"]
        )

    def test_form_delete_method_requires_valid_form(self):
        form = self.create_user_and_form(is_staff=True)
        self.assertRaises(form.InvalidFormError, form.delete)

    def test_view_deletion_also_logs_out(self):
        user = self.create_user_and_form().user
        self.client.force_login(user)
        self.client.post(reverse("delete_profile"))
        self.assertEqual(self.client.cookies["sessionid"].value, "")
