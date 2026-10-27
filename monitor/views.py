"""Read-only Firebase telemetry endpoints; no SQL reads or writes."""

from __future__ import annotations

import json

from django.conf import settings
from django.http import Http404, JsonResponse, StreamingHttpResponse
from django.shortcuts import render
from django.utils import timezone

from .auth import dashboard_login_required
from .services.firebase import FirebaseClient, FirebaseError, VitalReading
from .services.vitals import signal_status, status_for_bpm


@dashboard_login_required
def dashboard(request):
    return render(
        request,
        "monitor/dashboard.html",
        {
            "dashboard_username": settings.DASHBOARD_USERNAME,
            "firebase_path": settings.FIREBASE_PATIENT_PATH,
            "firebase_database_url": settings.FIREBASE_DATABASE_URL,
            "poll_interval_ms": settings.POLL_INTERVAL_MS,
            "sse_enabled": settings.ENABLE_SSE,
        },
    )


def _payload_for_reading(reading: VitalReading):
    return {
        "ok": True,
        "reading": {
            "bpm": reading.bpm,
            "ecg": reading.ecg,
            "temperature": reading.temperature,
            "sensor_timestamp": reading.sensor_timestamp,
            "received_at": reading.received_at.isoformat(),
            "server_time": timezone.now().isoformat(),
            "source": reading.source,
        },
        "status": {
            "bpm": status_for_bpm(reading.bpm),
            "ecg": signal_status(reading.ecg),
            "temperature": signal_status(reading.temperature),
            "sensor_timestamp": signal_status(reading.sensor_timestamp),
        },
        "firebase": {
            "path": f"/{settings.FIREBASE_PATIENT_PATH.strip('/')}",
            "database_url": settings.FIREBASE_DATABASE_URL,
        },
    }


@dashboard_login_required
def live_vitals(request):
    try:
        reading = FirebaseClient().fetch(settings.FIREBASE_PATIENT_PATH)
    except FirebaseError as exc:
        response = JsonResponse(
            {"ok": False, "error": "Unable to read Firebase Realtime Database", "detail": str(exc)},
            status=503,
        )
        response["Cache-Control"] = "no-store"
        return response
    response = JsonResponse(_payload_for_reading(reading))
    response["Cache-Control"] = "no-store"
    return response


@dashboard_login_required
def stream_vitals(request):
    """Optional SSE, intended for non-serverless deployments."""
    if not settings.ENABLE_SSE:
        raise Http404("SSE disabled: polling is the default on Vercel")

    def event_stream():
        yield ": connected\n\n"
        try:
            for reading in FirebaseClient().stream(settings.FIREBASE_PATIENT_PATH):
                payload = _payload_for_reading(reading)
                yield "event: telemetry\n"
                yield f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"
        except GeneratorExit:
            return
        except FirebaseError as exc:
            payload = json.dumps(
                {"ok": False, "error": "Firebase realtime stream disconnected", "detail": str(exc)},
                separators=(",", ":"),
            )
            yield "event: telemetry_error\n"
            yield f"data: {payload}\n\n"

    response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response["X-Accel-Buffering"] = "no"
    return response
