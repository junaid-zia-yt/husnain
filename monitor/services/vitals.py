"""Telemetry status helpers that do not store readings anywhere."""

from __future__ import annotations


def status_for_bpm(value: float | None) -> dict[str, str]:
    if value is None:
        return _status("unknown", "No signal")
    if 60 <= value <= 100:
        return _status("normal", "In range")
    if 50 <= value < 60 or 100 < value <= 120:
        return _status("warning", "Observe")
    return _status("critical", "Outside range")


def signal_status(value: float | None) -> dict[str, str]:
    return _status("normal", "Live") if value is not None else _status("unknown", "No signal")


def _status(level: str, label: str) -> dict[str, str]:
    return {"level": level, "label": label}
