"""Single-account, stateless login for a read-only telemetry dashboard.

The password is checked against environment variables, never a Django User table.
Only a credentials-bound fingerprint is stored in a signed session cookie.
"""

from __future__ import annotations

import hashlib
import hmac
from functools import wraps
from urllib.parse import urlencode

from django.conf import settings
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST

SESSION_KEY = "pulseward_auth"


def _fingerprint() -> str:
    # Changing the login credentials automatically invalidates old sessions.
    message = f"{settings.DASHBOARD_USERNAME}\0{settings.DASHBOARD_PASSWORD}".encode()
    return hmac.new(settings.SECRET_KEY.encode(), message, hashlib.sha256).hexdigest()


def is_authenticated(request) -> bool:
    marker = request.session.get(SESSION_KEY)
    return bool(
        marker
        and settings.DASHBOARD_USERNAME
        and settings.DASHBOARD_PASSWORD
        and hmac.compare_digest(str(marker), _fingerprint())
    )


def dashboard_login_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if is_authenticated(request):
            return view(request, *args, **kwargs)
        if request.path.startswith("/api/"):
            response = JsonResponse({"ok": False, "error": "Login required"}, status=401)
            response["Cache-Control"] = "no-store"
            return response
        return redirect(f"{reverse('login')}?{urlencode({'next': request.get_full_path()})}")
    return wrapped


def _safe_next(request):
    target = request.POST.get("next") or request.GET.get("next") or reverse("dashboard")
    if (
        target.startswith("/")
        and not target.startswith("//")
        and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure())
    ):
        return target
    return reverse("dashboard")


@require_http_methods(["GET", "POST"])
def login_view(request):
    target = _safe_next(request)
    if is_authenticated(request):
        return redirect(target)

    error = False
    if request.method == "POST":
        supplied_username = request.POST.get("username", "")
        supplied_password = request.POST.get("password", "")
        if (
            settings.DASHBOARD_USERNAME
            and settings.DASHBOARD_PASSWORD
            and hmac.compare_digest(supplied_username.encode("utf-8"), settings.DASHBOARD_USERNAME.encode("utf-8"))
            and hmac.compare_digest(supplied_password.encode("utf-8"), settings.DASHBOARD_PASSWORD.encode("utf-8"))
        ):
            request.session.cycle_key()
            request.session[SESSION_KEY] = _fingerprint()
            request.session.set_expiry(settings.SESSION_COOKIE_AGE)
            return redirect(target)
        error = True

    response = render(request, "registration/login.html", {"error": error, "next": target})
    response["Cache-Control"] = "no-store"
    return response


@require_POST
def logout_view(request):
    request.session.flush()
    return redirect("login")
