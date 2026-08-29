"""Fetching a source release: bounded, validated, atomically promoted.

Phase 6 item 3 (#132), generalized from ProteinTraitsMech's `fetch_source.py`.

Every test here runs offline. That is the point of the injectable transport:
PTM's version shells out to `curl`, so exercising a retry that eventually
succeeds, or a digest mismatch, or a destination left untouched by a failure,
needed the network and the binary — which means in practice none of it was
exercised at all.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kg_microbe_sources.fetch import (
    CurlTransport,
    FetchError,
    FetchPlan,
    TransportResult,
    ValidationFailed,
    fetch,
    sha256_of,
    validate,
    verify,
)

MOMENT = datetime(2026, 8, 29, 12, 0, tzinfo=timezone.utc)


def _at(moment: datetime = MOMENT):
    return lambda: moment


def _writes(payload: bytes, **outcome):
    """A transport that succeeds, writing `payload`."""

    def transport(plan, target: Path) -> TransportResult:
        target.write_bytes(payload)
        return TransportResult(**outcome)

    return transport


def _fails(message: str = "connection reset"):
    def transport(plan, target: Path) -> TransportResult:
        raise FetchError(message)

    return transport


def _plan(tmp_path: Path, **overrides) -> FetchPlan:
    return FetchPlan(url="https://example.org/x.tsv",
                     destination=tmp_path / "x.tsv", **overrides)


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------


def test_a_good_download_reports_its_size_and_digest(tmp_path):
    path = tmp_path / "f"
    path.write_bytes(b"hello")

    size, digest = validate(path, _plan(tmp_path))

    assert size == 5
    assert digest == hashlib.sha256(b"hello").hexdigest()


def test_an_empty_response_is_the_clearest_failure_and_is_reported_first(tmp_path):
    """A truncated or empty response is the common failure; naming the size is
    more use than a digest mismatch nobody can act on."""
    path = tmp_path / "f"
    path.write_bytes(b"")

    with pytest.raises(ValidationFailed, match="0 bytes; expected at least 1"):
        validate(path, _plan(tmp_path))


def test_a_digest_mismatch_names_both_digests(tmp_path):
    path = tmp_path / "f"
    path.write_bytes(b"hello")

    with pytest.raises(ValidationFailed, match="SHA-256 mismatch"):
        validate(path, _plan(tmp_path, sha256="00" * 32))


def test_a_pinned_digest_is_compared_case_insensitively(tmp_path):
    path = tmp_path / "f"
    path.write_bytes(b"hello")
    digest = hashlib.sha256(b"hello").hexdigest().upper()

    assert validate(path, _plan(tmp_path, sha256=digest))[1] == digest.lower()


def test_a_wrong_magic_prefix_is_caught(tmp_path):
    """An HTML error page served with a 200 is a gzip that is not gzipped."""
    path = tmp_path / "f"
    path.write_bytes(b"<!DOCTYPE html>")

    with pytest.raises(ValidationFailed, match="content prefix mismatch"):
        validate(path, _plan(tmp_path, prefix=b"\x1f\x8b"))


def test_required_text_must_be_present(tmp_path):
    path = tmp_path / "f"
    path.write_bytes(b"id\tlabel\n")

    with pytest.raises(ValidationFailed, match="required text"):
        validate(path, _plan(tmp_path, contains=("definition",)))


# --------------------------------------------------------------------------
# Retries
# --------------------------------------------------------------------------


def test_a_transient_failure_is_retried_and_the_attempt_is_recorded(tmp_path):
    calls = {"n": 0}

    def flaky(plan, target: Path) -> TransportResult:
        calls["n"] += 1
        if calls["n"] < 3:
            raise FetchError("connection reset")
        target.write_bytes(b"payload")
        return TransportResult()

    result = fetch(_plan(tmp_path), transport=flaky, attempts=4, now=_at())

    assert calls["n"] == 3
    assert result.attempts == 3
    assert result.metadata["attempts"] == 3


def test_the_attempt_bound_is_honoured(tmp_path):
    calls = {"n": 0}

    def always_fails(plan, target: Path) -> TransportResult:
        calls["n"] += 1
        raise FetchError("nope")

    with pytest.raises(FetchError, match="giving up after 3 attempt"):
        fetch(_plan(tmp_path), transport=always_fails, attempts=3, now=_at())

    assert calls["n"] == 3, "a bound nothing counts is a bound nobody has checked"


def test_a_validation_failure_is_retried_too(tmp_path):
    """A truncated response is exactly what a retry is for."""
    calls = {"n": 0}

    def truncated_then_whole(plan, target: Path) -> TransportResult:
        calls["n"] += 1
        target.write_bytes(b"" if calls["n"] == 1 else b"payload")
        return TransportResult()

    assert fetch(_plan(tmp_path), transport=truncated_then_whole, now=_at()).attempts == 2


def test_zero_attempts_is_refused(tmp_path):
    with pytest.raises(ValueError, match="at least 1"):
        fetch(_plan(tmp_path), transport=_writes(b"x"), attempts=0)


def test_the_final_error_says_what_actually_went_wrong(tmp_path):
    with pytest.raises(FetchError, match="connection reset"):
        fetch(_plan(tmp_path), transport=_fails(), attempts=2, now=_at())


# --------------------------------------------------------------------------
# Promotion
# --------------------------------------------------------------------------


def test_a_successful_fetch_replaces_the_destination(tmp_path):
    plan = _plan(tmp_path)

    fetch(plan, transport=_writes(b"new"), now=_at())

    assert plan.destination.read_bytes() == b"new"


def test_a_failed_fetch_leaves_the_previous_release_untouched(tmp_path):
    """The whole reason for downloading to a sibling temporary file: a
    half-written release in place is indistinguishable from a good one."""
    plan = _plan(tmp_path)
    plan.destination.write_bytes(b"previous")

    with pytest.raises(FetchError):
        fetch(plan, transport=_fails(), attempts=2, now=_at())

    assert plan.destination.read_bytes() == b"previous"


def test_a_validation_failure_leaves_the_previous_release_untouched(tmp_path):
    plan = _plan(tmp_path, sha256="00" * 32)
    plan.destination.write_bytes(b"previous")

    with pytest.raises(FetchError):
        fetch(plan, transport=_writes(b"new"), attempts=1, now=_at())

    assert plan.destination.read_bytes() == b"previous"
    assert not plan.sidecar.exists(), "no sidecar for a release that never landed"


def test_no_temporary_files_survive_a_failure(tmp_path):
    plan = _plan(tmp_path)

    with pytest.raises(FetchError):
        fetch(plan, transport=_fails(), attempts=2, now=_at())

    assert list(tmp_path.iterdir()) == []


def test_an_existing_mode_is_preserved(tmp_path):
    plan = _plan(tmp_path)
    plan.destination.write_bytes(b"old")
    os.chmod(plan.destination, 0o600)

    fetch(plan, transport=_writes(b"new"), now=_at())

    assert stat.S_IMODE(plan.destination.stat().st_mode) == 0o600


def test_a_new_file_gets_the_public_default_mode(tmp_path):
    plan = _plan(tmp_path)

    fetch(plan, transport=_writes(b"new"), now=_at())

    assert stat.S_IMODE(plan.destination.stat().st_mode) == 0o644


def test_a_missing_destination_directory_is_created(tmp_path):
    plan = FetchPlan(url="https://example.org/x", destination=tmp_path / "a" / "b" / "x")

    fetch(plan, transport=_writes(b"x"), now=_at())

    assert plan.destination.is_file()


# --------------------------------------------------------------------------
# Provenance
# --------------------------------------------------------------------------


def test_the_sidecar_records_what_was_fetched(tmp_path):
    plan = _plan(tmp_path)

    fetch(
        plan,
        transport=_writes(
            b"payload",
            resolved_url="https://cdn.example.org/x.tsv",
            headers={"etag": "W/\"abc\"", "content-type": "text/tab-separated-values"},
        ),
        now=_at(),
    )
    recorded = json.loads(plan.sidecar.read_text(encoding="utf-8"))

    assert recorded["sha256"] == hashlib.sha256(b"payload").hexdigest()
    assert recorded["bytes"] == 7
    assert recorded["requested_url"] == "https://example.org/x.tsv"
    assert recorded["resolved_url"] == "https://cdn.example.org/x.tsv"
    assert recorded["etag"] == 'W/"abc"'
    assert recorded["content_type"] == "text/tab-separated-values"
    assert recorded["fetched_at"] == "2026-08-29T12:00:00+00:00"


def test_the_recorded_time_is_timezone_aware_utc(tmp_path):
    plan = _plan(tmp_path)

    fetch(plan, transport=_writes(b"x"), now=_at())
    recorded = json.loads(plan.sidecar.read_text(encoding="utf-8"))

    assert datetime.fromisoformat(recorded["fetched_at"]).tzinfo is not None


def test_absent_headers_are_omitted_rather_than_recorded_empty(tmp_path):
    plan = _plan(tmp_path)

    fetch(plan, transport=_writes(b"x"), now=_at())
    recorded = json.loads(plan.sidecar.read_text(encoding="utf-8"))

    assert "etag" not in recorded and "content_type" not in recorded


# --------------------------------------------------------------------------
# A torn promotion is detectable
# --------------------------------------------------------------------------


def test_verify_accepts_a_matching_pair(tmp_path):
    plan = _plan(tmp_path)
    fetch(plan, transport=_writes(b"payload"), now=_at())

    assert verify(plan.destination) is None


def test_verify_detects_a_sidecar_from_a_different_fetch(tmp_path):
    """Two files cannot be replaced in one atomic step. A process that dies
    between them leaves silently wrong provenance, which is worse than none."""
    plan = _plan(tmp_path)
    fetch(plan, transport=_writes(b"payload"), now=_at())
    plan.destination.write_bytes(b"a later payload")

    complaint = verify(plan.destination)

    assert complaint and "written by different fetches" in complaint


@pytest.mark.parametrize(
    ("prepare", "expected"),
    [
        (lambda d, s: None, "does not exist"),
        (lambda d, s: d.write_bytes(b"x"), "no provenance sidecar"),
        (lambda d, s: (d.write_bytes(b"x"), s.write_text("{broken")), "cannot read"),
        (lambda d, s: (d.write_bytes(b"x"), s.write_text("[]")), "not a JSON object"),
        (lambda d, s: (d.write_bytes(b"x"), s.write_text("{}")), "records no sha256"),
    ],
)
def test_verify_names_what_is_wrong(tmp_path, prepare, expected):
    destination = tmp_path / "x.tsv"
    prepare(destination, Path(f"{destination}.fetch.json"))

    complaint = verify(destination)

    assert complaint and expected in complaint


# --------------------------------------------------------------------------
# The default transport
# --------------------------------------------------------------------------


def test_the_curl_transport_does_not_delegate_retries(tmp_path):
    """Retries are counted here so they can be observed. `curl --retry` would
    hide them inside one attempt and the bound would be unverifiable.

    Written first against the class's source text, which matched the docstring
    saying `--retry` is absent -- a test that passes on a comment. Reading the
    command it actually builds is the only version that checks anything.
    """
    command = CurlTransport().command(
        _plan(tmp_path), tmp_path / "t", tmp_path / "h"
    )

    assert "--retry" not in command
    assert "--fail" in command, "an HTTP error must not be written out as content"
    assert command[-2:] == ["--", "https://example.org/x.tsv"], (
        "the URL must follow `--`, so one beginning with a dash cannot be read "
        "as a flag"
    )


def test_the_curl_transport_passes_requested_headers(tmp_path):
    command = CurlTransport().command(
        _plan(tmp_path, headers=("Accept: text/plain",)), tmp_path / "t", tmp_path / "h"
    )

    assert "--header" in command
    assert "Accept: text/plain" in command


def test_a_missing_curl_is_reported_as_a_fetch_error(tmp_path, monkeypatch):
    def absent(*args, **kwargs):
        raise FileNotFoundError("curl")

    monkeypatch.setattr("kg_microbe_sources.fetch.subprocess.run", absent)

    with pytest.raises(FetchError, match="curl is not installed"):
        CurlTransport()(_plan(tmp_path), tmp_path / "t")


def test_sha256_of_reads_a_large_file_in_blocks(tmp_path):
    path = tmp_path / "big"
    payload = b"x" * (1024 * 1024 + 7)
    path.write_bytes(payload)

    assert sha256_of(path) == hashlib.sha256(payload).hexdigest()


def test_a_crash_between_the_two_renames_leaves_the_new_payload_not_the_old(
    tmp_path, monkeypatch
):
    """Two files cannot be replaced in one atomic step, so the order is a
    choice about which way it tears.

    `verify` catches either direction, so the code comment first justified this
    order by claiming only one was detectable -- which was simply wrong, and
    nothing tested it. The real asymmetry: payload-first leaves the NEW data
    with stale provenance, while sidecar-first leaves the OLD data with
    provenance claiming it is new. Every consumer that reads the file and not
    the sidecar -- most of them -- silently gets last release's bytes.
    """
    plan = _plan(tmp_path)
    plan.destination.write_bytes(b"previous")

    real_replace = os.replace
    calls = {"n": 0}

    def replace_then_die(source, target):
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("power loss between the two renames")
        real_replace(source, target)

    monkeypatch.setattr("kg_microbe_sources.fetch.os.replace", replace_then_die)

    with pytest.raises(OSError, match="power loss"):
        fetch(plan, transport=_writes(b"new"), attempts=1, now=_at())

    assert plan.destination.read_bytes() == b"new", (
        "the payload must be the file that landed; the other order would serve "
        "the previous release while the sidecar claimed otherwise"
    )
    assert verify(plan.destination) is not None, "and the tear must be visible"


def test_the_package_does_not_shadow_the_fetch_module():
    """Re-exporting a function named `fetch` from a module named `fetch` binds
    that name on the package and hides the module, so
    `import kg_microbe_sources.fetch` and every `monkeypatch.setattr` into it
    stop resolving. Two tests here broke exactly that way."""
    import kg_microbe_sources
    import kg_microbe_sources.fetch as module

    assert module.__name__ == "kg_microbe_sources.fetch"
    assert not hasattr(kg_microbe_sources, "fetch") or callable(
        getattr(kg_microbe_sources, "fetch")
    ) is False
    # The rest of the API is still reachable from the package.
    assert kg_microbe_sources.verify is module.verify
