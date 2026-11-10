"""Post-cutoff infrastructure admission cannot widen the frozen scientific lane."""
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
    build,
    commit,
    evolve_payload,
    git,
    init,
    put,
)

from kg_microbe_governance import GovernanceError
from kg_microbe_governance.cycle_release_audit import audit_release
from kg_microbe_governance.infrastructure_admission import (
    ADMISSION_ID,
    ADMISSION_PATH,
    ADMITTED,
    ADMITTED_MANIFEST_PATH,
    HISTORICAL_MANIFEST_PATH,
    NATIVE_TESTS,
    canonical_sha,
    parse_admission,
    sha,
    trusted_source_ref,
    validate_packaged_transition,
    validate_transition,
)


def admitted(tmp_path, *, installed=False, squash=False, source_kind=None):
    claw, roots, baseline, candidate = build(tmp_path, native_contracts=True)
    historic = (claw / MANIFEST).read_bytes()
    wrong_source = None
    if source_kind == "wrong_content":
        put(claw, "unrelated.txt", "A real commit that does not contain admission payloads\n")
        wrong_source = commit(claw)
    edge = tmp_path / ADMITTED.key
    init(edge, ADMITTED.github)
    put(edge, "README.md", "Empty bootstrap for reviewed feature work\n")
    bootstrap = commit(edge)
    roots[ADMITTED.key] = edge
    git(claw, "checkout", "-b", "admission-source")
    manifest = json.loads(historic)
    old_keys = sorted(manifest["consumers"])
    manifest["consumers"][ADMITTED.key] = {"github": ADMITTED.github, "package_path": ADMITTED.package_path}
    for artifact in manifest["artifacts"]:
        if artifact["id"] in NATIVE_TESTS:
            artifact["consumers"] = old_keys
    put(claw, MANIFEST, json.dumps(manifest))
    fleet = yaml.safe_load((claw / FLEET_PATH).read_bytes())
    entry = {**manifest["consumers"][ADMITTED.key], "display_name": "EdgeMech",
             "environment_variable": "EDGEMECH_ROOT", "schema_paths": ["schema.yaml"],
             "record_globs": ["packets/*.yaml"], "vendored_role": "consumer",
             "serialization": {"verified": False, "reason": "No native scientific corpus"},
             "capabilities": {"vendored_sync": {"status": "enabled"}}}
    fleet["mechs"][ADMITTED.key] = entry
    put(claw, FLEET_PATH, yaml.safe_dump(fleet))
    source = commit(claw, "reviewed infrastructure source data")
    git(claw, "checkout", "main")
    git(claw, "merge", "--squash" if squash else "--ff-only", "admission-source")
    policy = {
        "version": 1, "admission_id": ADMISSION_ID, "authority": "infrastructure_only",
        "historical_declaration_sha256": sha((claw / RELEASE_PATH).read_bytes()),
        "historical_manifest_sha256": sha(historic),
        "source_ref": "a" * 40 if source_kind == "absent" else wrong_source or source,
        "source_manifest_sha256": sha((claw / MANIFEST).read_bytes()),
        "consumer": {"key": ADMITTED.key, "github": ADMITTED.github, "package_path": ADMITTED.package_path},
        "bootstrap_main_ref": bootstrap, "fleet_entry_sha256": canonical_sha(entry),
        "excluded_native_tests": sorted(NATIVE_TESTS),
    }
    put(claw, HISTORICAL_MANIFEST_PATH, historic.decode())
    put(claw, ADMITTED_MANIFEST_PATH, (claw / MANIFEST).read_text())
    put(claw, ADMISSION_PATH, json.dumps(policy))
    anchor = commit(claw, "approve bounded infrastructure admission")
    if installed:
        put(edge, "scripts/legacy.py", "legacy source\n")
        put(edge, PIN, policy["source_ref"] + "\n")
        commit(edge, "install exact reviewed data pin")
    return claw, roots, policy, baseline, candidate, anchor


