"""The short report must preserve evidence, freshness, and distinct PR counts."""
from __future__ import annotations

import base64
import copy
import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

import kg_microbe_progress as progress
from kg_microbe_fleet import load_fleet_manifest

ROOT = Path(__file__).parents[1]
NOW = datetime(2026, 10, 20, 10, tzinfo=timezone.utc)
STAMP = NOW.isoformat()


@pytest.fixture
def status(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "mech_progress_status", ROOT / "scripts/mech_progress_status.py"
    )
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


@pytest.fixture
def bundle(tmp_path):
    """Use genuine collector output, including an independently verified goal."""
    fleet = load_fleet_manifest()
    runtime = tmp_path / "runtime"
    run_id = "summary-fixture"
    write(runtime / "config.json", {
        "run_id": run_id,
        "targets": [
            {"repository_key": key, "github_repository": mech.github}
            for key, mech in fleet.mechs.items()
        ],
    })
    goal_key = fleet.keys[0]
    for key in fleet.keys:
        ledger = {
            "schema_version": 2, "run_id": run_id, "repository_key": key,
            "cycle": 1, "stage": 2 if key == goal_key else 1,
            "created_at": "2026-10-20T01:00:00Z", "last_observed_at": STAMP,
            "completed_stages": [], "phase": "waiting",
        }
        if key == goal_key:
            identity = {"conversation_id": "test-only", "start_step_index": 1, "started_at": STAMP}
            receipt = {
                "run_id": run_id, "repository_key": key, "cycle": 1, "stage": 1,
                "goal_identity": identity, "goal_complete": True, "status": "no_changes",
                "pr": None,
            }
            checksum = progress.digest(receipt)
            ledger["completed_stages"].append({
                "cycle": 1, "stage": 1, "goal_identity": identity,
                "receipt_sha256": checksum,
                "verification": {"verified_at": STAMP, "status": "no_changes"},
            })
            write(runtime / key / "receipts" / "cycle-000001" /
                  f"stage-1-{checksum[:12]}.json", receipt)
        write(runtime / key / "ledger.json", ledger)
    common = {
        "repository_key": goal_key, "run_id": run_id, "cycle": 1, "stage": 2,
        "head_sha": "a" * 40, "observed_at": STAMP,
    }
    history, snapshot = progress.collect_progress(
        [runtime], generated_at=STAMP, verified_pr_observations=[
            {**common, "number": 11, "state": "merged",
             "merge_commit_sha": "b" * 40, "merged_at": STAMP},
            {**common, "number": 12, "state": "open"},
            {**common, "number": 13, "state": "merged",
             "merge_commit_sha": "c" * 40, "merged_at": STAMP},
        ],
    )
    return {"history": history, "snapshot": snapshot}


def test_exact_requested_format_pluralization_and_closed_prs(status):
    snapshot = {
        "repositories": [{}] * 14,
        "totals": {
            "unique_prs": 8, "merged_prs": 5, "open_prs": 3, "closed_prs": 0,
            "completed_goals": 1, "completed_cycles": 0,
        },
    }
    assert status.format_summary(snapshot) == (
        "14 Mechs, 8 PRs (5 merged, 3 open), 1 completed goal, 0 completed cycles"
    )
    snapshot["repositories"] = [{}]
    snapshot["totals"].update(
        unique_prs=1, merged_prs=0, open_prs=0, closed_prs=1,
        completed_goals=6, completed_cycles=1,
    )
    assert status.format_summary(snapshot) == (
        "1 Mech, 1 PR (0 merged, 0 open, 1 closed without merge), "
        "6 completed goals, 1 completed cycle"
    )


def test_valid_bundle_reports_distinct_goals_and_prs_without_mutation(
    status, tmp_path, bundle, capsys
):
    path = tmp_path / "bundle.json"
    write(path, bundle)
    before = path.read_bytes()
    assert status.main(["--bundle", str(path)], now=NOW) == 0
    output = capsys.readouterr()
    assert output.out == (
        f"{len(load_fleet_manifest().keys)} Mechs, 3 PRs (2 merged, 1 open), "
        "1 completed goal, 0 completed cycles\n"
    )
    assert output.err == ""
    assert path.read_bytes() == before


@pytest.mark.parametrize("tamper", ["count", "history"])
def test_invalid_evidence_never_emits_counts(status, tmp_path, bundle, capsys, tamper):
    if tamper == "count":
        bundle["snapshot"]["totals"]["completed_goals"] += 1
    else:
        # Snapshot itself remains valid, but its claimed goal has no history.
        bundle["history"]["closures"] = []
    path = tmp_path / "bundle.json"
    write(path, bundle)
    assert status.main(["--bundle", str(path)], now=NOW) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err


