"""scripts/adhoc/commit_and_push_mech_branch_locked.py commits only on a feature branch (#857, #858, #868, #871, #876-#878).

The repositories are real (a bare origin and a clone under tmp_path). The
origin-identity check is replaced in every test but one, because a local
origin can never be the manifest's GitHub repository; that one runs the real
check and expects it to refuse.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

from plugins.lock_manager import LockManager
from plugins.repository_settings import RepositoryTarget

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/adhoc/commit_and_push_mech_branch_locked.py"
SPEC = importlib.util.spec_from_file_location("commit_and_push_mech_branch_locked", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
helper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(helper)


def git(path: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(path), *args], text=True, capture_output=True,
                          check=True).stdout.strip()


class _AnyOrigin:
    def __init__(self, **kwargs):
        pass

    def open(self):
        return None


@pytest.fixture
def clone(tmp_path, monkeypatch):
    config = tmp_path / "gitconfig"
    config.write_text("[user]\n\tname = test\n\temail = test\n[init]\n\tdefaultBranch = main\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("OPENCLAW_ORCHESTRATION_ROOT", str(tmp_path))
    monkeypatch.setattr(helper, "RepositoryTarget", _AnyOrigin)
    source = tmp_path / "source"
    source.mkdir()
    git(source, "init", "-q")
    (source / "a.txt").write_text("a\n", encoding="utf-8")
    (source / "b.txt").write_text("b\n", encoding="utf-8")
    git(source, "add", "a.txt", "b.txt")
    git(source, "commit", "-q", "-m", "initial")
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(source), str(origin)], check=True)
    checkout = tmp_path / "checkout"
    subprocess.run(["git", "clone", "-q", str(origin), str(checkout)], check=True)
    message = tmp_path / "message.txt"
    message.write_text("Review fix\n", encoding="utf-8")
    return {"origin": origin, "checkout": checkout, "message": message}


def stage_change(checkout: Path) -> None:
    (checkout / "a.txt").write_text("changed\n", encoding="utf-8")
    git(checkout, "add", "a.txt")


def run_helper(clone, monkeypatch) -> int:
    monkeypatch.setattr(sys, "argv", ["commit_and_push_mech_branch_locked.py", "--mech", "traitmech",
                                      "--worktree", str(clone["checkout"]), "--message-file", str(clone["message"])])
    return helper.main()


def remote_heads(origin: Path) -> set[str]:
    return {line.split()[1] for line in git(origin, "show-ref", "--heads").split("\n") if line}


def test_a_feature_branch_is_committed_and_pushed(clone, monkeypatch):
    git(clone["checkout"], "switch", "-q", "-c", "fix/x")
    stage_change(clone["checkout"])

    assert run_helper(clone, monkeypatch) == 0

    head = git(clone["checkout"], "rev-parse", "HEAD")
    assert git(clone["origin"], "rev-parse", "refs/heads/fix/x") == head


def test_main_is_refused_and_nothing_is_committed(clone, monkeypatch):
    before = git(clone["checkout"], "rev-parse", "HEAD")
    stage_change(clone["checkout"])

    with pytest.raises(RuntimeError, match="default branch"):
        run_helper(clone, monkeypatch)

    assert git(clone["checkout"], "rev-parse", "HEAD") == before
    assert git(clone["origin"], "rev-parse", "refs/heads/main") == before
    assert git(clone["checkout"], "status", "--porcelain") == "M  a.txt"


def test_a_default_branch_named_by_origin_head_is_refused(clone, monkeypatch):
    git(clone["checkout"], "switch", "-q", "-c", "trunk")
    git(clone["checkout"], "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/trunk")
    before = git(clone["checkout"], "rev-parse", "HEAD")
    stage_change(clone["checkout"])

    with pytest.raises(RuntimeError, match="trunk is the default branch"):
        run_helper(clone, monkeypatch)

    assert git(clone["checkout"], "rev-parse", "HEAD") == before


def test_main_is_refused_even_when_origin_names_no_default(clone, monkeypatch):
    git(clone["checkout"], "remote", "set-head", "origin", "-d")
    before = git(clone["checkout"], "rev-parse", "HEAD")
    stage_change(clone["checkout"])

    with pytest.raises(RuntimeError, match="main is the default branch"):
        run_helper(clone, monkeypatch)

    assert git(clone["checkout"], "rev-parse", "HEAD") == before


def test_a_tag_named_like_the_default_branch_cannot_disguise_it(clone, monkeypatch):
    git(clone["checkout"], "tag", "main")
    before = git(clone["checkout"], "rev-parse", "HEAD")
    stage_change(clone["checkout"])

    with pytest.raises(RuntimeError, match="main is the default branch"):
        run_helper(clone, monkeypatch)

    assert git(clone["checkout"], "rev-parse", "HEAD") == before
    assert remote_heads(clone["origin"]) == {"refs/heads/main"}


def test_a_tag_named_like_the_feature_branch_still_pushes_to_the_branch(clone, monkeypatch):
    git(clone["checkout"], "switch", "-q", "-c", "fix/x")
    git(clone["checkout"], "tag", "fix/x")
    stage_change(clone["checkout"])

    assert run_helper(clone, monkeypatch) == 0

    head = git(clone["checkout"], "rev-parse", "refs/heads/fix/x")
    assert git(clone["origin"], "rev-parse", "refs/heads/fix/x") == head
    assert remote_heads(clone["origin"]) == {"refs/heads/main", "refs/heads/fix/x"}


def test_a_detached_head_is_refused(clone, monkeypatch):
    git(clone["checkout"], "checkout", "-q", "--detach")
    before = git(clone["checkout"], "rev-parse", "HEAD")
    stage_change(clone["checkout"])

    with pytest.raises(RuntimeError, match="detached HEAD"):
        run_helper(clone, monkeypatch)

    assert git(clone["checkout"], "rev-parse", "HEAD") == before


@pytest.mark.parametrize("extra", ["unstaged", "untracked"])
def test_unstaged_or_untracked_work_beside_the_staged_change_is_refused(clone, monkeypatch, extra):
    git(clone["checkout"], "switch", "-q", "-c", "fix/x")
    before = git(clone["checkout"], "rev-parse", "HEAD")
    stage_change(clone["checkout"])
    if extra == "unstaged":
        (clone["checkout"] / "a.txt").write_text("changed again\n", encoding="utf-8")
    else:
        (clone["checkout"] / "new.txt").write_text("new\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="nothing unstaged or untracked"):
        run_helper(clone, monkeypatch)

    assert git(clone["checkout"], "rev-parse", "HEAD") == before


def test_a_status_setting_cannot_hide_an_untracked_file(clone, monkeypatch):
    git(clone["checkout"], "switch", "-q", "-c", "fix/x")
    git(clone["checkout"], "config", "status.showUntrackedFiles", "no")
    before = git(clone["checkout"], "rev-parse", "HEAD")
    stage_change(clone["checkout"])
    (clone["checkout"] / "new_module.py").write_text("x = 1\n", encoding="utf-8")
    assert git(clone["checkout"], "status", "--porcelain") == "M  a.txt"

    with pytest.raises(RuntimeError, match="nothing unstaged or untracked"):
        run_helper(clone, monkeypatch)

    assert git(clone["checkout"], "rev-parse", "HEAD") == before


@pytest.mark.parametrize("flag", ["--skip-worktree", "--assume-unchanged"])
def test_an_edit_hidden_from_status_is_refused(clone, monkeypatch, flag):
    git(clone["checkout"], "switch", "-q", "-c", "fix/x")
    git(clone["checkout"], "update-index", flag, "b.txt")
    (clone["checkout"] / "b.txt").write_text("hidden edit\n", encoding="utf-8")
    before = git(clone["checkout"], "rev-parse", "HEAD")
    stage_change(clone["checkout"])
    assert git(clone["checkout"], "status", "--porcelain") == "M  a.txt"

    with pytest.raises(RuntimeError, match="skip-worktree or assume-unchanged"):
        run_helper(clone, monkeypatch)

    assert git(clone["checkout"], "rev-parse", "HEAD") == before


def test_a_held_lock_on_the_mech_stops_the_commit(clone, monkeypatch):
    git(clone["checkout"], "switch", "-q", "-c", "fix/x")
    before = git(clone["checkout"], "rev-parse", "HEAD")
    stage_change(clone["checkout"])

    with LockManager().lock("traitmech", "held-by-test"):
        with pytest.raises(RuntimeError, match="Failed to acquire lock on traitmech"):
            run_helper(clone, monkeypatch)

    assert git(clone["checkout"], "rev-parse", "HEAD") == before


def test_the_real_origin_check_refuses_an_origin_that_is_not_the_mech(clone, monkeypatch):
    monkeypatch.setattr(helper, "RepositoryTarget", RepositoryTarget)
    git(clone["checkout"], "switch", "-q", "-c", "fix/x")
    before = git(clone["checkout"], "rev-parse", "HEAD")
    stage_change(clone["checkout"])

    with pytest.raises(Exception, match="origin identity mismatch"):
        run_helper(clone, monkeypatch)

    assert git(clone["checkout"], "rev-parse", "HEAD") == before
    assert remote_heads(clone["origin"]) == {"refs/heads/main"}


def test_a_relative_message_file_is_read_from_the_current_directory(clone, monkeypatch):
    git(clone["checkout"], "switch", "-q", "-c", "fix/x")
    stage_change(clone["checkout"])
    monkeypatch.chdir(clone["message"].parent)
    monkeypatch.setattr(sys, "argv", ["commit_and_push_mech_branch_locked.py", "--mech", "traitmech",
                                      "--worktree", str(clone["checkout"]), "--message-file", clone["message"].name])

    assert helper.main() == 0
    assert git(clone["checkout"], "log", "-1", "--format=%s") == "Review fix"


def test_without_an_absolute_workspace_nothing_is_committed(clone, monkeypatch):
    git(clone["checkout"], "switch", "-q", "-c", "fix/x")
    before = git(clone["checkout"], "rev-parse", "HEAD")
    stage_change(clone["checkout"])
    monkeypatch.setenv("OPENCLAW_WORKSPACE", "workspace")

    with pytest.raises(RuntimeError, match="OPENCLAW_WORKSPACE"):
        run_helper(clone, monkeypatch)

    assert git(clone["checkout"], "rev-parse", "HEAD") == before
