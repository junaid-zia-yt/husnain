"""Django settings for the database-free PulseWard dashboard."""

from pathlib import Path
import os

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

DEBUG = os.getenv("DJANGO_DEBUG", "False").lower() in {"1", "true", "yes", "on"}
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if not DEBUG:
        raise ImproperlyConfigured("Set DJANGO_SECRET_KEY for production.")
    SECRET_KEY = "development-only-insecure-change-me"

ALLOWED_HOSTS = [
    "*"
]

# No Django ORM applications are installed and no SQL database is configured.
# Firebase Realtime Database remains the *external* live telemetry source.
INSTALLED_APPS = [
    "django.contrib.staticfiles",
    "monitor",
]
DATABASES = {}

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]
ROOT_URLCONF = "health_monitor.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
            ],
        },
    },
]
WSGI_APPLICATION = "health_monitor.wsgi.application"
ASGI_APPLICATION = "health_monitor.asgi.application"

# Signed-cookie sessions need no database, cache, or writable filesystem.
# Cookies are signed, NOT encrypted: do not store secrets in session data.
SESSION_ENGINE = "django.contrib.sessions.backends.signed_cookies"
SESSION_COOKIE_AGE = 8 * 60 * 60
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SECURE = not DEBUG
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_HTTPONLY = True
CSRF_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SAMESITE = "Lax"
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"

DASHBOARD_USERNAME = os.getenv("DASHBOARD_USERNAME", "").strip()
DASHBOARD_PASSWORD = os.getenv("DASHBOARD_PASSWORD", "")
if not DEBUG and (not DASHBOARD_USERNAME or not DASHBOARD_PASSWORD):
    raise ImproperlyConfigured("Set DASHBOARD_USERNAME and DASHBOARD_PASSWORD for production.")
LOGIN_URL = "login"
LOGIN_REDIRECT_URL = "dashboard"
LOGOUT_REDIRECT_URL = "login"

LANGUAGE_CODE = "en-us"
TIME_ZONE = "Asia/Karachi"
USE_I18N = True
USE_TZ = True
STATIC_URL = "static/"
STATICFILES_DIRS = [BASE_DIR / "static"]
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"
    }
}

FIREBASE_DATABASE_URL = os.getenv(
    "FIREBASE_DATABASE_URL",
    "https://health-monitor-iot-ce814-default-rtdb.asia-southeast1.firebasedatabase.app",
).rstrip("/")
FIREBASE_PATIENT_PATH = os.getenv("FIREBASE_PATIENT_PATH", "patient").strip("/") or "patient"
FIREBASE_SERVICE_ACCOUNT_FILE = os.getenv("FIREBASE_SERVICE_ACCOUNT_FILE", "").strip()
FIREBASE_SERVICE_ACCOUNT_JSON = os.getenv("FIREBASE_SERVICE_ACCOUNT_JSON", "").strip()
FIREBASE_AUTH_TOKEN = os.getenv("FIREBASE_AUTH_TOKEN", "").strip()
FIREBASE_TIMEOUT_SECONDS = int(os.getenv("FIREBASE_TIMEOUT_SECONDS", "8"))
POLL_INTERVAL_MS = max(1000, int(os.getenv("POLL_INTERVAL_MS", "2000")))
# Streaming connections can last longer than serverless request limits.
# Polling works consistently on Vercel; use SSE only on a suitable host.
ENABLE_SSE = os.getenv("ENABLE_SSE", "False").lower() in {"1", "true", "yes", "on"}
