"""Behavioral regressions for canonical pin updates, not live action execution."""

from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from kg_microbe_governance import GovernanceError
from kg_microbe_governance.workflow_pins import (
    CONTRACT_PATH,
    MANIFEST_PATH,
    _walk,
    check_workflow_pins,
    load_pin_contract,
    render_workflow,
)
from scripts import update_governed_workflow_pins as updater

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = Path("src/kg_microbe_governance/artifacts/workflows/pr-shepherd.yml")


@pytest.fixture
def checkout(tmp_path: Path) -> Path:
    for path in (CONTRACT_PATH, MANIFEST_PATH, WORKFLOW):
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_bytes((ROOT / path).read_bytes())
    return tmp_path


def snapshot(root: Path) -> dict[Path, bytes]:
    return {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def test_shipped_governed_workflows_match_contract_and_ci_checks_it():
    check_workflow_pins(ROOT)
    workflow = yaml.safe_load((ROOT / ".github/workflows/tests.yaml").read_text())
    assert any(step.get("run") == "uv run python scripts/update_governed_workflow_pins.py --check"
               for step in workflow["jobs"]["pytest"]["steps"])
    assert "governed-workflow-pins *args:" in (ROOT / "justfile").read_text()


@pytest.mark.parametrize("mutation", [
    lambda s: s.replace("@3d3c42e5aac5ba805825da76410c181273ba90b1", "@v7"),
    lambda s: s.replace("@3d3c42e5aac5ba805825da76410c181273ba90b1", "@" + "a" * 39),
    lambda s: s.replace("@3d3c42e5aac5ba805825da76410c181273ba90b1", "@" + "a" * 40),
    lambda s: s.replace(" # v7.0.1", ""),
    lambda s: s.replace(" # v7.0.1", " # v4.0.0"),
    lambda s: s.replace("actions/checkout@", "someone/checkout@"),
    lambda s: s.replace('          version: "0.12.5"\n', ""),
    lambda s: s.replace('version: "0.12.5"', 'version: "latest"'),
    lambda s: s.replace("uses: actions/checkout@", "'uses': actions/checkout@v7 # "),
    lambda s: s.replace("      - name: Checkout", "      - uses: actions/checkout@v7\n        name: Checkout"),
    lambda s: s + "\nbad: [unterminated\n",
])
def test_ci_rejects_action_comment_runtime_or_yaml_mutation(checkout, mutation):
    path = checkout / WORKFLOW
    changed = mutation(path.read_text())
    assert changed != path.read_text()
    path.write_text(changed)
    with pytest.raises(GovernanceError):
        check_workflow_pins(checkout)


def test_checksum_gate_catches_non_pin_drift(checkout):
    path = checkout / WORKFLOW
    path.write_text(path.read_text() + "# unexplained payload edit\n")
    with pytest.raises(GovernanceError, match="checksum drift"):
        check_workflow_pins(checkout)


def test_new_unregistered_canonical_workflow_cannot_escape_contract(checkout):
    (checkout / WORKFLOW).with_name("extra.yaml").write_text("jobs: {}\n")
    with pytest.raises(GovernanceError, match="registry differ"):
        check_workflow_pins(checkout)


@pytest.mark.parametrize("key,value", [
    ("sha", "a" * 39), ("sha", "A" * 40), ("sha", "main"),
    ("version", "v1"), ("version", "v7.0.1 # plausible"),
])
def test_pin_contract_rejects_unreviewable_revisions(checkout, key, value):
    path = checkout / CONTRACT_PATH
    contract = load_pin_contract(path)
    contract["actions"]["actions/checkout"][key] = value
    path.write_text(json.dumps(contract))
    with pytest.raises(GovernanceError):
        load_pin_contract(path)


def test_pin_contract_rejects_duplicate_declarations(checkout):
    path = checkout / CONTRACT_PATH
    path.write_text(path.read_text().replace('"version": 1,', '"version": 1, "version": 1,'))
    with pytest.raises(GovernanceError, match="Duplicate"):
        load_pin_contract(path)


def test_updater_previews_then_updates_contract_payload_and_digest(checkout, monkeypatch, capsys):
    before = snapshot(checkout)
    monkeypatch.setattr(updater, "resolve_tag", lambda *_: "b" * 40)
    args = ["--action", "astral-sh/setup-uv@v10.2.0", "--uv-version", "0.12.6"]
    assert updater.main(args, root=checkout) == 0
    assert snapshot(checkout) == before
    assert "Preview: 3 canonical files" in capsys.readouterr().out
    assert updater.main([*args, "--apply"], root=checkout) == 0
    check_workflow_pins(checkout)
    after = snapshot(checkout)
    assert {path for path in before if before[path] != after[path]} == {
        CONTRACT_PATH, MANIFEST_PATH, WORKFLOW,
    }
    text = after[WORKFLOW].decode()
    assert f"astral-sh/setup-uv@{'b' * 40} # v10.2.0" in text
    assert 'version: "0.12.6"' in text
    # The update must not disturb workflow behavior or the provider prompt.
    old = yaml.safe_load(before[WORKFLOW])
    new = yaml.safe_load(after[WORKFLOW])
    old_step = old["jobs"]["shepherd"]["steps"][1]
    new["jobs"]["shepherd"]["steps"][1] = old_step
    assert new == old
    assert updater.main(["--check"], root=checkout) == 0


def test_updater_updates_every_registered_workflow(checkout):
    source = (checkout / WORKFLOW).with_name("second.yaml")
    source.write_bytes((checkout / WORKFLOW).read_bytes())
    manifest_path = checkout / MANIFEST_PATH
    manifest = json.loads(manifest_path.read_text())
    entry = copy.deepcopy(manifest["artifacts"][-1])
    entry.update(id="second_workflow", source=source.relative_to(checkout).as_posix(),
                 target=".github/workflows/second.yaml")
    manifest["artifacts"].append(entry)
    manifest_path.write_text(json.dumps(manifest))
    contract = load_pin_contract(checkout / CONTRACT_PATH)
    contract["uv_version"] = "0.12.6"
    updater.apply_plan(checkout, updater.update_plan(checkout, contract))
    check_workflow_pins(checkout)
    assert 'version: "0.12.6"' in source.read_text()
    manifest = json.loads(manifest_path.read_text())
    assert manifest["artifacts"][-1]["sha256"] == hashlib.sha256(source.read_bytes()).hexdigest()


def test_bad_workflow_does_not_partially_apply_new_contract(checkout, monkeypatch):
    path = checkout / WORKFLOW
    path.write_text(path.read_text().replace('          version: "0.12.5"\n', ""))
    before = snapshot(checkout)
    monkeypatch.setattr(updater, "resolve_tag", lambda *_: "b" * 40)
    assert updater.main(["--action", "astral-sh/setup-uv@v10.2.0", "--apply"], root=checkout) == 1
    assert snapshot(checkout) == before


def test_failed_replace_restores_original_files(checkout, monkeypatch):
    before = snapshot(checkout)
    contract = load_pin_contract(checkout / CONTRACT_PATH)
    contract["uv_version"] = "0.12.6"
    plan = updater.update_plan(checkout, contract)
    replace = updater.os.replace
    calls = 0

    def fails_once(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("simulated disk error")
        replace(source, target)

    monkeypatch.setattr(updater.os, "replace", fails_once)
    with pytest.raises(OSError, match="simulated"):
        updater.apply_plan(checkout, plan)
    assert snapshot(checkout) == before


def test_resolves_annotated_tag_to_commit_without_running_action(monkeypatch):
    replies = [
        {"object": {"type": "tag", "sha": "a" * 40}},
        {"object": {"type": "commit", "sha": "b" * 40}},
    ]
    calls = []

    def run(args, **kwargs):
        assert kwargs == dict(check=True, capture_output=True, text=True, timeout=60)
        calls.append(args)
        return SimpleNamespace(stdout=json.dumps(replies.pop(0)))

    monkeypatch.setattr(subprocess, "run", run)
    assert updater.resolve_tag("actions/checkout", "v7.0.1") == "b" * 40
    assert calls == [
        ["gh", "api", "repos/actions/checkout/git/ref/tags/v7.0.1"],
        ["gh", "api", "repos/actions/checkout/git/tags/" + "a" * 40],
    ]


def test_verify_upstream_catches_version_comment_lying_about_sha(checkout, monkeypatch):
    before = snapshot(checkout)
    monkeypatch.setattr(updater, "resolve_tag", lambda *_: "0" * 40)
    assert updater.main(["--verify-upstream", "--apply"], root=checkout) == 1
    assert snapshot(checkout) == before


def test_ci_check_never_contacts_upstream(checkout, monkeypatch):
    def forbidden(*_):
        pytest.fail("offline CI attempted a network request")
    monkeypatch.setattr(updater, "resolve_tag", forbidden)
    assert updater.main(["--check"], root=checkout) == 0


def test_yaml_alias_cycle_and_flow_uses_fail_closed():
    contract = load_pin_contract()
    with pytest.raises(GovernanceError, match="Cyclic"):
        render_workflow("root: &cycle {self: *cycle}\n", contract)
    with pytest.raises(GovernanceError, match="own line"):
        render_workflow("job: {uses: actions/checkout@v7, name: inline}\n", contract)


def test_agent_model_config_has_no_silently_overridden_keys():
    content = (ROOT / ".github/agent-config.yaml").read_text()
    list(_walk(yaml.compose(content, Loader=yaml.BaseLoader)))
    assert yaml.safe_load(content)["workflows"]["pr-shepherd"]["model"] == "claude-opus-5"