@pytest.mark.parametrize("source_kind", ["absent", "wrong_content"])
def test_initial_admission_source_ref_must_authenticate_actual_objects(tmp_path, source_kind):
    claw, roots, policy, *_ = admitted(tmp_path, installed=True, source_kind=source_kind)
    # This is the FIRST declaration, and the consumer carries that exact bad
    # pin. The immutable-introduction guard must not be what rejects it.
    assert trusted_source_ref(claw) == policy["source_ref"]
    with pytest.raises(GovernanceError):
        audit_release(claw, roots)


def test_trusted_data_preparation_skips_historical_and_rejects_candidate_policy(tmp_path):
    historical, _, _, _ = build(tmp_path)
    assert trusted_source_ref(historical) is None
    admitted_root = tmp_path / "admitted"
    admitted_root.mkdir()
    claw, _, policy, _, candidate, _ = admitted(admitted_root, squash=True)
    assert trusted_source_ref(claw) == policy["source_ref"]
    git(claw, "update-ref", "refs/remotes/origin/main", candidate)
    with pytest.raises(GovernanceError, match="protected trusted HEAD"):
        trusted_source_ref(claw)


@pytest.mark.parametrize("installed", [False, True])
@pytest.mark.parametrize("squash", [False, True])
def test_separate_infrastructure_state_preserves_every_historical_pin(tmp_path, installed, squash):
    claw, roots, policy, baseline, candidate, anchor = admitted(tmp_path, installed=installed, squash=squash)
    result = audit_release(claw, roots)
    assert result["ok"]
    assert result["infrastructure_admission"]["anchor"] == anchor
    assert result["infrastructure_admission"]["scientific_capabilities_enabled"] is False
    assert result["baseline_ref"] == baseline and result["candidate_ref"] == candidate
    edge = next(row for row in result["repositories"] if row["key"] == ADMITTED.key)
    assert edge["state"] == ("installed_infrastructure" if installed else "pending_infrastructure_bootstrap")
    assert edge["checked_artifacts"] == edge["expected_artifacts"] == int(installed)
    assert edge["installation_verified"] is installed
    assert edge["pin"] == (policy["source_ref"] if installed else None)
    assert result["counts"]["pending"] == result["counts"]["retained"] == 1
    assert result["counts"]["invalid"] == 0
    if squash:
        assert policy["source_ref"] not in git(claw, "rev-list", "HEAD").splitlines()
    assert validate_packaged_transition(claw) == policy


@pytest.mark.parametrize("damage", ["new_tip", "partial_files", "wrong_origin", "dirty_file", "wrong_pin", "ignored_files"])
def test_bootstrap_is_not_an_unconditional_infrastructure_skip(tmp_path, damage):
    claw, roots, policy, *_ = admitted(tmp_path)
    edge = roots[ADMITTED.key]
    if damage == "wrong_origin":
        git(edge, "remote", "set-url", "origin", "https://github.com/Other/Wrong")
    else:
        if damage == "ignored_files":
            put(edge, ".git/info/exclude", "scripts/\n")
        put(edge, PIN if damage == "wrong_pin" else "scripts/legacy.py", "a" * 40 + "\n")
        if damage in {"new_tip", "partial_files", "wrong_pin"}:
            if damage == "new_tip":
                (edge / "scripts/legacy.py").unlink()
                put(edge, "README.md", "Changed main must end pending bootstrap\n")
            commit(edge)
    try:
        result = audit_release(claw, roots)
    except GovernanceError:
        return
    assert not result["ok"]
    assert all(row["checked_artifacts"] == 0 for row in result["repositories"])
    assert not any(row["state"] == "pending_infrastructure_bootstrap" for row in result["repositories"])


@pytest.mark.parametrize("key", ["traitmech", "dufmech"])
def test_infrastructure_pin_never_becomes_a_historical_consumer_permission(tmp_path, key):
    claw, roots, policy, *_ = admitted(tmp_path, installed=True)
    put(roots[key], PIN, policy["source_ref"] + "\n")
    commit(roots[key])
    result = audit_release(claw, roots)
    assert not result["ok"]
    assert all(row["checked_artifacts"] == 0 for row in result["repositories"])
    assert any(issue["code"] == "unexpected_pin" for row in result["repositories"] for issue in row["issues"])


