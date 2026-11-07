"""scripts/adhoc/commit_and_push_mech_branch_locked.py commits only on a feature branch (#857, #858).

The repositories are real (a bare origin and a clone under tmp_path). Only the
origin-identity check is replaced, because a local origin can never be the
manifest's GitHub repository; the rest runs as written.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

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
    monkeypatch.setattr(helper, "RepositoryTarget", _AnyOrigin)
    source = tmp_path / "source"
    source.mkdir()
    git(source, "init", "-q")
    (source / "a.txt").write_text("a\n", encoding="utf-8")
    git(source, "add", "a.txt")
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


def test_without_an_absolute_workspace_nothing_is_committed(clone, monkeypatch):
    git(clone["checkout"], "switch", "-q", "-c", "fix/x")
    before = git(clone["checkout"], "rev-parse", "HEAD")
    stage_change(clone["checkout"])
    monkeypatch.setenv("OPENCLAW_WORKSPACE", "workspace")

    with pytest.raises(RuntimeError, match="OPENCLAW_WORKSPACE"):
        run_helper(clone, monkeypatch)

    assert git(clone["checkout"], "rev-parse", "HEAD") == before
