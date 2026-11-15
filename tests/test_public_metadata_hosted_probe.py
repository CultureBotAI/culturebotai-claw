"""The hosted diagnostic performs one anonymous bounded request, never an audit."""

import importlib.util
import io
import json
import urllib.error
from pathlib import Path

import pytest


@pytest.fixture
def probe(tmp_path, monkeypatch):
    source = Path(__file__).parents[1] / "scripts/adhoc/probe_public_metadata_hosted_20261115.py"
    spec = importlib.util.spec_from_file_location("hosted_metadata_probe", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "STATE", tmp_path)
    return module, tmp_path / "receipt.json"


def test_plan_never_opens_network_or_output(probe, monkeypatch):
    module, output = probe

    def refused(*args):
        raise AssertionError("plan attempted network")

    monkeypatch.setattr(module.metadata.PublicRepositoryMetadata, "get", refused)
    receipt, code = module.probe(output, plan=True)
    assert code == 0 and receipt["executed_requests"] == 0
    assert not output.exists()


@pytest.mark.parametrize("http_failure", [False, True])
def test_actual_client_persists_closed_result_and_refuses_overwrite(probe, monkeypatch, http_failure):
    module, output = probe
    calls = []
    sentinel = "private-response-sentinel"

    class Response(io.BytesIO):
        status = 200
        headers = {}

    class Opener:
        def open(self, request, timeout):
            assert request.full_url == "https://api.github.com/repos/CultureBotAI/AIMech"
            assert request.get_method() == "GET" and timeout == 30
            assert not request.has_header("Authorization")
            calls.append(request.full_url)
            if http_failure:
                raise urllib.error.HTTPError(
                    request.full_url, 403, sentinel,
                    {"X-RateLimit-Remaining": "0", "Location": sentinel},
                    io.BytesIO(sentinel.encode()),
                )
            return Response(json.dumps({
                "full_name": "CultureBotAI/AIMech", "private": False,
                "default_branch": "main", "description": sentinel,
            }).encode())

    monkeypatch.setattr(module.metadata.urllib.request, "build_opener", lambda *args: Opener())
    receipt, code = module.probe(output)
    assert len(calls) == 1 and receipt["executed_requests"] == 1
    assert code == (2 if http_failure else 0)
    assert json.loads(output.read_bytes()) == receipt
    assert sentinel not in output.read_text()
    assert receipt["inputs_unchanged"] is True
    if http_failure:
        assert "http_status=403" in receipt["diagnostic"]
        assert "rate_remaining=0" in receipt["diagnostic"]
    with pytest.raises(ValueError, match="new private diagnostic"):
        module.probe(output)
    assert len(calls) == 1
