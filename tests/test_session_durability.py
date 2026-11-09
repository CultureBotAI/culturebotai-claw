"""Offline synthetic coverage of #938's read-only session observations."""
from __future__ import annotations

import copy
import os
import subprocess
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kg_microbe_workflows import session_durability as durability

DAY = 86400


def git(root: Path, *args: str) -> str:
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    return subprocess.check_output(
        ["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
         "-c", "commit.gpgsign=false", "-C", str(root), *args],
        stderr=subprocess.STDOUT, env=env, text=True,
    ).strip()


def commit(root: Path, message: str = "batch") -> str:
    git(root, "commit", "--allow-empty", "-m", message)
    return git(root, "rev-parse", "HEAD")


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    durable = tmp_path / "durable"
    cleaner = tmp_path / "cleaner"
    durable.mkdir()
    cleaner.mkdir()
    # Pytest itself may live below /tmp; it is allowed scratch, not a live scan.
    monkeypatch.setattr(durability, "_temporary_bases", lambda _: (cleaner,))
    return durable, cleaner


def repository(parent: Path, name: str = "repo", remote: bool = True) -> Path:
    root = parent / name
    root.mkdir()
    git(root, "init", "--initial-branch=main", "--template=")
    first = commit(root, "base")
    if remote:
        git(root, "update-ref", "refs/remotes/origin/main", first)
    return root


def observe(root: Path, paths=(), **kwargs):
    return durability.observe_repository(root, session_state_paths=paths, **kwargs)


def codes(result):
    return {item["code"] for item in result["errors"]}


def aged_entries(monkeypatch, ages: dict[str, tuple[float, float, float]], now: datetime):
    """Inject independent stat times; never alter any actual file's timestamps."""
    scan = os.scandir

    class Entry:
        def __init__(self, item):
            self.item = item
            self.name = item.name

        def stat(self, *, follow_symlinks=True):
            info = self.item.stat(follow_symlinks=follow_symlinks)
            if self.name not in ages:
                return info
            values = list(info)
            values[7:10] = [now.timestamp() - value for value in ages[self.name]]
            return os.stat_result(values)

    @contextmanager
    def replaced(path):
        with scan(path) as entries:
            yield (Entry(entry) for entry in entries)

    monkeypatch.setattr(durability.os, "scandir", replaced)


def test_counts_unique_local_commits_not_on_any_remote_ref(sandbox):
    durable, _ = sandbox
    root = repository(durable)
    first = commit(root, "first")
    git(root, "branch", "another-local", first)
    second = commit(root, "second")
    git(root, "update-ref", "refs/remotes/backup/other-branch", first)
    git(root, "tag", "local-backup", second)
    report = observe(root)
    assert report["status"] == "alert"
    assert report["complete"]
    assert report["unpushed_commits"] == 1
    assert report["commit_samples"] == [second]
    # Neither the configured upstream nor a local tag defines the denominator.
    git(root, "update-ref", "refs/remotes/another/published-batch", second)
    report = observe(root)
    assert report["unpushed_commits"] == 0
    assert report["status"] == "healthy"


def test_linked_worktrees_share_one_branch_census(sandbox):
    durable, _ = sandbox
    root = repository(durable)
    value = commit(root)
    linked = durable / "linked"
    git(root, "worktree", "add", "-b", "linked-branch", str(linked), value)
    result = durability.observe_mech([root, linked], session_state_paths=[])
    assert result["repository_count"] == 1
    assert result["unpushed_commits"] == 1
    assert result["commit_samples"] == [value]


def test_a_second_registered_clone_can_supply_remote_coverage(sandbox):
    durable, _ = sandbox
    root = repository(durable)
    commit(root)
    clone = durable / "clone"
    git(durable, "clone", str(root), str(clone))
    assert observe(root)["unpushed_commits"] == 1
    result = durability.observe_mech([root, clone], session_state_paths=[])
    assert result["repository_count"] == 2
    assert result["unpushed_commits"] == 0
    assert result["status"] == "healthy"


