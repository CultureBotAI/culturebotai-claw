"""Strict offline contracts for cached provider-availability evidence."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from kg_microbe_research import AvailabilityError, AvailabilityEvidence
from kg_microbe_research.providers import _load_availability

NOW = datetime(2026, 8, 25, 12, tzinfo=timezone.utc)


class MutableClock:
    """Deterministic clock for expiry tests; it performs no sleeping or I/O."""

    def __init__(self, current: datetime) -> None:
        self.current = current

    def __call__(self) -> datetime:
        return self.current


def load_at(path: Path, current: datetime = NOW) -> AvailabilityEvidence:
    return _load_availability(path, clock=MutableClock(current))


def record(**updates: object) -> dict[str, object]:
    result: dict[str, object] = {
        "status": "available",
        "reason": "cached preflight from a trusted wrapper",
        "checked_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(hours=1)).isoformat(),
        "source": "pytest-static-fixture",
        "context": "fake account/model on test host",
    }
    result.update(updates)
    return result


def write_evidence(tmp_path: Path, document: object) -> Path:
    path = tmp_path / "availability.json"
    path.write_text(json.dumps(document), encoding="utf-8")
    return path


def test_valid_evidence_loads_without_contacting_a_provider(tmp_path: Path) -> None:
    evidence = load_at(
        write_evidence(
            tmp_path,
            {
                "version": 1,
                "providers": {"asta": record()},
            },
        )
    )
    status, reason = evidence.verified_status("asta") or (None, None)
    assert status == "available"
    assert reason is not None
    assert reason.startswith("cached preflight from a trusted wrapper;")
    assert "source=pytest-static-fixture" in reason


@pytest.mark.parametrize(
    "document",
    [
        [],
        {"version": 1},
        {"version": 1, "providers": {}, "extra": True},
        {"version": True, "providers": {}},
        {"version": 1.0, "providers": {}},
        {"version": 2, "providers": {}},
        {"version": 1, "providers": []},
        {
            "version": 1,
            "providers": {"asta": {"status": "available"}},
        },
        {
            "version": 1,
            "providers": {"asta": record(extra=True)},
        },
        {
            "version": 1,
            "providers": {"asta": record(status=True)},
        },
        {
            "version": 1,
            "providers": {"asta": record(status="working")},
        },
        {
            "version": 1,
            "providers": {"asta": record(reason="")},
        },
        {
            "version": 1,
            "providers": {"asta": record(source="")},
        },
        {
            "version": 1,
            "providers": {"nosuchprovider": record()},
        },
    ],
)
def test_malformed_or_unsupported_evidence_fails_closed(tmp_path: Path, document: object) -> None:
    with pytest.raises(AvailabilityError):
        load_at(write_evidence(tmp_path, document))


@pytest.mark.parametrize(
    "text",
    [
        "not json",
        '{"version": 1, "version": 1, "providers": {}}',
    ],
)
def test_invalid_or_duplicate_json_is_refused(tmp_path: Path, text: str) -> None:
    path = tmp_path / "availability.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(AvailabilityError):
        load_at(path)


def test_nested_duplicate_json_key_is_the_only_invalidity(tmp_path: Path) -> None:
    text = (
        '{"version": 1, "providers": {"asta": {'
        '"status": "available", "status": "blocked", '
        '"reason": "complete duplicate-key fixture", '
        '"checked_at": "2026-08-25T12:00:00+00:00", '
        '"expires_at": "2026-08-25T13:00:00+00:00", '
        '"source": "pytest-static-fixture", '
        '"context": "fake account/model on test host"}}}'
    )
    path = tmp_path / "availability.json"
    path.write_text(text, encoding="utf-8")

    with pytest.raises(AvailabilityError, match="duplicate JSON key 'status'"):
        load_at(path)


def test_alias_collisions_are_refused(tmp_path: Path) -> None:
    path = write_evidence(
        tmp_path,
        {
            "version": 1,
            "providers": {
                "falcon": record(status="blocked", reason="first"),
                "edison": record(reason="second"),
            },
        },
    )
    with pytest.raises(AvailabilityError, match="multiple names resolving"):
        load_at(path)


def test_missing_evidence_file_reports_its_path(tmp_path: Path) -> None:
    missing = tmp_path / "missing.json"
    with pytest.raises(AvailabilityError, match="Cannot read availability evidence"):
        load_at(missing)


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"checked_at": "2026-08-25T12:00:00"}, "timezone"),
        ({"checked_at": "0001-01-01T00:00:00+23:59"}, "ISO-8601"),
        ({"expires_at": NOW.isoformat()}, "expire after"),
        (
            {
                "checked_at": (NOW + timedelta(minutes=6)).isoformat(),
                "expires_at": (NOW + timedelta(hours=1)).isoformat(),
            },
            "future",
        ),
        ({"expires_at": (NOW + timedelta(hours=25)).isoformat()}, "24-hour"),
        (
            {
                "checked_at": (NOW - timedelta(hours=2)).isoformat(),
                "expires_at": (NOW - timedelta(hours=1)).isoformat(),
            },
            "expired",
        ),
    ],
)
def test_stale_or_invalid_time_bounds_are_refused(
    tmp_path: Path, updates: dict[str, object], message: str
) -> None:
    path = write_evidence(
        tmp_path,
        {"version": 1, "providers": {"asta": record(**updates)}},
    )
    with pytest.raises(AvailabilityError, match=message):
        load_at(path)


def test_reference_clock_must_be_timezone_aware(tmp_path: Path) -> None:
    path = write_evidence(
        tmp_path,
        {"version": 1, "providers": {"asta": record()}},
    )
    with pytest.raises(AvailabilityError, match="reference time"):
        load_at(path, NOW.replace(tzinfo=None))


def test_maximum_reference_clock_fails_cleanly_without_overflow(tmp_path: Path) -> None:
    path = write_evidence(
        tmp_path,
        {"version": 1, "providers": {"asta": record()}},
    )

    with pytest.raises(AvailabilityError, match="expired"):
        load_at(path, datetime.max.replace(tzinfo=timezone.utc))


def test_expiry_is_rechecked_on_every_cached_evidence_lookup(tmp_path: Path) -> None:
    expiry = NOW + timedelta(hours=1)
    clock = MutableClock(NOW)
    path = write_evidence(
        tmp_path,
        {"version": 1, "providers": {"asta": record(expires_at=expiry.isoformat())}},
    )
    evidence = _load_availability(path, clock=clock)

    clock.current = expiry - timedelta(microseconds=1)
    assert (evidence.verified_status("asta") or (None,))[0] == "available"

    clock.current = expiry
    status, reason = evidence.verified_status("asta") or (None, "")
    assert status == "unavailable"
    assert "cached evidence expired" in reason


def test_non_utf8_evidence_fails_as_an_availability_error(tmp_path: Path) -> None:
    path = tmp_path / "availability.json"
    path.write_bytes(b"\xff\xfe")
    with pytest.raises(AvailabilityError, match="Cannot read availability evidence"):
        load_at(path)
