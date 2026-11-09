"""Publication transport must preserve history and isolate data from deployed code."""
import base64
import copy
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from kg_microbe_progress import collect_progress
from kg_microbe_progress.prs import AssociationCollection

ROOT = Path(__file__).parents[1]
SPEC = importlib.util.spec_from_file_location("mech_progress_publish", ROOT / "scripts/mech_progress_publish.py")
publisher = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = publisher
SPEC.loader.exec_module(publisher)
BUILD_SPEC = importlib.util.spec_from_file_location("build_mech_progress_site", ROOT / "scripts/build_mech_progress_site.py")
builder = importlib.util.module_from_spec(BUILD_SPEC)
BUILD_SPEC.loader.exec_module(builder)


@pytest.fixture
def bundle():
    history, snapshot = collect_progress([], generated_at="2026-10-20T10:00:00Z")
    return {"history": history, "snapshot": snapshot}


class GitHub:
    def __init__(self):
        self.objects = {}
        self.head = None
        self.calls = []
        self.fail_dispatch = False
        self.race = False

    def __call__(self, path, *, method="GET", payload=None):
        self.calls.append((path, method, payload))
        kind = path.split("/git/")[-1]
        if method == "GET":
            if kind.startswith("ref/"):
                return {"object": {"sha": self.head}} if self.head else None
            return copy.deepcopy(self.objects[kind.split("/")[-1]])
        if path.endswith("/dispatches"):
            if self.fail_dispatch:
                raise publisher.PublishError("dispatch unavailable")
            return None
        if kind.startswith("refs"):
            if self.race:
                raise publisher.PublishError("non-fast-forward")
            assert payload.get("force", False) is False
            self.head = payload["sha"]
            return {"object": {"sha": self.head}}
        sha = f"{len(self.objects) + 1:040x}"
        if kind == "blobs":
            raw = payload["content"].encode()
            value = {"encoding": "base64", "size": len(raw), "content": base64.b64encode(raw).decode()}
        elif kind == "trees":
            value = copy.deepcopy(payload)
        else:
            value = {**payload, "tree": {"sha": payload["tree"]}}
        self.objects[sha] = value
        return {"sha": sha}


def test_initialization_is_explicit_and_atomic(bundle):
    api = GitHub()
    with pytest.raises(publisher.PublishError, match="initialize"):
        publisher.publish(bundle, None, None, api=api)
    assert api.calls == []
    head = publisher.publish(bundle, None, None, initialize=True, api=api)
    observed, restored = publisher.read_remote(api)
    assert observed == head
    assert restored == bundle
    assert set(api.objects[api.objects[head]["tree"]["sha"]]["tree"][i]["path"] for i in range(2)) == {"history.json", "progress.json"}
    before = len(api.calls)
    assert publisher.publish(bundle, head, restored, api=api) == head
    assert len(api.calls) == before


def test_failed_dispatch_keeps_committed_data(bundle):
    api = GitHub()
    api.fail_dispatch = True
    with pytest.raises(publisher.PublishError, match="dispatch"):
        publisher.publish(bundle, None, None, initialize=True, api=api)
    assert api.head
    assert publisher.read_remote(api)[1] == bundle


def test_racing_publisher_cannot_force_replace_branch(bundle):
    api = GitHub()
    head = publisher.publish(bundle, None, None, initialize=True, api=api)
    next_bundle = copy.deepcopy(bundle)
    next_bundle["snapshot"]["generated_at"] = "2026-10-20T11:00:00Z"
    api.race = True
    with pytest.raises(publisher.PublishError, match="non-fast-forward"):
        publisher.publish(next_bundle, head, bundle, api=api)
    assert api.head == head
    assert publisher.read_remote(api)[1] == bundle


def test_refuse_unexpected_executable_data_branch_entries(bundle):
    api = GitHub()
    head = publisher.publish(bundle, None, None, initialize=True, api=api)
    tree = api.objects[api.objects[head]["tree"]["sha"]]
    tree["tree"].append({"path": "deploy.sh", "type": "blob", "mode": "100755", "sha": "bad"})
    with pytest.raises(publisher.PublishError, match="unexpected"):
        publisher.read_remote(api)


