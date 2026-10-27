from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("api/live/", views.live_vitals, name="live-vitals"),
    path("api/stream/", views.stream_vitals, name="stream-vitals"),
]
