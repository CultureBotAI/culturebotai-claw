"""Exercise fleet updates against isolated Git remotes, never the live Mechs."""

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest
from git import Repo
from git.exc import InvalidGitRepositoryError, NoSuchPathError

from plugins.lock_manager import LockManager
from plugins.repository_settings import RepositoryConfigurationError, RepositorySettings
from scripts import fleet_pull


def git(path: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(path), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def commit(path: Path, filename: str, contents: str) -> str:
    (path / filename).write_text(contents, encoding="utf-8")
    git(path, "add", filename)
    git(path, "commit", "-m", f"Update {filename}")
    return git(path, "rev-parse", "HEAD")


class LocalSettings:
    """Allow local test remotes while retaining real Git operations."""

    def __init__(self, paths: dict[str, Path]):
        self.paths = paths
        self.errors = {}
        self.unconfigured = ()

    def get_target(self, key: str):
        self.open_repository(key)
        return SimpleNamespace(path=self.paths[key])

    def open_repository(self, key: str) -> Repo:
        try:
            return Repo(self.paths[key], search_parent_directories=False)
        except (InvalidGitRepositoryError, NoSuchPathError) as exc:
            raise RepositoryConfigurationError(f"Invalid repository: {self.paths[key]}") from exc


@dataclass
class LocalFleet:
    origin: Path
    writer: Path
    checkout: Path
    initial: str
    settings: LocalSettings
    locks: LockManager

    def publish(self, filename: str = "remote.txt", contents: str = "remote\n") -> str:
        revision = commit(self.writer, filename, contents)
        git(self.writer, "push", "origin", "HEAD")
        return revision

    def run(self, *, apply: bool = False):
        return fleet_pull.run_fleet(
            self.settings, ["culturemech"], apply=apply, locks=self.locks
        )[0]


@pytest.fixture(autouse=True)
def isolated_git(monkeypatch: pytest.MonkeyPatch):
    for name in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_COMMON_DIR"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", "/dev/null")
    monkeypatch.setenv("GIT_ALLOW_PROTOCOL", "file")
    monkeypatch.setenv("GIT_AUTHOR_NAME", "Fleet tests")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "fleet-tests@example.invalid")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "Fleet tests")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "fleet-tests@example.invalid")
    monkeypatch.setenv("GIT_TERMINAL_PROMPT", "0")


@pytest.fixture
def fleet(tmp_path: Path) -> LocalFleet:
    origin = tmp_path / "origin.git"
    writer = tmp_path / "writer"
    checkout = tmp_path / "checkout"
    git(tmp_path, "init", "--bare", "--initial-branch=main", str(origin))
    git(tmp_path, "clone", str(origin), str(writer))
    initial = commit(writer, "tracked.txt", "initial\n")
    git(writer, "push", "--set-upstream", "origin", "main")
    git(tmp_path, "clone", str(origin), str(checkout))
    return LocalFleet(
        origin,
        writer,
        checkout,
        initial,
        LocalSettings({"culturemech": checkout}),
        LockManager({"locks_dir": tmp_path / "locks", "my_id": "fleet-pull-tests"}),
    )


def git_files(path: Path) -> dict[str, bytes]:
    """Capture Git metadata, including index, refs, reflogs, and FETCH_HEAD."""
    return {
        str(item.relative_to(path)): item.read_bytes()
        for item in (path / ".git").rglob("*")
        if item.is_file()
    }


def test_default_preview_does_not_fetch_or_write_metadata(fleet: LocalFleet):
    fleet.publish()
    before = git_files(fleet.checkout)

    result = fleet.run()

    assert result["status"] == "up_to_date"
    assert git_files(fleet.checkout) == before
    assert git(fleet.checkout, "rev-parse", "origin/main") == fleet.initial
    assert not (fleet.checkout / "remote.txt").exists()


def test_preview_reports_known_update_without_changing_git_state(fleet: LocalFleet):
    remote = fleet.publish()
    git(fleet.checkout, "fetch", "origin")
    before = git_files(fleet.checkout)

    result = fleet.run()

    assert result["status"] == "would_update"
    assert result["ahead"] == 0
    assert result["behind"] == 1
    assert git_files(fleet.checkout) == before
    assert git(fleet.checkout, "rev-parse", "HEAD") == fleet.initial
    assert git(fleet.checkout, "rev-parse", "origin/main") == remote


