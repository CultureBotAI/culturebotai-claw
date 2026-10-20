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
    monkeypatch.setattr(publisher, "gather_associations", lambda _: [])
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