def test_refuse_invalid_or_private_snapshot_fields(bundle):
    api = GitHub()
    broken = copy.deepcopy(bundle)
    broken["snapshot"]["terminal_output"] = "private secret"
    with pytest.raises(ValueError):
        publisher.publish(broken, None, None, initialize=True, api=api)
    assert api.calls == []


def test_atomic_state_refuses_symlink_without_touching_target(tmp_path, bundle):
    target = tmp_path / "unrelated"
    target.write_text("preserve me")
    link = tmp_path / "bundle.json"
    link.symlink_to(target)
    with pytest.raises(publisher.PublishError, match="symlink"):
        publisher.atomic_json(link, bundle)
    assert target.read_text() == "preserve me"


def test_failed_publish_retains_local_history(tmp_path, monkeypatch, bundle):
    api = GitHub()
    api.fail_dispatch = True
    monkeypatch.setattr(publisher, "collect_associations", lambda _: AssociationCollection([], {}))
    monkeypatch.setattr(publisher, "fetch_pr_observations", lambda _: [])
    monkeypatch.setattr(publisher, "collect_progress", lambda *a, **kw: (bundle["history"], bundle["snapshot"]))
    with pytest.raises(publisher.PublishError):
        publisher.collect_once([], tmp_path, apply=True, initialize=True, api=api)
    assert json.loads((tmp_path / "bundle.json").read_text()) == bundle
    assert publisher.read_remote(api)[1] == bundle


def test_build_pins_one_bundle_and_copies_only_static_source(tmp_path, monkeypatch, bundle):
    source = tmp_path / "source"
    source.mkdir()
    (source / "index.html").write_text("<!doctype html><title>Progress</title>")
    monkeypatch.setattr(builder, "read_remote", lambda: ("a" * 40, bundle))
    output = tmp_path / "out"
    assert builder.build(source, output) == "a" * 40
    assert json.loads((output / "data/progress.json").read_text()) == bundle["snapshot"]
    assert json.loads((output / "data/publication.json").read_text())["data_commit"] == "a" * 40
    with pytest.raises(ValueError, match="already exists"):
        builder.build(source, output)


def test_pages_workflow_executes_main_code_and_limits_deployment_permissions():
    import yaml
    value = yaml.safe_load((ROOT / ".github/workflows/mech-progress-pages.yaml").read_text())
    build = value["jobs"]["build"]
    assert build["if"] == "github.ref == 'refs/heads/main'"
    checkout = build["steps"][0]
    assert checkout["with"]["ref"] == "main"
    assert value["permissions"] == {"contents": "read"}
    assert value["jobs"]["deploy"]["permissions"] == {"pages": "write", "id-token": "write"}
    assert value["concurrency"]["cancel-in-progress"] is False


def test_fifo_bundle_fails_promptly_in_a_fresh_process(tmp_path):
    fifo = tmp_path / "bundle.json"
    os.mkfifo(fifo)
    code = (
        "import sys; sys.path.insert(0, 'scripts'); "
        "from mech_progress_publish import read_json; "
        "from pathlib import Path; read_json(Path(sys.argv[1]))"
    )
    result = subprocess.run([sys.executable, "-c", code, str(fifo)], cwd=ROOT,
                            capture_output=True, text=True, timeout=8)
    assert result.returncode != 0
    assert "not a regular file" in result.stderr


def test_fifo_lock_fails_without_mutating_state(tmp_path):
    os.mkfifo(tmp_path / "publisher.lock")
    with pytest.raises(publisher.PublishError, match="regular file"):
        publisher.collect_once([], tmp_path)
    assert not (tmp_path / "bundle.json").exists()


