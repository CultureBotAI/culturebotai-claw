"""Offline tests: no native input, repository access or real metadata mutation."""

import importlib.util
import json
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def case(tmp_path, monkeypatch):
    path = Path(__file__).parents[1] / "scripts/adhoc/edgemech_supervisor_metadata_20261128.py"
    spec = importlib.util.spec_from_file_location("metadata_writer", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    claw = tmp_path / "claw"
    campaign = tmp_path / "campaign"
    (claw / "workspace/tasks").mkdir(parents=True)
    campaign.mkdir()
    events = []

    @contextmanager
    def lock(*args, **kwargs):
        events.append("held")
        try:
            yield
        finally:
            events.append("released")

    monkeypatch.setattr(module, "RepositoryTarget", lambda *a: SimpleNamespace(open=lambda: None))
    monkeypatch.setattr(module, "LockManager", lambda *a: SimpleNamespace(lock=lock))
    monkeypatch.setattr(module, "merged_repository_environment",
                        lambda *a: {"OPENCLAW_WORKSPACE": str(claw / "workspace")})
    targets = {"ACK.md": campaign / "ACK.md", "progress.json": campaign / "progress.json",
               "edgemech_restart_20261120.yaml": claw / "workspace/tasks/edgemech_restart_20261120.yaml"}
    files = {}
    for name, target in targets.items():
        target.write_text("before\n")
        new = tmp_path / (name + ".candidate")
        new.write_text("Current acknowledgement\n" if name == "ACK.md" else json.dumps(
            {"task_id": "edgemech_restart_20261120", "scientific_review_coverage": 0}))
        files[name] = {"target": str(target), "before_sha256": module.digest(target.read_bytes()),
                       "candidate": str(new), "candidate_sha256": module.digest(new.read_bytes())}
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"version": 1, "run_id": "20261128T084706Z", "files": files}))
    return SimpleNamespace(m=module, claw=claw, campaign=campaign, plan=plan,
                           targets=targets, events=events, files=files)


def run(case, apply=True):
    return case.m.apply_plan(case.claw, case.campaign, case.plan,
                             case.m.digest(case.plan.read_bytes()), apply=apply)


def test_dry_run_and_exact_apply(case):
    assert run(case, False)["mode"] == "dry_run"
    assert not case.events
    assert not (case.campaign / "supervisor-checkpoints").exists()
    result = run(case)
    snapshot = Path(result["checkpoint"])
    assert case.events == ["held", "released"]
    for name, target in case.targets.items():
        assert (snapshot / "before" / name).read_bytes() == b"before\n"
        assert target.read_bytes() == Path(case.files[name]["candidate"]).read_bytes()
    assert json.loads((snapshot / "APPLIED.json").read_text())["mode"] == "applied"


def test_stale_beforeimage_refuses_every_write(case):
    case.targets["progress.json"].write_text("concurrent edit\n")
    with pytest.raises(ValueError, match="beforeimage changed"):
        run(case)
    assert case.targets["ACK.md"].read_bytes() == b"before\n"
    assert not (case.campaign / "supervisor-checkpoints").exists()


@pytest.mark.parametrize("which", ["candidate", "plan"])
def test_bound_bytes_required(case, which):
    expected = case.m.digest(case.plan.read_bytes())
    if which == "candidate":
        Path(case.files["ACK.md"]["candidate"]).write_text("changed")
    else:
        case.plan.write_text(case.plan.read_text() + " ")
    with pytest.raises(ValueError, match="changed|differs"):
        case.m.apply_plan(case.claw, case.campaign, case.plan, expected, apply=True)
    assert not case.events


def test_destination_allowlist(case):
    plan = json.loads(case.plan.read_text())
    plan["files"]["ACK.md"]["target"] = str(case.campaign / "COORDINATOR-PROGRESS.json")
    case.plan.write_text(json.dumps(plan))
    with pytest.raises(ValueError, match="allowlist"):
        run(case)


@pytest.mark.parametrize("which", ["target", "candidate"])
def test_symlinks_refused(case, which):
    path = case.targets["ACK.md"] if which == "target" else Path(case.files["ACK.md"]["candidate"])
    retained = path.with_suffix(".retained")
    path.rename(retained)
    path.symlink_to(retained)
    with pytest.raises(ValueError, match="symlinks"):
        run(case)
    assert not case.events


def test_existing_snapshot_refused_without_clobber(case):
    snapshot = case.campaign / "supervisor-checkpoints/20261128T084706Z"
    snapshot.mkdir(parents=True)
    (snapshot / "retained").write_text("keep")
    with pytest.raises(FileExistsError):
        run(case)
    assert (snapshot / "retained").read_text() == "keep"
    assert case.targets["ACK.md"].read_bytes() == b"before\n"


def test_exclusive_write_preserves_existing_receipt(case):
    path = case.campaign / "existing-receipt.json"
    path.write_bytes(b"original retained receipt\n")
    with pytest.raises(FileExistsError):
        case.m.exclusive(path, b"replacement\n")
    assert path.read_bytes() == b"original retained receipt\n"


def test_partial_failure_retains_beforeimages_and_releases(case, monkeypatch):
    original = case.m.os.replace
    calls = []

    def fail_second(source, target):
        calls.append(target)
        if len(calls) == 2:
            raise OSError("simulated replacement failure")
        original(source, target)

    monkeypatch.setattr(case.m.os, "replace", fail_second)
    with pytest.raises(OSError, match="simulated"):
        run(case)
    snapshot = case.campaign / "supervisor-checkpoints/20261128T084706Z"
    result = json.loads((snapshot / "FAILED.json").read_text())
    assert result["replaced"] == ["ACK.md"]
    assert case.events == ["held", "released"]
    assert all((snapshot / "before" / name).read_bytes() == b"before\n" for name in case.targets)
    assert case.targets["progress.json"].read_bytes() == b"before\n"