def test_duplicate_unpublished_commits_in_separate_clones_count_once(sandbox):
    durable, _ = sandbox
    root = repository(durable)
    base = git(root, "rev-parse", "HEAD")
    value = commit(root)
    clone = durable / "clone"
    git(durable, "clone", str(root), str(clone))
    git(clone, "update-ref", "refs/remotes/origin/main", base)
    result = durability.observe_mech([root, clone], session_state_paths=[])
    assert result["unpushed_commits"] == 1
    assert result["commit_samples"] == [value]


def test_no_remote_refs_preserves_count_but_never_claims_healthy(sandbox):
    root = repository(sandbox[0], remote=False)
    report = observe(root)
    assert report["unpushed_commits"] == 1
    assert not report["complete"] and report["alert"]
    assert "no_remote_tracking_refs" in codes(report)


def test_missing_state_inventory_is_not_zero_risk(sandbox):
    root = repository(sandbox[0])
    report = durability.observe_repository(root)
    assert report["status"] == "unknown" and report["alert"]
    assert report["unpushed_commits"] is None
    assert report["at_risk_files"] is None
    assert "state_inventory_missing" in codes(report)


@pytest.mark.parametrize("ages,risk,overdue", [
    ((3 * DAY, 3 * DAY, 3 * DAY), 1, 0),
    ((4 * DAY, 4 * DAY, 4 * DAY), 1, 1),
    ((5 * DAY, 5 * DAY, 2 * DAY), 0, 0),
    ((5 * DAY, 2 * DAY, 5 * DAY), 0, 0),
    ((2 * DAY, 5 * DAY, 5 * DAY), 0, 0),
    ((3 * DAY - 1, 4 * DAY, 4 * DAY), 0, 0),
])
def test_cutoff_uses_newest_of_all_three_times(sandbox, monkeypatch, ages, risk, overdue):
    durable, cleaner = sandbox
    root = repository(durable)
    owned = cleaner / "campaign"
    owned.mkdir()
    (owned / "bundle").write_bytes(b"retained review")
    now = datetime.now(timezone.utc)
    aged_entries(monkeypatch, {"bundle": ages}, now)
    result = observe(root, [owned], now=now)
    assert result["at_risk_files"] == risk
    assert result["overdue_files"] == overdue
    assert result["status"] == ("alert" if risk else "healthy")


def test_missing_and_future_stats_are_unknown(sandbox, monkeypatch):
    durable, cleaner = sandbox
    root = repository(durable)
    assert observe(root, [cleaner / "lost"])["at_risk_files"] is None
    owned = cleaner / "campaign"
    owned.mkdir()
    (owned / "bundle").write_text("content")
    now = datetime.now(timezone.utc)
    aged_entries(monkeypatch, {"bundle": (-3600, 4 * DAY, 4 * DAY)}, now)
    result = observe(root, [owned], now=now)
    assert result["at_risk_files"] is None
    assert result["status"] == "unknown"
    assert "invalid_or_future_file_time" in codes(result)


def test_overlapping_scopes_do_not_double_count_files_and_samples_are_bounded(sandbox, monkeypatch):
    durable, cleaner = sandbox
    root = repository(durable)
    owned = cleaner / "campaign"
    child = owned / "nested"
    child.mkdir(parents=True)
    for name in ("one", "two"):
        (child / name).write_text("review")
    now = datetime.now(timezone.utc)
    aged_entries(monkeypatch, {name: (4 * DAY,) * 3 for name in ("one", "two")}, now)
    result = observe(root, [owned, child], now=now, limits=durability.Limits(max_samples=1))
    assert result["at_risk_files"] == 2
    assert len(result["temporary"]["samples"]) == 1
    assert result["complete"]


def test_stat_pass_never_reads_or_refreshes_file_contents(sandbox, monkeypatch):
    durable, cleaner = sandbox
    root = repository(durable)
    owned = cleaner / "campaign"
    owned.mkdir()
    bundle = owned / "bundle"
    bundle.write_bytes(b"private evidence must not be read")
    before = bundle.stat()

    def forbidden(*args, **kwargs):
        raise AssertionError("the observer attempted a content/timestamp mutation")

    monkeypatch.setattr(Path, "read_bytes", forbidden)
    monkeypatch.setattr(Path, "read_text", forbidden)
    monkeypatch.setattr(Path, "touch", forbidden)
    monkeypatch.setattr(Path, "unlink", forbidden)
    monkeypatch.setattr(os, "utime", forbidden)
    result = observe(root, [owned])
    after = bundle.stat()
    assert result["complete"]
    assert (before.st_atime_ns, before.st_mtime_ns, before.st_ctime_ns) == (
        after.st_atime_ns, after.st_mtime_ns, after.st_ctime_ns)


