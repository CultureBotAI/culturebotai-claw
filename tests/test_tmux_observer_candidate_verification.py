"""Evidence-verifier regressions for issue 1249; no live observer interaction.

Synthetic fixtures run everywhere. Optional explicitly selected private evidence
is read only, without invoking the receipt writer or checking a live process.
"""
import copy
import importlib.util
import json
import os
from pathlib import Path

import pytest

SOURCE = Path(os.environ.get("MECH_TMUX_CANDIDATE_VERIFIER_SOURCE",
                            Path(__file__).parents[1] / "scripts/adhoc/verify_tmux_observer_candidate.py"))
SPEC = importlib.util.spec_from_file_location("tmux_candidate_verifier", SOURCE)
verifier = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verifier)


@pytest.fixture
def evidence():
    baseline = {"schema_version": 1, "role": "observer_only", "targets": [
        {"key": key, "binding_status": binding, "window": number, "tab": 1, "tty": f"tty{number}"}
        for number, (key, binding) in enumerate((
            ("embedded", "bound"), ("managed", "bound"), ("legacy", "bound"), ("candidate", "unbound")))
    ]}
    proposal = copy.deepcopy(baseline)
    for row in proposal["targets"][:2]:
        prior = copy.deepcopy(row)
        row.update(transport="tmux", prior_binding=prior,
                   viewer={field: prior[field] for field in ("window", "tab", "tty")},
                   tmux_observation={"key": row["key"], "native": {"mode": row["key"]}})
    counts = {"configured": 4, "live_process_bindings": 2, "stale_or_unverified_bindings": 1,
              "unbound_candidates": 1, "verified_native_threads": 1}
    status = {"schema_version": 1, "role": "observer_only", "observer_pid": 1234,
              "completed_at": "2026-11-15T08:00:00+00:00", "registry_sha256": "a" * 64,
              "no_input": True, "no_goal_or_registry_writes": True, "counts": counts,
              "targets": [
                  {"key": "embedded", "transport": "tmux", "binding": "live", "native": {"state": "verified"}},
                  {"key": "managed", "transport": "tmux", "binding": "live", "native": {"state": "unknown"}},
                  {"key": "legacy", "binding": "stale", "native": {"state": "unknown"}},
                  {"key": "candidate", "binding": "unbound", "native": {"state": "unbound"}},
              ]}
    heartbeat = {"schema_version": 1, "pid": 1234, "updated_at": status["completed_at"],
                 "running": True, "registry_sha256": status["registry_sha256"],
                 "complete_cycle": True, "counts": copy.deepcopy(counts)}
    return {"baseline": baseline, "proposal": proposal, "status": status, "heartbeat": heartbeat,
            "once": copy.deepcopy(status), "snapshot": copy.deepcopy(status)}


def validate(evidence):
    counts = verifier.validate_cycle(*(evidence[name] for name in ("status", "heartbeat", "once", "snapshot")),
                                     evidence["status"]["registry_sha256"])
    transports = verifier.validate_scope(*(evidence[name] for name in ("baseline", "proposal", "status")))
    return counts, transports


def test_complete_cycle_preserves_scope_and_managed_unknown(evidence):
    original = copy.deepcopy(evidence)
    counts, transports = validate(evidence)
    assert counts == {"configured": 4, "live_process_bindings": 2, "stale_or_unverified_bindings": 1,
                      "unbound_candidates": 1, "verified_native_threads": 1}
    assert transports == {"tmux": 2, "legacy": 1, "unbound": 1}
    assert evidence == original


@pytest.mark.parametrize("field", ["configured", "live_process_bindings", "stale_or_unverified_bindings",
                                   "unbound_candidates", "verified_native_threads"])
def test_consistently_wrong_counts_rejected(evidence, field):
    for name in ("status", "heartbeat", "once", "snapshot"):
        evidence[name]["counts"][field] += 1
    with pytest.raises(ValueError, match="counts differ from observations"):
        validate(evidence)


@pytest.mark.parametrize("invalid", [True, -1, 4.0, "4"])
def test_count_types_are_exact(evidence, invalid):
    for name in ("status", "heartbeat", "once", "snapshot"):
        evidence[name]["counts"]["configured"] = invalid
    with pytest.raises(ValueError, match="counts differ from observations"):
        validate(evidence)


@pytest.mark.parametrize("change", ["missing", "extra"])
def test_count_fields_are_exact(evidence, change):
    for name in ("status", "heartbeat", "once", "snapshot"):
        if change == "missing":
            del evidence[name]["counts"]["verified_native_threads"]
        else:
            evidence[name]["counts"]["invented"] = 0
    with pytest.raises(ValueError, match="counts differ from observations"):
        validate(evidence)


@pytest.mark.parametrize("name", ["baseline", "proposal", "status", "once", "snapshot"])
def test_each_target_list_rejects_duplicates(evidence, name):
    evidence[name]["targets"].append(copy.deepcopy(evidence[name]["targets"][0]))
    with pytest.raises(ValueError, match="duplicate target key"):
        validate(evidence)


def test_matching_duplicate_lists_cannot_hide_extra_observations(evidence):
    for name in ("baseline", "proposal", "status", "once", "snapshot"):
        evidence[name]["targets"].append(copy.deepcopy(evidence[name]["targets"][0]))
    counts = {"configured": 5, "live_process_bindings": 3, "stale_or_unverified_bindings": 1,
              "unbound_candidates": 1, "verified_native_threads": 2}
    for name in ("status", "heartbeat", "once", "snapshot"):
        evidence[name]["counts"] = copy.deepcopy(counts)
    with pytest.raises(ValueError, match="duplicate target key"):
        validate(evidence)