@pytest.mark.parametrize("linked_worktree", [False, True])
def test_stale_rebase_head_allows_preview_and_fast_forward_without_removing_marker(
    fleet: LocalFleet, linked_worktree: bool
):
    primary_checkout = fleet.checkout
    if linked_worktree:
        linked = primary_checkout.parent / "linked"
        git(primary_checkout, "worktree", "add", "--track", "-b", "linked-main",
            str(linked), "origin/main")
        fleet.checkout = linked
        fleet.settings.paths["culturemech"] = linked
    branch = git(fleet.checkout, "branch", "--show-current")
    assert branch
    remote = fleet.publish()
    git(fleet.checkout, "fetch", "origin")
    git(fleet.checkout, "update-ref", "REBASE_HEAD", fleet.initial)
    git_dir = Path(git(fleet.checkout, "rev-parse", "--absolute-git-dir"))
    marker = git_dir / "REBASE_HEAD"
    marker_contents = marker.read_bytes()
    assert not (git_dir / "rebase-merge").exists()
    assert not (git_dir / "rebase-apply").exists()
    assert not git(fleet.checkout, "status", "--porcelain")
    before_preview = git_files(primary_checkout)

    preview = fleet.run()

    assert preview["status"] == "would_update"
    assert git_files(primary_checkout) == before_preview
    assert git(fleet.checkout, "rev-parse", "HEAD") == fleet.initial
    assert marker.read_bytes() == marker_contents

    result = fleet.run(apply=True)

    assert result["status"] == "updated"
    assert result["before"] == fleet.initial
    assert result["after"] == remote
    assert git(fleet.checkout, "rev-parse", "HEAD") == remote
    assert git(fleet.checkout, "branch", "--show-current") == branch
    assert (fleet.checkout / "remote.txt").read_text() == "remote\n"
    assert not git(fleet.checkout, "status", "--porcelain")
    assert marker.read_bytes() == marker_contents
    assert fleet.locks.check_lock("culturemech") is None
    if linked_worktree:
        assert git(primary_checkout, "rev-parse", "HEAD") == fleet.initial


def test_apply_fetches_then_fast_forwards(fleet: LocalFleet):
    remote = fleet.publish()

    result = fleet.run(apply=True)

    assert result["status"] == "updated"
    assert result["before"] == fleet.initial
    assert result["after"] == remote
    assert git(fleet.checkout, "rev-parse", "HEAD") == remote
    assert git(fleet.checkout, "branch", "--show-current") == "main"
    assert (fleet.checkout / "remote.txt").read_text() == "remote\n"
    assert not git(fleet.checkout, "status", "--porcelain")
    assert fleet.locks.check_lock("culturemech") is None


def test_apply_reports_already_current(fleet: LocalFleet):
    result = fleet.run(apply=True)

    assert result["status"] == "up_to_date"
    assert git(fleet.checkout, "rev-parse", "HEAD") == fleet.initial
    assert fleet.locks.check_lock("culturemech") is None


def test_fast_forward_overrides_configured_squash_and_autostash(fleet: LocalFleet):
    git(fleet.checkout, "config", "branch.main.mergeOptions", "--squash --autostash")
    remote = fleet.publish()

    result = fleet.run(apply=True)

    assert result["status"] == "updated"
    assert git(fleet.checkout, "rev-parse", "HEAD") == remote
    assert not git(fleet.checkout, "status", "--porcelain")
    assert not git(fleet.checkout, "stash", "list")


def test_symbolic_tracking_ref_cannot_overwrite_a_local_branch(fleet: LocalFleet):
    git(fleet.checkout, "branch", "precious")
    git(fleet.checkout, "symbolic-ref", "refs/remotes/origin/main", "refs/heads/precious")
    fleet.publish()
    before = git_files(fleet.checkout)

    result = fleet.run(apply=True)

    assert result["status"] == "skipped_symbolic_upstream"
    assert git_files(fleet.checkout) == before
    assert git(fleet.checkout, "rev-parse", "HEAD") == fleet.initial
    assert git(fleet.checkout, "rev-parse", "precious") == fleet.initial
    assert not (fleet.checkout / "remote.txt").exists()


