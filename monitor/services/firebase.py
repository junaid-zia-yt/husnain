from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

import requests
from django.conf import settings

try:
    from google.auth.transport.requests import Request as GoogleAuthRequest
    from google.oauth2 import service_account
except ImportError:  # pragma: no cover
    GoogleAuthRequest = None
    service_account = None


class FirebaseError(RuntimeError):
    pass


@dataclass
class VitalReading:
    bpm: float | None
    ecg: float | None
    temperature: float | None
    sensor_timestamp: float | None
    received_at: datetime
    source: str
    raw: dict[str, Any]


class FirebaseClient:
    """Read the single Realtime Database object stored at /patient.

    Final Firebase contract:
        patient/
            BPM
            ECG
            Temperature
            Timestamp
    """

    def __init__(self):
        self.database_url = settings.FIREBASE_DATABASE_URL.rstrip("/")
        self.timeout = settings.FIREBASE_TIMEOUT_SECONDS

    def _access_token(self) -> str | None:
        file_path = settings.FIREBASE_SERVICE_ACCOUNT_FILE
        account_json = settings.FIREBASE_SERVICE_ACCOUNT_JSON
        if not file_path and not account_json:
            return None
        if not service_account or not GoogleAuthRequest:
            raise FirebaseError(
                "google-auth is required for Firebase service-account authentication"
            )
        scopes = [
            "https://www.googleapis.com/auth/firebase.database",
            "https://www.googleapis.com/auth/userinfo.email",
        ]
        if account_json:
            try:
                credentials = service_account.Credentials.from_service_account_info(
                    json.loads(account_json), scopes=scopes
                )
            except (ValueError, TypeError, KeyError) as exc:
                raise FirebaseError("Invalid FIREBASE_SERVICE_ACCOUNT_JSON") from exc
        else:
            path = Path(file_path)
            if not path.exists():
                raise FirebaseError("Firebase service-account file not found")
            credentials = service_account.Credentials.from_service_account_file(
                str(path), scopes=scopes
            )
        credentials.refresh(GoogleAuthRequest())
        return credentials.token

    def _request_parts(self, path: str, *, streaming: bool = False):
        clean_path = path.strip("/")
        url = f"{self.database_url}/{clean_path}.json"
        params: dict[str, str] = {}
        headers: dict[str, str] = {
            "Accept": "text/event-stream" if streaming else "application/json",
            "Cache-Control": "no-cache",
        }
        token = self._access_token()
        if token:
            headers["Authorization"] = f"Bearer {token}"
        elif settings.FIREBASE_AUTH_TOKEN:
            params["auth"] = settings.FIREBASE_AUTH_TOKEN
        return clean_path, url, params, headers

    def fetch(self, path: str | None = None) -> VitalReading:
        clean_path, url, params, headers = self._request_parts(
            path or settings.FIREBASE_PATIENT_PATH
        )
        try:
            response = requests.get(
                url, params=params, headers=headers, timeout=self.timeout
            )
            response.raise_for_status()
            payload = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise FirebaseError(f"Firebase snapshot request failed: {exc}") from exc

        if payload is None:
            raise FirebaseError(f"No Firebase data found at '/{clean_path}'")
        if not isinstance(payload, dict):
            raise FirebaseError(f"Firebase '/{clean_path}' must contain a JSON object")
        return reading_from_payload(payload, source="firebase-snapshot")

    def stream(self, path: str | None = None) -> Iterator[VitalReading]:
        """Yield a complete reading whenever any /patient field changes."""

        clean_path, url, params, headers = self._request_parts(
            path or settings.FIREBASE_PATIENT_PATH, streaming=True
        )
        try:
            with requests.get(
                url,
                params=params,
                headers=headers,
                stream=True,
                timeout=(self.timeout, None),
            ) as response:
                response.raise_for_status()
                content_type = response.headers.get("Content-Type", "")
                if "text/event-stream" not in content_type.lower():
                    raise FirebaseError(
                        "Firebase did not return a realtime stream. Check database URL, "
                        "Realtime Database rules, and credentials."
                    )

                response.encoding = "utf-8"
                state: dict[str, Any] = {}
                event_name: str | None = None
                data_lines: list[str] = []

                for raw_line in response.iter_lines(decode_unicode=True):
                    if raw_line is None:
                        continue
                    line = raw_line.strip("\r")

                    if line == "":
                        if event_name and data_lines:
                            payload_text = "\n".join(data_lines)
                            if event_name in {"put", "patch"}:
                                try:
                                    event_payload = json.loads(payload_text)
                                except json.JSONDecodeError:
                                    event_payload = None
                                if isinstance(event_payload, dict):
                                    state = apply_firebase_event(
                                        state,
                                        event_name,
                                        event_payload.get("path", "/"),
                                        event_payload.get("data"),
                                    )
                                    if state:
                                        yield reading_from_payload(
                                            state, source="firebase-realtime"
                                        )
                            elif event_name in {"cancel", "auth_revoked"}:
                                raise FirebaseError(
                                    f"Firebase realtime stream stopped: {payload_text}"
                                )
                        event_name = None
                        data_lines = []
                        continue

                    if line.startswith(":"):
                        continue
                    if line.startswith("event:"):
                        event_name = line[6:].strip()
                    elif line.startswith("data:"):
                        data_lines.append(line[5:].lstrip())
        except FirebaseError:
            raise
        except requests.RequestException as exc:
            raise FirebaseError(
                f"Realtime Firebase connection failed for '/{clean_path}': {exc}"
            ) from exc


def reading_from_payload(payload: dict[str, Any], *, source: str) -> VitalReading:
    """Parse only the four fields present in the final Firebase structure."""

    return VitalReading(
        bpm=_to_float(payload.get("BPM")),
        ecg=_to_float(payload.get("ECG")),
        temperature=_to_float(payload.get("Temperature")),
        sensor_timestamp=_to_float(payload.get("Timestamp")),
        received_at=datetime.now(timezone.utc),
        source=source,
        raw=payload.copy(),
    )


def apply_firebase_event(
    state: dict[str, Any], event_name: str, path: str, data: Any
) -> dict[str, Any]:
    current = _deep_copy_dict(state)
    segments = [part for part in str(path or "/").strip("/").split("/") if part]

    if event_name == "put":
        if not segments:
            return data.copy() if isinstance(data, dict) else {}
        _set_path(current, segments, data)
        return current

    if event_name == "patch":
        if not isinstance(data, dict):
            return current
        if not segments:
            for key, value in data.items():
                _set_path(current, [str(key)], value)
        else:
            target = _get_or_create_dict(current, segments)
            for key, value in data.items():
                if value is None:
                    target.pop(str(key), None)
                else:
                    target[str(key)] = value
        return current

    return current


def _deep_copy_dict(value: dict[str, Any]) -> dict[str, Any]:
    return json.loads(json.dumps(value)) if value else {}


def _get_or_create_dict(root: dict[str, Any], segments: list[str]) -> dict[str, Any]:
    cursor = root
    for segment in segments:
        child = cursor.get(segment)
        if not isinstance(child, dict):
            child = {}
            cursor[segment] = child
        cursor = child
    return cursor


def _set_path(root: dict[str, Any], segments: list[str], value: Any) -> None:
    if not segments:
        return
    parent = _get_or_create_dict(root, segments[:-1]) if len(segments) > 1 else root
    key = segments[-1]
    if value is None:
        parent.pop(key, None)
    else:
        parent[key] = value


def _to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