def test_refresh_skips_known_merged_bindings_but_checks_new_and_reopenable_prs():
    history = {"pr_events": [
        {"pr_id": "merged", "number": 1, "state": "merged"},
        {"pr_id": "closed", "number": 2, "state": "closed"}],
        "associations": [
            {"pr_id": name, "repository_key": "traitmech", "run_key": publisher.run_key("run"),
             "cycle": 1, "stage_number": 1} for name in ("merged", "closed")]}
    old = {"repository_key": "traitmech", "run_id": "run", "cycle": 1, "stage": 1, "pr_number": 1}
    new_binding = {**old, "stage": 2}
    refresh = publisher.refresh_associations([old, new_binding], history)
    assert len(refresh) == 2
    assert new_binding in refresh
    assert any(item["pr_number"] == 2 for item in refresh)
    assert old not in refresh


def test_dry_run_excludes_orphan_and_preserves_public_history(tmp_path, monkeypatch):
    from test_progress_model import KEY, pr_observation, runtime, save_ledger

    from kg_microbe_progress import prs, validate_bundle

    root, ledger = runtime(tmp_path)
    ledger.update(adopted_goal={"conversation_id": "private", "started_at": ledger["created_at"],
                                "start_step_index": 2}, workflow={"sha256": "c" * 64})
    save_ledger(root, ledger)
    orphan = {**prs._context(ledger), "schema_version": 1, "pr_number": 42,
              "reported_at": ledger["last_observed_at"]}
    orphan["goal_identity"] = {**ledger["adopted_goal"], "start_step_index": 1}
    registry = root / KEY / prs.REGISTRY_NAME
    registry.write_text(json.dumps(orphan) + "\n")
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    history, snapshot = collect_progress([root], verified_pr_observations=[pr_observation(ledger)])
    state = tmp_path / "state"
    publisher.atomic_json(state / "bundle.json", {"history": history, "snapshot": snapshot})
    queries = []
    def fetch(associations):
        queries.extend(associations)
        return []
    monkeypatch.setattr(publisher, "fetch_pr_observations", fetch)
    api = GitHub()
    result = publisher.collect_once([root], state, api=api)
    bundle = json.loads((state / "bundle.json").read_text())
    validate_bundle(bundle["history"], bundle["snapshot"])
    row = next(r for r in bundle["snapshot"]["repositories"] if r["key"] == KEY)
    assert result["status"] == "collected"
    assert row["excluded_pr_associations"] == 1
    assert [r["number"] for r in row["pull_requests"]] == [7]
    assert [r["pr_number"] for r in queries] == [7]  # retained history, never orphan #42
    assert bundle["history"]["associations"] == history["associations"]
    assert bundle["snapshot"]["totals"] == snapshot["totals"]
    assert api.calls == []
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


def test_published_association_later_orphaned_keeps_history_and_refreshes_pr(tmp_path, monkeypatch):
    from test_progress_model import GITHUB, KEY, runtime, save_ledger

    from kg_microbe_progress import prs, validate_bundle

    root, ledger = runtime(tmp_path)
    ledger.update(adopted_goal={"conversation_id": "private", "started_at": ledger["created_at"],
                                "start_step_index": 2}, workflow={"sha256": "c" * 64})
    save_ledger(root, ledger)
    registry = root / KEY / prs.REGISTRY_NAME
    registry.write_text(json.dumps({**prs._context(ledger), "schema_version": 1,
        "pr_number": 42, "reported_at": ledger["last_observed_at"]}) + "\n")
    queries = []
    def github(args):
        queries.append(args)
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps({
            "number": 42, "base": {"repo": {"full_name": GITHUB}},
            "head": {"sha": "a" * 40}, "html_url": f"https://github.com/{GITHUB}/pull/42",
            "merged": False, "state": "open", "merged_at": None,
        }))
    monkeypatch.setattr(publisher, "fetch_pr_observations",
                        lambda associations: prs.fetch_pr_observations(associations, gh=github))
    state = tmp_path / "state"
    api = GitHub()
    publisher.collect_once([root], state, api=api, apply=True, initialize=True)
    published = publisher.read_remote(api)[1]
    assert published["snapshot"]["totals"]["unique_prs"] == 1
    assert published["history"]["cursors"][0]["excluded_pr_associations"] == 0
    ledger["adopted_goal"]["start_step_index"] = 99
    save_ledger(root, ledger)
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    collected = prs.collect_associations([root])
    assert collected.records == []
    assert collected.excluded_counts == {(ledger["run_id"], KEY): 1}
    publisher.collect_once([root], state, api=api)
    refreshed = json.loads((state / "bundle.json").read_text())
    validate_bundle(refreshed["history"], refreshed["snapshot"])
    assert refreshed["history"]["associations"] == published["history"]["associations"]
    assert refreshed["history"]["pr_events"] == published["history"]["pr_events"]
    assert refreshed["snapshot"]["totals"] == published["snapshot"]["totals"]
    assert refreshed["history"]["cursors"][0]["excluded_pr_associations"] == 1
    assert queries == [["gh", "api", f"repos/{GITHUB}/pulls/42"]] * 2
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