def test_symlink_children_do_not_escape_owned_scope(sandbox, monkeypatch):
    durable, cleaner = sandbox
    root = repository(durable)
    outside = durable / "unrelated"
    outside.mkdir()
    (outside / "old").write_bytes(b"not owned")
    owned = cleaner / "campaign"
    owned.mkdir()
    (owned / "escape").symlink_to(outside, target_is_directory=True)
    now = datetime.now(timezone.utc)
    aged_entries(monkeypatch, {"old": (5 * DAY,) * 3}, now)
    result = observe(root, [owned], now=now)
    assert result["at_risk_files"] == 0
    assert result["temporary"]["symlinks_skipped"] == 1
    assert result["temporary"]["regular_files"] == 0


def test_explicit_alias_into_temporary_storage_is_recognized(sandbox, monkeypatch):
    durable, cleaner = sandbox
    root = repository(durable)
    owned = cleaner / "campaign"
    owned.mkdir()
    (owned / "old").write_bytes(b"review")
    alias = durable / "alias"
    alias.symlink_to(owned, target_is_directory=True)
    now = datetime.now(timezone.utc)
    aged_entries(monkeypatch, {"old": (5 * DAY,) * 3}, now)
    assert observe(root, [alias], now=now)["at_risk_files"] == 1


def test_ancestor_symlink_race_cannot_redirect_the_scan(sandbox, monkeypatch):
    durable, cleaner = sandbox
    root = repository(durable)
    ancestor = cleaner / "ancestor"
    owned = ancestor / "nested" / "campaign"
    owned.mkdir(parents=True)
    outside = durable / "unrelated"
    (outside / "nested" / "campaign").mkdir(parents=True)
    (outside / "nested" / "campaign" / "private").write_text("must not be scanned")
    actual = durability._open_directory
    changed = False

    def swapped(path, budget):
        nonlocal changed
        if path == owned.parent and not changed:
            changed = True
            ancestor.rename(cleaner / "retained-original")
            ancestor.symlink_to(outside, target_is_directory=True)
        return actual(path, budget)

    monkeypatch.setattr(durability, "_open_directory", swapped)
    result = observe(root, [owned])
    assert changed
    assert result["status"] == "unknown"
    assert result["temporary"]["regular_files"] == 0
    assert "unreadable_owned_path" in codes(result)


def test_whole_temporary_root_is_not_an_owned_campaign(sandbox):
    root = repository(sandbox[0])
    result = observe(root, [sandbox[1]])
    assert "unbounded_owned_path" in codes(result)
    assert result["at_risk_files"] is None


@pytest.mark.parametrize("bare", [False, True])
def test_unregistered_clones_are_unknown_not_silently_ignored(sandbox, bare):
    durable, cleaner = sandbox
    root = repository(durable)
    owned = cleaner / "campaign"
    clone = owned / "unregistered"
    clone.mkdir(parents=True)
    if bare:
        (clone / "HEAD").write_text("private content is never read")
        (clone / "objects").mkdir()
        (clone / "refs").mkdir()
    else:
        (clone / ".git").write_text("gitdir: private content is never read")
    result = observe(root, [owned])
    assert result["unpushed_commits"] is None
    assert result["status"] == "unknown"
    assert "unregistered_repository" in codes(result)


def test_registered_temporary_worktrees_are_observed_automatically(sandbox, monkeypatch):
    durable, cleaner = sandbox
    root = repository(durable)
    linked = cleaner / "registered"
    git(root, "worktree", "add", "-b", "batch", str(linked), "HEAD")
    (linked / "review").write_text("retained review")
    now = datetime.now(timezone.utc)
    aged_entries(monkeypatch, {"review": (4 * DAY,) * 3}, now)
    result = observe(root, now=now)
    assert result["at_risk_files"] == 1
    assert "unregistered_repository" not in codes(result)


