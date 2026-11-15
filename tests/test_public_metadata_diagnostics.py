"""Keep #1223 failures fatal while exposing only bounded public metadata facts."""

import io
import json
import socket
import urllib.error

import pytest

from kg_microbe_governance import automatic_fleet_component as component
from kg_microbe_governance import automatic_private_audit_cli as cli
from kg_microbe_governance import private_scaleup_audit as manual
from kg_microbe_governance import public_repository_metadata as metadata

PUBLIC = "CultureBotAI/PublicMech"
SENTINEL = "secret-response-credential-sentinel"
SHA = "a" * 40


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("Live network is forbidden")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def invoke(monkeypatch, tmp_path, capsys, error):
    """Exercise real CLI formatting and real metadata get; replace only HTTP I/O."""
    calls = []

    class Opener:
        def open(self, request, timeout):
            assert request.full_url == "https://api.github.com/repos/" + PUBLIC
            assert request.get_method() == "GET" and timeout == 30
            assert not request.has_header("Authorization")
            calls.append(request.full_url)
            raise error

    def build(*handlers):
        assert len(handlers) == 1 and isinstance(handlers[0], manual.NoRedirect)
        return Opener()

    monkeypatch.setattr(metadata.urllib.request, "build_opener", build)
    monkeypatch.setattr(cli, "integer", lambda name: 1)
    monkeypatch.setattr(manual, "GitHubRead", lambda token: object())
    monkeypatch.setattr(cli, "protected_runtime", lambda *args: SHA)
    monkeypatch.setattr(component.auto, "parent_binding", lambda *a, **k: {"protected_main_sha": SHA})

    def fail(*args):
        with component.diagnostic_stage("public_metadata"):
            metadata.PublicRepositoryMetadata({PUBLIC}).get(PUBLIC)

    monkeypatch.setattr(component, "public_component", fail)
    output = tmp_path / "receipt.json"
    code = component.main([
        "--trusted-root", str(tmp_path), "--workspace", str(tmp_path / "workspace"),
        "--output", str(output), "--checkout-sha", SHA,
    ])
    captured = capsys.readouterr()
    assert code == 2 and not output.exists()
    assert len(calls) == 1 and captured.out == ""
    assert SENTINEL not in captured.err
    assert "https://" not in captured.err
    return captured.err


def test_native_cli_preserves_http_failure_with_bounded_diagnostics(monkeypatch, tmp_path, capsys):
    error = urllib.error.HTTPError(
        "https://example.invalid/" + SENTINEL, 403, SENTINEL,
        {"X-RateLimit-Limit": "60", "X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1794718296",
         "Location": "https://example.invalid/" + SENTINEL, "Authorization": SENTINEL},
        io.BytesIO(SENTINEL.encode()),
    )
    actual = invoke(monkeypatch, tmp_path, capsys, error)
    assert actual == (
        "public_fleet_component_failed stage=public_metadata code=transport_refused"
        " repository=CultureBotAI/PublicMech category=http_error http_status=403"
        " rate_limit=60 rate_remaining=0 rate_reset=1794718296\n"
    )


@pytest.mark.parametrize("status", [301, 302, 307, 403, 404, 429, 500])
def test_http_status_never_retries_follows_or_passes(monkeypatch, tmp_path, capsys, status):
    error = urllib.error.HTTPError("https://example.invalid/" + SENTINEL, status, SENTINEL,
                                   {"Location": "https://example.invalid/" + SENTINEL}, None)
    actual = invoke(monkeypatch, tmp_path, capsys, error)
    assert f"category=http_error http_status={status}\n" in actual


@pytest.mark.parametrize("error,category", [
    (TimeoutError(SENTINEL), "timeout"),
    (urllib.error.URLError(TimeoutError(SENTINEL)), "timeout"),
    (urllib.error.URLError(SENTINEL), "url_error"),
    (OSError(SENTINEL), "io_error"),
])
def test_connection_exception_text_never_printed(monkeypatch, tmp_path, capsys, error, category):
    actual = invoke(monkeypatch, tmp_path, capsys, error)
    assert actual.endswith(f"repository={PUBLIC} category={category}\n")


@pytest.mark.parametrize("value", [SENTINEL, "-1", "1.5", "١", "0\n" + SENTINEL,
                                   "4294967296", "123456789012345", 42, True])
def test_non_numeric_or_out_of_bounds_quota_omitted(monkeypatch, tmp_path, capsys, value):
    error = urllib.error.HTTPError("https://example.invalid/" + SENTINEL, 403, SENTINEL,
                                   {"X-RateLimit-Remaining": value}, None)
    actual = invoke(monkeypatch, tmp_path, capsys, error)
    assert actual.endswith("category=http_error http_status=403\n")


@pytest.mark.parametrize("field,value", [
    ("repository", "CultureBotAI/NotAdmitted"),
    ("repository", "https://example.invalid/" + SENTINEL),
    ("repository", manual.PRIVATE),
    ("category", SENTINEL), ("category", []),
    ("http_status", SENTINEL), ("http_status", True), ("http_status", 999),
    ("quota", {"rate_remaining": SENTINEL}), ("quota", {"secret": SENTINEL}),
    ("quota", {"rate_limit": True}), ("quota", {"rate_reset": -1}),
    ("admitted", None),
])
def test_forged_diagnostic_fields_fail_closed(field, value):
    error = metadata.PublicMetadataFailure(PUBLIC, "http_error", 403, {}, frozenset({PUBLIC}))
    setattr(error, field, value)
    assert metadata.diagnostic_suffix(error) == ""
    assert metadata.diagnostic_suffix(RuntimeError(SENTINEL)) == ""


def test_diagnostic_repository_size_is_bounded():
    repository = "CultureBotAI/" + "x" * 200
    error = metadata.PublicMetadataFailure(repository, "http_error", 403, {}, frozenset({repository}))
    assert metadata.diagnostic_suffix(error) == ""


@pytest.mark.parametrize("raw,category", [
    (b"not-json", "invalid_json"),
    (b" " * (metadata.MAX_METADATA_BYTES + 1), "response_too_large"),
    (json.dumps({"full_name": PUBLIC, "private": True, "default_branch": "main"}).encode(), "invalid_metadata"),
    (json.dumps({"full_name": PUBLIC + "-other", "private": False, "default_branch": "main"}).encode(), "invalid_metadata"),
    (json.dumps({"full_name": PUBLIC, "private": False, "default_branch": "other"}).encode(), "invalid_metadata"),
])
def test_response_validation_failures_keep_original_fatal_code(monkeypatch, raw, category):
    class Response(io.BytesIO):
        status = 200

    class Opener:
        def open(self, request, timeout):
            return Response(raw)

    monkeypatch.setattr(metadata.urllib.request, "build_opener", lambda *args: Opener())
    with pytest.raises(manual.AuditError) as caught:
        metadata.PublicRepositoryMetadata({PUBLIC}).get(PUBLIC)
    assert caught.value.code == "transport_refused"
    assert metadata.diagnostic_suffix(caught.value) == (
        f" repository={PUBLIC} category={category} http_status=200"
    )