@pytest.mark.parametrize("stage", [1, 3, 6])
@pytest.mark.parametrize("apply", [False, True])
def test_unadopted_target_does_not_block_healthy_fleet_publication(tmp_path, monkeypatch, stage, apply):
    from test_progress_model import GITHUB, KEY, runtime, save_ledger, write

    from kg_microbe_fleet import load_fleet_manifest
    from kg_microbe_progress import prs, validate_bundle

    root, healthy = runtime(tmp_path)
    healthy.update(adopted_goal={"conversation_id": "private", "started_at": healthy["created_at"],
                                 "start_step_index": 2}, workflow={"sha256": "c" * 64})
    save_ledger(root, healthy)
    (root / KEY / prs.REGISTRY_NAME).write_text(json.dumps({**prs._context(healthy),
        "schema_version": 1, "pr_number": 42, "reported_at": healthy["last_observed_at"]}) + "\n")
    unadopted = {**healthy, "repository_key": "traitmech", "stage": stage,
        "adopted_goal": None, "awaiting_goal": False, "phase": "blocked",
        "blocked_reason": "no authoritative current goal; assessment required"}
    write(root / "traitmech" / "ledger.json", unadopted)
    config = json.loads((root / "config.json").read_text())
    config["targets"].append({"repository_key": "traitmech",
                              "github_repository": load_fleet_manifest().get("traitmech").github})
    write(root / "config.json", config)
    assert sorted(p.name for p in (root / "traitmech").iterdir()) == ["ledger.json"]
    before = {p: p.read_bytes() for p in root.rglob("*") if p.is_file()}
    queries = []
    def github(args):
        queries.append(args)
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps({
            "number": 42, "base": {"repo": {"full_name": GITHUB}},
            "head": {"sha": "a" * 40}, "html_url": f"https://github.com/{GITHUB}/pull/42",
            "merged": False, "state": "open", "merged_at": None,
        }))
    monkeypatch.setattr(publisher, "fetch_pr_observations",
                        lambda associations: prs.fetch_pr_observations(associations, gh=github))
    api = GitHub()
    state = tmp_path / "state"
    result = publisher.collect_once([root], state, api=api, apply=apply, initialize=apply)
    bundle = json.loads((state / "bundle.json").read_text())
    validate_bundle(bundle["history"], bundle["snapshot"])
    rows = {row["key"]: row for row in bundle["snapshot"]["repositories"]}
    assert [pr["number"] for pr in rows[KEY]["pull_requests"]] == [42]
    assert rows["traitmech"]["pull_requests"] == []
    assert rows["traitmech"]["excluded_pr_associations"] == 0
    assert bundle["snapshot"]["totals"]["unique_prs"] == 1
    assert bundle["snapshot"]["totals"]["completed_goals"] == 0
    assert queries == [["gh", "api", f"repos/{GITHUB}/pulls/42"]]
    assert result["status"] == ("published" if apply else "collected")
    if apply:
        assert publisher.read_remote(api)[1] == bundle
    else:
        assert api.calls == []
    assert {p: p.read_bytes() for p in root.rglob("*") if p.is_file()} == before


