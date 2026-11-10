"""Goal-boundary freshness against isolated real Git repositories, offline only."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from kg_microbe_workflows import freshness as fresh
from plugins.lock_manager import LockManager
from plugins.repository_settings import RepositoryTarget

POLICY = "b" * 64
BOUNDARY = "fixture-cycle-2-stage-1"
REPOSITORY = "Fixture/FreshnessMech"


def git(path: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(path), *args], capture_output=True,
                            text=True, check=True)
    return result.stdout.strip()


def commit(path: Path, name: str, text: str, *, force: bool = False) -> str:
    destination = path / name
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text)
    git(path, "add", *( ["--force"] if force else []), "--", name)
    git(path, "commit", "-m", "Fixture update " + name)
    return git(path, "rev-parse", "HEAD")


@dataclass
class LocalRepository:
    root: Path
    origin: Path
    writer: Path
    checkout: Path
    initial: str
    target: RepositoryTarget
    locks: LockManager
    receipts: Path

    def publish(self, name: str = "backlog.txt", contents: str = "new inventory\n",
                *, force: bool = False) -> str:
        head = commit(self.writer, name, contents, force=force)
        git(self.writer, "push", "origin", "main")
        return head

    def run(self, **overrides: Any) -> dict[str, Any]:
        options = dict(phase="pre_goal", boundary_id=BOUNDARY, policy_sha256=POLICY,
                       locks=self.locks, receipt_dir=self.receipts,
                       protected_roots=[], apply=True)
        options.update(overrides)
        return fresh.ensure_freshness(self.target, **options)

    def head(self) -> str:
        return git(self.checkout, "rev-parse", "HEAD")

    def assert_receipt(self, report: dict[str, Any]) -> dict[str, Any]:
        receipt = report["receipt"]
        raw = Path(receipt["path"]).read_bytes()
        assert hashlib.sha256(raw).hexdigest() == receipt["sha256"]
        payload = json.loads(raw)
        assert payload == {k: v for k, v in report.items() if k != "receipt"}
        assert git(self.checkout, "for-each-ref", "--format=%(refname)",
                   "refs/goal-freshness/") == ""
        return payload


@pytest.fixture(autouse=True)
def isolated_git(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in tuple(os.environ):
        if name.startswith("GIT_"):
            monkeypatch.delenv(name, raising=False)
    for name, value in {
        "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_ALLOW_PROTOCOL": "file", "GIT_TERMINAL_PROMPT": "0",
        "GIT_AUTHOR_NAME": "Freshness fixture", "GIT_AUTHOR_EMAIL": "fixture@example.invalid",
        "GIT_COMMITTER_NAME": "Freshness fixture", "GIT_COMMITTER_EMAIL": "fixture@example.invalid",
    }.items():
        monkeypatch.setenv(name, value)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> LocalRepository:
    origin, writer, checkout = (tmp_path / name for name in ("origin.git", "writer", "checkout"))
    git(tmp_path, "init", "--bare", "--initial-branch=main", str(origin))
    git(tmp_path, "clone", str(origin), str(writer))
    commit(writer, ".gitignore", ".scratch/\nblocked.txt\n")
    initial = commit(writer, "tracked.txt", "initial\n")
    git(writer, "push", "--set-upstream", "origin", "main")
    git(tmp_path, "clone", str(origin), str(checkout))
    actual_identity = fresh._repository_identity
    monkeypatch.setattr(fresh, "_repository_identity",
                        lambda value: REPOSITORY if value == str(origin) else actual_identity(value))
    monkeypatch.setattr(fresh, "owner_snapshot",
                        lambda roots, allowed: {"checked_at": fresh.utc(), "allowed": dict(allowed),
                                                "cwd_holders": {}})
    return LocalRepository(tmp_path, origin, writer, checkout, initial,
                           RepositoryTarget("fixturemech", checkout, REPOSITORY),
                           LockManager({"locks_dir": tmp_path / "shared-locks", "my_id": "freshness-tests"}),
                           tmp_path / "receipts")


def test_current_revision_is_verified_and_receipted(repo: LocalRepository) -> None:
    result = repo.run()
    assert result["status"] == "verified"
    assert result["outcome"] == "already_current"
    assert result["before"] == result["fetched"] == result["after"] == repo.initial
    assert result["default_branch"] == "main"
    assert result["repository"] == REPOSITORY
    assert result["remote"] == "origin"
    assert result["verified_at"].endswith("Z")
    repo.assert_receipt(result)


def test_behind_fetches_then_fast_forwards_and_inventory_reads_new_bytes(repo: LocalRepository) -> None:
    wanted = repo.publish()
    result = repo.run()
    assert result["status"] == "verified"
    assert result["outcome"] == "fast_forwarded"
    assert result["before"] == repo.initial
    assert result["after"] == result["fetched"] == wanted == repo.head()
    assert fresh.verify_inventory_head(repo.target, result, boundary_id=BOUNDARY,
                                       policy_sha256=POLICY) == wanted
    assert (repo.checkout / "backlog.txt").read_text() == "new inventory\n"
    repo.assert_receipt(result)


def test_preview_never_fetches_mutates_or_writes_receipt(repo: LocalRepository,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    repo.publish()
    original = fresh.Git.run
    def guarded(self, *args, **kwargs):
        assert args[0] not in {"fetch", "merge", "ls-remote"}
        return original(self, *args, **kwargs)
    monkeypatch.setattr(fresh.Git, "run", guarded)
    result = repo.run(apply=False)
    assert result["status"] == "preview"
    assert repo.head() == repo.initial
    assert not repo.receipts.exists()


@pytest.mark.parametrize("kind,reason", [
    ("ahead", "local_ahead_checkout"), ("diverged", "diverged_checkout"),
    ("dirty", "dirty_or_staged_checkout"), ("staged", "dirty_or_staged_checkout"),
    ("detached", "detached_checkout"), ("feature", "feature_checkout"),
])
def test_ineligible_state_preserves_user_work(repo: LocalRepository, kind: str, reason: str) -> None:
    if kind in {"ahead", "diverged"}:
        commit(repo.checkout, "local.txt", "unpublished user work\n")
    elif kind in {"dirty", "staged"}:
        (repo.checkout / "tracked.txt").write_text("uncommitted user work\n")
        if kind == "staged":
            git(repo.checkout, "add", "tracked.txt")
    elif kind == "detached":
        git(repo.checkout, "checkout", "--detach", "HEAD")
    else:
        git(repo.checkout, "switch", "-c", "owned-feature")
    if kind != "ahead":
        repo.publish()
    before = repo.head()
    status = git(repo.checkout, "status", "--porcelain=v1", "--untracked-files=all")
    result = repo.run()
    assert result["status"] == "hold"
    assert result["reason"].startswith(reason)
    assert repo.head() == before
    assert git(repo.checkout, "status", "--porcelain=v1", "--untracked-files=all") == status
    repo.assert_receipt(result)


@pytest.mark.parametrize("ignored", [False, True])
def test_incoming_untracked_or_ignored_collision_holds(repo: LocalRepository, ignored: bool) -> None:
    name = "blocked.txt" if ignored else "incoming.txt"
    destination = repo.checkout / name
    destination.write_text("unique local evidence\n")
    repo.publish(name, "published replacement\n", force=ignored)
    result = repo.run()
    assert result["status"] == "hold"
    if ignored:
        assert result["reason"] == "untracked_or_ignored_overwrite_collision"
        assert name in result["overwrite_collisions"]
    else:
        assert result["reason"].startswith("dirty_or_staged_checkout")
    assert destination.read_text() == "unique local evidence\n"
    assert repo.head() == repo.initial


def test_noncolliding_ignored_evidence_survives(repo: LocalRepository) -> None:
    evidence = repo.checkout / ".scratch" / "evidence.json"
    evidence.parent.mkdir()
    evidence.write_text('{"unique": true}\n')
    wanted = repo.publish()
    result = repo.run()
    assert result["status"] == "verified"
    assert repo.head() == wanted
    assert evidence.read_text() == '{"unique": true}\n'


def test_incoming_directory_parent_collision_is_preserved(repo: LocalRepository) -> None:
    (repo.checkout / "new-directory").write_text("local file at incoming parent\n")
    repo.publish("new-directory/record.txt", "remote\n")
    result = repo.run()
    assert result["reason"].startswith("dirty_or_staged_checkout")
    assert (repo.checkout / "new-directory").is_file()


@pytest.mark.parametrize("marker", ["MERGE_HEAD", "rebase-merge", "index.lock"])
def test_active_git_operation_holds_without_fetch(repo: LocalRepository, marker: str,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    path = Path(git(repo.checkout, "rev-parse", "--path-format=absolute", "--git-path", marker))
    path.mkdir() if marker == "rebase-merge" else path.write_text(repo.initial + "\n")
    original = fresh.Git.run
    def guarded(self, *args, **kwargs):
        assert args[0] != "fetch"
        return original(self, *args, **kwargs)
    monkeypatch.setattr(fresh.Git, "run", guarded)
    result = repo.run()
    assert result["reason"] == "active_git_operation:" + marker
    assert path.exists()


def test_other_live_owner_blocks_and_is_not_signaled(repo: LocalRepository,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    def owner(roots, allowed):
        assert roots == [repo.checkout]
        raise fresh.FreshnessError("other_live_owner:12345")
    monkeypatch.setattr(fresh, "owner_snapshot", owner)
    result = repo.run()
    assert result["reason"] == "other_live_owner:12345"
    assert result["fetched"] is None


def test_shared_worktree_owner_is_checked(repo: LocalRepository,
                                         monkeypatch: pytest.MonkeyPatch) -> None:
    peer = repo.root / "peer"
    git(repo.checkout, "worktree", "add", "-b", "peer-work", str(peer))
    def owner(roots, allowed):
        assert set(roots) == {repo.checkout, peer}
        raise fresh.FreshnessError("other_live_owner:23456")
    monkeypatch.setattr(fresh, "owner_snapshot", owner)
    result = repo.run()
    assert result["reason"] == "other_live_owner:23456"
    assert git(peer, "branch", "--show-current") == "peer-work"


def test_owner_appearing_after_fetch_blocks_fast_forward(repo: LocalRepository,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    repo.publish()
    calls = []
    def owner(roots, allowed):
        calls.append(tuple(roots))
        if len(calls) > 1:
            raise fresh.FreshnessError("other_live_owner:34567")
        return {"allowed": {}, "cwd_holders": {}}
    monkeypatch.setattr(fresh, "owner_snapshot", owner)
    result = repo.run()
    assert result["reason"] == "other_live_owner:34567"
    assert repo.head() == repo.initial


def test_shared_lock_excludes_another_cooperating_controller(repo: LocalRepository) -> None:
    other = LockManager({"locks_dir": repo.locks.locks_dir, "my_id": "other-controller"})
    with other.lock(repo.target.name, "active-goal-owner"):
        result = repo.run()
        assert result["status"] == "hold"
        assert result["fetched"] is None
        assert list(repo.locks.locks_dir.glob("*.lock"))
    assert repo.head() == repo.initial


@pytest.mark.parametrize("push_only", [False, True])
def test_wrong_remote_fails_before_network(repo: LocalRepository, push_only: bool,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    git(repo.checkout, "remote", "set-url", *(["--push"] if push_only else []),
        "origin", "https://github.com/Other/Repository.git")
    original = fresh.Git.run
    def guarded(self, *args, **kwargs):
        assert args[0] not in {"fetch", "ls-remote"}
        return original(self, *args, **kwargs)
    monkeypatch.setattr(fresh.Git, "run", guarded)
    result = repo.run()
    assert result["reason"] == "wrong_canonical_remote"
    assert repo.head() == repo.initial


def test_fetch_failure_holds_without_losing_local_state(repo: LocalRepository,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    repo.publish()
    original = fresh.Git.run
    def fail(self, *args, **kwargs):
        if args[0] == "fetch":
            raise fresh.FreshnessError("git_fetch_failed")
        return original(self, *args, **kwargs)
    monkeypatch.setattr(fresh.Git, "run", fail)
    result = repo.run()
    assert result["reason"] == "git_fetch_failed"
    assert repo.head() == repo.initial
    repo.assert_receipt(result)


def test_checkout_edit_during_fetch_holds(repo: LocalRepository,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    repo.publish()
    original = fresh.Git.run
    def changed(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        if args[0] == "fetch":
            (repo.checkout / "tracked.txt").write_text("concurrent session work\n")
        return result
    monkeypatch.setattr(fresh.Git, "run", changed)
    result = repo.run()
    assert result["reason"] == "checkout_changed_during_fetch"
    assert repo.head() == repo.initial
    assert (repo.checkout / "tracked.txt").read_text() == "concurrent session work\n"


def test_remote_race_before_fetch_retries_to_new_observed_tip(repo: LocalRepository,
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    first = repo.publish("first.txt", "first\n")
    original = fresh.Git.run
    changed = []
    def raced(self, *args, **kwargs):
        if args[0] == "fetch" and not changed:
            changed.append(repo.publish("later.txt", "later\n"))
        return original(self, *args, **kwargs)
    monkeypatch.setattr(fresh.Git, "run", raced)
    result = repo.run()
    assert result["status"] == "verified"
    assert result["fetched"] == repo.head() == changed[0]
    assert result["observations"][0]["advertised"] == first
    assert [r["outcome"] for r in result["observations"]] == ["remote_ref_race", "verified"]


def test_remote_race_after_fast_forward_retries_and_reads_latest_inventory(repo: LocalRepository,
                                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    first = repo.publish("first.txt", "first\n")
    original = fresh.Git.run
    changed = []
    def raced(self, *args, **kwargs):
        value = original(self, *args, **kwargs)
        if args[0] == "merge" and not changed:
            changed.append(repo.publish("later.txt", "new frozen inventory\n"))
        return value
    monkeypatch.setattr(fresh.Git, "run", raced)
    result = repo.run()
    assert result["status"] == "verified"
    assert result["before"] == repo.initial
    assert result["fetched"] == result["after"] == changed[0] != first
    assert [r["outcome"] for r in result["observations"]] == ["remote_ref_race_after_fast_forward", "verified"]
    assert (repo.checkout / "later.txt").read_text() == "new frozen inventory\n"
    repo.assert_receipt(result)


def test_remote_races_exhaust_bound_and_never_authorize_inventory(repo: LocalRepository,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    repo.publish()
    original = fresh.Git.run
    count = []
    def raced(self, *args, **kwargs):
        if args[0] == "fetch":
            count.append(repo.publish(f"raced-{len(count)}.txt", "raced\n"))
        return original(self, *args, **kwargs)
    monkeypatch.setattr(fresh.Git, "run", raced)
    result = repo.run(attempts=2)
    assert result["status"] == "hold"
    assert result["reason"] == "remote_ref_race:retry_bound_exhausted"
    assert len(count) == len(result["observations"]) == 2
    assert repo.head() == repo.initial
    with pytest.raises(fresh.FreshnessError, match="context_mismatch"):
        fresh.verify_inventory_head(repo.target, result, boundary_id=BOUNDARY, policy_sha256=POLICY)


def test_own_merge_is_insufficient_when_external_backlog_advanced(repo: LocalRepository) -> None:
    own_merge = repo.publish("own-merged-result.txt", "own result\n")
    git(repo.checkout, "fetch", "origin")
    git(repo.checkout, "merge", "--ff-only", own_merge)
    external = repo.publish("external-backlog.txt", "another user's next task\n")
    result = repo.run(phase="post_merge", merge_commits=[own_merge])
    assert result["status"] == "verified"
    assert result["before"] == own_merge
    assert result["after"] == result["fetched"] == external
    assert (repo.checkout / "external-backlog.txt").read_text() == "another user's next task\n"
    repo.assert_receipt(result)


def test_post_merge_rejects_unmerged_commit(repo: LocalRepository) -> None:
    unmerged = commit(repo.writer, "unmerged.txt", "not published\n")
    git(repo.checkout, "fetch", str(repo.writer), unmerged)
    result = repo.run(phase="post_merge", merge_commits=[unmerged])
    assert result["status"] == "hold"
    assert result["reason"] == "git_merge-base_failed"
    assert repo.head() == repo.initial


def test_no_change_goal_still_fetches_before_inventory_without_rewriting_active_evidence(repo: LocalRepository) -> None:
    evidence = repo.root / "active-goal-evidence.json"
    original = b'{"adopted_goal": 17, "baseline": "frozen", "budget": 3}\n'
    evidence.write_bytes(original)
    wanted = repo.publish("no-change-inventory.txt", "newly available scope\n")
    result = repo.run(boundary_id="no-change-goal-inventory")
    assert result["status"] == "verified"
    assert fresh.verify_inventory_head(repo.target, result, boundary_id="no-change-goal-inventory",
                                       policy_sha256=POLICY) == wanted
    assert evidence.read_bytes() == original


@pytest.mark.parametrize("change", ["head", "dirty", "branch"])
def test_inventory_handoff_rejects_checkout_changes(repo: LocalRepository, change: str) -> None:
    receipt = repo.run()
    if change == "head":
        commit(repo.checkout, "late.txt", "late local work\n")
    elif change == "dirty":
        (repo.checkout / "tracked.txt").write_text("changed after verification\n")
    else:
        git(repo.checkout, "switch", "-c", "late-feature")
    with pytest.raises(fresh.FreshnessError, match="inventory_head_changed"):
        fresh.verify_inventory_head(repo.target, receipt, boundary_id=BOUNDARY, policy_sha256=POLICY)


@pytest.mark.parametrize("field,value", [
    ("boundary_id", "different-boundary"), ("policy_sha256", "a" * 64),
    ("phase", "post_merge"), ("repository", "Other/Repository"),
    ("repository_key", "other"), ("checkout", "/different/path"),
    ("status", "preview"),
])
def test_inventory_receipt_context_cannot_be_reused(repo: LocalRepository, field: str, value: str) -> None:
    receipt = repo.run()
    receipt[field] = value
    with pytest.raises(fresh.FreshnessError, match="context_mismatch"):
        fresh.verify_inventory_head(repo.target, receipt, boundary_id=BOUNDARY, policy_sha256=POLICY)


def test_inventory_receipt_cannot_be_rewritten_to_bless_a_later_head(repo: LocalRepository) -> None:
    receipt = repo.run()
    changed = repo.publish("later-published.txt", "not covered by original observation\n")
    git(repo.checkout, "fetch", "origin")
    git(repo.checkout, "merge", "--ff-only", changed)
    tampered = copy.deepcopy(receipt)
    tampered["fetched"] = tampered["after"] = changed
    with pytest.raises(fresh.FreshnessError):
        fresh.verify_inventory_head(repo.target, tampered, boundary_id=BOUNDARY, policy_sha256=POLICY)


def test_live_claw_checkout_and_shared_git_hold_without_fetch(repo: LocalRepository) -> None:
    repo.target = RepositoryTarget("claw", repo.checkout, REPOSITORY)
    result = repo.run(protected_roots=[repo.checkout])
    assert result["reason"] == "deploy_required:live_control_checkout_or_shared_git"
    assert result["fetched"] is None
    peer = repo.root / "control-peer"
    git(repo.checkout, "worktree", "add", "-b", "control", str(peer))
    result = repo.run(protected_roots=[peer])
    assert result["reason"] == "deploy_required:live_control_checkout_or_shared_git"
    assert repo.head() == repo.initial


def test_claw_requires_registered_live_control_protection(repo: LocalRepository) -> None:
    repo.target = RepositoryTarget("claw", repo.checkout, REPOSITORY)
    result = repo.run()
    assert result["reason"] == "deploy_required:claw_protected_roots_unregistered"


def test_claw_isolated_base_can_be_fresh_without_touching_control_checkout(repo: LocalRepository) -> None:
    repo.target = RepositoryTarget("claw", repo.checkout, REPOSITORY)
    control = repo.root / "unrelated-control"
    git(repo.root, "clone", str(repo.origin), str(control))
    wanted = repo.publish()
    result = repo.run(protected_roots=[control])
    assert result["status"] == "verified"
    assert repo.head() == wanted
    assert git(control, "rev-parse", "HEAD") == repo.initial


@pytest.mark.parametrize("phase,merges,reason", [
    ("post_merge", [], "post_merge_requires_verified_merge_commits"),
    ("pre_goal", ["a" * 40], "pre_goal_cannot_claim_merge"),
    ("post_merge", ["not-a-commit"], "invalid_merge_commit"),
])
def test_boundary_contract_rejects_invalid_merge_claims(repo: LocalRepository, phase: str,
                                                       merges: list[str], reason: str) -> None:
    with pytest.raises(fresh.FreshnessError, match=reason):
        repo.run(phase=phase, merge_commits=merges)
    assert not repo.receipts.exists()


def owner_fixture(monkeypatch: pytest.MonkeyPatch, root: Path, *, output: str,
                  process_rows: list[dict[int, dict[str, Any]]] | None = None,
                  stderr: str = "") -> list[int]:
    """Model platform observations without probing or controlling a real process."""
    stable = {900: {"ppid": 901, "identity": "900 caller"},
              901: {"ppid": 1, "identity": "901 parent"},
              100: {"ppid": 1, "identity": "100 owner-start-one"}}
    observations = process_rows or [stable]
    calls: list[int] = []
    def processes():
        index = min(len(calls), len(observations) - 1)
        calls.append(index)
        return copy.deepcopy(observations[index])
    class FakeProcess:
        pid = 999
        returncode = 0
        def __init__(self, command, **kwargs):
            assert command[:2] == ["lsof", "-nP"]
            assert "cwd" in command
        def communicate(self, timeout):
            assert timeout > 0
            return output, stderr
    monkeypatch.setattr(fresh.sys, "platform", "darwin")
    monkeypatch.setattr(fresh.os, "getpid", lambda: 900)
    monkeypatch.setattr(fresh, "_processes", processes)
    monkeypatch.setattr(fresh.subprocess, "Popen", FakeProcess)
    return calls


def test_platform_owner_snapshot_rejects_an_unapproved_cwd_owner(tmp_path: Path,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    owner_fixture(monkeypatch, tmp_path, output=f"p100\nn{tmp_path}\n")
    with pytest.raises(fresh.FreshnessError, match="other_live_owner:100"):
        fresh.owner_snapshot([tmp_path], {})


def test_platform_owner_snapshot_accepts_exact_authorized_identity(tmp_path: Path,
                                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    owner_fixture(monkeypatch, tmp_path, output=f"p100\nn{tmp_path}\n")
    result = fresh.owner_snapshot([tmp_path], {100: "100 owner-start-one"})
    assert result["cwd_holders"]["100"] == "100 owner-start-one"


def test_platform_owner_snapshot_rejects_changed_start_identity(tmp_path: Path,
                                                               monkeypatch: pytest.MonkeyPatch) -> None:
    owner_fixture(monkeypatch, tmp_path, output=f"p100\nn{tmp_path}\n")
    with pytest.raises(fresh.FreshnessError, match="owner_identity_changed"):
        fresh.owner_snapshot([tmp_path], {100: "100 wrong-start"})


def test_platform_owner_snapshot_rechecks_identity_after_cwd(tmp_path: Path,
                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    before = {900: {"ppid": 1, "identity": "900 caller"},
              100: {"ppid": 1, "identity": "100 owner-start-one"}}
    after = {900: {"ppid": 1, "identity": "900 caller"},
             100: {"ppid": 1, "identity": "100 different-reused-pid"}}
    owner_fixture(monkeypatch, tmp_path, output=f"p100\nn{tmp_path}\n", process_rows=[before, after])
    with pytest.raises(fresh.FreshnessError, match="owner_identity_changed"):
        fresh.owner_snapshot([tmp_path], {100: "100 owner-start-one"})


def test_remote_races_after_each_fast_forward_hold_at_bound_with_truthful_after(repo: LocalRepository,
                                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    published = [repo.publish("first.txt", "first\n")]
    original = fresh.Git.run
    def raced(self, *args, **kwargs):
        value = original(self, *args, **kwargs)
        if args[0] == "merge":
            published.append(repo.publish(f"after-{len(published)}.txt", "raced after merge\n"))
        return value
    monkeypatch.setattr(fresh.Git, "run", raced)
    result = repo.run(attempts=2)
    assert result["status"] == "hold"
    assert result["reason"] == "remote_ref_race:retry_bound_exhausted"
    assert len(published) == 3
    assert result["before"] == repo.initial
    assert result["after"] == repo.head() == published[1]
    assert repo.head() != published[-1]
    assert all(o["outcome"] == "remote_ref_race_after_fast_forward" for o in result["observations"])
    repo.assert_receipt(result)


def test_remote_movement_before_inventory_handoff_requires_another_boundary_observation(repo: LocalRepository) -> None:
    result = repo.run()
    repo.publish("late-inventory.txt", "arrived before freeze\n")
    with pytest.raises(fresh.FreshnessError, match="remote_moved_since_inventory_freshness"):
        fresh.verify_inventory_head(repo.target, result, boundary_id=BOUNDARY, policy_sha256=POLICY)
    assert repo.head() == repo.initial


def test_saved_receipt_byte_tampering_is_detected(repo: LocalRepository) -> None:
    result = repo.run()
    path = Path(result["receipt"]["path"])
    raw = path.read_bytes()
    path.write_bytes(raw.replace(b"observed_revision_verified", b"unverified_revision_claim"))
    with pytest.raises(fresh.FreshnessError, match="freshness_receipt_digest_changed"):
        fresh.verify_inventory_head(repo.target, result, boundary_id=BOUNDARY, policy_sha256=POLICY)


def test_platform_owner_probe_warning_remains_unknown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    owner_fixture(monkeypatch, tmp_path, output=f"p900\nn{tmp_path}\n",
                  stderr="lsof: WARNING: cannot stat() one owned path; output may be incomplete\n")
    with pytest.raises(fresh.FreshnessError, match="owner_cwd_inventory"):
        fresh.owner_snapshot([tmp_path], {})


def test_incoming_workflow_profile_cannot_silently_replace_frozen_contract(repo: LocalRepository) -> None:
    profile = "workflow/mech-workflow.yaml"
    pinned = repo.publish(profile, "parent: released-v1\n")
    git(repo.checkout, "fetch", "origin")
    git(repo.checkout, "merge", "--ff-only", pinned)
    repo.publish(profile, "parent: candidate-v2\n")
    result = repo.run()
    assert result["status"] == "hold"
    assert result["reason"] == "workflow_pin_change_requires_adoption"
    assert repo.head() == pinned
    assert (repo.checkout / profile).read_text() == "parent: released-v1\n"
    repo.assert_receipt(result)


def test_supplied_frozen_path_digest_change_holds_even_with_clean_current_head(repo: LocalRepository) -> None:
    profile = "custom/active-profile.yaml"
    frozen_bytes = b"policy: active-v1\n"
    pinned = repo.publish(profile, frozen_bytes.decode())
    git(repo.checkout, "fetch", "origin")
    git(repo.checkout, "merge", "--ff-only", pinned)
    later = repo.publish(profile, "policy: changed-v2\n")
    git(repo.checkout, "fetch", "origin")
    git(repo.checkout, "merge", "--ff-only", later)
    assert git(repo.checkout, "status", "--porcelain=v1") == ""
    result = repo.run(frozen_paths={profile: hashlib.sha256(frozen_bytes).hexdigest()})
    assert result["status"] == "hold"
    assert result["reason"] == "frozen_workflow_bytes_changed"
    assert repo.head() == later
    repo.assert_receipt(result)


@pytest.mark.parametrize('flag', ['--assume-unchanged', '--skip-worktree'])
def test_hidden_index_flags_never_authorize_dirty_owner_tree(repo: LocalRepository, flag: str) -> None:
    git(repo.checkout, 'update-index', flag, 'tracked.txt')
    (repo.checkout / 'tracked.txt').write_text('hidden unique owner work\n')
    assert git(repo.checkout, 'status', '--porcelain') == ''
    result = repo.run()
    assert result['status'] == 'hold'
    assert result['reason'].startswith('hidden_index_flags:')
    assert repo.head() == repo.initial
    assert (repo.checkout / 'tracked.txt').read_text() == 'hidden unique owner work\n'
    assert git(repo.checkout, 'ls-files', '-v', 'tracked.txt')[0] in {'h', 'S'}


def test_sparse_index_configuration_holds_without_clearing_owner_setting(repo: LocalRepository) -> None:
    git(repo.checkout, 'config', 'index.sparse', 'true')
    result = repo.run()
    assert result['status'] == 'hold'
    assert result['reason'] == 'sparse_checkout_requires_owned_full_base'
    assert git(repo.checkout, 'config', '--bool', 'index.sparse') == 'true'


def test_failed_merge_transport_reports_actual_persisted_head(repo: LocalRepository,
                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    wanted = repo.publish()
    original = fresh.Git.run
    def fail_after_merge(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        if args[0] == 'merge':
            raise fresh.FreshnessError('simulated_transport_loss_after_successful_ff')
        return result
    monkeypatch.setattr(fresh.Git, 'run', fail_after_merge)
    report = repo.run()
    assert report['status'] == 'hold'
    assert report['after'] == wanted == repo.head()
    assert report['before'] != report['after']
    repo.assert_receipt(report)


def test_noncolliding_untracked_work_holds_before_fetch(repo: LocalRepository) -> None:
    path = repo.checkout / "unique-evidence.txt"
    path.write_text("preserve exactly\n")
    repo.publish()
    result = repo.run()
    assert result["status"] == "hold"
    assert result["reason"].startswith("dirty_or_staged_checkout")
    assert result["fetched"] is None
    assert repo.head() == repo.initial
    assert path.read_text() == "preserve exactly\n"


@pytest.mark.parametrize("size,accepted", [(76_215_489, True), (128_000_001, False)])
def test_git_output_allows_measured_fleet_inventory_with_a_finite_bound(tmp_path, monkeypatch, size, accepted):
    payload = "x" * size
    monkeypatch.setattr(fresh.subprocess, "run", lambda *a, **k:
                        subprocess.CompletedProcess(a, 0, stdout=payload, stderr=""))
    if accepted:
        assert fresh.Git(tmp_path).run("ls-files", "-v", "-z") == payload
    else:
        with pytest.raises(fresh.FreshnessError, match="git_output_bound"):
            fresh.Git(tmp_path).run("ls-files", "-v", "-z")


def test_git_inventory_bound_counts_utf8_bytes(tmp_path, monkeypatch):
    payload = "é" * 64_000_001
    monkeypatch.setattr(fresh.subprocess, "run", lambda *a, **k:
                        subprocess.CompletedProcess(a, 0, stdout=payload, stderr=""))
    with pytest.raises(fresh.FreshnessError, match="git_output_bound"):
        fresh.Git(tmp_path).run("ls-tree", "-r", "-z", "HEAD")