def test_apply_follows_current_branch_upstream_without_switching(fleet: LocalFleet):
    git(fleet.writer, "switch", "-c", "curation")
    git(fleet.writer, "push", "--set-upstream", "origin", "curation")
    git(fleet.checkout, "fetch", "origin")
    git(fleet.checkout, "switch", "-c", "local-curation", "--track", "origin/curation")
    remote = fleet.publish()

    result = fleet.run(apply=True)

    assert result["status"] == "updated"
    assert result["branch"] == "local-curation"
    assert "curation" in result["upstream"]
    assert git(fleet.checkout, "branch", "--show-current") == "local-curation"
    assert git(fleet.checkout, "rev-parse", "HEAD") == remote
    assert git(fleet.checkout, "rev-parse", "main") == fleet.initial


@pytest.mark.parametrize("dirty_kind", ["unstaged", "staged", "untracked"])
def test_dirty_checkout_is_skipped_before_fetch(fleet: LocalFleet, dirty_kind: str):
    fleet.publish()
    filename = "new.txt" if dirty_kind == "untracked" else "tracked.txt"
    changed = fleet.checkout / filename
    changed.write_text("local work\n", encoding="utf-8")
    if dirty_kind == "staged":
        git(fleet.checkout, "add", filename)
    status = git(fleet.checkout, "status", "--porcelain")

    result = fleet.run(apply=True)

    assert result["status"] == "skipped_dirty"
    assert git(fleet.checkout, "rev-parse", "HEAD") == fleet.initial
    assert git(fleet.checkout, "rev-parse", "origin/main") == fleet.initial
    assert changed.read_text() == "local work\n"
    assert git(fleet.checkout, "status", "--porcelain") == status


@pytest.mark.parametrize(
    ("setup", "expected"),
    [
        ("detached", "skipped_detached"),
        ("no_upstream", "skipped_no_upstream"),
        ("other_remote", "skipped_non_origin"),
        ("local_upstream", "skipped_non_origin"),
    ],
)
def test_unsupported_branch_states_preserve_checkout(
    fleet: LocalFleet, setup: str, expected: str
):
    fleet.publish()
    if setup == "detached":
        git(fleet.checkout, "checkout", "--detach")
    elif setup == "no_upstream":
        git(fleet.checkout, "branch", "--unset-upstream")
    elif setup == "other_remote":
        git(fleet.checkout, "remote", "add", "other", str(fleet.origin))
        git(fleet.checkout, "fetch", "other")
        git(fleet.checkout, "branch", "--set-upstream-to=other/main")
    else:
        git(fleet.checkout, "branch", "local-base")
        git(fleet.checkout, "branch", "--set-upstream-to=local-base")
    before = git_files(fleet.checkout)

    result = fleet.run(apply=True)

    assert result["status"] == expected
    assert git_files(fleet.checkout) == before
    assert git(fleet.checkout, "rev-parse", "HEAD") == fleet.initial


def test_diverged_branch_is_never_merged_or_reset(fleet: LocalFleet):
    local = commit(fleet.checkout, "local.txt", "keep local\n")
    remote = fleet.publish()

    result = fleet.run(apply=True)

    assert result["status"] == "skipped_diverged"
    assert result["ahead"] == 1
    assert result["behind"] == 1
    assert git(fleet.checkout, "rev-parse", "HEAD") == local
    assert git(fleet.checkout, "rev-parse", "origin/main") == remote
    assert (fleet.checkout / "local.txt").read_text() == "keep local\n"
    assert not (fleet.checkout / "remote.txt").exists()


def test_ahead_branch_is_left_alone(fleet: LocalFleet):
    local = commit(fleet.checkout, "local.txt", "local commit\n")

    result = fleet.run(apply=True)

    assert result["status"] == "ahead"
    assert result["ahead"] == 1
    assert result["behind"] == 0
    assert git(fleet.checkout, "rev-parse", "HEAD") == local
    assert git(fleet.origin, "rev-parse", "main") == fleet.initial


