"""Offline repositories prove inventory preserves material and fails closed."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shlex
import subprocess
from pathlib import Path

import pytest

SOURCE = Path(__file__).resolve().parents[1] / "scripts/repo_crud_inventory.py"
SPEC = importlib.util.spec_from_file_location("repo_crud_inventory", SOURCE)
crud = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(crud)
IDENTITY = "ExampleOrg/ExampleMech"


def git(root: Path, *args: str) -> str:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
    return subprocess.run(
        ["git", "-c", "core.hooksPath=" + os.devnull, "-C", str(root), *args],
        check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
    ).stdout.decode().strip()


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "user.name", "Offline Fixture")
    git(root, "remote", "add", "origin", f"https://github.com/{IDENTITY}.git")
    (root / "README.md").write_text("Tracked baseline\n")
    (root / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n.ruff_cache/\n.env\n")
    git(root, "add", ".")
    git(root, "commit", "-m", "fixture")
    return root


def write(root: Path, relative: str, content: str = "fixture") -> Path:
    target = root / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    return target


def run(root: Path, **kwargs) -> dict:
    return crud.inventory(root, IDENTITY, **kwargs)


def rows(report: dict) -> dict:
    return {row["path"]: row for row in report["entries"]}


def candidate_paths(report: dict) -> set:
    return {row["path"] for row in report["candidates"]}


def snapshot(root: Path) -> dict:
    return {
        str(path.relative_to(root)): (
            path.lstat().st_mode, path.lstat().st_mtime_ns,
            os.readlink(path) if path.is_symlink() else hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in root.rglob("*") if path.is_symlink() or path.is_file()
    }


def test_ignored_and_hidden_paths_included_without_content_disclosure(repo):
    secret = "TOP-SECRET-FIXTURE-CONTENT"
    write(repo, ".env", secret)
    write(repo, ".hidden/notes.txt")
    write(repo, "__pycache__/module.cpython-313.pyc")
    report = run(repo)
    assert report["complete"], report["errors"]
    assert rows(report)[".env"]["ignored"]
    assert rows(report)[".env"]["disposition"] == "protected"
    assert rows(report)[".hidden/notes.txt"]["untracked"]
    assert candidate_paths(report) == {"__pycache__"}
    assert secret not in json.dumps(report)
    assert "not content hashes" in report["limitations"][0]
    assert report["apply_supported"] is False


@pytest.mark.parametrize("relative", [
    "__pycache__/measurements.csv", "__pycache__/.env", "__pycache__/nested/module.cpython-313.pyc",
    "__pycache__/research/results.tsv", "__pycache__/private_key.cpython-313.pyc",
    "__pycache__/module.py", ".pytest_cache/v/cache/data.csv", ".ruff_cache/0.16.3/secrets.json",
])
def test_unknown_data_or_secret_descendant_blocks_entire_cache(repo, relative):
    write(repo, relative)
    write(repo, relative.split("/")[0] + "/CACHEDIR.TAG")
    report = run(repo)
    assert report["complete"], report["errors"]
    assert not report["candidates"]
    assert rows(report)[relative.split("/")[0]]["disposition"] == "protected"


@pytest.mark.parametrize("parent", ["data", "history", "research", "references_cache", "build", "site", "docs", ".claude"])
def test_recognized_cache_under_protected_parent_is_not_selected(repo, parent):
    write(repo, f"{parent}/__pycache__/module.cpython-313.pyc")
    assert not run(repo)["candidates"]


def test_tool_cache_shapes_are_review_candidates_only(repo):
    write(repo, ".pytest_cache/v/cache/nodeids", "[]")
    write(repo, ".pytest_cache/README.md")
    write(repo, ".ruff_cache/0.16.3/a012345")
    report = run(repo)
    assert candidate_paths(report) == {".pytest_cache", ".ruff_cache"}
    assert all(item["requires_manual_review"] for item in report["candidates"])
    assert "safe_to_delete" not in json.dumps(report)


def test_tracked_mixed_cache_and_deleted_tracked_member_are_protected(repo):
    tracked = write(repo, "__pycache__/curated.csv")
    git(repo, "add", "-f", "__pycache__/curated.csv")
    git(repo, "commit", "-m", "tracked data in cache-shaped path")
    write(repo, "__pycache__/module.cpython-313.pyc")
    report = run(repo)
    assert not report["candidates"]
    assert rows(report)["__pycache__"]["tracked_descendants"]
    tracked.unlink()
    report = run(repo)
    assert not report["candidates"]
    assert report["unstaged_content_state"].startswith("unmeasured")
    assert report["staged_status"] == []


def test_symlink_is_not_followed_or_selected(repo, tmp_path):
    outside = tmp_path / "outside"
    write(outside, "private.txt", "must-not-read")
    (repo / "__pycache__").symlink_to(outside, target_is_directory=True)
    report = run(repo)
    assert report["complete"], report["errors"]
    assert rows(report)["__pycache__"]["reason"] == "symlink_not_followed"
    assert "__pycache__/private.txt" not in rows(report)
    assert not report["candidates"]


def test_symlink_descendant_protects_cache(repo, tmp_path):
    write(repo, "__pycache__/module.cpython-313.pyc")
    (repo / "__pycache__/other.cpython-313.pyc").symlink_to(tmp_path / "missing")
    assert not run(repo)["candidates"]


def test_directory_replaced_by_symlink_cannot_redirect_traversal(repo, tmp_path, monkeypatch):
    write(repo, "__pycache__/module.cpython-313.pyc")
    outside = tmp_path / "outside"
    write(outside, "private.txt")
    actual = os.open
    swapped = []
    def replace_before_open(path, flags, *args, **kwargs):
        if path == "__pycache__" and not swapped:
            swapped.append(True)
            (repo / "__pycache__").rename(repo / "moved-cache")
            (repo / "__pycache__").symlink_to(outside, target_is_directory=True)
        return actual(path, flags, *args, **kwargs)
    monkeypatch.setattr(os, "open", replace_before_open)
    report = run(repo)
    assert swapped
    assert not report["complete"]
    assert not report["candidates"]
    assert "__pycache__/private.txt" not in rows(report)


def test_nested_repository_and_mount_are_protected(repo, monkeypatch):
    write(repo, ".pytest_cache/.git", "gitdir: /do/not/follow")
    write(repo, ".pytest_cache/v/cache/nodeids")
    write(repo, ".ruff_cache/0.16.3/12345")
    actual = os.path.ismount
    monkeypatch.setattr(os.path, "ismount", lambda path: Path(path).name == ".ruff_cache" or actual(path))
    report = run(repo)
    assert report["complete"], report["errors"]
    assert rows(report)[".pytest_cache"]["reason"] == "nested_repository_not_traversed"
    assert rows(report)[".ruff_cache"]["disposition"] == "protected"
    assert ".pytest_cache/v/cache/nodeids" not in rows(report)
    assert ".ruff_cache/0.16.3/12345" not in rows(report)
    assert not report["candidates"]


def test_scan_bounds_remove_all_candidates(repo):
    write(repo, "__pycache__/module.cpython-313.pyc")
    report = run(repo, max_entries=2)
    assert not report["complete"]
    assert any("bound" in error for error in report["errors"])
    assert not report["candidates"]


def test_protected_trees_are_retained_with_explicit_unknown_coverage(repo):
    write(repo, "data/research/.env", "do-not-inspect")
    write(repo, "build/pinned/input.csv")
    write(repo, ".venv/private.txt")
    write(repo, "src/tracked.py")
    git(repo, "add", "src/tracked.py")
    git(repo, "commit", "-m", "tracked source subtree")
    write(repo, "src/__pycache__/tracked.cpython-313.pyc")
    report = run(repo, max_entries=12)
    assert report["complete"], report["errors"]
    for path in ("data", "build", ".venv"):
        assert path in report["retained_subtrees"]
        assert rows(report)[path]["descendants_not_inspected"]
        assert rows(report)[path]["subtree_size_unmeasured"]
    assert "data/research/.env" not in rows(report)
    assert rows(report)["src/tracked.py"]["tracked"]
    assert candidate_paths(report) == {"src/__pycache__"}


def test_stale_rebase_head_is_diagnostic_not_an_active_operation(repo):
    write(repo, ".git/REBASE_HEAD", git(repo, "rev-parse", "HEAD"))
    write(repo, "__pycache__/module.cpython-313.pyc")
    report = run(repo)
    assert not report["operations"]
    assert report["diagnostic_refs"] == ["REBASE_HEAD"]
    assert candidate_paths(report) == {"__pycache__"}
    (repo / ".git/rebase-merge").mkdir()
    report = run(repo)
    assert "rebase-merge" in report["operations"]
    assert not report["candidates"]


def test_git_output_bound_fails_closed(repo):
    report = run(repo, git_max_bytes=1)
    assert not report["complete"]
    assert any("output bound" in error for error in report["errors"])
    assert not report["candidates"]


def test_git_warning_about_broken_ref_is_incomplete_not_empty_success(repo):
    write(repo, ".git/refs/heads/broken", "not-an-object-id\n")
    report = run(repo)
    assert not report["complete"]
    assert report["errors"]
    assert not report["candidates"]


def test_identity_failure_never_scans_or_emits_remote_credentials(repo, monkeypatch):
    git(repo, "remote", "set-url", "origin", "https://example-token@github.com/Wrong/Repository.git")
    monkeypatch.setattr(crud, "scan_tree", lambda *a, **k: pytest.fail("must not scan wrong repository"))
    report = run(repo)
    assert not report["complete"]
    assert not report["entries"]
    assert "example-token" not in json.dumps(report)


def test_subdirectory_is_not_accepted_as_root(repo):
    (repo / "subdir").mkdir()
    report = run(repo / "subdir")
    assert not report["complete"]
    assert "exact Git" in report["errors"][0]


def test_no_repository_mutation_including_git_index(repo):
    write(repo, "README.md", "dirty tracked change")
    write(repo, "__pycache__/module.cpython-313.pyc")
    before = snapshot(repo)
    report = run(repo)
    assert report["complete"], report["errors"]
    assert snapshot(repo) == before


@pytest.mark.parametrize("driver", ["clean", "process"])
def test_configured_content_filters_are_never_executed(repo, tmp_path, driver):
    write(repo, ".gitattributes", "*.txt filter=tripwire\n")
    tracked = write(repo, "tracked.txt", "original\n")
    git(repo, "add", ".gitattributes", "tracked.txt")
    git(repo, "commit", "-m", "filtered path fixture")
    marker = tmp_path / "filter-executed"
    command = "touch " + shlex.quote(str(marker)) + ("; cat" if driver == "clean" else "; exit 1")
    git(repo, "config", f"filter.tripwire.{driver}", command)
    tracked.write_text("modified\n")
    report = run(repo)
    assert report["complete"], report["errors"]
    assert not marker.exists(), "status must not execute repository-configured filters"


def test_helper_never_opens_application_file_contents(repo, monkeypatch):
    write(repo, "__pycache__/module.cpython-313.pyc")
    def forbid(*args, **kwargs):
        pytest.fail("application content read is outside inventory scope")
    monkeypatch.setattr(Path, "read_text", forbid)
    monkeypatch.setattr(Path, "read_bytes", forbid)
    report = run(repo)
    assert report["complete"], report["errors"]


def test_git_reads_disable_lazy_fetch_and_ignore_inherited_repository_overrides(repo, monkeypatch):
    actual = subprocess.Popen
    seen = []
    def guarded(*args, **kwargs):
        env = kwargs["env"]
        assert env["GIT_NO_LAZY_FETCH"] == "1"
        assert env["GIT_OPTIONAL_LOCKS"] == "0"
        assert "GIT_DIR" not in env
        assert "GIT_INDEX_FILE" not in env
        seen.append(args[0])
        return actual(*args, **kwargs)
    monkeypatch.setenv("GIT_DIR", "/not/the/requested/repository")
    monkeypatch.setenv("GIT_INDEX_FILE", "/not/the/requested/index")
    monkeypatch.setattr(subprocess, "Popen", guarded)
    report = run(repo)
    assert report["complete"], report["errors"]
    assert seen


@pytest.mark.parametrize("target", ["eventTarget", "normalTarget", "perfTarget"])
def test_global_trace_targets_cannot_write_files(repo, tmp_path, monkeypatch, target):
    marker = tmp_path / "git-trace-output"
    config = tmp_path / "global-git-config"
    config.write_text(f'[trace2]\n\t{target} = {marker.as_posix()}\n')
    actual = subprocess.Popen
    def with_fixture_global(*args, **kwargs):
        # Inject only the test Git global config after the helper sanitizes its
        # inherited environment; do not modify HOME or the user's real config.
        kwargs["env"]["GIT_CONFIG_GLOBAL"] = str(config)
        kwargs["env"]["GIT_CONFIG_NOSYSTEM"] = "1"
        return actual(*args, **kwargs)
    monkeypatch.setattr(subprocess, "Popen", with_fixture_global)
    before = snapshot(repo)
    report = run(repo)
    assert report["complete"], report["errors"]
    assert report["provenance"]["origin"] == IDENTITY
    assert not marker.exists(), "read-only inventory must disable configured Git trace writes"
    assert snapshot(repo) == before


def test_worktree_lock_reason_is_private_but_lock_presence_is_retained(repo, tmp_path):
    other = tmp_path / "other-worktree"
    git(repo, "worktree", "add", "-b", "other", str(other))
    private_reason = "synthetic-private-worktree-note"
    git(repo, "worktree", "lock", "--reason", private_reason, str(other))
    report = run(repo)
    assert report["complete"], report["errors"]
    assert private_reason not in json.dumps(report)
    linked = next(row for row in report["worktrees"] if row["worktree"] == str(other))
    assert linked["locked"] is True


def test_prunable_worktree_reason_is_not_emitted(repo, monkeypatch):
    actual = crud.Git.run
    private_reason = b"synthetic-private-pruning-note"
    def worktree_with_reason(self, *args, **kwargs):
        raw = actual(self, *args, **kwargs)
        if args == ("worktree", "list", "--porcelain", "-z"):
            raw = raw[:-1] + b"prunable " + private_reason + b"\0\0"
        return raw
    monkeypatch.setattr(crud.Git, "run", worktree_with_reason)
    report = run(repo)
    assert report["complete"], report["errors"]
    assert private_reason.decode() not in json.dumps(report)
    assert report["worktrees"][0]["prunable"] is True


def test_staged_paths_with_newlines_and_rename_are_metadata_only(repo):
    name = "new\nname with spaces.md"
    git(repo, "mv", "README.md", name)
    report = run(repo)
    assert report["complete"], report["errors"]
    assert {"index_status": "A", "path": name} in report["staged_status"]
    assert {"index_status": "D", "path": "README.md"} in report["staged_status"]
    assert name in rows(report)


def test_operations_suppress_candidates_and_git_metadata_is_read_only(repo, tmp_path):
    write(repo, "README.md", "stash evidence")
    git(repo, "stash", "push", "-m", "private-subject-not-emitted")
    other = tmp_path / "other-worktree"
    git(repo, "worktree", "add", "-b", "other", str(other))
    write(repo, "__pycache__/module.cpython-313.pyc")
    write(repo, ".git/MERGE_HEAD", git(repo, "rev-parse", "HEAD"))
    report = run(repo)
    assert report["complete"], report["errors"]
    assert report["operations"] == ["MERGE_HEAD"]
    assert len(report["stashes"]) == 1
    assert len(report["worktrees"]) == 2
    assert "refs/heads/other" in {row["ref"] for row in report["branches"]}
    assert "private-subject" not in json.dumps(report)
    assert not report["candidates"]


def test_head_change_and_git_failure_are_not_empty_success(repo, monkeypatch):
    actual = crud.Git.text
    calls = []
    def changed(self, *args):
        value = actual(self, *args)
        if args == ("rev-parse", "--verify", "HEAD"):
            calls.append(args)
            return "f" * 40 if len(calls) == 2 else value
        return value
    monkeypatch.setattr(crud.Git, "text", changed)
    report = run(repo)
    assert not report["complete"]
    assert "HEAD changed during inventory" in report["errors"]
    assert not report["candidates"]


def test_cli_json_and_no_apply_mode(repo, capsys):
    assert crud.main(["--repo", str(repo), "--expected-origin", IDENTITY, "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["provenance"]["head"] == git(repo, "rev-parse", "HEAD")
    assert report["provenance"]["origin"] == IDENTITY
    assert report["provenance"]["git_common_dir"] == str(repo / ".git")
    with pytest.raises(SystemExit) as exc:
        crud.main(["--repo", str(repo), "--expected-origin", IDENTITY, "--apply"])
    assert exc.value.code == 2


@pytest.mark.parametrize("raw", [b"missing-terminator", b"R\0"])
def test_truncated_git_path_or_rename_output_is_rejected(raw):
    if raw.startswith(b"R"):
        with pytest.raises(crud.InventoryError):
            crud.status_records(raw)
    else:
        with pytest.raises(crud.InventoryError):
            crud.nul_paths(raw)