def test_entry_depth_and_root_bounds_do_not_become_zero(sandbox):
    durable, cleaner = sandbox
    root = repository(durable)
    owned = cleaner / "campaign"
    deep = owned / "a" / "b"
    deep.mkdir(parents=True)
    (deep / "review").write_text("review")
    for limits, expected in ((durability.Limits(max_entries=1), "entry_limit"),
                             (durability.Limits(max_depth=1), "depth_limit")):
        result = observe(root, [owned], limits=limits)
        assert result["at_risk_files"] is None
        assert result["alert"] and expected in codes(result)
    second = cleaner / "second"
    second.mkdir()
    result = observe(root, [owned, second], limits=durability.Limits(max_roots=1))
    assert "state_root_limit" in codes(result)
    assert result["unpushed_commits"] is None and result["at_risk_files"] is None


def test_git_limits_and_corruption_do_not_report_healthy(sandbox):
    root = repository(sandbox[0])
    commit(root, "one")
    commit(root, "two")
    result = observe(root, limits=durability.Limits(max_commits=1))
    assert result["unpushed_commits"] is None and "commit_limit" in codes(result)
    result = observe(root, limits=durability.Limits(max_refs=1))
    assert result["unpushed_commits"] is None and "ref_limit" in codes(result)
    result = observe(root, limits=durability.Limits(max_output_bytes=10))
    assert result["unpushed_commits"] is None and "git_output_limit" in codes(result)
    (root / ".git/refs/heads/broken").write_text("f" * 40 + "\n")
    result = observe(root)
    assert result["unpushed_commits"] is None and result["alert"]


def test_shallow_history_cannot_establish_a_zero_count(sandbox):
    durable, _ = sandbox
    root = repository(durable)
    commit(root)
    clone = durable / "shallow"
    git(durable, "clone", "--depth", "1", root.as_uri(), str(clone))
    result = observe(clone)
    assert result["unpushed_commits"] is None
    assert result["status"] == "unknown" and "shallow_history" in codes(result)


def test_references_are_rechecked_after_the_observation(sandbox, monkeypatch):
    root = repository(sandbox[0])
    actual = durability.run_git
    calls = 0

    def changing(path, args, **kwargs):
        nonlocal calls
        if args[0] == "for-each-ref":
            calls += 1
            if calls == 2:
                git(root, "branch", "concurrent", "HEAD")
        return actual(path, args, **kwargs)

    monkeypatch.setattr(durability, "run_git", changing)
    result = observe(root)
    assert result["unpushed_commits"] is None
    assert "refs_changed_during_observation" in codes(result)


def test_registered_worktree_inventory_is_rechecked(sandbox, monkeypatch):
    root = repository(sandbox[0])
    actual = durability.run_git
    calls = 0

    def changing(path, args, **kwargs):
        nonlocal calls
        data = actual(path, args, **kwargs)
        if args[0] == "worktree":
            calls += 1
            if calls == 2:
                data += b"worktree /unknown/concurrent\0\0"
        return data

    monkeypatch.setattr(durability, "run_git", changing)
    result = observe(root)
    assert result["unpushed_commits"] is None
    assert "worktrees_changed_during_observation" in codes(result)


@pytest.mark.parametrize("failure", ["git_timeout", "git_unavailable", "time_limit"])
def test_unknown_measurement_never_reports_healthy(sandbox, monkeypatch, failure):
    root = repository(sandbox[0])

    def unavailable(*args, **kwargs):
        raise durability.ObservationError(failure)

    monkeypatch.setattr(durability, "run_git", unavailable)
    result = observe(root)
    assert result["status"] == "unknown" and result["alert"]
    assert result["unpushed_commits"] is None and failure in codes(result)


def test_ambient_git_paths_and_config_cannot_redirect_the_observation(sandbox, monkeypatch):
    root = repository(sandbox[0])
    monkeypatch.setenv("GIT_DIR", str(sandbox[0] / "not-the-repo"))
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "extensions.partialClone")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "untrusted")
    monkeypatch.setenv("GIT_NO_LAZY_FETCH", "0")
    actual = durability.subprocess.Popen
    calls = []

    def checked(command, **kwargs):
        calls.append(command)
        assert kwargs["env"]["GIT_NO_LAZY_FETCH"] == "1"
        assert kwargs["env"]["GIT_OPTIONAL_LOCKS"] == "0"
        assert kwargs["env"]["GIT_TERMINAL_PROMPT"] == "0"
        return actual(command, **kwargs)

    monkeypatch.setattr(durability.subprocess, "Popen", checked)
    assert observe(root)["status"] == "healthy"
    assert calls