@pytest.mark.parametrize("name", ["baseline", "proposal"])
@pytest.mark.parametrize("change", ["missing", "extra", "reordered"])
def test_cardinality_and_order_must_match(evidence, name, change):
    rows = evidence[name]["targets"]
    if change == "missing":
        rows.pop()
    elif change == "extra":
        rows.append({"key": "other"})
    else:
        rows.reverse()
    with pytest.raises(ValueError, match="scope/order changed"):
        validate(evidence)


@pytest.mark.parametrize("name", ["baseline", "proposal", "status", "once", "snapshot"])
@pytest.mark.parametrize(("field", "invalid"), [("schema_version", True), ("schema_version", 2),
                                                ("role", "controller"), ("role", None)])
def test_target_document_schema_and_role_are_required(evidence, name, field, invalid):
    evidence[name][field] = invalid
    with pytest.raises(ValueError, match="schema or role differs"):
        validate(evidence)


@pytest.mark.parametrize("name", ["status", "once", "snapshot"])
@pytest.mark.parametrize("field", ["no_input", "no_goal_or_registry_writes"])
@pytest.mark.parametrize("invalid", [False, 1, None])
def test_read_only_flags_are_required(evidence, name, field, invalid):
    if invalid is None:
        del evidence[name][field]
    else:
        evidence[name][field] = invalid
    with pytest.raises(ValueError, match="read-only flags differ"):
        validate(evidence)


@pytest.mark.parametrize(("field", "invalid", "message"), [
    ("schema_version", True, "Heartbeat schema"), ("schema_version", 2, "Heartbeat schema"),
    ("complete_cycle", 1, "persisted cycle"), ("running", False, "persisted cycle"),
    ("pid", True, "persisted cycle"), ("updated_at", "different", "persisted cycle"),
    ("registry_sha256", "b" * 64, "registry pin"), ("counts", {}, "counts differ"),
])
def test_heartbeat_contract(evidence, field, invalid, message):
    evidence["heartbeat"][field] = invalid
    with pytest.raises(ValueError, match=message):
        validate(evidence)


def write_evidence(root, evidence):
    state = root / "state"
    (state / "snapshots").mkdir(parents=True)
    paths = {"baseline": root / "baseline.json", "proposal": root / "proposal.json",
             "status": state / "status.json", "heartbeat": state / "heartbeat.json",
             "once": root / "once.json", "snapshot": state / "snapshots" / "cycle.json"}
    paths["proposal"].write_text(json.dumps(evidence["proposal"]))
    for name in ("status", "heartbeat", "once", "snapshot"):
        evidence[name]["registry_sha256"] = verifier.sha(paths["proposal"])
    for name, path in paths.items():
        path.write_text(json.dumps(evidence[name]))
    return state, paths


def test_saved_artifact_helper_reads_without_writes_or_live_processes(tmp_path, evidence, monkeypatch):
    state, paths = write_evidence(tmp_path, evidence)
    before = {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()}

    def no_process(*_args, **_kwargs):
        pytest.fail("Saved evidence validation must not contact live processes")

    monkeypatch.setattr(verifier.subprocess, "run", no_process)
    result = verifier.validate_saved_artifacts(state, paths["once"], paths["baseline"], paths["proposal"])
    assert result["counts"] == evidence["status"]["counts"]
    assert result["registry_transport_counts"] == {"tmux": 2, "legacy": 1, "unbound": 1}
    assert {path: path.read_bytes() for path in tmp_path.rglob("*") if path.is_file()} == before


@pytest.mark.parametrize("number", [0, 2])
def test_saved_artifacts_require_one_snapshot(tmp_path, evidence, number):
    state, paths = write_evidence(tmp_path, evidence)
    if number == 0:
        paths["snapshot"].unlink()
    else:
        (state / "snapshots" / "extra.json").write_bytes(paths["snapshot"].read_bytes())
    with pytest.raises(ValueError, match="Exactly one persisted snapshot"):
        verifier.validate_saved_artifacts(state, paths["once"], paths["baseline"], paths["proposal"])


@pytest.mark.skipif(not os.environ.get("MECH_TMUX_SAVED_EVIDENCE"), reason="Explicit private evidence not selected")
def test_explicit_private_saved_evidence_read_only(monkeypatch):
    evidence_root = Path(os.environ["MECH_TMUX_SAVED_EVIDENCE"])
    registries = Path(os.environ["MECH_TMUX_SAVED_REGISTRIES"])
    state = evidence_root / "test-runs/once-final"
    once = evidence_root / "once-result.json"
    baseline = registries / "legacy-registry.original.json"
    proposal = registries / "legacy-registry.proposed.json"
    paths = [once, baseline, proposal, evidence_root / "verification.json"]
    paths.extend(path for path in state.rglob("*") if path.is_file())
    before = {path: path.read_bytes() for path in paths}

    def no_process(*_args, **_kwargs):
        pytest.fail("Saved evidence validation must not contact live processes")

    monkeypatch.setattr(verifier.subprocess, "run", no_process)
    result = verifier.validate_saved_artifacts(state, once, baseline, proposal)
    receipt = json.loads(before[evidence_root / "verification.json"])
    assert result["counts"] == receipt["counts"]
    assert result["registry_transport_counts"] == receipt["registry_transport_counts"]
    assert result["completed_at"] == receipt["candidate_completed_at"]
    assert {path: path.read_bytes() for path in paths} == before