@pytest.mark.parametrize("damage", ["extra_member", "capability", "payload", "scope", "historical_identity"])
def test_even_rehashed_candidate_cannot_expand_declared_transition(tmp_path, damage):
    claw, _, policy, *_ = admitted(tmp_path)
    manifest = json.loads((claw / MANIFEST).read_bytes())
    fleet = yaml.safe_load((claw / FLEET_PATH).read_bytes())
    if damage == "extra_member":
        manifest["consumers"]["newmech"] = {"github": "CultureBotAI/NewMech", "package_path": "src/newmech"}
    elif damage == "historical_identity":
        manifest["consumers"]["traitmech"]["github"] = "Other/TraitMech"
    elif damage == "capability":
        fleet["capability_catalogue"]["scientific_worker"] = {}
        for row in fleet["mechs"].values():
            row["capabilities"]["scientific_worker"] = {"status": "enabled"}
        policy["fleet_entry_sha256"] = canonical_sha(fleet["mechs"][ADMITTED.key])
    else:
        artifact = manifest["artifacts"][0]
        if damage == "payload":
            artifact["sha256"] = "a" * 64
        else:
            artifact["consumers"] = [ADMITTED.key]
    raw = json.dumps(manifest).encode()
    policy["source_manifest_sha256"] = sha(raw)
    with pytest.raises(GovernanceError):
        validate_transition(policy, (claw / RELEASE_PATH).read_bytes(),
                            (claw / HISTORICAL_MANIFEST_PATH).read_bytes(), raw,
                            yaml.safe_dump(fleet).encode())


@pytest.mark.parametrize("field", ["historical_declaration_sha256", "historical_manifest_sha256",
                                   "source_manifest_sha256", "fleet_entry_sha256"])
def test_substituted_admission_hashes_fail_closed(tmp_path, field):
    claw, _, policy, *_ = admitted(tmp_path)
    policy[field] = "a" * 64
    with pytest.raises(GovernanceError, match="hash differs"):
        validate_transition(policy, (claw / RELEASE_PATH).read_bytes(),
                            (claw / HISTORICAL_MANIFEST_PATH).read_bytes(),
                            (claw / MANIFEST).read_bytes(), (claw / FLEET_PATH).read_bytes())


@pytest.mark.parametrize("damage", ["declaration", "source_ref", "deleted_reintroduced", "historical_policy"])
def test_protected_admission_cannot_be_rewritten_or_resurrected(tmp_path, damage):
    claw, roots, policy, *_ = admitted(tmp_path)
    path = claw / (RELEASE_PATH if damage == "historical_policy" else ADMISSION_PATH)
    if damage == "deleted_reintroduced":
        content = path.read_bytes()
        path.unlink()
        commit(claw)
        path.write_bytes(content)
    elif damage == "source_ref":
        policy["source_ref"] = "a" * 40
        path.write_text(json.dumps(policy))
    else:
        path.write_bytes(path.read_bytes() + b"\n")
    commit(claw)
    with pytest.raises(GovernanceError, match="modified|reintroduced"):
        audit_release(claw, roots)


def test_candidate_admission_does_not_activate_itself_before_protected_merge(tmp_path):
    claw, roots, _, _, candidate, _ = admitted(tmp_path)
    git(claw, "update-ref", "refs/remotes/origin/main", candidate)
    assert validate_packaged_transition(claw)
    with pytest.raises(GovernanceError, match="not protected"):
        audit_release(claw, roots)


def test_duplicate_unknown_fields_and_historical_pin_substitution_fail(tmp_path):
    claw, _, policy, baseline, *_ = admitted(tmp_path)
    for changed in ({**policy, "allow_any_new_member": True}, {**policy, "version": True},
                    {**policy, "excluded_native_tests": []}):
        with pytest.raises(GovernanceError):
            parse_admission(json.dumps(changed).encode())
    with pytest.raises(GovernanceError, match="duplicate"):
        parse_admission(b'{"version":1,"version":1}')
    changed = deepcopy(policy)
    changed["source_ref"] = baseline
    with pytest.raises(GovernanceError, match="historical cohort pin"):
        validate_transition(changed, (claw / RELEASE_PATH).read_bytes(),
                            (claw / HISTORICAL_MANIFEST_PATH).read_bytes(),
                            (claw / MANIFEST).read_bytes(), (claw / FLEET_PATH).read_bytes())