@pytest.mark.parametrize("apply", [False, True])
@pytest.mark.parametrize(
    "marker", ["MERGE_HEAD", "CHERRY_PICK_HEAD", "rebase-merge", "rebase-apply"]
)
def test_in_progress_operation_is_skipped(fleet: LocalFleet, marker: str, apply: bool):
    fleet.publish()
    marker_path = fleet.checkout / ".git" / marker
    if marker in {"rebase-merge", "rebase-apply"}:
        marker_path.mkdir()
    else:
        marker_path.write_text(fleet.initial + "\n", encoding="utf-8")

    result = fleet.run(apply=apply)

    assert result["status"] == "skipped_in_progress"
    assert git(fleet.checkout, "rev-parse", "HEAD") == fleet.initial
    assert git(fleet.checkout, "rev-parse", "origin/main") == fleet.initial
    assert marker_path.exists()


@pytest.mark.parametrize("resource", ["culturemech", "global"])
def test_existing_lease_prevents_fetch_and_is_not_released(
    fleet: LocalFleet, resource: str
):
    fleet.publish()
    owner = LockManager({"locks_dir": fleet.locks.locks_dir, "my_id": "other-worker"})
    assert owner.acquire_lock(resource, "ongoing curation")
    held = owner.check_lock(resource)
    before = git_files(fleet.checkout)

    result = fleet.run(apply=True)

    assert result["status"] == "skipped_locked"
    assert owner.check_lock(resource) == held
    assert git_files(fleet.checkout) == before


def test_failure_for_one_repository_does_not_hide_success_for_next(fleet: LocalFleet):
    remote = fleet.publish()
    fleet.settings.paths["traitmech"] = fleet.checkout.parent / "does-not-exist"

    results = fleet_pull.run_fleet(
        fleet.settings, ["traitmech", "culturemech"], apply=True, locks=fleet.locks
    )

    assert [row["key"] for row in results] == ["traitmech", "culturemech"]
    assert [row["status"] for row in results] == ["error", "updated"]
    assert results[0]["detail"]
    assert git(fleet.checkout, "rev-parse", "HEAD") == remote
    assert fleet.locks.check_lock("traitmech") is None


def test_locked_repository_does_not_block_next_repository(fleet: LocalFleet):
    remote = fleet.publish()
    sibling = fleet.checkout.parent / "sibling"
    git(fleet.checkout.parent, "clone", str(fleet.origin), str(sibling))
    fleet.settings.paths["traitmech"] = sibling
    owner = LockManager({"locks_dir": fleet.locks.locks_dir, "my_id": "other-worker"})
    assert owner.acquire_lock("traitmech", "ongoing curation")

    results = fleet_pull.run_fleet(
        fleet.settings, ["traitmech", "culturemech"], apply=True, locks=fleet.locks
    )

    assert [row["status"] for row in results] == ["skipped_locked", "updated"]
    assert git(fleet.checkout, "rev-parse", "HEAD") == remote
    assert owner.check_lock("traitmech") is not None


