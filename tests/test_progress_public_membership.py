"""Public transport excludes tagged members before aggregation; local evidence survives."""
from __future__ import annotations

import copy
import json
from dataclasses import replace

import pytest
from test_progress_publish import GitHub, builder, publisher

import kg_microbe_progress as progress
from kg_microbe_fleet import FleetManifest, load_fleet_manifest


@pytest.fixture
def mixed(tmp_path, monkeypatch):
    import test_progress_model as fixtures

    fleet = load_fleet_manifest()
    fleet = FleetManifest(
        {key: replace(fleet.get(key), tags=("exclude-from-public",) if key == "traitmech" else ())
         for key in ("culturemech", "traitmech")},
        fleet.capability_catalogue, fleet.vendored_governance, fleet.source,
    )
    roots = []
    for key, count in (("culturemech", 1), ("traitmech", 2)):
        with monkeypatch.context() as patch:
            patch.setattr(fixtures, "KEY", key)
            patch.setattr(fixtures, "GITHUB", fleet.get(key).github)
            root, ledger = fixtures.runtime(tmp_path, name=key, stage=count + 1)
            for stage in range(1, count + 1):
                fixtures.add_closure(root, ledger, stage=stage, pr=100 + stage)
            roots.append(root)
    history, snapshot = progress.collect_progress(roots, generated_at=fixtures.NOW, manifest=fleet)
    monkeypatch.setattr(progress, "load_fleet_manifest", lambda: fleet)
    monkeypatch.setattr(publisher, "load_fleet_manifest", lambda: fleet)
    return fleet, {"history": history, "snapshot": snapshot}


@pytest.fixture
def three_members(tmp_path, monkeypatch):
    """Interleaved public membership with distinct nonzero private contributions."""
    import test_progress_model as fixtures

    full = load_fleet_manifest()
    keys = full.keys[:3]
    fleet = FleetManifest(
        {key: replace(full.get(key), tags=("exclude-from-public",) if key == keys[1] else ())
         for key in keys},
        full.capability_catalogue, full.vendored_governance, full.source,
    )
    roots = []
    for count, key in enumerate(keys, 1):
        with monkeypatch.context() as patch:
            patch.setattr(fixtures, "KEY", key)
            patch.setattr(fixtures, "GITHUB", fleet.get(key).github)
            root, ledger = fixtures.runtime(tmp_path, name=key, stage=count + 1)
            for stage in range(1, count + 1):
                fixtures.add_closure(root, ledger, stage=stage, pr=100 + stage)
            roots.append(root)
    history, snapshot = progress.collect_progress(roots, generated_at=fixtures.NOW, manifest=fleet)
    return fleet, {"history": history, "snapshot": snapshot}


@pytest.mark.parametrize("change", ["exclude_again", "reenable"])
def test_policy_change_reads_reconciles_and_republishes_retained_membership(
    three_members, change, tmp_path, monkeypatch,
):
    from kg_microbe_progress.prs import AssociationCollection

    old_fleet, local = three_members
    first, middle, last = old_fleet.keys
    excluded = {first, middle} if change == "exclude_again" else set()
    current = FleetManifest(
        {key: replace(mech, tags=("exclude-from-public",) if key in excluded else ())
         for key, mech in old_fleet.mechs.items()},
        old_fleet.capability_catalogue, old_fleet.vendored_governance, old_fleet.source,
    )
    api = GitHub()
    publisher.publish(local, None, None, initialize=True, api=api, manifest=old_fleet)
    _, retained = publisher.read_remote(api, manifest=current, project_expanded=False)
    assert [row["key"] for row in retained["snapshot"]["repositories"]] == (
        [last] if change == "exclude_again" else [first, last]
    )
    state = tmp_path / "policy-change"
    publisher.atomic_json(state / "bundle.json", local)
    monkeypatch.setattr(progress, "load_fleet_manifest", lambda: current)
    monkeypatch.setattr(publisher, "load_fleet_manifest", lambda: current)
    monkeypatch.setattr(publisher, "collect_associations", lambda _: AssociationCollection([], {}))
    monkeypatch.setattr(publisher, "fetch_pr_observations", lambda _: [])
    for _ in range(2):
        publisher.collect_once([], state, apply=True, api=api)
        saved = json.loads((state / "bundle.json").read_text())
        assert saved["history"] == local["history"]
        assert saved["snapshot"]["totals"]["completed_goals"] == 6
    _, observed = publisher.read_remote(api, manifest=current)
    assert observed["snapshot"]["totals"]["completed_goals"] == (3 if excluded else 6)
    assert [row["key"] for row in observed["snapshot"]["repositories"]] == list(current.public().keys)
    assert observed["history"] == progress.public_history(local["history"], current)


@pytest.mark.parametrize("damage", ["unknown", "duplicate", "reordered", "omitted", "totals"])
def test_retained_subset_still_validates_its_exact_membership_and_evidence(three_members, damage):
    fleet, bundle = three_members
    snapshot = bundle["snapshot"]
    if damage == "unknown":
        snapshot["repositories"][1]["key"] = "unknownmech"
    elif damage == "duplicate":
        snapshot["repositories"].append(copy.deepcopy(snapshot["repositories"][0]))
    elif damage == "reordered":
        snapshot["repositories"].reverse()
    elif damage == "omitted":
        snapshot["repositories"].pop(1)
    else:
        snapshot["totals"]["completed_goals"] += 1
    with pytest.raises(progress.ProgressError):
        progress.public_bundle(**bundle, manifest=fleet)