@pytest.mark.parametrize(
    "problem", ["snapshot", "repository", "unobserved", "future", "snapshot_future"]
)
def test_fresh_publication_cannot_hide_stale_or_absent_observations(
    status, tmp_path, bundle, capsys, problem
):
    if problem == "snapshot":
        bundle["snapshot"]["generated_at"] = (NOW - timedelta(seconds=901)).isoformat()
    elif problem == "repository":
        bundle["history"]["cursors"][0]["observed_at"] = (
            NOW - timedelta(seconds=901)
        ).isoformat()
    elif problem == "unobserved":
        bundle["history"]["cursors"].pop()
    elif problem == "future":
        bundle["history"]["cursors"][0]["observed_at"] = (
            NOW + timedelta(seconds=61)
        ).isoformat()
    else:
        bundle["snapshot"]["generated_at"] = (NOW + timedelta(seconds=61)).isoformat()
    bundle["snapshot"] = progress.snapshot_from_history(
        bundle["history"], generated_at=bundle["snapshot"]["generated_at"]
    )
    path = tmp_path / "bundle.json"
    write(path, bundle)
    assert status.main(["--bundle", str(path)], now=NOW) == 3
    output = capsys.readouterr()
    assert output.out == status.format_summary(bundle["snapshot"]) + "\n"
    assert output.err


def test_freshness_boundary_and_timezone_offsets(status, bundle):
    snapshot = copy.deepcopy(bundle["snapshot"])
    snapshot["generated_at"] = "2026-10-20T02:45:00-07:00"
    snapshot["repositories"][0]["last_observed_at"] = "2026-10-20T10:01:00+00:00"
    snapshot["repositories"][0]["current"]["observed_at"] = "2026-10-20T10:01:00+00:00"
    assert status.freshness_warnings(snapshot, NOW) == []
    snapshot["repositories"][0]["last_observed_at"] = "2026-10-20T10:01:01+00:00"
    snapshot["repositories"][0]["current"]["observed_at"] = "2026-10-20T10:01:01+00:00"
    assert status.freshness_warnings(snapshot, NOW)


def test_missing_bundle_does_not_report_zero(status, tmp_path, capsys):
    assert status.main(["--bundle", str(tmp_path / "missing.json")], now=NOW) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err


@pytest.mark.parametrize("value", [
    [], {},
    {"history": [], "snapshot": {}},
    {"history": {}, "snapshot": None},
])
def test_malformed_bundle_objects_report_unavailable(status, tmp_path, capsys, value):
    path = tmp_path / "bundle.json"
    write(path, value)
    assert status.main(["--bundle", str(path)], now=NOW) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err.startswith("Progress unavailable:")


def test_published_bundle_is_validated_and_network_failure_has_no_zero_fallback(
    status, bundle, monkeypatch, capsys
):
    monkeypatch.setattr(status, "read_remote", lambda **kwargs: ("a" * 40, bundle))
    assert status.main(["--published"], now=NOW) == 0
    assert capsys.readouterr().out == status.format_summary(bundle["snapshot"]) + "\n"
    bundle["history"]["closures"] = []
    assert status.main(["--published"], now=NOW) == 1
    assert capsys.readouterr().out == ""
    monkeypatch.setattr(status, "read_remote", lambda **kwargs: (None, None))
    assert status.main(["--published"], now=NOW) == 1
    assert capsys.readouterr().out == ""

    def unavailable(**kwargs):
        raise OSError("offline")

    monkeypatch.setattr(status, "read_remote", unavailable)
    assert status.main(["--published"], now=NOW) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err


def mismatch_default_manifest(tmp_path, monkeypatch):
    """Model an older checkout while retaining the publisher's reviewed fleet."""
    pinned_text = load_fleet_manifest().source.read_text()
    older = yaml.safe_load(pinned_text)
    older["mechs"].pop(next(reversed(older["mechs"])))
    old_path = tmp_path / "older-fleet.yaml"
    write(old_path, older)
    monkeypatch.setenv("KG_MICROBE_FLEET_MANIFEST", str(old_path))
    return pinned_text


def test_mismatched_default_manifest_refuses_counts(status, tmp_path, bundle, monkeypatch, capsys):
    mismatch_default_manifest(tmp_path, monkeypatch)
    path = tmp_path / "bundle.json"
    write(path, bundle)
    assert status.main(["--bundle", str(path)], now=NOW) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err.startswith("Progress unavailable:")


