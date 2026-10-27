from django.urls import include, path

from monitor.auth import login_view, logout_view

urlpatterns = [
    path("login/", login_view, name="login"),
    path("logout/", logout_view, name="logout"),
    path("", include("monitor.urls")),
]