@pytest.mark.parametrize("args", [
    ["fetch", "origin"], ["push", "origin", "main"], ["worktree", "remove", "/tmp/unsafe"],
    ["cat-file", "--filters", "HEAD:file"], ["rev-list", "--all"],
])
def test_query_allowlist_refuses_mutation_and_filter_execution(tmp_path, monkeypatch, args):
    def forbidden(*args, **kwargs):
        raise AssertionError("disallowed query spawned a child")

    monkeypatch.setattr(durability.subprocess, "Popen", forbidden)
    with pytest.raises(durability.ObservationError, match="disallowed_git_query"):
        durability.run_git(tmp_path, args, timeout=1, output_limit=10)


def test_private_fields_do_not_enter_public_summary(sandbox):
    root = repository(sandbox[0])
    report = observe(root)
    public = durability.public_summary(report)
    assert set(public) == {"schema_version", "observed_at", "status", "alert", "complete",
                           "repository_count", "unpushed_commits", "at_risk_files", "overdue_files"}
    assert str(root) not in str(public)


@pytest.mark.parametrize("changes", [
    {"unpushed_commits": True, "status": "alert", "alert": True},
    {"at_risk_files": -1, "status": "alert", "alert": True}, {"repository_count": None},
    {"status": "/private/session/identity"}, {"observed_at": "2026-11-07T12:00:00"},
    {"observed_at": 17}, {"alert": 0}, {"extra": "private content"},
    {"complete": False}, {"unpushed_commits": None}, {"repository_count": 0},
    {"status": []}, {"status": "unknown", "alert": True},
    {"status": "alert", "alert": True, "at_risk_files": 1, "overdue_files": 2},
])
def test_public_projection_validates_types_and_unknown_fields(sandbox, changes):
    root = repository(sandbox[0])
    report = copy.deepcopy(observe(root))
    report.update(changes)
    with pytest.raises(ValueError):
        durability.public_summary(report)


@pytest.mark.parametrize("changes", [
    {"max_entries": True}, {"max_roots": 0}, {"timeout_seconds": float("inf")},
    {"warning_seconds": 4 * DAY},
])
def test_bad_limits_fail_before_observing(changes):
    with pytest.raises(ValueError):
        durability.Limits(**changes)


def test_real_temporary_aliases_and_supplied_tmpdir(monkeypatch, tmp_path):
    monkeypatch.setenv("TMPDIR", str(tmp_path / "runtime-temp"))
    bases = durability._temporary_bases(None)
    assert Path("/tmp").resolve() in bases
    assert Path("/private/tmp").resolve() in bases
    assert tmp_path / "runtime-temp" in bases
    with pytest.raises(durability.ObservationError, match="invalid_tmpdir"):
        durability._temporary_bases(Path("relative"))


def test_naive_clock_is_rejected(sandbox):
    with pytest.raises(ValueError, match="timezone-aware"):
        observe(repository(sandbox[0]), now=datetime(2026, 11, 7))


def test_legacy_graft_cannot_hide_unpublished_batch(sandbox):
    """#955: local graph overlays are not remote publication evidence."""
    durable, _ = sandbox
    root = repository(durable)
    base = git(root, "rev-parse", "refs/remotes/origin/main")
    batch = commit(root, "unpublished batch")
    assert observe(root)["unpushed_commits"] == 1
    grafts = root / ".git/info/grafts"
    grafts.parent.mkdir(exist_ok=True)
    grafts.write_text(f"{base} {batch}\n")
    # This proves the contrast: an unguarded Git graph query is fooled.
    assert batch not in git(root, "rev-list", "--branches", "--not", "--remotes").splitlines()
    report = observe(root)
    assert report["complete"] is True
    assert report["status"] == "alert"
    assert report["unpushed_commits"] == 1
    assert report["commit_samples"] == [batch]
