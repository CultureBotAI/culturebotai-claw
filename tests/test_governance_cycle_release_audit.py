"""Offline exact-cohort release boundaries for #849; no downstream execution."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

from kg_microbe_governance import GovernanceError
from kg_microbe_governance import cycle_release_audit as lane
from kg_microbe_governance.cycle_release_audit import (
    CANARY,
    FLEET_PATH,
    PARENT_PATH,
    RELEASE_ID,
    RELEASE_PATH,
    WORKFLOW_ASSETS,
    audit_release,
    main,
    parse_release,
)

MANIFEST = "src/kg_microbe_governance/vendored_artifacts.json"
PIN = "scripts/.vendored_canon_ref"
SOURCE = "src/kg_microbe_governance/artifacts/"


def git(root, *args):
    return subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", "-C", str(root), *args],
        capture_output=True, text=True, check=True,
        env={key: value for key, value in os.environ.items() if not key.startswith("GIT_")},
    ).stdout.strip()


def put(root, path, content):
    target = root / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return target


def init(root, identity):
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Offline release fixture")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "remote", "add", "origin", f"https://github.com/{identity}.git")


def commit(root, message="fixture"):
    git(root, "add", "-A")
    git(root, "commit", "-m", message)
    head = git(root, "rev-parse", "HEAD")
    git(root, "update-ref", "refs/remotes/origin/main", head)
    return head


def descriptor(identifier, source, target, payload, consumers="all"):
    return {"id": identifier, "source": source, "target": target,
            "sha256": hashlib.sha256(payload.encode()).hexdigest(),
            "mode": "0644", "consumers": consumers}


def build(tmp_path, alter=None, alter_policy=None, include_canary=True, native_contracts=False):
    """Two declared fixture Mechs contrast canary and noncanary behavior."""
    claw = tmp_path / "trusted-claw"
    init(claw, "CultureBotAI/culturebotai-claw")
    consumers = {
        CANARY: {"github": "CultureBotAI/DUFMech", "package_path": "src/dufmech"},
        "traitmech": {"github": "CultureBotAI/TraitMech", "package_path": "src/traitmech"},
    }
    if not include_canary:
        consumers.pop(CANARY)
    fleet = {
        "version": 1,
        "capability_catalogue": {"vendored_sync": {}},
        "vendored_governance": {"state": "authoritative", "canonical_repository": "CultureBotAI/culturebotai-claw",
                               "manifest_path": MANIFEST, "pin_path": PIN},
        "mechs": {
            key: {**row, "display_name": key, "environment_variable": key.upper() + "_ROOT",
                  "schema_paths": ["schema.yaml"], "record_globs": ["data/*.yaml"],
                  "vendored_role": "consumer", "capabilities": {
                      "vendored_sync": {"status": "enabled"},
                  }} for key, row in consumers.items()
        },
    }
    legacy = descriptor("legacy", SOURCE + "legacy.py", "scripts/legacy.py", "legacy source\n")
    artifacts = [legacy]
    if native_contracts:
        from kg_microbe_governance.infrastructure_admission import NATIVE_TESTS
        artifacts.extend(descriptor(key, SOURCE + key + ".py", "tests/" + key + ".py", key + "\n")
                         for key in sorted(NATIVE_TESTS))
    baseline_doc = {"version": 1, "canonical_repository": "CultureBotAI/culturebotai-claw",
                    "pin_path": PIN, "consumers": consumers, "artifacts": artifacts}
    put(claw, FLEET_PATH, yaml.safe_dump(fleet))
    put(claw, MANIFEST, json.dumps(baseline_doc))
    put(claw, legacy["source"], "legacy source\n")
    for artifact in artifacts[1:]:
        put(claw, artifact["source"], artifact["id"] + "\n")
    baseline = commit(claw, "baseline")
    for path in WORKFLOW_ASSETS:
        put(claw, path, "canonical fixture text\n")
    parent = {"version": "2.0.0", "schema_version": "2.0.0",
              "stages": [{"key": "open_issue_triage"}, *[{"key": f"stage_{n}"} for n in range(2, 8)]]}
    put(claw, PARENT_PATH, yaml.safe_dump(parent))
    if alter is not None:
        alter(claw)
    candidate = commit(claw, "publish immutable cycle release")
    policy = {"version": 1, "release_id": RELEASE_ID, "baseline_ref": baseline,
              "release_ref": candidate, "canary": CANARY, "parent_version": "2.0.0",
              "manifest_sha256": hashlib.sha256((claw / MANIFEST).read_bytes()).hexdigest(),
              "workflow_assets": {path: hashlib.sha256((claw / path).read_bytes()).hexdigest()
                                  for path in WORKFLOW_ASSETS}}
    if alter_policy is not None:
        alter_policy(policy)
    put(claw, RELEASE_PATH, json.dumps(policy))
    commit(claw, "introduce reviewed lane")
    roots = {}
    for key, row in consumers.items():
        root = tmp_path / key
        init(root, row["github"])
        put(root, "scripts/legacy.py", "legacy source\n")
        for artifact in artifacts[1:]:
            put(root, artifact["target"], artifact["id"] + "\n")
        put(root, PIN, baseline + "\n")
        commit(root)
        roots[key] = root
    return claw, roots, baseline, candidate


def adopt(claw, root, ref):
    document = json.loads(git(claw, "show", f"{ref}:{MANIFEST}"))
    for artifact in document["artifacts"]:
        if artifact["consumers"] == "all" or CANARY in artifact["consumers"]:
            text = subprocess.run(["git", "-C", str(claw), "show", f"{ref}:{artifact['source']}"],
                                  capture_output=True, text=True, check=True).stdout
            target = put(root, artifact["target"], text)
            target.chmod(int(artifact["mode"], 8))
    put(root, PIN, ref + "\n")
    commit(root, "adopt exact release")


@pytest.mark.parametrize("adopted", [False, True])
def test_pending_and_exact_single_canary_adoption_keep_other_mech_at_baseline(tmp_path, adopted):
    claw, roots, baseline, candidate = build(tmp_path)
    if adopted:
        adopt(claw, roots[CANARY], candidate)
    result = audit_release(claw, roots)
    assert result["ok"]
    assert result["baseline_ref"] == baseline and result["candidate_ref"] == candidate
    assert result["counts"] == {"pending": int(not adopted), "adopted": int(adopted), "retained": 1, "invalid": 0}
    assert all(row["checked_artifacts"] == row["expected_artifacts"] for row in result["repositories"])
    other = next(row for row in result["repositories"] if row["key"] == "traitmech")
    assert other["pin"] == baseline and other["allowed_refs"] == [baseline]


def test_later_unrelated_trusted_commit_keeps_exact_introducing_candidate(tmp_path):
    claw, roots, _, candidate = build(tmp_path)
    put(claw, "unrelated.txt", "next main commit\n")
    newer = commit(claw)
    adopt(claw, roots[CANARY], candidate)
    result = audit_release(claw, roots)
    assert result["ok"] and result["trusted_head"] == newer
    assert result["candidate_ref"] == candidate != newer


def test_older_protected_lane_base_remains_valid(tmp_path):
    claw, roots, _, candidate = build(tmp_path)
    lane = git(claw, "rev-parse", "HEAD")
    put(claw, "unrelated.txt", "later main\n")
    newer = commit(claw)
    git(claw, "checkout", "--detach", lane)
    adopt(claw, roots[CANARY], candidate)
    result = audit_release(claw, roots)
    assert result["ok"] and result["trusted_head"] == lane
    assert result["trusted_origin_main"] == newer


def test_release_on_merged_side_parent_is_not_protected_first_parent(tmp_path):
    claw, roots, baseline, candidate = build(tmp_path)
    git(claw, "branch", "feature")
    git(claw, "checkout", "-b", "protected", baseline)
    put(claw, "protected.txt", "independent main\n")
    commit(claw)
    git(claw, "merge", "--no-ff", "feature", "-m", "merge feature")
    merged = git(claw, "rev-parse", "HEAD")
    git(claw, "update-ref", "refs/remotes/origin/main", merged)
    adopt(claw, roots[CANARY], candidate)
    with pytest.raises(GovernanceError, match="first-parent history"):
        audit_release(claw, roots)


@pytest.mark.parametrize("surface", ["manifest", "payload"])
def test_later_main_cannot_change_active_governance(tmp_path, surface):
    claw, roots, _, _ = build(tmp_path)
    document = json.loads((claw / MANIFEST).read_text())
    if surface == "manifest":
        document["artifacts"][0]["target"] = "scripts/different.py"
    else:
        payload = "changed canonical source\n"
        put(claw, document["artifacts"][0]["source"], payload)
        document["artifacts"][0]["sha256"] = hashlib.sha256(payload.encode()).hexdigest()
    put(claw, MANIFEST, json.dumps(document))
    commit(claw)
    with pytest.raises(GovernanceError, match="differs from the active cycle"):
        audit_release(claw, roots)


@pytest.mark.parametrize("key", [CANARY, "traitmech"])
def test_only_duf_can_advance_and_only_to_the_exact_candidate(tmp_path, key):
    claw, roots, _, candidate = build(tmp_path)
    put(claw, "later.txt", "later\n")
    later = commit(claw)
    put(roots[key], PIN, (later if key == CANARY else candidate) + "\n")
    commit(roots[key])
    result = audit_release(claw, roots)
    assert not result["ok"]
    assert any(issue["code"] == "unexpected_pin" for row in result["repositories"] for issue in row["issues"])
    assert all(row["checked_artifacts"] == 0 for row in result["repositories"])


@pytest.mark.parametrize("change", ["modified", "deleted_reintroduced", "mode"])
def test_declaration_history_cannot_silently_reanchor_a_release(tmp_path, change):
    claw, roots, _, _ = build(tmp_path)
    path = claw / RELEASE_PATH
    original = path.read_text()
    if change == "modified":
        path.write_text(original + "\n")
    elif change == "mode":
        path.chmod(0o755)
    else:
        path.unlink()
        commit(claw, "delete declaration")
        path.write_text(original)
    commit(claw)
    with pytest.raises(GovernanceError, match="modified|reintroduced|mode"):
        audit_release(claw, roots)


def test_cycle_release_cannot_change_governance_even_with_matching_digest(tmp_path):
    def alter(claw):
        document = json.loads((claw / MANIFEST).read_text())
        document["artifacts"][0]["target"] = "scripts/unreviewed.py"
        put(claw, MANIFEST, json.dumps(document))
    claw, roots, _, _ = build(tmp_path, alter)
    with pytest.raises(GovernanceError, match="preserve exact baseline"):
        audit_release(claw, roots)


@pytest.mark.parametrize("defect", ["version", "first_key", "length"])
def test_release_parent_must_be_v2_seven_goals_even_with_matching_hash(tmp_path, defect):
    def alter(claw):
        parent = yaml.safe_load((claw / PARENT_PATH).read_text())
        if defect == "version":
            parent["version"] = "1.0.0"
        elif defect == "first_key":
            parent["stages"][0]["key"] = "add_records"
        else:
            parent["stages"].pop()
        put(claw, PARENT_PATH, yaml.safe_dump(parent))
    claw, roots, _, _ = build(tmp_path, alter)
    with pytest.raises(GovernanceError, match="seven-goal parent"):
        audit_release(claw, roots)


def test_trusted_artifact_checksum_must_hold(tmp_path):
    def alter(claw):
        put(claw, SOURCE + "legacy.py", "unreviewed bytes\n")
    claw, roots, _, _ = build(tmp_path, alter)
    with pytest.raises(GovernanceError, match="checksum drift"):
        audit_release(claw, roots)


@pytest.mark.parametrize("defect", ["wrong_origin", "dirty", "untrusted_head"])
def test_claw_execution_boundary_requires_clean_canonical_main_history(tmp_path, defect):
    claw, roots, baseline, _ = build(tmp_path)
    if defect == "wrong_origin":
        git(claw, "remote", "set-url", "origin", "https://github.com/Other/Authority")
    elif defect == "dirty":
        put(claw, "unreviewed.py", "unreviewed source\n")
    else:
        git(claw, "update-ref", "refs/remotes/origin/main", baseline)
    with pytest.raises(GovernanceError, match="expected|dirty|protected"):
        audit_release(claw, roots)


@pytest.mark.parametrize("defect", ["missing", "wrong_origin", "dirty", "non_main", "duplicate"])
def test_every_consumer_root_must_pass_preflight(tmp_path, defect):
    claw, roots, _, _ = build(tmp_path)
    root = roots["traitmech"]
    if defect == "missing":
        roots.pop("traitmech")
    elif defect == "duplicate":
        roots["traitmech"] = roots[CANARY]
    elif defect == "wrong_origin":
        git(root, "remote", "set-url", "origin", "https://github.com/Other/Wrong")
    elif defect == "dirty":
        put(root, "dirty.txt", "untracked\n")
    else:
        previous = git(root, "rev-parse", "HEAD")
        put(root, "ahead.txt", "local commit\n")
        commit(root)
        git(root, "update-ref", "refs/remotes/origin/main", previous)
    if defect in {"missing", "duplicate"}:
        with pytest.raises(GovernanceError, match="every exact fleet root|distinct"):
            audit_release(claw, roots)
    else:
        result = audit_release(claw, roots)
        assert not result["ok"]
        assert all(row["checked_artifacts"] == 0 for row in result["repositories"])


@pytest.mark.parametrize("defect", ["committed_bytes", "committed_mode", "masked_worktree", "unsafe_mode", "symlink"])
def test_committed_blobs_modes_and_safe_working_paths_are_all_required(tmp_path, defect):
    claw, roots, _, _ = build(tmp_path)
    root = roots["traitmech"]
    artifact = root / "scripts/legacy.py"
    if defect == "committed_bytes":
        artifact.write_text("changed bytes\n")
        commit(root)
    elif defect == "committed_mode":
        artifact.chmod(0o755)
        commit(root)
    elif defect == "masked_worktree":
        artifact.write_text("wrong committed source\n")
        commit(root)
        git(root, "update-index", "--skip-worktree", "scripts/legacy.py")
        artifact.write_text("legacy source\n")
    elif defect == "unsafe_mode":
        artifact.chmod(0o666)
    else:
        artifact.unlink()
        artifact.symlink_to("../elsewhere")
        put(root, "elsewhere", "legacy source\n")
        commit(root)
    result = audit_release(claw, roots)
    assert not result["ok"]
    issues = [issue for row in result["repositories"] for issue in row["issues"]]
    assert any(issue["code"] in {"committed_drift", "working_artifact"} for issue in issues)


def test_historical_payload_is_checked_without_executing_it(tmp_path):
    claw, roots, _, candidate = build(tmp_path)
    # Fixture "new runner" and "legacy source" are invalid Python. Successful
    # audit proves neither trusted historical nor downstream payload is loaded.
    adopt(claw, roots[CANARY], candidate)
    assert audit_release(claw, roots)["ok"]


def test_unknown_policy_fields_and_duplicate_keys_are_refused(tmp_path):
    claw, _, _, _ = build(tmp_path)
    policy = json.loads((claw / RELEASE_PATH).read_text())
    with pytest.raises(GovernanceError, match="unknown fields"):
        parse_release(json.dumps({**policy, "allow_other_mechs": True}).encode())
    with pytest.raises(GovernanceError, match="duplicate"):
        parse_release(b'{"version":1,"version":1}')
    policy["workflow_assets"] = {"unapproved/path": "a" * 64}
    with pytest.raises(GovernanceError, match="exactly the parent"):
        parse_release(json.dumps(policy).encode())


def test_packaged_release_binds_exact_manifest_and_workflow_assets():
    from kg_microbe_governance.infrastructure_admission import (
        HISTORICAL_MANIFEST_PATH,
        validate_packaged_transition,
    )
    root = Path(__file__).resolve().parents[1]
    policy = parse_release((root / RELEASE_PATH).read_bytes())
    # The immutable release still binds its original bytes. Current admission
    # is an additional checked policy, not a replacement digest in that release.
    assert policy["manifest_sha256"] == hashlib.sha256((root / HISTORICAL_MANIFEST_PATH).read_bytes()).hexdigest()
    validate_packaged_transition(root)
    for path, digest in policy["workflow_assets"].items():
        assert hashlib.sha256((root / path).read_bytes()).hexdigest() == digest


@pytest.mark.parametrize("path", sorted(WORKFLOW_ASSETS))
def test_each_declared_release_asset_digest_is_enforced(tmp_path, path):
    def alter_policy(policy):
        policy["workflow_assets"][path] = "0" * 64
    claw, roots, _, _ = build(tmp_path, alter_policy=alter_policy)
    with pytest.raises(GovernanceError, match="workflow asset digest differs"):
        audit_release(claw, roots)


@pytest.mark.parametrize("field,value", [
    ("canary", "traitmech"), ("parent_version", "1.0.0"),
    ("release_ref", "main"), ("baseline_ref", "b" * 7),
    ("manifest_sha256", "A" * 64), ("version", True),
])
def test_policy_cannot_widen_the_canary_or_use_mutable_refs(tmp_path, field, value):
    claw, _, _, _ = build(tmp_path)
    policy = json.loads((claw / RELEASE_PATH).read_text())
    policy[field] = value
    with pytest.raises(GovernanceError):
        parse_release(json.dumps(policy).encode())


def test_release_ref_must_be_in_verified_main_history(tmp_path):
    claw, roots, _, _ = build(tmp_path, alter_policy=lambda p: p.update(release_ref="0" * 40))
    with pytest.raises(GovernanceError, match="first-parent history"):
        audit_release(claw, roots)


def test_canary_must_exist_in_the_manifest_cohort(tmp_path):
    claw, roots, _, _ = build(tmp_path, include_canary=False)
    with pytest.raises(GovernanceError, match="not a manifest-defined consumer"):
        audit_release(claw, roots)


def test_audit_detects_a_head_change_during_payload_checks(tmp_path, monkeypatch):
    claw, roots, _, _ = build(tmp_path)
    original = lane.check_repository
    changed = False
    def check(root, *args, **kwargs):
        nonlocal changed
        result = original(root, *args, **kwargs)
        if not changed:
            changed = True
            put(roots["traitmech"], "concurrent.txt", "concurrent main commit\n")
            commit(roots["traitmech"])
        return result
    monkeypatch.setattr(lane, "check_repository", check)
    with pytest.raises(GovernanceError, match="changed during the release audit"):
        audit_release(claw, roots)


def test_cli_writes_json_outside_checkouts_and_returns_nonzero_on_failure(tmp_path, capsys):
    claw, roots, _, _ = build(tmp_path)
    argv = ["--trusted-root", str(claw)]
    for key, root in roots.items():
        argv.extend(["--target-root", f"{key}={root}"])
    output = tmp_path / "report.json"
    assert main([*argv, "--json-output", str(output)]) == 0
    assert json.loads(output.read_text())["counts"]["pending"] == 1
    assert json.loads(capsys.readouterr().out)["ok"]
    assert main([*argv, "--json-output", str(roots[CANARY] / "forbidden.json")]) == 2
    assert not (roots[CANARY] / "forbidden.json").exists()
    assert not json.loads(capsys.readouterr().out)["ok"]
    put(roots[CANARY], "dirty.txt", "dirty\n")
    assert main(argv) == 1
    assert not json.loads(capsys.readouterr().out)["ok"]
    git(claw, "remote", "set-url", "origin", "https://github.com/Other/Wrong")
    assert main([*argv, "--json-output", str(output)]) == 2
    assert not json.loads(output.read_text())["ok"]
    assert "error" in json.loads(capsys.readouterr().out)
