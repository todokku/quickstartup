# coding: utf-8

import re
from unittest import mock

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.urlresolvers import reverse
from django.test import override_settings

from tests.base import BaseTestCase

STATIC_ROOT = str(settings.FRONTEND_DIR / "static")


def getmessage(response):
    for c in response.context:
        message = [m for m in c.get('messages')][0]
        if message:
            return message


@override_settings(STATIC_ROOT=STATIC_ROOT)
class AccountTest(BaseTestCase):
    def setUp(self):
        super(AccountTest, self).setUp()
        self.user_model = get_user_model()
        self.user = self.user_model.objects.create_user(email="test@example.com", password="secret")

    def _login(self):
        self.client.login(email="test@example.com", password="secret")

    def test_simple_reset_password(self):
        url = reverse("qs_accounts:password_reset")
        data = {"email": "test@example.com"}
        response = self.client.post(url, data, follow=True)
        self.assertStatusCode(response, 200)

        message = getmessage(response)
        self.assertEqual(message.tags, "success")
        self.assertEqual(message.message, "We've e-mailed you instructions for setting a new password to the "
                                          "e-mail address you've submitted.")

        self.assertEqual(len(mail.outbox), 1)

        text, html = self.get_mail_payloads(mail.outbox[0])
        self.assertIn("Hi,", text)
        self.assertIn("<h3>Hi,</h3>", html)

        reset_token = re.search(r"https://quickstartup.us(.*)$", text, re.MULTILINE)
        self.assertTrue(reset_token, "No reset token")

        reset_token_url = reset_token.groups()[0]
        self.client.get(reverse("qs_accounts:signin"))  # consume flash messages

        data = {"new_password1": "new-sekret", "new_password2": "new-sekret"}
        response = self.client.post(reset_token_url, data, follow=True)
        self.assertStatusCode(response, 200)

        message = getmessage(response)
        self.assertEqual(message.tags, "success")
        self.assertEqual(message.message, "Password has been reset successfully.")

        user = self.user_model.objects.get(email="test@example.com")  # reload user
        self.assertTrue(user.check_password("new-sekret"), "Password unchanged")

    def test_reset_password_with_passwords_that_does_not_match(self):
        url = reverse("qs_accounts:password_reset")
        data = {"email": "test@example.com", "name": "John Doe"}
        response = self.client.post(url, data)

        reset_token_url = reverse("qs_accounts:password_reset_confirm",
                                  kwargs={"reset_token": response.context["reset_token"]})

        data = {"new_password1": "sekret", "new_password2": "do-not-match"}
        response = self.client.post(reset_token_url, data)
        self.assertStatusCode(response, 200)
        self.assertFormError(response, "form", "new_password2", ["The two password fields didn't match."])

    def test_simple_reset_password_of_user_with_name(self):
        self.user.name = "John Doe"
        self.user.save()

        url = reverse("qs_accounts:password_reset")
        data = {"email": "test@example.com"}
        self.client.post(url, data)

        text, html = self.get_mail_payloads(mail.outbox[0])
        self.assertIn("Hi John Doe,", text)
        self.assertIn("<h3>Hi John Doe,</h3>", html)

    @mock.patch("quickstartup.qs_core.antispam.AntiSpamField.clean")
    def test_full_signup_and_signin_signout_cycle(self, patched_clean):
        patched_clean.return_value = "1337"
        url = reverse("qs_accounts:signup")
        data = {
            "name": "John Doe",
            "email": "john.doe@example.com",
            "password1": "sekr3t",
            "password2": "sekr3t",
            "antispam": "1337",
        }

        # signup
        response = self.client.post(url, data, follow=True)
        self.assertStatusCode(response, 200)

        # redirected to activation notice
        self.assertEqual(len(response.redirect_chain), 1)
        redirect_url = response.redirect_chain[0][0].replace("http://testserver", "")
        self.assertEqual(redirect_url, reverse("qs_accounts:signup_complete"))

        # check user creation on database
        user = self.user_model.objects.get(email="john.doe@example.com")
        self.assertEqual(user.name, "John Doe")
        self.assertEqual(user.is_active, False)
        self.assertEqual(user.is_staff, False)
        self.assertEqual(user.is_superuser, False)

        # check activation email
        text, html = self.get_mail_payloads(mail.outbox[0])
        self.assertIn("Hi John Doe,", text)
        self.assertIn("<h3>Hi John Doe,</h3>", html)

        activation = re.search(r"https://quickstartup.us(.*)$", text, re.MULTILINE)
        self.assertTrue(activation, "No activation link in text email")

        activation_url = activation.groups()[0]
        self.assertIn(activation_url, html)

        # "click" on activation link
        response = self.client.get(activation_url, follow=True)
        self.assertStatusCode(response, 200)
        self.assertEqual(len(response.redirect_chain), 1)

        # check redirection as logged user
        redirect_url = response.redirect_chain[0][0].replace("http://testserver", "")
        self.assertEqual(redirect_url, reverse("app:index"))

        # logout
        response = self.client.get(reverse("qs_accounts:signout"), follow=True)
        self.assertStatusCode(response, 200)
        self.assertEqual(len(response.redirect_chain), 1)

        redirect_url = response.redirect_chain[0][0].replace("http://testserver", "")
        self.assertEqual(redirect_url, reverse("qs_pages:index"))

    def test_fail_signup_password_doesnt_match(self):
        url = reverse("qs_accounts:signup")
        data = {
            "name": "John Doe",
            "email": "john.doe@example.com",
            "password1": "sekr3t",
            "password2": "oops!",
        }
        response = self.client.post(url, data, follow=True)
        self.assertStatusCode(response, 200)
        self.assertFormError(response, "form", "password2", ["The two password fields didn't match."])

    def test_change_password(self):
        self._login()
        data = {
            "old_password": "secret",
            "new_password1": "sekret",
            "new_password2": "sekret",
        }

        response = self.client.post(reverse("qs_accounts:password_change"), data, follow=True)
        self.assertStatusCode(response, 200)

        # refresh!
        self.user.refresh_from_db()

        self.assertTrue(self.user.check_password("sekret"), "Password not modified")

    def test_change_email(self):
        self._login()
        data = {
            "new_email": "new@example.com",
        }

        response = self.client.post(reverse("qs_accounts:email_change"), data, follow=True)
        self.assertStatusCode(response, 200)
        self.assertEqual(len(mail.outbox), 1)

        self.user.refresh_from_db()
        self.assertEqual(self.user.email, "test@example.com")
        self.assertEqual(self.user.new_email, "new@example.com")
