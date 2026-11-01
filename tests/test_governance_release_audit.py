"""Offline exact-cohort release boundaries for #687; no downstream execution."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path

import pytest
import yaml

from kg_microbe_governance import GovernanceError
from kg_microbe_governance.release_audit import (
    CANARY,
    CAPABILITY,
    FLEET_PATH,
    RELEASE_ID,
    RELEASE_PATH,
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


def build(tmp_path, alter=None):
    """Two declared fixture Mechs contrast canary and noncanary behavior."""
    claw = tmp_path / "trusted-claw"
    init(claw, "CultureBotAI/culturebotai-claw")
    consumers = {
        CANARY: {"github": "CultureBotAI/MediaIngredientMech", "package_path": "src/mediaingredientmech"},
        "traitmech": {"github": "CultureBotAI/TraitMech", "package_path": "src/traitmech"},
    }
    fleet = {
        "version": 1,
        "capability_catalogue": {"vendored_sync": {}, CAPABILITY: {}},
        "vendored_governance": {"state": "authoritative", "canonical_repository": "CultureBotAI/culturebotai-claw",
                               "manifest_path": MANIFEST, "pin_path": PIN},
        "mechs": {
            key: {**row, "display_name": key, "environment_variable": key.upper() + "_ROOT",
                  "schema_paths": ["schema.yaml"], "record_globs": ["data/*.yaml"],
                  "vendored_role": "consumer", "capabilities": {
                      "vendored_sync": {"status": "enabled"},
                      CAPABILITY: {"status": "disabled", "reason": "Not adopted."},
                  }} for key, row in consumers.items()
        },
    }
    legacy = descriptor("legacy", SOURCE + "legacy.py", "scripts/legacy.py", "legacy source\n")
    baseline_doc = {"version": 1, "canonical_repository": "CultureBotAI/culturebotai-claw",
                    "pin_path": PIN, "consumers": consumers, "artifacts": [legacy]}
    put(claw, FLEET_PATH, yaml.safe_dump(fleet))
    put(claw, MANIFEST, json.dumps(baseline_doc))
    put(claw, legacy["source"], "legacy source\n")
    baseline = commit(claw, "baseline")
    additions = [
        descriptor("evidence_validator_runner", SOURCE + "scripts/run_shared_evidence_validator.py",
                   "scripts/run_shared_evidence_validator.py", "new runner\n", [CANARY]),
        descriptor("evidence_validation_workflow", SOURCE + "workflows/qc-evidence.yaml",
                   ".github/workflows/qc-evidence.yaml", "new workflow\n", [CANARY]),
    ]
    candidate_doc = {**baseline_doc, "artifacts": [dict(legacy), *additions]}
    fleet["mechs"][CANARY]["capabilities"][CAPABILITY] = {"status": "enabled"}
    if alter is not None:
        alter(candidate_doc, fleet, additions)
    raw = json.dumps(candidate_doc)
    policy = {"version": 1, "release_id": RELEASE_ID, "baseline_ref": baseline,
              "canary": CANARY, "capability": CAPABILITY,
              "candidate_manifest_sha256": hashlib.sha256(raw.encode()).hexdigest(),
              "allowed_additions": additions}
    put(claw, FLEET_PATH, yaml.safe_dump(fleet))
    put(claw, MANIFEST, raw)
    put(claw, additions[0]["source"], "new runner\n")
    put(claw, additions[1]["source"], "new workflow\n")
    put(claw, RELEASE_PATH, json.dumps(policy))
    candidate = commit(claw, "introduce reviewed release")
    roots = {}
    for key, row in consumers.items():
        root = tmp_path / key
        init(root, row["github"])
        put(root, "scripts/legacy.py", "legacy source\n")
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


def test_older_protected_main_base_is_still_a_valid_trusted_audit_revision(tmp_path):
    claw, roots, _, candidate = build(tmp_path)
    put(claw, "unrelated.txt", "next protected main commit\n")
    newer = commit(claw)
    git(claw, "checkout", "--detach", candidate)
    adopt(claw, roots[CANARY], candidate)
    result = audit_release(claw, roots)
    assert result["ok"]
    assert result["trusted_head"] == result["candidate_ref"] == candidate
    assert result["trusted_origin_main"] == newer


def test_merged_side_parent_cannot_select_its_own_release_introduction(tmp_path):
    claw, roots, baseline, feature = build(tmp_path)
    git(claw, "branch", "feature", feature)
    git(claw, "checkout", "-b", "protected", baseline)
    put(claw, "protected.txt", "independent protected main commit\n")
    commit(claw)
    git(claw, "merge", "--no-ff", "feature", "-m", "protected merge")
    merged = git(claw, "rev-parse", "HEAD")
    git(claw, "update-ref", "refs/remotes/origin/main", merged)
    adopt(claw, roots[CANARY], merged)
    accepted = audit_release(claw, roots)
    assert accepted["ok"] and accepted["candidate_ref"] == merged
    git(claw, "checkout", "--detach", feature)
    adopt(claw, roots[CANARY], feature)
    # Both revisions are ancestors of origin/main; only the protected merge
    # belongs to its first-parent chain and introduced the reviewed declaration.
    assert git(claw, "merge-base", "--is-ancestor", feature, merged) == ""
    with pytest.raises(GovernanceError, match="first-parent history"):
        audit_release(claw, roots)


@pytest.mark.parametrize("surface", ["manifest", "payload", "capability"])
def test_later_main_cannot_change_the_active_governance_or_evidence_contract(tmp_path, surface):
    claw, roots, _, _ = build(tmp_path)
    if surface == "capability":
        fleet = yaml.safe_load((claw / FLEET_PATH).read_text())
        fleet["capability_catalogue"][CAPABILITY] = {"settings": {"cache_dir": {"type": "string"}}}
        fleet["mechs"][CANARY]["capabilities"][CAPABILITY]["settings"] = {"cache_dir": "other_cache"}
        put(claw, FLEET_PATH, yaml.safe_dump(fleet))
    else:
        document = json.loads((claw / MANIFEST).read_text())
        if surface == "manifest":
            document["artifacts"][0]["target"] = "scripts/different.py"
        else:
            payload = "changed canonical source\n"
            put(claw, document["artifacts"][0]["source"], payload)
            document["artifacts"][0]["sha256"] = hashlib.sha256(payload.encode()).hexdigest()
        put(claw, MANIFEST, json.dumps(document))
    commit(claw)
    with pytest.raises(GovernanceError, match="differs from the active candidate"):
        audit_release(claw, roots)


@pytest.mark.parametrize("key", [CANARY, "traitmech"])
def test_only_mim_can_advance_and_only_to_the_exact_candidate(tmp_path, key):
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


def test_unreviewed_legacy_artifact_delta_fails_even_with_matching_candidate_digest(tmp_path):
    def alter(document, _fleet, _additions):
        document["artifacts"][0]["target"] = "scripts/unreviewed.py"
    claw, roots, _, _ = build(tmp_path, alter)
    with pytest.raises(GovernanceError, match="exactly the two"):
        audit_release(claw, roots)


def test_capability_cannot_enable_a_second_consumer(tmp_path):
    def alter(_document, fleet, _additions):
        fleet["mechs"]["traitmech"]["capabilities"][CAPABILITY] = {"status": "enabled"}
    claw, roots, _, _ = build(tmp_path, alter)
    with pytest.raises(GovernanceError, match="enable exactly MIM"):
        audit_release(claw, roots)


def test_addition_cannot_apply_to_a_second_consumer(tmp_path):
    def alter(_document, _fleet, additions):
        additions[0]["consumers"].append("traitmech")
    claw, roots, _, _ = build(tmp_path, alter)
    with pytest.raises(GovernanceError, match="only to MIM"):
        audit_release(claw, roots)


def test_trusted_artifact_bytes_must_match_the_reviewed_digest(tmp_path):
    def alter(_document, _fleet, additions):
        additions[0]["sha256"] = "a" * 64
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
    policy["allowed_additions"][0]["id"] = ["not", "a", "name"]
    with pytest.raises(GovernanceError, match="two evidence"):
        parse_release(json.dumps(policy).encode())


def test_packaged_release_binds_the_current_manifest_and_exact_artifact_descriptors():
    root = Path(__file__).resolve().parents[1]
    policy = parse_release((root / RELEASE_PATH).read_bytes())
    content = (root / MANIFEST).read_bytes()
    assert policy["candidate_manifest_sha256"] == hashlib.sha256(content).hexdigest()
    document = json.loads(content)
    artifacts = {artifact["id"]: artifact for artifact in document["artifacts"]}
    assert all(artifacts[row["id"]] == row for row in policy["allowed_additions"])


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
