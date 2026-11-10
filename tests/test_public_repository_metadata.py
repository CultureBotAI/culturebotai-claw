"""Exercise the production public metadata transport, never a fake get method."""

import io
import json
import socket
import urllib.error
from pathlib import Path

import pytest

from kg_microbe_governance import automatic_fleet_component as component
from kg_microbe_governance import private_scaleup_audit as manual
from kg_microbe_governance import public_repository_metadata as metadata

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = "CultureBotAI/PublicMech"


class Response(io.BytesIO):
    status = 200


class Opener:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error
        self.calls = []

    def open(self, request, timeout):
        self.calls.append(request.full_url)
        assert request.get_method() == "GET" and timeout == 30
        assert not request.has_header("Authorization")
        assert request.full_url.startswith("https://api.github.com/repos/")
        if self.error:
            raise self.error
        name = request.full_url.removeprefix("https://api.github.com/repos/")
        raw = self.payload
        if raw is None:
            raw = json.dumps({"full_name": name, "private": False, "default_branch": "main"}).encode()
        return Response(raw)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def fail(*args, **kwargs):
        raise AssertionError("Live network is forbidden")
    monkeypatch.setattr(socket.socket, "connect", fail)
    monkeypatch.setattr(socket, "create_connection", fail)


def client(monkeypatch, **kwargs):
    opener = Opener(**kwargs)
    def build(*handlers):
        assert len(handlers) == 1 and isinstance(handlers[0], manual.NoRedirect)
        assert handlers[0].redirect_request(None, None, 302, None, None, None) is None
        return opener
    monkeypatch.setattr(metadata.urllib.request, "build_opener", build)
    return metadata.PublicRepositoryMetadata({PUBLIC}), opener


def test_anonymous_exact_public_metadata(monkeypatch):
    actual, opener = client(monkeypatch)
    assert actual.get(PUBLIC) == {"full_name": PUBLIC, "private": False, "default_branch": "main"}
    assert opener.calls == ["https://api.github.com/repos/" + PUBLIC]


@pytest.mark.parametrize("route", [
    "CultureBotAI/Unknown", manual.PRIVATE, PUBLIC + "/contents", PUBLIC + "?x=1",
    PUBLIC + "#x", PUBLIC + "\n", PUBLIC + "%2Fcontents", "/repos/" + PUBLIC,
    "https://api.github.com/repos/" + PUBLIC, PUBLIC.lower(), None, [],
])
def test_only_exact_admitted_repository_argument_reaches_opener(monkeypatch, route):
    actual, opener = client(monkeypatch)
    with pytest.raises(manual.AuditError, match="transport_refused"):
        actual.get(route)
    assert opener.calls == []


@pytest.mark.parametrize("name", [
    manual.PRIVATE, manual.PRIVATE.lower(), PUBLIC + "/child", PUBLIC + "?x=1",
    PUBLIC + "%2fchild", PUBLIC + "#fragment", "../PublicMech", "//host/repo",
    "CultureBotAI/..", "CultureBotAI/", "CultureBotAI/PublicMech\r", None,
])
def test_invalid_or_reserved_allowlist_is_refused_before_opener(monkeypatch, name):
    def fail(*args):
        raise AssertionError("Invalid allowlist built an opener")
    monkeypatch.setattr(metadata.urllib.request, "build_opener", fail)
    with pytest.raises(manual.AuditError, match="transport_refused"):
        metadata.PublicRepositoryMetadata([name])


@pytest.mark.parametrize("change", ["missing", "null", "true", "zero", "name", "branch"])
def test_nonpublic_or_mismatched_metadata_never_clones(monkeypatch, tmp_path, change):
    value = {"full_name": PUBLIC, "private": False, "default_branch": "main"}
    if change == "missing":
        del value["private"]
    elif change in {"null", "true", "zero"}:
        value["private"] = {"null": None, "true": True, "zero": 0}[change]
    elif change == "name":
        value["full_name"] = PUBLIC + "-other"
    else:
        value["default_branch"] = "other"
    actual, opener = client(monkeypatch, payload=json.dumps(value).encode())
    with pytest.raises(manual.AuditError):
        actual.get(PUBLIC)
    assert len(opener.calls) == 1


@pytest.mark.parametrize("raw", [b"not-json", b"[]", b"null", b'{"private":false,"private":true}', b" " * (metadata.MAX_METADATA_BYTES + 1)])
def test_invalid_bounded_response_fails(monkeypatch, raw):
    actual, _ = client(monkeypatch, payload=raw)
    with pytest.raises(manual.AuditError):
        actual.get(PUBLIC)


@pytest.mark.parametrize("status", [301, 302, 307, 403, 404, 500])
def test_redirect_or_http_failure_is_not_followed(monkeypatch, status):
    actual, opener = client(monkeypatch, error=urllib.error.HTTPError(
        "https://api.github.com/repos/" + PUBLIC, status, "synthetic", {"Location": "https://example.invalid"}, None))
    with pytest.raises(manual.AuditError):
        actual.get(PUBLIC)
    assert len(opener.calls) == 1


def test_strict_manual_transport_still_refuses_public_consumer(monkeypatch):
    opener = Opener()
    monkeypatch.setattr(manual.urllib.request, "build_opener", lambda *args: opener)
    strict = manual.GitHubRead("synthetic-placeholder")
    with pytest.raises(manual.AuditError, match="transport_refused"):
        strict.get("/repos/" + PUBLIC)
    assert opener.calls == []


def test_actual_clone_entry_composes_real_public_transport(monkeypatch, tmp_path):
    # The same production client/callsite that failed #1168 uses a real
    # transport with only the network opener replaced. No API .get is patched.
    opener = Opener()
    monkeypatch.setattr(metadata.urllib.request, "build_opener", lambda *args: opener)
    strict = manual.GitHubRead("synthetic-placeholder")
    model = component.parse_manifest((ROOT / component.auto.MANIFEST_PATH).read_bytes())
    calls = []
    monkeypatch.setattr(component, "git", lambda root, *args: calls.append(args) or "")
    roots = component.clone_public(strict, tmp_path / "clones", {"protected": model, "candidate": model})
    expected = {consumer.github for key, consumer in model.consumers.items() if key != "scaleupmech"}
    assert set(opener.calls) == {"https://api.github.com/repos/" + name for name in expected}
    assert len(opener.calls) == len(expected) == len(roots)
    assert {args[-2] for args in calls if args[0] == "clone"} == {"https://github.com/" + name + ".git" for name in expected}
