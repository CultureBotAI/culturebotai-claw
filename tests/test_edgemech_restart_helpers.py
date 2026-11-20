"""Offline authorization, identity and provenance controls for EdgeMech#228."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
DIRECTORY = ROOT / "scripts/adhoc/edgemech_restart_20261120"


def load(name):
    spec = importlib.util.spec_from_file_location(name, DIRECTORY / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


trust = load("answer_exact_trust_once")
prepare = load("prepare_coordinator")


@pytest.fixture
def invocation(tmp_path):
    receipt = tmp_path / "consumed.json"
    binding = {"pane": "%9", "checkout": str(tmp_path / "checkout"),
               "session_name": "test-coordinator", "pane_pid": "1234", "pane_tty": "/dev/pts/9",
               "tmux_binary": "/fixture/tmux", "tmux_socket": str(tmp_path / "server.sock")}
    authorization = {"source": "explicit_user_response", "action": "Trust and continue",
                     "pane": binding["pane"], "checkout": binding["checkout"], "receipt": str(receipt)}
    auth_file, bind_file = tmp_path / "authorization.json", tmp_path / "binding.json"
    bind_file.write_text(json.dumps(binding))
    authorization["binding_sha256"] = hashlib.sha256(bind_file.read_bytes()).hexdigest()
    auth_file.write_text(json.dumps(authorization))
    return dict(authorization_file=auth_file, binding_file=bind_file, receipt=receipt,
                tmux_binary=Path("/fixture/tmux"), tmux_socket=tmp_path / "server.sock", apply=True)


def trust_panel(checkout):
    return (
        "Folder access\n" + checkout + "\n\n"
        "Trust this folder? Codex can read, edit, and run files here, subject to your\n"
        "permission settings. Folder settings can run code automatically, even\n"
        "without a model request. Continue only if you trust these files. Your trust\n"
        "decision will be saved.\n\n› 1. Trust and continue\n"
        "2. Back to Agent Command Center\n\nenter continue · esc back\n"
    )


def fake_tmux(monkeypatch, invocation, *, returncode=0, wrong_binding=False, screen=None):
    binding = json.loads(invocation["binding_file"].read_bytes())
    prompt = screen or trust_panel(binding["checkout"])
    calls = []

    def output(argv, **kwargs):
        calls.append(argv)
        if "display-message" in argv:
            values = [binding[k] for k in ("session_name", "pane_pid", "pane_tty", "checkout")]
            if wrong_binding:
                values[1] = "9999"
            return "|".join(values)
        return prompt

    def run(argv, **kwargs):
        calls.append(argv)
        saved = json.loads(invocation["receipt"].read_bytes())
        assert saved["state"] == "ONE_SHOT_CONSUMED_BEFORE_INPUT"
        return subprocess.CompletedProcess(argv, returncode, stdout="", stderr="")

    monkeypatch.setattr(trust.subprocess, "check_output", output)
    monkeypatch.setattr(trust.subprocess, "run", run)
    return calls


@pytest.mark.parametrize("field,value", [
    ("source", "inferred_permission"), ("action", "Allow once"), ("pane", "%10"),
    ("checkout", "/different/checkout"), ("receipt", "/different/receipt.json"),
])
def test_wrong_authorization_never_reaches_tmux(invocation, monkeypatch, field, value):
    doc = json.loads(invocation["authorization_file"].read_bytes())
    doc[field] = value
    invocation["authorization_file"].write_text(json.dumps(doc))
    monkeypatch.setattr(trust.subprocess, "check_output", lambda *a, **k: pytest.fail("tmux called"))
    with pytest.raises(ValueError):
        trust.answer(**invocation)
    assert not invocation["receipt"].exists()


def test_requires_explicit_apply(invocation, monkeypatch):
    invocation["apply"] = False
    monkeypatch.setattr(trust.subprocess, "check_output", lambda *a, **k: pytest.fail("tmux called"))
    with pytest.raises(ValueError, match="--apply"):
        trust.answer(**invocation)


def test_exact_binding_failure_before_consumption(invocation, monkeypatch):
    calls = fake_tmux(monkeypatch, invocation, wrong_binding=True)
    with pytest.raises(ValueError, match="Live session"):
        trust.answer(**invocation)
    assert not invocation["receipt"].exists()
    assert not any("send-keys" in call for call in calls)


@pytest.mark.parametrize("extra", ["Sign in", "Update available", "Allow once"])
def test_unrelated_prompt_refused(invocation, monkeypatch, extra):
    binding = json.loads(invocation["binding_file"].read_bytes())
    prompt = trust_panel(binding["checkout"]) + "\n" + extra
    fake_tmux(monkeypatch, invocation, screen=prompt)
    with pytest.raises(ValueError, match="exact visible"):
        trust.answer(**invocation)
    assert not invocation["receipt"].exists()


def test_checkout_substring_is_not_exact_display(invocation, monkeypatch):
    binding = json.loads(invocation["binding_file"].read_bytes())
    prompt = trust_panel(binding["checkout"] + "-other")
    fake_tmux(monkeypatch, invocation, screen=prompt)
    with pytest.raises(ValueError, match="exact visible"):
        trust.answer(**invocation)


@pytest.mark.parametrize("returncode", [0, 1])
def test_consumption_precedes_single_input_and_prevents_retry(invocation, monkeypatch, returncode):
    calls = fake_tmux(monkeypatch, invocation, returncode=returncode)
    if returncode:
        with pytest.raises(ValueError, match="do not retry"):
            trust.answer(**invocation)
    else:
        outcome = trust.answer(**invocation)
        assert outcome["continuation_verified"] is False
        assert outcome["state"] == "INPUT_COMMAND_SUCCEEDED_CONTINUATION_UNPROVEN"
        assert "screen_after_sha256" in outcome
    assert len([call for call in calls if "send-keys" in call]) == 1
    saved = json.loads(invocation["receipt"].read_bytes())
    assert saved["state"] == "ONE_SHOT_CONSUMED_BEFORE_INPUT"
    assert "helper_sha256" in saved
    with pytest.raises(ValueError, match="no retry"):
        trust.answer(**invocation)
    assert len([call for call in calls if "send-keys" in call]) == 1


def test_receipt_exclusive_race_never_sends(invocation, monkeypatch):
    calls = fake_tmux(monkeypatch, invocation)
    original = trust.validate_live_binding

    def race(actual, binding):
        original(actual, binding)
        invocation["receipt"].write_text("other consumption")

    monkeypatch.setattr(trust, "validate_live_binding", race)
    with pytest.raises(FileExistsError):
        trust.answer(**invocation)
    assert not any("send-keys" in call for call in calls)


def test_control_client_requires_explicit_authorization(invocation, monkeypatch):
    binding = json.loads(invocation["binding_file"].read_bytes())
    binding["control_client"] = "test-normal-client"
    invocation["binding_file"].write_text(json.dumps(binding))
    auth = json.loads(invocation["authorization_file"].read_bytes())
    auth["binding_sha256"] = hashlib.sha256(invocation["binding_file"].read_bytes()).hexdigest()
    invocation["authorization_file"].write_text(json.dumps(auth))
    fake_tmux(monkeypatch, invocation)
    with pytest.raises(ValueError, match="control-client"):
        trust.answer(**invocation)
    auth = json.loads(invocation["authorization_file"].read_bytes())
    auth["control_client"] = binding["control_client"]
    invocation["authorization_file"].write_text(json.dumps(auth))
    calls = fake_tmux(monkeypatch, invocation)
    trust.answer(**invocation)
    send = next(call for call in calls if "send-keys" in call)
    assert send[send.index("-c") + 1] == "test-normal-client"


@pytest.mark.parametrize("field", ["session_name", "pane_pid", "pane_tty", "checkout"])
def test_each_binding_component_is_exact(invocation, field):
    binding = json.loads(invocation["binding_file"].read_bytes())
    actual = dict(binding)
    actual[field] += "-different"
    with pytest.raises(ValueError, match="Live session"):
        trust.validate_live_binding("|".join(actual[k] for k in
                                   ("session_name", "pane_pid", "pane_tty", "checkout")), binding)


def test_selected_commit_and_docs_only_delta():
    selected = {"headRefOid": "a" * 40}
    prepare.validate_delta(selected, "a" * 40, ["docs/plan.md"])
    with pytest.raises(ValueError, match="selected commit"):
        prepare.validate_delta(selected, "b" * 40, ["docs/plan.md"])
    with pytest.raises(ValueError, match="documentation-only"):
        prepare.validate_delta(selected, "a" * 40, ["docs/plan.md", "src/runner.py"])


@pytest.mark.parametrize("bad", ["abc", "HEAD", "a" * 39, "g" * 40])
def test_selection_requires_full_commit(tmp_path, bad):
    path = tmp_path / "selection.json"
    path.write_text(json.dumps({"headRefOid": bad, "headRefName": "docs/review"}))
    with pytest.raises(ValueError, match="Full selected"):
        prepare.selection(path)


def test_prepare_uses_resolved_target_lease_and_actual_receipt(tmp_path, monkeypatch):
    selected = tmp_path / "selected.json"
    selected.write_text(json.dumps({"headRefOid": "a" * 40, "headRefName": "docs/review"}))
    prior = tmp_path / "prior.json"
    prior.write_text(json.dumps({"headRefOid": "b" * 40, "headRefName": "code/review"}))
    request = tmp_path / "REQUEST.md"
    request.write_text("Explicit test request")
    receipt, destination = tmp_path / "receipt.json", tmp_path / "coordinator"
    state = {"lease": False, "calls": []}
    repo = SimpleNamespace(is_dirty=lambda **kwargs: False, head=SimpleNamespace(commit=SimpleNamespace(hexsha="c" * 40)))
    target = SimpleNamespace(path=tmp_path / "canonical", expected_repository="CultureBotAI/EdgeMech", open=lambda: repo)
    monkeypatch.setattr(prepare.RepositorySettings, "from_environment",
                        lambda **kwargs: SimpleNamespace(get_target=lambda key: target))
    monkeypatch.setattr(prepare, "RepositoryTarget", lambda *args: SimpleNamespace(open=lambda: repo))
    monkeypatch.setattr(prepare, "merged_repository_environment", lambda *args: {"OPENCLAW_WORKSPACE": str(tmp_path / "workspace")})

    @contextmanager
    def lock(name, operation):
        assert name == "edgemech"
        state["lease"] = True
        yield
        state["lease"] = False

    def manager(config):
        assert config == {"locks_dir": str(tmp_path / "workspace" / "locks")}
        return SimpleNamespace(lock=lock)

    monkeypatch.setattr(prepare, "LockManager", manager)

    def run(argv, cwd=None):
        state["calls"].append(argv)
        if argv[:2] == ["git", "clone"]:
            assert state["lease"]
            destination.mkdir()
        if "FETCH_HEAD" in argv:
            return "a" * 40 + "\n"
        if "diff" in argv:
            return "docs/review.md\n"
        return ""

    monkeypatch.setattr(prepare, "run", run)
    result = prepare.prepare(claw_root=tmp_path, selection_file=selected, prior_selection_file=prior,
                             request=request, destination=destination, branch="campaign/test",
                             receipt=receipt, apply=True)
    assert result["head"] == "a" * 40
    assert result["canonical_root"] == str(target.path)
    assert result["inputs"]["request"]["sha256"] == hashlib.sha256(request.read_bytes()).hexdigest()
    assert result["inputs"]["selection"]["sha256"] == hashlib.sha256(selected.read_bytes()).hexdigest()
    assert result == json.loads(receipt.read_bytes())
    assert state["lease"] is False
    with pytest.raises(ValueError, match="Fresh destination"):
        prepare.prepare(claw_root=tmp_path, selection_file=selected, prior_selection_file=prior,
                        request=request, destination=destination, branch="campaign/test",
                        receipt=receipt, apply=True)


@pytest.mark.parametrize("field", ["session_name", "pane_pid", "pane_tty", "tmux_socket"])
def test_binding_retarget_cannot_reuse_authorization(invocation, monkeypatch, field):
    binding = json.loads(invocation["binding_file"].read_bytes())
    binding[field] += "-different"
    invocation["binding_file"].write_text(json.dumps(binding))
    monkeypatch.setattr(trust.subprocess, "check_output", lambda *a, **k: pytest.fail("tmux called"))
    with pytest.raises(ValueError, match="binding digest"):
        trust.answer(**invocation)


def test_old_trust_panel_followed_by_current_prompt_is_refused(invocation, monkeypatch):
    binding = json.loads(invocation["binding_file"].read_bytes())
    calls = fake_tmux(monkeypatch, invocation, screen=trust_panel(binding["checkout"]) + "\nRun shell command?\n1. Yes\n2. No")
    with pytest.raises(ValueError, match="exact visible"):
        trust.answer(**invocation)
    assert not any("send-keys" in call for call in calls)
    assert all("-S" not in call[4:] for call in calls if "capture-pane" in call)


def test_cli_cannot_retarget_authorized_socket(invocation, monkeypatch):
    invocation["tmux_socket"] = Path("/different/server.sock")
    monkeypatch.setattr(trust.subprocess, "check_output", lambda *a, **k: pytest.fail("tmux called"))
    with pytest.raises(ValueError, match="transport mismatch"):
        trust.answer(**invocation)


def test_consumption_is_fsynced_before_input(invocation, monkeypatch):
    fake_tmux(monkeypatch, invocation)
    synced = []
    monkeypatch.setattr(trust.os, "fsync", lambda fd: synced.append(fd))
    def run(argv, **kwargs):
        assert len(synced) == 2
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
    monkeypatch.setattr(trust.subprocess, "run", run)
    trust.answer(**invocation)