def test_unconfigured_repository_is_reported_without_using_cwd(
    fleet: LocalFleet, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(fleet.checkout)
    settings = RepositorySettings.from_environment(environ={})
    before = git_files(fleet.checkout)

    results = fleet_pull.run_fleet(settings, ["culturemech"], locks=fleet.locks)

    assert results[0]["status"] == "not_configured"
    assert git_files(fleet.checkout) == before


def test_wrong_identity_is_rejected_by_real_repository_settings(fleet: LocalFleet):
    git(fleet.checkout, "remote", "set-url", "origin", "https://github.com/attacker/fake")
    settings = RepositorySettings.from_environment(
        environ={"CULTUREMECH_ROOT": str(fleet.checkout)}
    )

    results = fleet_pull.run_fleet(
        settings, ["culturemech"], apply=True, locks=fleet.locks
    )

    assert results[0]["status"] == "error"
    assert "identity mismatch" in results[0]["detail"]
    assert git(fleet.checkout, "rev-parse", "HEAD") == fleet.initial


def test_operation_time_identity_failure_does_not_fetch(
    fleet: LocalFleet, monkeypatch: pytest.MonkeyPatch
):
    fleet.publish()

    def reject_repository(key: str):
        raise RepositoryConfigurationError("origin identity changed")

    monkeypatch.setattr(fleet.settings, "open_repository", reject_repository)

    result = fleet.run(apply=True)

    assert result["status"] == "error"
    assert "identity changed" in result["detail"]
    assert git(fleet.checkout, "rev-parse", "origin/main") == fleet.initial


def test_fast_forward_does_not_overwrite_an_ignored_local_file(fleet: LocalFleet):
    (fleet.checkout / ".git" / "info" / "exclude").write_text("remote.txt\n")
    local_file = fleet.checkout / "remote.txt"
    local_file.write_text("local ignored artifact\n")
    remote = fleet.publish()
    assert not git(fleet.checkout, "status", "--porcelain")

    result = fleet.run(apply=True)

    assert result["status"] == "error"
    assert result["branch"] == "main"
    assert result["upstream"] == "refs/remotes/origin/main"
    assert result["before"] == fleet.initial
    assert result["target"] == remote
    assert result["after"] is None
    assert "| culturemech | main | error |" in fleet_pull.render_table([result])
    assert git(fleet.checkout, "rev-parse", "HEAD") == fleet.initial
    assert git(fleet.checkout, "rev-parse", "origin/main") == remote
    assert local_file.read_text() == "local ignored artifact\n"
    assert fleet.locks.check_lock("culturemech") is None


@pytest.mark.parametrize("change", ["dirty", "branch", "upstream", "rebase-merge", "rebase-apply"])
def test_revalidates_checkout_after_fetch_before_fast_forward(
    fleet: LocalFleet, monkeypatch: pytest.MonkeyPatch, change: str
):
    remote = fleet.publish()
    original_run = fleet_pull.Git.run

    def change_during_fetch(self, *args, **kwargs):
        output = original_run(self, *args, **kwargs)
        if args[0] == "fetch":
            if change == "dirty":
                (fleet.checkout / "tracked.txt").write_text("concurrent edit\n")
            elif change == "branch":
                git(fleet.checkout, "switch", "-c", "concurrent", "--track", "origin/main")
                # Keep HEAD fixed so the race is specifically a branch switch.
                git(fleet.checkout, "reset", "--hard", fleet.initial)
            elif change == "upstream":
                git(fleet.checkout, "branch", "--unset-upstream")
            else:
                (fleet.checkout / ".git" / change).mkdir()
        return output

    monkeypatch.setattr(fleet_pull.Git, "run", change_during_fetch)

    result = fleet.run(apply=True)

    expected = {
        "dirty": "skipped_dirty", "branch": "error", "upstream": "skipped_no_upstream",
        "rebase-merge": "skipped_in_progress", "rebase-apply": "skipped_in_progress",
    }
    assert result["status"] == expected[change]
    assert git(fleet.checkout, "rev-parse", "HEAD") == fleet.initial
    assert git(fleet.checkout, "rev-parse", "origin/main") == remote
    assert not (fleet.checkout / "remote.txt").exists()
    if change == "dirty":
        assert (fleet.checkout / "tracked.txt").read_text() == "concurrent edit\n"
    if change in {"rebase-merge", "rebase-apply"}:
        assert (fleet.checkout / ".git" / change).is_dir()
    assert fleet.locks.check_lock("culturemech") is None


def test_merge_uses_immutable_target_when_remote_tracking_ref_moves(
    fleet: LocalFleet, monkeypatch: pytest.MonkeyPatch
):
    remote = fleet.publish()
    original_run = fleet_pull.Git.run

    def move_tracking_ref_before_merge(self, *args, **kwargs):
        if "merge" in args:
            git(fleet.checkout, "update-ref", "refs/remotes/origin/main", fleet.initial)
        return original_run(self, *args, **kwargs)

    monkeypatch.setattr(fleet_pull.Git, "run", move_tracking_ref_before_merge)

    result = fleet.run(apply=True)

    assert result["status"] == "updated"
    assert git(fleet.checkout, "rev-parse", "HEAD") == remote
    assert git(fleet.checkout, "rev-parse", "origin/main") == fleet.initial


def test_fetch_does_not_update_unrelated_remote_branch(fleet: LocalFleet):
    git(fleet.writer, "branch", "unrelated")
    git(fleet.writer, "push", "origin", "unrelated")
    remote = fleet.publish()

    result = fleet.run(apply=True)

    assert result["status"] == "updated"
    assert git(fleet.checkout, "rev-parse", "HEAD") == remote
    assert not git(fleet.checkout, "for-each-ref", "refs/remotes/origin/unrelated")


def test_deleted_upstream_fails_without_merging_cached_commit(fleet: LocalFleet):
    fleet.publish()
    git(fleet.checkout, "fetch", "origin")
    git(fleet.origin, "update-ref", "-d", "refs/heads/main")

    result = fleet.run(apply=True)

    assert result["status"] == "error"
    assert result["branch"] == "main"
    assert result["upstream"] == "refs/remotes/origin/main"
    assert result["remote_ref"] == "refs/heads/main"
    assert result["before"] == fleet.initial
    assert result["after"] is None
    assert "target" not in result
    assert "| culturemech | main | error |" in fleet_pull.render_table([result])
    assert git(fleet.checkout, "rev-parse", "HEAD") == fleet.initial
    assert not (fleet.checkout / "remote.txt").exists()
    assert fleet.locks.check_lock("culturemech") is None


def test_fetch_timeout_releases_lease_and_continues_other_repositories(
    fleet: LocalFleet, monkeypatch: pytest.MonkeyPatch
):
    sibling = fleet.checkout.parent / "sibling"
    git(fleet.checkout.parent, "clone", str(fleet.origin), str(sibling))
    fleet.settings.paths["traitmech"] = sibling
    remote = fleet.publish()
    original_run = fleet_pull.Git.run

    def timeout_first_fetch(self, *args, **kwargs):
        if args[0] == "fetch" and self.root == sibling:
            raise fleet_pull.GitError("git fetch timed out")
        return original_run(self, *args, **kwargs)

    monkeypatch.setattr(fleet_pull.Git, "run", timeout_first_fetch)

    results = fleet_pull.run_fleet(
        fleet.settings, ["traitmech", "culturemech"], apply=True, locks=fleet.locks
    )

    assert [row["status"] for row in results] == ["error", "updated"]
    assert "timed out" in results[0]["detail"]
    assert results[0]["branch"] == "main"
    assert results[0]["upstream"] == "refs/remotes/origin/main"
    assert results[0]["before"] == fleet.initial
    assert results[0]["after"] is None
    table = fleet_pull.render_table(results)
    assert "| traitmech | main | error |" in table
    assert table.index("| culturemech |") < table.index("| traitmech |")
    assert git(sibling, "rev-parse", "HEAD") == fleet.initial
    assert git(fleet.checkout, "rev-parse", "HEAD") == remote
    assert fleet.locks.check_lock("traitmech") is None
    assert fleet.locks.check_lock("culturemech") is None


@pytest.mark.parametrize("failure", ["merge_error", "postcheck_timeout"])
def test_failure_after_merge_retains_initial_state_without_claiming_final_head(
    fleet: LocalFleet, monkeypatch: pytest.MonkeyPatch, failure: str
):
    sibling = fleet.checkout.parent / "sibling"
    git(fleet.checkout.parent, "clone", str(fleet.origin), str(sibling))
    fleet.settings.paths["traitmech"] = sibling
    remote = fleet.publish()
    original_run = fleet_pull.Git.run

    def fail_after_real_merge(self, *args, **kwargs):
        output = original_run(self, *args, **kwargs)
        if args[0] == "merge" and self.root == sibling:
            if failure == "merge_error":
                raise fleet_pull.GitError("git merge failed after updating HEAD")
            # Exercise the real shared-deadline check at the post-merge read.
            self.deadline = 0
        return output

    monkeypatch.setattr(fleet_pull.Git, "run", fail_after_real_merge)

    results = fleet_pull.run_fleet(
        fleet.settings, ["traitmech", "culturemech"], apply=True, locks=fleet.locks
    )

    assert [row["status"] for row in results] == ["error", "updated"]
    failed = results[0]
    assert failed["branch"] == "main"
    assert failed["upstream"] == "refs/remotes/origin/main"
    assert failed["before"] == fleet.initial
    assert failed["target"] == remote
    assert failed["after"] is None
    assert git(sibling, "rev-parse", "HEAD") == remote
    assert (sibling / "remote.txt").read_text() == "remote\n"
    assert git(fleet.checkout, "rev-parse", "HEAD") == remote
    assert fleet.locks.check_lock("traitmech") is None
    assert fleet.locks.check_lock("culturemech") is None


def test_preview_comparison_failure_retains_inspected_state(fleet: LocalFleet):
    git(fleet.checkout, "update-ref", "-d", "refs/remotes/origin/main")
    before = git_files(fleet.checkout)

    result = fleet.run()

    assert result["status"] == "error"
    assert result["branch"] == "main"
    assert result["upstream"] == "refs/remotes/origin/main"
    assert result["before"] == fleet.initial
    assert result["after"] == fleet.initial
    assert "| culturemech | main | error |" in fleet_pull.render_table([result])
    assert git_files(fleet.checkout) == before


@pytest.mark.parametrize("apply", [False, True])
def test_cli_selects_manifest_repositories_and_reports_coverage(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture, apply: bool
):
    selected_settings = object()
    monkeypatch.setattr(fleet_pull, "merged_repository_environment", lambda _path: {})
    monkeypatch.setattr(
        fleet_pull.RepositorySettings, "from_environment", lambda **_kwargs: selected_settings
    )
    selected = ["culturemech", "traitmech"] if apply else list(fleet_pull.load_fleet_manifest().mechs)
    observed = []

    def record_fleet(settings, keys, **kwargs):
        observed.append((settings, keys, kwargs))
        return [{"key": key, "status": "up_to_date", "detail": ""} for key in keys]

    monkeypatch.setattr(fleet_pull, "run_fleet", record_fleet)
    argv = ["--json"]
    if apply:
        argv.extend(["--apply", "--mech", "culturemech", "--mech", "traitmech",
                     "--mech", "culturemech"])

    assert fleet_pull.main(argv) == 0

    report = json.loads(capsys.readouterr().out)
    assert observed == [(selected_settings, selected, {"apply": apply, "timeout": 60})]
    assert report["selected"] == selected
    assert report["mode"] == ("apply" if apply else "dry_run")
    assert report["comparison"] == ("fetch_eligible_only" if apply else "cached_refs")
    assert report["complete"] is True
    assert [row["key"] for row in report["results"]] == selected


def test_cli_incomplete_report_has_nonzero_exit(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    monkeypatch.setattr(fleet_pull, "merged_repository_environment", lambda _path: {})
    monkeypatch.setattr(fleet_pull.RepositorySettings, "from_environment", lambda **_kwargs: object())
    monkeypatch.setattr(
        fleet_pull,
        "run_fleet",
        lambda *_args, **_kwargs: [{"key": "culturemech", "status": "skipped_dirty"}],
    )

    assert fleet_pull.main(["--json", "--mech", "culturemech"]) == 1

    assert json.loads(capsys.readouterr().out)["complete"] is False


@pytest.mark.parametrize(
    "argv",
    [["--mech", "not-a-mech"], ["--timeout", "0"], ["--timeout", "301"],
     ["--apply", "--dry-run"]],
)
def test_invalid_cli_usage_never_runs_git(monkeypatch: pytest.MonkeyPatch, argv: list[str]):
    def unexpected_run(*_args, **_kwargs):
        pytest.fail("invalid command must be rejected before running Git")

    monkeypatch.setattr(fleet_pull, "run_fleet", unexpected_run)

    with pytest.raises(SystemExit) as exc:
        fleet_pull.main(argv)

    assert exc.value.code == 2