def test_candidate_completeness_distinguishes_exact_bootstrap_from_changed_main(tmp_path, monkeypatch):
    import test_vendored_consumer_completeness as completeness

    claw, roots, _, *_ = admitted(tmp_path)
    monkeypatch.setattr(completeness, "ROOT", claw)
    monkeypatch.setattr(completeness, "MANIFEST", json.loads((claw / MANIFEST).read_bytes()))
    monkeypatch.setattr(completeness, "resolve_mech_root", lambda *args, **kwargs: roots[ADMITTED.key])
    completeness.test_a_declared_consumer_carries_every_artifact_that_applies_to_it(ADMITTED.key)
    put(roots[ADMITTED.key], "README.md", "Another uninstalled tip\n")
    commit(roots[ADMITTED.key])
    with pytest.raises(AssertionError, match="does not track"):
        completeness.test_a_declared_consumer_carries_every_artifact_that_applies_to_it(ADMITTED.key)


@pytest.mark.parametrize("installed", [False, True])
@pytest.mark.parametrize("squash", [False, True])
def test_future_payload_publication_preserves_exact_admitted_data(tmp_path, installed, squash):
    claw, roots, policy, baseline, candidate, _ = admitted(tmp_path, installed=installed, squash=squash)
    snapshots = {path: (claw / path).read_bytes() for path in
                 (RELEASE_PATH, ADMISSION_PATH, HISTORICAL_MANIFEST_PATH, ADMITTED_MANIFEST_PATH)}
    newer, payload = evolve_payload(claw)
    assert validate_packaged_transition(claw) == policy
    assert trusted_source_ref(claw) == policy["source_ref"]
    result = audit_release(claw, roots)
    assert result["ok"] and result["trusted_head"] == newer
    assert result["baseline_ref"] == baseline and result["candidate_ref"] == candidate
    edge = next(row for row in result["repositories"] if row["key"] == ADMITTED.key)
    assert edge["installation_verified"] is installed
    assert edge["pin"] == (policy["source_ref"] if installed else None)
    assert all((claw / path).read_bytes() == content for path, content in snapshots.items())
    assert (roots["traitmech"] / "scripts/legacy.py").read_text() != payload
    if installed:
        assert (roots[ADMITTED.key] / "scripts/legacy.py").read_text() != payload


def test_future_payload_requires_valid_current_checksum_even_with_admission(tmp_path):
    claw, roots, *_ = admitted(tmp_path, installed=True)
    evolve_payload(claw, update_digest=False)
    with pytest.raises(GovernanceError, match="checksum drift"):
        validate_packaged_transition(claw)
    with pytest.raises(GovernanceError, match="checksum drift"):
        audit_release(claw, roots)


@pytest.mark.parametrize("key", ["traitmech", "dufmech", ADMITTED.key])
def test_new_current_payload_never_substitutes_for_any_admitted_or_historical_pin(tmp_path, key):
    claw, roots, *_ = admitted(tmp_path, installed=True)
    _, payload = evolve_payload(claw)
    put(roots[key], "scripts/legacy.py", payload)
    commit(roots[key])
    result = audit_release(claw, roots)
    assert not result["ok"]
    row = next(row for row in result["repositories"] if row["key"] == key)
    assert any(issue["code"] == "committed_drift" for issue in row["issues"])