@pytest.mark.parametrize("selection", ["explicit", "adjacent"])
def test_pinned_manifest_validates_publisher_fleet_without_changing_default(
    status, tmp_path, bundle, monkeypatch, capsys, selection
):
    pinned_text = mismatch_default_manifest(tmp_path, monkeypatch)
    path = tmp_path / "bundle.json"
    write(path, bundle)
    pin = tmp_path / ("explicit-fleet.yaml" if selection == "explicit" else "fleet.yaml")
    pin.write_text(pinned_text)
    arguments = ["--bundle", str(path)]
    if selection == "explicit":
        arguments.extend(["--manifest", str(pin)])
    default_before = load_fleet_manifest()
    assert status.main(arguments, now=NOW) == 0
    output = capsys.readouterr()
    assert output.out == status.format_summary(bundle["snapshot"]) + "\n"
    assert output.err == ""
    assert load_fleet_manifest().keys == default_before.keys
    assert len(default_before.keys) + 1 == len(bundle["snapshot"]["repositories"])


@pytest.mark.parametrize(
    "selection", ["explicit", "adjacent", "missing", "broken_symlink", "directory"]
)
def test_invalid_manifest_pin_never_falls_back_to_matching_default(
    status, tmp_path, bundle, capsys, selection
):
    path = tmp_path / "bundle.json"
    write(path, bundle)
    pin = tmp_path / ("explicit-fleet.yaml" if selection in {"explicit", "missing"} else "fleet.yaml")
    if selection == "broken_symlink":
        pin.symlink_to(tmp_path / "absent.yaml")
    elif selection == "directory":
        pin.mkdir()
    elif selection != "missing":
        pin.write_text("[]\n")
    arguments = ["--bundle", str(path)]
    if selection in {"explicit", "missing"}:
        arguments.extend(["--manifest", str(pin)])
    assert status.main(arguments, now=NOW) == 1
    output = capsys.readouterr()
    assert output.out == ""
    assert output.err.startswith("Progress unavailable:")


@pytest.mark.parametrize("selection", ["explicit", "adjacent"])
def test_published_read_and_bundle_validation_use_pinned_manifest(
    status, tmp_path, bundle, monkeypatch, capsys, selection
):
    pinned_text = mismatch_default_manifest(tmp_path, monkeypatch)
    pin = tmp_path / (
        "pinned-fleet.yaml" if selection == "explicit"
        else "workspace/progress-publisher/fleet.yaml"
    )
    pin.parent.mkdir(parents=True, exist_ok=True)
    pin.write_text(pinned_text)
    monkeypatch.chdir(tmp_path)
    seen = []

    def remote(*, manifest):
        seen.append(manifest)
        return "a" * 40, bundle

    monkeypatch.setattr(status, "read_remote", remote)
    arguments = ["--published"]
    if selection == "explicit":
        arguments.extend(["--manifest", str(pin)])
    assert status.main(arguments, now=NOW) == 0
    output = capsys.readouterr()
    assert output.out == status.format_summary(bundle["snapshot"]) + "\n"
    assert output.err == ""
    assert len(seen) == 1
    assert seen[0].source == pin
    assert list(seen[0].keys) == [row["key"] for row in bundle["snapshot"]["repositories"]]


def test_remote_reader_validates_with_the_selected_manifest(status, tmp_path, bundle, monkeypatch):
    pinned_text = mismatch_default_manifest(tmp_path, monkeypatch)
    pin = tmp_path / "pinned-fleet.yaml"
    pin.write_text(pinned_text)
    prefix = "repos/CultureBotAI/culturebotai-claw/git/"
    responses = {
        prefix + "ref/heads/mech-progress-data": {"object": {"sha": "a" * 40}},
        prefix + "commits/" + "a" * 40: {"tree": {"sha": "b" * 40}},
    }
    tree = []
    for name, key, sha in (
        ("history.json", "history", "c" * 40),
        ("progress.json", "snapshot", "d" * 40),
    ):
        raw = json.dumps(bundle[key]).encode()
        tree.append({"path": name, "sha": sha, "type": "blob", "mode": "100644", "size": len(raw)})
        responses[prefix + "blobs/" + sha] = {
            "encoding": "base64", "size": len(raw), "content": base64.b64encode(raw).decode(),
        }
    responses[prefix + "trees/" + "b" * 40] = {"tree": tree}
    with pytest.raises(progress.ProgressError):
        status.read_remote(api=responses.__getitem__)
    assert status.read_remote(
        api=responses.__getitem__, manifest=load_fleet_manifest(pin)
    ) == ("a" * 40, bundle)
