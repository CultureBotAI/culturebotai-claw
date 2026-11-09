"""Independent native-consumer admissions preserve every prior authority boundary."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from test_governance_cycle_release_audit import (
    FLEET_PATH,
    MANIFEST,
    PIN,
    RELEASE_PATH,
    commit,
    evolve_payload,
    git,
    init,
    put,
)
from test_governance_infrastructure_admission import admitted

from kg_microbe_governance import GovernanceError
from kg_microbe_governance.artifacts.scripts.check_vendored_sync import (
    expand_target,
    parse_manifest,
)
from kg_microbe_governance.consumer_admission import SPECS, bootstrap_pending, compose, source_refs
from kg_microbe_governance.cycle_release_audit import audit_release
from kg_microbe_governance.infrastructure_admission import (
    ADMISSION_PATH,
    HISTORICAL_MANIFEST_PATH,
    NATIVE_TESTS,
    canonical_sha,
    sha,
    validate_packaged_transition,
)

SPEC = SPECS[0]
KEY = SPEC.consumer.key


def native_admitted(tmp_path, *, installed=False, bad_ref=False):
    claw, roots, edge_policy, baseline, candidate, edge_anchor = admitted(tmp_path, installed=True)
    edge_bytes = (claw / ADMISSION_PATH).read_bytes()
    native = tmp_path / KEY
    init(native, SPEC.consumer.github)
    put(native, "README.md", "Uninstalled native bootstrap\n")
    bootstrap = commit(native, "empty native bootstrap")
    roots[KEY] = native
    manifest = json.loads((claw / MANIFEST).read_bytes())
    manifest["consumers"][KEY] = {"github": SPEC.consumer.github, "package_path": SPEC.consumer.package_path}
    for artifact in manifest["artifacts"]:
        if artifact["id"] in NATIVE_TESTS:
            artifact["consumers"].append(KEY)
    put(claw, MANIFEST, json.dumps(manifest))
    fleet = yaml.safe_load((claw / FLEET_PATH).read_bytes())
    entry = {**manifest["consumers"][KEY], "display_name": "CofactorMech",
             "environment_variable": "COFACTORMECH_ROOT", "schema_paths": ["schema.yaml"],
             "record_globs": ["data/*.yaml"], "vendored_role": "consumer",
             "serialization": {"verified": False, "reason": "No deployed native corpus"},
             "capabilities": {"vendored_sync": {"status": "enabled"}}}
    fleet["mechs"][KEY] = entry
    put(claw, FLEET_PATH, yaml.safe_dump(fleet))
    source = commit(claw, "native admission source snapshot")
    raw = (claw / MANIFEST).read_bytes()
    historical = parse_manifest((claw / HISTORICAL_MANIFEST_PATH).read_bytes())
    policy = {
        "version": 1, "admission_id": SPEC.admission_id, "authority": "infrastructure_only",
        "consumer": {"key": KEY, "github": SPEC.consumer.github, "package_path": SPEC.consumer.package_path},
        "source_ref": (edge_anchor if bad_ref == "wrong_content" else "a" * 40) if bad_ref else source,
        "source_manifest_sha256": sha(raw), "bootstrap_main_ref": bootstrap,
        "fleet_entry_sha256": canonical_sha(entry),
        "historical_declaration_sha256": sha((claw / RELEASE_PATH).read_bytes()),
        "historical_manifest_sha256": sha((claw / HISTORICAL_MANIFEST_PATH).read_bytes()),
        "edge_declaration_sha256": sha(edge_bytes),
        "required_artifacts": sorted(a.artifact_id for a in historical.artifacts if not a.consumers),
    }
    put(claw, SPEC.snapshot, raw.decode())
    put(claw, SPEC.declaration, json.dumps(policy))
    anchor = commit(claw, "explicit protected native admission")
    if installed:
        for artifact in manifest["artifacts"]:
            if artifact["consumers"] == "all" or KEY in artifact["consumers"]:
                target = artifact["target"].replace("{package_path}", SPEC.consumer.package_path)
                put(native, target, (claw / artifact["source"]).read_text())
                (native / target).chmod(int(artifact["mode"], 8))
        put(native, PIN, source + "\n")
        commit(native, "install admitted native snapshot")
    assert (claw / ADMISSION_PATH).read_bytes() == edge_bytes
    return claw, roots, policy, edge_policy, baseline, candidate, edge_anchor, anchor


def composition(root):
    return compose(lambda p: (root / p).read_bytes(), (root / FLEET_PATH).read_bytes(),
                   (root / MANIFEST).read_bytes())


@pytest.mark.parametrize("installed", [False, True])
def test_additional_admission_has_separate_protected_pin_and_no_prior_permissions(tmp_path, installed):
    claw, roots, policy, edge, baseline, candidate, _, anchor = native_admitted(tmp_path, installed=installed)
    assert validate_packaged_transition(claw) == edge
    assert source_refs(claw) == (edge["source_ref"], policy["source_ref"])
    result = audit_release(claw, roots)
    assert result["ok"]
    rows = {r["key"]: r for r in result["repositories"]}
    assert rows[KEY]["allowed_refs"] == [policy["source_ref"]]
    assert rows[KEY]["installation_verified"] is installed
    assert rows[KEY]["checked_artifacts"] == (len(policy["required_artifacts"]) if installed else 0)
    assert rows["edgemech"]["allowed_refs"] == [edge["source_ref"]]
    assert rows["traitmech"]["allowed_refs"] == [baseline]
    assert rows["dufmech"]["allowed_refs"] == [baseline, candidate]
    assert result["consumer_admissions"][0]["anchor"] == anchor


@pytest.mark.parametrize("field", ["unknown_member", "edge_identity", "edge_capability", "native_test", "old_scope"])
def test_composition_cannot_filter_away_unapproved_changes(tmp_path, field):
    claw, *_ = native_admitted(tmp_path)
    fleet = yaml.safe_load((claw / FLEET_PATH).read_bytes())
    manifest = json.loads((claw / MANIFEST).read_bytes())
    if field == "unknown_member":
        fleet["mechs"]["unknownmech"] = deepcopy(fleet["mechs"][KEY])
        fleet["mechs"]["unknownmech"].update(github="CultureBotAI/UnknownMech", environment_variable="UNKNOWNMECH_ROOT")
    elif field == "edge_identity":
        fleet["mechs"]["edgemech"]["github"] = "CultureBotAI/OtherEdgeMech"
    elif field == "edge_capability":
        fleet["mechs"]["edgemech"]["capabilities"]["vendored_sync"] = {"status": "disabled", "reason": "Mutation"}
    elif field == "native_test":
        next(a for a in manifest["artifacts"] if a["id"] in NATIVE_TESTS)["consumers"].remove(KEY)
    else:
        manifest["artifacts"][0]["consumers"] = [KEY]
    put(claw, FLEET_PATH, yaml.safe_dump(fleet))
    put(claw, MANIFEST, json.dumps(manifest))
    with pytest.raises(GovernanceError):
        composition(claw)


@pytest.mark.parametrize("bad_ref", [True, "wrong_content"])
def test_source_objects_are_required_even_for_first_pending_bootstrap(tmp_path, bad_ref):
    claw, roots, *_ = native_admitted(tmp_path, bad_ref=bad_ref)
    with pytest.raises(GovernanceError):
        audit_release(claw, roots)


@pytest.mark.parametrize("mutation", ["changed_empty_tip", "partial_committed", "uncommitted_artifact"])
def test_bootstrap_is_exact_tip_and_never_partial_installation(tmp_path, mutation):
    claw, roots, *_ = native_admitted(tmp_path)
    _, _, additions = composition(claw)
    native = roots[KEY]
    if mutation == "changed_empty_tip":
        put(native, "README.md", "changed empty tip\n")
        commit(native)
        assert not bootstrap_pending(native, additions[KEY])
        assert not audit_release(claw, roots)["ok"]
    else:
        put(native, PIN, additions[KEY].policy["source_ref"] + "\n")
        if mutation == "partial_committed":
            commit(native)
            assert not audit_release(claw, roots)["ok"]
        else:
            with pytest.raises(GovernanceError):
                bootstrap_pending(native, additions[KEY])


@pytest.mark.parametrize("mutation", ["edit", "delete", "resurrect", "off_protected"])
def test_declaration_requires_immutable_protected_introduction(tmp_path, mutation):
    claw, roots, policy, *_ = native_admitted(tmp_path)
    content = (claw / SPEC.declaration).read_bytes()
    if mutation == "edit":
        policy["bootstrap_main_ref"] = "e" * 40
        put(claw, SPEC.declaration, json.dumps(policy))
        commit(claw)
    elif mutation in {"delete", "resurrect"}:
        (claw / SPEC.declaration).unlink()
        commit(claw)
        if mutation == "resurrect":
            put(claw, SPEC.declaration, content.decode())
            commit(claw)
    else:
        current = git(claw, "rev-parse", "HEAD")
        git(claw, "update-ref", "refs/remotes/origin/main", current + "^")
    with pytest.raises(GovernanceError):
        audit_release(claw, roots)
    with pytest.raises(GovernanceError):
        source_refs(claw)


def test_current_payload_cannot_replace_native_pinned_bytes(tmp_path):
    claw, roots, policy, *_ = native_admitted(tmp_path, installed=True)
    _, newer = evolve_payload(claw)
    assert audit_release(claw, roots)["ok"]
    put(roots[KEY], "scripts/legacy.py", newer)
    commit(roots[KEY])
    result = audit_release(claw, roots)
    row = next(r for r in result["repositories"] if r["key"] == KEY)
    assert not result["ok"] and row["allowed_refs"] == [policy["source_ref"]]
    assert any(issue["code"] == "committed_drift" for issue in row["issues"])


def test_pre_admission_protected_base_cannot_activate_candidate_policy(tmp_path):
    claw, roots, _, edge, _, _, old_head, _ = native_admitted(tmp_path)
    git(claw, "checkout", "--detach", old_head)
    assert source_refs(claw) == (edge["source_ref"],)
    result = audit_release(claw, {k: v for k, v in roots.items() if k != KEY})
    assert result["ok"] and "consumer_admissions" not in result


def test_real_cofactor_admission_keeps_all_twenty_two_native_artifacts():
    root = Path(__file__).parents[1]
    _, _, additions = composition(root)
    item = additions[KEY]
    assert item.policy["source_ref"] == "5790569efd881bd8bca82a04ea278cc462c0c2c8"
    assert len(item.policy["required_artifacts"]) == 22
    assert NATIVE_TESTS <= set(item.policy["required_artifacts"])


def test_selector_cannot_read_skip_worktree_policy_instead_of_committed_bytes(tmp_path):
    claw, _, policy, edge, *_ = native_admitted(tmp_path)
    git(claw, "update-index", "--skip-worktree", SPEC.declaration)
    changed = dict(policy)
    changed["source_ref"] = "f" * 40
    put(claw, SPEC.declaration, json.dumps(changed))
    assert git(claw, "status", "--porcelain") == ""
    assert source_refs(claw) == (edge["source_ref"], policy["source_ref"])


@pytest.mark.parametrize("change", ["native_omission", "target", "mode", "source"])
def test_resealing_candidate_source_cannot_change_required_native_contract(tmp_path, change):
    claw, _, policy, *_ = native_admitted(tmp_path)
    source = json.loads((claw / SPEC.snapshot).read_bytes())
    artifact = next(a for a in source["artifacts"] if a["id"] in NATIVE_TESTS)
    if change == "native_omission":
        policy["required_artifacts"].remove(artifact["id"])
        artifact["consumers"].remove(KEY)
    else:
        artifact[change] = {"target": "scripts/wrong.py", "mode": "0755",
                            "source": "src/kg_microbe_governance/artifacts/wrong.py"}[change]
    raw = json.dumps(source).encode()
    policy["source_manifest_sha256"] = sha(raw)
    put(claw, SPEC.snapshot, raw.decode())
    put(claw, MANIFEST, raw.decode())
    put(claw, SPEC.declaration, json.dumps(policy))
    with pytest.raises(GovernanceError):
        composition(claw)


def test_resealed_fleet_entry_cannot_enable_scientific_capability():
    root = Path(__file__).parents[1]
    fleet = yaml.safe_load((root / FLEET_PATH).read_bytes())
    policy = json.loads((root / SPEC.declaration).read_bytes())
    fleet["mechs"][KEY]["capabilities"]["record_review"] = {"status": "enabled"}
    policy["fleet_entry_sha256"] = canonical_sha(fleet["mechs"][KEY])

    def read(path):
        return json.dumps(policy).encode() if path == SPEC.declaration else (root / path).read_bytes()

    with pytest.raises(GovernanceError, match="cannot enable execution"):
        compose(read, yaml.safe_dump(fleet).encode(), (root / MANIFEST).read_bytes())


@pytest.mark.parametrize('victim', ['traitmech', 'dufmech', 'edgemech'])
def test_fully_matching_new_source_does_not_grant_other_consumers_its_pin(tmp_path, victim):
    claw, roots, policy, *_ = native_admitted(tmp_path, installed=True)
    assert audit_release(claw, roots)['ok']
    source = parse_manifest((claw / SPEC.snapshot).read_bytes())
    target = roots[victim]
    consumer = source.consumers[victim]
    for artifact in source.artifacts_for(consumer):
        relative = expand_target(artifact, consumer)
        put(target, relative, (claw / artifact.source).read_text())
        (target / relative).chmod(artifact.mode)
    put(target, PIN, policy['source_ref'] + '\n')
    commit(target, 'Install valid but unauthorized native-consumer source')
    result = audit_release(claw, roots)
    assert not result['ok']
    row = next(r for r in result['repositories'] if r['key'] == victim)
    assert any(i['code'] == 'unexpected_pin' for i in row['issues'])
    assert all(r['checked_artifacts'] == 0 for r in result['repositories'])
