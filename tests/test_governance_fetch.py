"""Bounded-fetch and retry-status contracts for the standalone checker."""

from __future__ import annotations

from typing import Any

import pytest

from kg_microbe_governance.artifacts.scripts import check_vendored_sync as checker

RAW_URL = (
    "https://raw.githubusercontent.com/CultureBotAI/culturebotai-claw/"
    + "a" * 40
    + "/src/kg_microbe_governance/vendored_artifacts.json"
)


class _Response:
    def __init__(
        self,
        *,
        url: str = RAW_URL,
        headers: dict[str, str] | None = None,
        chunks: tuple[bytes, ...] = (b"payload", b""),
    ) -> None:
        self._url = url
        self.headers = headers or {}
        self._chunks = iter(chunks)

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_args: Any) -> None:
        return None

    def geturl(self) -> str:
        return self._url

    def read(self, _size: int) -> bytes:
        return next(self._chunks)


def test_fetch_returns_bytes_from_bounded_chunk_loop(monkeypatch) -> None:
    monkeypatch.setattr(checker.urllib.request, "urlopen", lambda *_a, **_k: _Response())
    assert checker.fetch_url(RAW_URL) == b"payload"


def test_fetch_rejects_redirect_outside_raw_github(monkeypatch) -> None:
    monkeypatch.setattr(
        checker.urllib.request,
        "urlopen",
        lambda *_a, **_k: _Response(url="https://example.invalid/payload"),
    )
    with pytest.raises(checker.CanonicalFetchError, match="redirected outside"):
        checker.fetch_url(RAW_URL)


def test_redirect_diagnostic_never_echoes_userinfo_path_or_query(monkeypatch) -> None:
    secret_url = "https://user:token@example.invalid/private?api_key=secret"
    monkeypatch.setattr(
        checker.urllib.request,
        "urlopen",
        lambda *_a, **_k: _Response(url=secret_url),
    )

    with pytest.raises(checker.CanonicalFetchError) as caught:
        checker.fetch_url(RAW_URL)

    message = str(caught.value)
    assert "https://example.invalid" in message
    assert "user:token" not in message
    assert "/private" not in message
    assert "api_key=secret" not in message


def test_fetch_enforces_total_deadline_between_chunks(monkeypatch) -> None:
    moments = iter((10.0, 10.1, 11.1))
    monkeypatch.setattr(checker.time, "monotonic", lambda: next(moments))
    monkeypatch.setattr(
        checker.urllib.request,
        "urlopen",
        lambda *_a, **_k: _Response(chunks=(b"partial", b"never-read")),
    )
    with pytest.raises(checker.CanonicalFetchError, match="exceeded 1 seconds"):
        checker.fetch_url(RAW_URL, timeout=1)


def test_fetch_failure_uses_retryable_exit_one(monkeypatch, capsys) -> None:
    def unavailable(*_args: Any, **_kwargs: Any) -> tuple[int, tuple[str, ...]]:
        raise checker.CanonicalFetchError("offline fixture")

    monkeypatch.setattr(checker, "check_repository", unavailable)
    assert checker.main(["--root", "/does/not/matter"]) == 1
    assert "FETCH ERROR" in capsys.readouterr().err


def test_local_precondition_failure_remains_exit_two(monkeypatch, capsys) -> None:
    def invalid(*_args: Any, **_kwargs: Any) -> tuple[int, tuple[str, ...]]:
        raise checker.GovernanceError("bad pin fixture")

    monkeypatch.setattr(checker, "check_repository", invalid)
    assert checker.main(["--root", "/does/not/matter"]) == 2
    assert "ERROR: bad pin fixture" in capsys.readouterr().err
