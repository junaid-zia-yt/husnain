"""Database-free regression tests. Run with: python manage.py test"""

from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase, override_settings
from django.urls import reverse

from monitor.services.firebase import apply_firebase_event, reading_from_payload


class FirebasePayloadTests(SimpleTestCase):
    def test_final_payload_contract(self):
        reading = reading_from_payload(
            {"BPM": 71, "ECG": 1895, "Temperature": 85, "Timestamp": 33695},
            source="test",
        )
        self.assertEqual(reading.bpm, 71)
        self.assertEqual(reading.ecg, 1895)
        self.assertEqual(reading.temperature, 85)
        self.assertEqual(reading.sensor_timestamp, 33695)

    def test_leaf_patch_updates_state(self):
        state = {"BPM": 71, "ECG": 1895, "Temperature": 85, "Timestamp": 33695}
        updated = apply_firebase_event(state, "put", "/BPM", 72)
        self.assertEqual(updated["BPM"], 72)
        self.assertEqual(updated["ECG"], 1895)


@override_settings(
    DASHBOARD_USERNAME="Hospital@123",
    DASHBOARD_PASSWORD="test-password-ONLY-123!",
    SECRET_KEY="strong-demo-secret-for-testing-123456789",
    ALLOWED_HOSTS=["testserver", "localhost", "127.0.0.1"],
    SESSION_ENGINE="django.contrib.sessions.backends.signed_cookies",
    ENABLE_SSE=False,
)
class NoDatabaseTests(SimpleTestCase):
    def _login(self):
        return self.client.post(
            reverse("login"), {"username": "doctor", "password": "test-password-ONLY-123!"}
        )

    def test_no_sql_database_configured(self):
        self.assertIn(settings.DATABASES.get("default", {}).get("ENGINE"),
                      (None, "django.db.backends.dummy"),
                      "Only a dummy, non-connecting backend is permitted")
        self.assertNotIn("django.contrib.auth", settings.INSTALLED_APPS)
        self.assertEqual(settings.SESSION_ENGINE, "django.contrib.sessions.backends.signed_cookies")

    def test_login_required(self):
        result = self.client.get(reverse("dashboard"))
        self.assertEqual(result.status_code, 302)
        self.assertIn("/login/", result["Location"])
        result = self.client.get(reverse("live-vitals"))
        self.assertEqual(result.status_code, 401)
        self.assertEqual(result.json()["error"], "Login required")

    def test_wrong_password_rejected(self):
        result = self.client.post(reverse("login"), {"username": "doctor", "password": "incorrect"})
        self.assertEqual(result.status_code, 200)
        self.assertContains(result, "Invalid username or password")
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 302)

    def test_stateless_login_dashboard_and_logout(self):
        result = self._login()
        self.assertRedirects(result, reverse("dashboard"), fetch_redirect_response=False)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)
        self.assertEqual(self.client.get(reverse("stream-vitals")).status_code, 404)
        self.assertRedirects(
            self.client.post(reverse("logout")), reverse("login"), fetch_redirect_response=False
        )
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 302)

    def test_credentials_rotation_revokes_session(self):
        self._login()
        with override_settings(DASHBOARD_PASSWORD="changed-secret-123456"):
            self.assertEqual(self.client.get(reverse("dashboard")).status_code, 302)

    def test_open_redirect_is_blocked(self):
        result = self.client.post(
            reverse("login") + "?next=https://evil.example/",
            {"username": "doctor", "password": "test-password-ONLY-123!", "next": "//evil.example/"},
        )
        self.assertRedirects(result, reverse("dashboard"), fetch_redirect_response=False)

    def test_live_api_has_no_sql_history(self):
        self._login()
        reading = reading_from_payload(
            {"BPM": 71, "ECG": 1895, "Temperature": 85, "Timestamp": 33695},
            source="test",
        )
        with patch("monitor.views.FirebaseClient") as client:
            client.return_value.fetch.return_value = reading
            response = self.client.get(reverse("live-vitals"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["reading"]["bpm"], 71)
        self.assertNotIn("history", response.json())
        self.assertEqual(response["Cache-Control"], "no-store")