def test_reenabling_member_does_not_allow_deleting_retained_history(three_members):
    old_fleet, local = three_members
    current = FleetManifest(
        {key: replace(mech, tags=()) for key, mech in old_fleet.mechs.items()},
        old_fleet.capability_catalogue, old_fleet.vendored_governance, old_fleet.source,
    )
    api = GitHub()
    head = publisher.publish(local, None, None, initialize=True, api=api, manifest=old_fleet)
    _, retained = publisher.read_remote(api, manifest=current, project_expanded=False)
    history = copy.deepcopy(local["history"])
    assert history["closures"][-1]["repository_key"] == current.keys[-1]
    history["closures"].pop()
    snapshot = progress.snapshot_from_history(history, generated_at=local["snapshot"]["generated_at"], manifest=current)
    before = copy.deepcopy(api.calls)
    with pytest.raises(progress.ProgressError, match="append-only history changed"):
        publisher.publish({"history": history, "snapshot": snapshot}, head, retained, api=api, manifest=current)
    assert api.calls == before


def test_public_projection_removes_history_and_nonzero_contributions(mixed):
    fleet, bundle = mixed
    original = copy.deepcopy(bundle)
    projected = progress.public_bundle(**bundle, manifest=fleet)
    assert list(fleet.keys) == ["culturemech", "traitmech"]
    assert bundle == original
    assert bundle["snapshot"]["totals"]["completed_goals"] == 3
    assert bundle["snapshot"]["totals"]["unique_prs"] == 3
    assert projected["snapshot"]["totals"]["completed_goals"] == 1
    assert projected["snapshot"]["totals"]["unique_prs"] == 1
    assert [row["key"] for row in projected["snapshot"]["repositories"]] == ["culturemech"]
    assert "traitmech" not in json.dumps(projected).lower()
    assert all(projected["history"][field] for field in ("closures", "pr_events", "associations", "cursors"))
    progress.validate_bundle(**projected, manifest=fleet.public())


def test_transport_and_site_never_serialize_excluded_member(tmp_path, monkeypatch, mixed):
    fleet, bundle = mixed
    api = GitHub()
    head = publisher.publish(bundle, None, None, initialize=True, api=api, manifest=fleet)
    assert "traitmech" not in json.dumps(api.calls).lower()
    _, published = publisher.read_remote(api, manifest=fleet)
    assert published == progress.public_bundle(**bundle, manifest=fleet)
    source = tmp_path / "source"
    source.mkdir()
    (source / "index.html").write_text("<!doctype html><title>Progress</title>")
    # Even a pre-filter legacy remote bundle must not leak through Pages.
    monkeypatch.setattr(builder, "read_remote", lambda: (head, bundle))
    destination = tmp_path / "site"
    builder.build(source, destination)
    for path in (destination / "data").glob("*.json"):
        assert "traitmech" not in path.read_text().lower()
    assert json.loads((destination / "data/progress.json").read_text())["totals"]["completed_goals"] == 1


def test_remote_public_updates_preserve_excluded_local_history(mixed):
    fleet, bundle = mixed
    local = bundle["history"]
    public = progress.public_history(local, fleet)
    assert publisher.newest_history(local, public, manifest=fleet) == local
    newer = copy.deepcopy(public)
    newer["cursors"][0]["observed_at"] = "2026-10-20T09:00:00Z"
    reconciled = publisher.newest_history(local, newer, manifest=fleet)
    progress.validate_extension(local, reconciled, fleet)
    assert progress.public_history(reconciled, fleet) == newer
    for field in ("closures", "pr_events", "associations", "cursors"):
        assert [row for row in reconciled[field] if row["repository_key"] == "traitmech"] == [
            row for row in local[field] if row["repository_key"] == "traitmech"]


def test_invalid_excluded_evidence_is_not_hidden(mixed):
    fleet, bundle = mixed
    bundle["history"]["closures"][-1]["id"] = "0" * 64
    with pytest.raises(progress.ProgressError):
        progress.public_bundle(**bundle, manifest=fleet)


def test_empty_public_projection_is_valid_and_stays_empty(mixed):
    fleet, bundle = mixed
    excluded = FleetManifest(
        {key: replace(mech, tags=("exclude-from-public",)) for key, mech in fleet.mechs.items()},
        fleet.capability_catalogue, fleet.vendored_governance, fleet.source,
    )
    projected = progress.public_bundle(**bundle, manifest=excluded)
    assert projected["snapshot"]["repositories"] == []
    assert not any(projected["snapshot"]["totals"].values())
    assert progress.public_bundle(**projected, manifest=excluded) == projected
    progress.validate_bundle(**projected, manifest=excluded.public())


def test_invalid_excluded_snapshot_is_not_recomputed_away(mixed):
    fleet, bundle = mixed
    bundle["snapshot"]["repositories"][-1]["counters"]["completed_goals"] = 200
    with pytest.raises(progress.ProgressError):
        progress.public_bundle(**bundle, manifest=fleet)


def test_publisher_keeps_full_local_bundle(tmp_path, monkeypatch, mixed):
    from kg_microbe_progress.prs import AssociationCollection

    fleet, bundle = mixed
    monkeypatch.setattr(publisher, "collect_associations", lambda _: AssociationCollection([], {}))
    monkeypatch.setattr(publisher, "fetch_pr_observations", lambda _: [])
    monkeypatch.setattr(publisher, "collect_progress", lambda *a, **kw: (bundle["history"], bundle["snapshot"]))
    api = GitHub()
    state = tmp_path / "state"
    publisher.collect_once([], state, apply=True, initialize=True, api=api)
    assert json.loads((state / "bundle.json").read_text()) == bundle
    publisher.collect_once([], state, apply=True, api=api)
    assert json.loads((state / "bundle.json").read_text()) == bundle
    assert publisher.read_remote(api, manifest=fleet)[1]["snapshot"]["totals"]["completed_goals"] == 1
