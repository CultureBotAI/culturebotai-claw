"""Offline disposable Git fixtures for the clean-only retirement helper.
Each test owns a disposable fixture under the repository ignored .temp root.
Normal pytest/CI requires no manual --basetemp. No real worktree is selected.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HELPER = ROOT / "scripts/adhoc/cycle-maintenance-20261115/cleanup-inventory/retire_owned_worktree.py"
# Only the offline paired-control runner sets this to its private source copy.
HELPER = Path(os.environ.get("CLAW_RETIREMENT_TEST_HELPER", str(DEFAULT_HELPER)))
SPEC = importlib.util.spec_from_file_location("retire_owned_worktree", HELPER)
assert SPEC and SPEC.loader
mod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mod)


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.PIPE).decode().strip()


@pytest.fixture
def durable_fixture():
    temporary = ROOT / ".temp"
    assert not temporary.is_symlink()
    subprocess.run(["git", "-C", str(ROOT), "check-ignore", "--quiet", ".temp/retirement-test-fixture"], check=True)
    temporary.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="retirement-test-", dir=temporary) as directory:
        yield Path(directory)


@pytest.fixture
def prepared(durable_fixture):
    tmp_path = durable_fixture
    anchor = tmp_path / "anchor"
    anchor.mkdir()
    git(anchor, "init", "-q", "-b", "main")
    git(anchor, "config", "user.name", "Offline fixture")
    git(anchor, "config", "user.email", "offline-fixture.invalid")
    git(anchor, "remote", "add", "origin", "https://github.com/CultureBotAI/culturebotai-claw.git")
    (anchor / "tracked.txt").write_text("original\n")
    (anchor / "nested").mkdir()
    (anchor / "nested/kept.txt").write_text("tracked nested file\n")
    git(anchor, "add", ".")
    git(anchor, "commit", "-qm", "fixture base")
    task = tmp_path / "task"
    task.mkdir()
    worktree = task / "owned"
    git(anchor, "worktree", "add", "-q", "-b", "owned-fixture", str(worktree))
    (worktree / "tracked.txt").write_text("reviewed\n")
    git(worktree, "add", "tracked.txt")
    git(worktree, "commit", "-qm", "reviewed fixture")
    head = git(worktree, "rev-parse", "HEAD")
    git(anchor, "merge", "--no-ff", "--no-edit", "owned-fixture")
    merge = git(anchor, "rev-parse", "HEAD")
    common = anchor / ".git"
    locks = tmp_path / "locks"
    locks.mkdir()
    quarantine_parent = task / "quarantine"
    quarantine_parent.mkdir()
    action_plan = task / "plan.json"
    action_plan.write_text(json.dumps({"items": [{"root": str(worktree), "common_git_directory": str(common), "head": head, "decision": "CONDITIONAL"}]}))
    proof_path = task / "proof.json"
    observed = datetime.now(timezone.utc).isoformat()
    proof = {"schema_version": 1, "repository": mod.REPOSITORY, "task_scope": str(task),
        "worktree": str(worktree), "common_git": str(common), "quarantine": str(quarantine_parent / "run"),
        "expected_head": head, "expected_branch": "refs/heads/owned-fixture", "disposition": "retire_clean",
        "owner_complete": True, "readers_clear": True, "owner_evidence": "offline fixture owner completed",
        "observed_at": observed, "plan_sha256": mod.digest(action_plan.read_bytes()),
        "merged_pr": {"number": 1, "state": "MERGED", "base_ref": "main", "repository": mod.REPOSITORY,
            "head": head, "merge_commit": merge, "published_main": merge, "merge_method": "merge",
            "url": f"https://github.com/{mod.REPOSITORY}/pull/1", "observed_at": observed}}
    proof_path.write_text(json.dumps(proof))
    args = argparse.Namespace(task_scope=task, worktree=worktree, common_git=common,
        quarantine=quarantine_parent / "run", proof=proof_path, action_plan=action_plan,
        expected_head=head, locks_dir=locks, owner="offline-fixture", apply=False)
    return args, anchor


def quiet(_):
    pass


def test_dry_run_preserves_all_state_and_reports_nested_extras(prepared):
    args, anchor = prepared
    (args.worktree / "nested/cache").mkdir()
    (args.worktree / "nested/cache/value").write_bytes(b"retained\x00bytes")
    (args.worktree / "untracked-link").symlink_to("missing-target")
    before = git(anchor, "show-ref")
    result = mod.retire(args, probe=quiet)
    assert result["mode"] == "dry_run" and result["actions_performed"] == 0
    assert result["preservation_roots"] == ["untracked-link", "nested/cache"]
    assert not args.quarantine.exists() and args.worktree.exists()
    assert git(anchor, "show-ref") == before


def test_fixture_apply_preserves_bytes_symlink_and_recovery_before_removal(prepared):
    args, anchor = prepared
    (args.worktree / "nested/cache").mkdir()
    (args.worktree / "nested/cache/value").write_bytes(b"valuable\x00bytes")
    (args.worktree / "untracked-link").symlink_to("outside-target")
    (args.worktree / "empty").mkdir()
    main = git(anchor, "rev-parse", "main")
    args.apply = True
    result = mod.retire(args, probe=quiet)
    assert not args.worktree.exists()
    assert (args.quarantine / "preserved/nested/cache/value").read_bytes() == b"valuable\x00bytes"
    assert (args.quarantine / "preserved/untracked-link").is_symlink()
    assert (args.quarantine / "preserved/empty").is_dir()
    assert git(anchor, "rev-parse", result["recovery_ref"]) == args.expected_head
    assert git(anchor, "rev-parse", "main") == main
    assert "refs/heads/owned-fixture" not in git(anchor, "show-ref")
    assert (args.quarantine / "completed.json").is_file()


@pytest.mark.parametrize("damage", ["tracked", "staged", "head", "operation", "owner", "wrong-branch", "stale", "quarantine", "nested-git", "sparse-flag", "wrong-origin"])
def test_refusals_do_not_change_live_fixture_state(prepared, damage):
    args, anchor = prepared
    if damage == "tracked":
        (args.worktree / "tracked.txt").write_text("uncommitted")
    elif damage == "staged":
        (args.worktree / "tracked.txt").write_text("staged")
        git(args.worktree, "add", "tracked.txt")
        (args.worktree / "tracked.txt").write_text("reviewed\n")
    elif damage == "head":
        args.expected_head = "0" * 40
    elif damage == "operation":
        gitdir = Path(git(args.worktree, "rev-parse", "--absolute-git-dir"))
        (gitdir / "MERGE_HEAD").write_text(args.expected_head)
    elif damage in {"owner", "stale", "wrong-branch"}:
        proof = json.loads(args.proof.read_text())
        if damage == "owner":
            proof["owner_complete"] = False
        elif damage == "wrong-branch":
            proof["expected_branch"] = "refs/heads/someone-else"
        else:
            proof["observed_at"] = "2000-01-01T00:00:00+00:00"
        args.proof.write_text(json.dumps(proof))
    elif damage == "quarantine":
        args.quarantine.mkdir()
    elif damage == "nested-git":
        (args.worktree / "nested/.git").mkdir()
    elif damage == "sparse-flag":
        git(args.worktree, "update-index", "--skip-worktree", "tracked.txt")
    else:
        git(anchor, "remote", "set-url", "origin", "https://github.com/Other/Repo")
    before = git(anchor, "show-ref")
    args.apply = True
    with pytest.raises(mod.Refusal):
        mod.retire(args, probe=quiet)
    assert args.worktree.exists() and git(anchor, "show-ref") == before
    assert not (args.quarantine / "before.json").exists()


def test_active_reader_is_a_refusal(prepared):
    args, _ = prepared
    def active(_):
        raise mod.Refusal("active reader")
    with pytest.raises(mod.Refusal, match="active reader"):
        mod.retire(args, probe=active)
    assert not args.quarantine.exists()


def test_new_file_after_inventory_is_not_removed(prepared):
    args, _ = prepared
    before = mod.inspect(args, probe=quiet)
    (args.worktree / "late-value").write_text("new work")
    with pytest.raises(mod.Refusal, match="filesystem entry"):
        mod.fast_recheck(args, before, moved=False)
    assert (args.worktree / "late-value").read_text() == "new work"


@pytest.mark.parametrize("changed", ["proof", "plan"])
def test_proof_revocation_during_inventory_refuses_before_any_change(prepared, changed):
    """#1269: parsed permission must remain bound to exactly its captured bytes."""
    args, anchor = prepared
    args.apply = True
    original_refs = git(anchor, "show-ref")
    def revoke(_):
        if changed == "proof":
            proof = json.loads(args.proof.read_text())
            proof["owner_complete"] = False
            args.proof.write_text(json.dumps(proof))
        else:
            plan = json.loads(args.action_plan.read_text())
            plan["items"] = []
            args.action_plan.write_text(json.dumps(plan))
    with pytest.raises(mod.Refusal, match="changed during inventory"):
        mod.retire(args, probe=revoke)
    assert args.worktree.exists() and git(anchor, "show-ref") == original_refs
    assert not args.quarantine.exists()


def test_second_reader_failure_preserves_moved_bytes_and_recovery(prepared):
    args, anchor = prepared
    args.apply = True
    (args.worktree / "valuable.bin").write_bytes(b"keep-me")
    calls = []
    def late_reader(_):
        calls.append(True)
        if len(calls) == 2:
            raise mod.Refusal("late reader")
    with pytest.raises(mod.Refusal, match="late reader"):
        mod.retire(args, probe=late_reader)
    assert args.worktree.exists()
    assert (args.quarantine / "preserved/valuable.bin").read_bytes() == b"keep-me"
    recovery = json.loads((args.quarantine / "recovery.json").read_text())
    assert git(anchor, "rev-parse", recovery["ref"]) == args.expected_head
    assert git(anchor, "rev-parse", "owned-fixture") == args.expected_head
    assert (args.quarantine / "failure.json").is_file()
