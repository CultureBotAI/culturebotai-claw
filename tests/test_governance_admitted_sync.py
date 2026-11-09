"""Exact admitted old bytes survive current publication through public sync APIs."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

import kg_microbe_governance as governance
from kg_microbe_governance.artifacts.scripts.check_vendored_sync import (
    CANONICAL_MANIFEST_PATH,
    parse_manifest,
)
from kg_microbe_governance.infrastructure_admission import ADMITTED_MANIFEST_PATH

ROOT = Path(__file__).resolve().parents[1]
REF = "7e672227fb246a8359ad57b6d3975ce5ed329007"


@pytest.fixture
def source(monkeypatch):
    raw = (ROOT / ADMITTED_MANIFEST_PATH).read_bytes()
    manifest = parse_manifest(raw)
    payloads = {CANONICAL_MANIFEST_PATH: raw}
    for artifact in manifest.artifacts:
        content = (ROOT / artifact.source).read_bytes()
        if hashlib.sha256(content).hexdigest() != artifact.sha256:
            content = (ROOT / "tests/fixtures/edgemech-admitted-source" / Path(artifact.source).name).read_bytes()
        assert hashlib.sha256(content).hexdigest() == artifact.sha256
        payloads[artifact.source] = content

    def fetch(url):
        path = url.split("/", 6)[-1]
        return payloads[path]

    monkeypatch.setattr(governance, "fetch_url", fetch)
    return payloads


def repository(tmp_path, github="CultureBotAI/EdgeMech"):
    root = tmp_path / "consumer"
    root.mkdir()
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "remote", "add", "origin", f"https://github.com/{github}"], check=True)
    return root


def commit(root):
    subprocess.run(["git", "-C", str(root), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(root), "-c", "user.name=Offline sync fixture",
                    "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture"], check=True)


def test_public_admitted_plan_install_and_noop_keep_same_old_source(tmp_path, source, monkeypatch):
    root = repository(tmp_path)
    changes = governance.plan_sync("edgemech", root, REF)
    assert len(changes) == 20 and not (root / "scripts").exists()
    # This contrasts old admitted payloads with genuinely different current bytes.
    old = source["src/kg_microbe_governance/artifacts/prompts/backlog-loop-goal.md"]
    assert old != (ROOT / "src/kg_microbe_governance/artifacts/prompts/backlog-loop-goal.md").read_bytes()
    assert governance.sync_repository("edgemech", root, REF, apply=True) == changes
    assert (root / "prompts/backlog-loop-goal.md").read_bytes() == old
    assert (root / "scripts/.vendored_canon_ref").read_text() == REF + "\n"
    commit(root)
    assert governance.plan_sync("CultureBotAI/EdgeMech", root, REF) == ()
    assert governance.sync_repository("edgemech", root, REF, apply=True) == ()


@pytest.mark.parametrize("operation", ["other_consumer", "wrong_ref", "generic_verifier"])
def test_admitted_source_is_never_a_generic_old_package_exception(tmp_path, source, operation):
    root = repository(tmp_path, "CultureBotAI/TraitMech" if operation == "other_consumer" else "CultureBotAI/EdgeMech")
    with pytest.raises(governance.GovernanceError, match="does not match the installed"):
        if operation == "generic_verifier":
            governance.verify_canonical_ref(REF)
        else:
            governance.plan_sync("traitmech" if operation == "other_consumer" else "edgemech",
                                 root, "a" * 40 if operation == "wrong_ref" else REF)
    assert not (root / "scripts").exists()


@pytest.mark.parametrize("damage", ["manifest", "payload"])
def test_admitted_remote_corruption_is_rejected_before_target_writes(tmp_path, source, damage):
    root = repository(tmp_path)
    path = CANONICAL_MANIFEST_PATH if damage == "manifest" else "src/kg_microbe_governance/artifacts/docs/record-reviews.md"
    source[path] += b"\n"
    with pytest.raises(governance.GovernanceError, match="differs from admitted|checksum drift"):
        governance.sync_repository("edgemech", root, REF, apply=True)
    assert not (root / "scripts").exists()


def test_admitted_sync_still_checks_current_package_payloads(tmp_path, source, monkeypatch):
    root = repository(tmp_path)
    bad = tmp_path / "bad-current-payload"
    bad.write_bytes(b"current source corruption")
    monkeypatch.setattr(governance, "_artifact_resource", lambda path: bad)
    with pytest.raises(governance.GovernanceError, match="Canonical artifact checksum drift"):
        governance.plan_sync("edgemech", root, REF)
    assert not (root / "scripts").exists()


def test_admitted_apply_uses_existing_rollback_after_postverification_failure(tmp_path, source, monkeypatch):
    root = repository(tmp_path)
    governance.sync_repository("edgemech", root, REF, apply=True)
    target = root / "prompts/backlog-loop-goal.md"
    target.write_bytes(b"committed drift")
    commit(root)
    original = governance._plan_sync

    def fail_postverify(*args, **kwargs):
        assert kwargs["desired"]  # The frozen bundle reaches post-write verification.
        result = original(*args, **kwargs)
        if not result:
            return (governance.SyncChange("injected", "prompts/backlog-loop-goal.md", "drift"),)
        return result

    monkeypatch.setattr(governance, "_plan_sync", fail_postverify)
    with pytest.raises(governance.GovernanceError, match="verification failed"):
        governance.sync_repository("edgemech", root, REF, apply=True)
    assert target.read_bytes() == b"committed drift"
    assert subprocess.run(["git", "-C", str(root), "status", "--porcelain"], capture_output=True,
                          check=True).stdout == b""


def test_retained_old_fixtures_are_bound_to_admitted_manifest():
    manifest = json.loads((ROOT / ADMITTED_MANIFEST_PATH).read_bytes())
    expected = {Path(a["source"]).name: a["sha256"] for a in manifest["artifacts"]}
    for path in (ROOT / "tests/fixtures/edgemech-admitted-source").iterdir():
        assert hashlib.sha256(path.read_bytes()).hexdigest() == expected[path.name]