def test_fleet_expansion_projects_prefix_remote_bundle_and_publishes_full_fleet(tmp_path, monkeypatch):
    from kg_microbe_fleet import FleetManifest, load_fleet_manifest
    from kg_microbe_progress import ProgressError, project_bundle_to_manifest, validate_bundle

    fleet = load_fleet_manifest()
    prefix_keys = list(fleet.keys[:-1])
    added_key = fleet.keys[-1]
    prefix_manifest = FleetManifest(
        {key: fleet.mechs[key] for key in prefix_keys},
        fleet.capability_catalogue,
        fleet.vendored_governance,
        fleet.source,
    )
    prefix_history, prefix_snapshot = collect_progress(
        [], generated_at="2026-10-20T10:00:00Z", manifest=prefix_manifest,
    )
    prefix_bundle = {"history": prefix_history, "snapshot": prefix_snapshot}

    api = GitHub()
    monkeypatch.setattr(publisher, "validate_bundle", lambda h, s, m=None: validate_bundle(h, s, m or prefix_manifest))
    initial_head = publisher.publish(prefix_bundle, None, None, initialize=True, api=api)
    monkeypatch.setattr(publisher, "validate_bundle", validate_bundle)

    observed_head, projected_bundle = publisher.read_remote(api)
    assert observed_head == initial_head
    assert [row["key"] for row in projected_bundle["snapshot"]["repositories"]] == list(fleet.keys)
    added_row = projected_bundle["snapshot"]["repositories"][-1]
    assert added_row["key"] == added_key
    assert added_row["history_coverage"] == "unobserved"
    assert "current" not in added_row
    assert added_row["counters"]["completed_goals"] == 0

    _, unprojected_bundle = publisher.read_remote(api, project_expanded=False)
    assert [row["key"] for row in unprojected_bundle["snapshot"]["repositories"]] == prefix_keys

    source = tmp_path / "source"
    source.mkdir()
    (source / "index.html").write_text("<!doctype html><title>Progress</title>")
    monkeypatch.setattr(builder, "read_remote", lambda: (initial_head, prefix_bundle))
    built = tmp_path / "built"
    assert builder.build(source, built) == initial_head
    built_progress = json.loads((built / "data/progress.json").read_text())
    assert [row["key"] for row in built_progress["repositories"]] == list(fleet.keys)

    # Even if generated_at matches the pre-expansion snapshot, collect_once must publish the expanded snapshot.
    full_history, full_snapshot = collect_progress(
        [], generated_at="2026-10-20T10:00:00Z", manifest=fleet,
    )
    monkeypatch.setattr(publisher, "collect_associations", lambda _: AssociationCollection([], {}))
    monkeypatch.setattr(publisher, "fetch_pr_observations", lambda _: [])
    monkeypatch.setattr(publisher, "collect_progress", lambda *a, **kw: (full_history, full_snapshot))
    result = publisher.collect_once([], tmp_path / "state", apply=True, api=api)
    assert result["status"] == "published"
    assert result["data_commit"] != initial_head
    _, after_publish = publisher.read_remote(api, project_expanded=False)
    assert [row["key"] for row in after_publish["snapshot"]["repositories"]] == list(fleet.keys)

    # Reject a prefix snapshot if history already contains evidence for the omitted suffix Mech.
    bad_history = copy.deepcopy(prefix_history)
    bad_history["cursors"].append({
        "repository_key": added_key,
        "run_key": publisher.run_key("run"),
        "cycle": 1,
        "stage_number": 1,
        "stage_id": "add_new_records",
        "phase": "waiting",
        "blocker_code": None,
        "observed_at": "2026-10-20T09:59:00Z",
        "started_at": "2026-10-20T09:00:00Z",
    })
    with pytest.raises(ProgressError, match="complete manifest fleet"):
        project_bundle_to_manifest(bad_history, prefix_snapshot, fleet)