@pytest.mark.parametrize("field", ["target", "mode", "consumers", "consumer_identity", "extra_member", "pin_path"])
def test_future_current_manifest_cannot_change_admitted_authority_or_layout(tmp_path, field):
    claw, roots, *_ = admitted(tmp_path)
    manifest = json.loads((claw / MANIFEST).read_bytes())
    if field in {"target", "mode", "consumers"}:
        artifact = manifest["artifacts"][0]
        artifact[field] = {"target": "scripts/other.py", "mode": "0755", "consumers": [ADMITTED.key]}[field]
        if field == "mode":
            (claw / artifact["source"]).chmod(0o755)
    elif field == "consumer_identity":
        manifest["consumers"][ADMITTED.key]["github"] = "CultureBotAI/OtherMech"
    elif field == "extra_member":
        manifest["consumers"]["othermech"] = {"github": "CultureBotAI/OtherMech", "package_path": "src/othermech"}
    else:
        manifest["pin_path"] = "scripts/other-pin"
    put(claw, MANIFEST, json.dumps(manifest))
    commit(claw)
    with pytest.raises(GovernanceError):
        validate_packaged_transition(claw)
    with pytest.raises(GovernanceError):
        trusted_source_ref(claw)
    with pytest.raises(GovernanceError):
        audit_release(claw, roots)


def test_packaged_admitted_snapshot_remains_bound_to_original_declaration(tmp_path):
    claw, roots, *_ = admitted(tmp_path)
    evolve_payload(claw)
    put(claw, ADMITTED_MANIFEST_PATH, (claw / MANIFEST).read_text())
    commit(claw)
    for validate in (lambda: validate_packaged_transition(claw), lambda: trusted_source_ref(claw),
                     lambda: audit_release(claw, roots)):
        with pytest.raises(GovernanceError, match="source manifest hash differs"):
            validate()


def test_post_admission_catalogue_addition_permits_withheld_capability_and_rejects_drift():
    root = Path(__file__).resolve().parents[1]
    policy = parse_admission((root / ADMISSION_PATH).read_bytes())
    historical = (root / RELEASE_PATH).read_bytes()
    historical_manifest = (root / HISTORICAL_MANIFEST_PATH).read_bytes()
    admitted_manifest = (root / ADMITTED_MANIFEST_PATH).read_bytes()
    admitted_consumers = set(json.loads(admitted_manifest)["consumers"])
    fleet = yaml.safe_load((root / FLEET_PATH).read_bytes())
    fleet["mechs"] = {k: v for k, v in fleet["mechs"].items() if k in admitted_consumers}

    expanded = deepcopy(fleet)
    expanded["capability_catalogue"]["taxon_links"] = {
        "settings": {
            "slots": {
                "type": "string_list",
                "required_when_enabled": True,
            },
        },
    }
    for key, mech in expanded["mechs"].items():
        mech["capabilities"]["taxon_links"] = {
            "status": "disabled",
            "reason": f"{key} taxon_links disabled in test.",
        }
    assert validate_transition(
        policy,
        historical,
        historical_manifest,
        admitted_manifest,
        yaml.safe_dump(expanded).encode(),
    )

    enabled_on_edge = deepcopy(expanded)
    enabled_on_edge["mechs"][ADMITTED.key]["capabilities"]["taxon_links"] = {
        "status": "enabled",
        "settings": {"slots": ["taxon"]},
    }
    with pytest.raises(GovernanceError, match="cannot enable scientific"):
        validate_transition(
            policy,
            historical,
            historical_manifest,
            admitted_manifest,
            yaml.safe_dump(enabled_on_edge).encode(),
        )

    settings_on_withheld = deepcopy(expanded)
    settings_on_withheld["mechs"][ADMITTED.key]["capabilities"]["taxon_links"] = {
        "status": "disabled",
        "reason": "Withheld but carrying execution settings.",
        "settings": {"slots": ["taxon"]},
    }
    with pytest.raises(GovernanceError, match="cannot enable scientific"):
        validate_transition(
            policy,
            historical,
            historical_manifest,
            admitted_manifest,
            yaml.safe_dump(settings_on_withheld).encode(),
        )

    tampered_original = deepcopy(expanded)
    tampered_original["mechs"][ADMITTED.key]["capabilities"]["kgx_export"]["reason"] = "Tampered reason."
    with pytest.raises(GovernanceError, match="fleet entry hash differs"):
        validate_transition(
            policy,
            historical,
            historical_manifest,
            admitted_manifest,
            yaml.safe_dump(tampered_original).encode(),
        )

