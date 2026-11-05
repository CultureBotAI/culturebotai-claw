"""Exercise cleanup commands against local Git refs without changing evidence files."""

import argparse
import importlib.util
import json
import shutil
from pathlib import Path

import pytest

GIT = shutil.which("git")
SCRIPT = Path(__file__).resolve().parents[1] / "scripts/adhoc/edge_curation_metadata.py"
SPEC = importlib.util.spec_from_file_location("edge_curation_metadata", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
metadata = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(metadata)
pytestmark = pytest.mark.skipif(GIT is None, reason="Offline Git fixtures require git")
BRANCH = metadata.TARGETS["claw"][2]


def git(root, *arguments, allow=(0,)):
    return metadata.run([GIT, "-C", str(root), *arguments], allow=allow, timeout=10)


def initialize(root):
    metadata.run([GIT, "init", "--quiet", "--initial-branch=main", str(root)], timeout=10)
    for key, value in (
        ("user.name", "Offline fixture"), ("user.email", "fixture@example.invalid"),
        ("commit.gpgsign", "false"), ("core.hooksPath", "/dev/null"), ("core.autocrlf", "false"),
    ):
        git(root, "config", "--local", key, value)
    (root / "tracked.txt").write_bytes(b"tracked original\n")
    (root / ".gitignore").write_text("ignored.txt\n")
    git(root, "add", "tracked.txt", ".gitignore")
    git(root, "commit", "--quiet", "-m", "Initial fixture")


def arguments(root, operation, head=None):
    return argparse.Namespace(target="claw", repository=root, operation=operation, head=head)


def test_default_ref_fetch_does_not_follow_tags(tmp_path):
    """Issue #812: an explicit branch refspec must not import a reachable release tag."""
    remote = tmp_path / "local-remote"
    initialize(remote)
    checkout = tmp_path / "checkout"
    metadata.run([GIT, "clone", "--quiet", str(remote), str(checkout)], timeout=10)
    before = git(checkout, "rev-parse", "refs/remotes/origin/main")
    (remote / "tracked.txt").write_bytes(b"new default-branch bytes\n")
    git(remote, "commit", "--quiet", "-am", "Advance main")
    git(remote, "tag", "unrelated-release-tag")
    expected = git(remote, "rev-parse", "HEAD")
    assert expected != before

    command = metadata.command_for(arguments(checkout, "fetch"), GIT)
    metadata.run(command, timeout=10)
    assert git(checkout, "rev-parse", "refs/remotes/origin/main") == expected
    assert git(checkout, "tag", "--list", "unrelated-release-tag") == ""
    assert (checkout / "tracked.txt").read_bytes() == b"tracked original\n"


@pytest.fixture
def merged_candidate(tmp_path, monkeypatch):
    root = tmp_path / "candidate"
    initialize(root)
    base = git(root, "rev-parse", "HEAD")
    git(root, "switch", "--quiet", "-c", BRANCH)
    (root / "tracked.txt").write_bytes(b"reviewed feature bytes\n")
    git(root, "commit", "--quiet", "-am", "Reviewed feature")
    head = git(root, "rev-parse", "HEAD")
    tree = git(root, "rev-parse", "HEAD^{tree}")
    merge = git(root, "commit-tree", tree, "-p", base, "-p", head, "-m", "Fixture merge")
    git(root, "update-ref", "refs/remotes/origin/main", merge)
    (root / "untracked.txt").write_bytes(b"untracked evidence\x00\n")
    (root / "ignored.txt").write_bytes(b"ignored evidence\xff\n")
    before = {path.name: path.read_bytes() for path in root.iterdir() if path.is_file()}
    pr = {
        "state": "MERGED", "baseRefName": "main", "headRefName": BRANCH,
        "headRefOid": head, "headRepository": {"nameWithOwner": "CultureBotAI/culturebotai-claw"},
        "mergeCommit": {"oid": merge},
    }
    real_run, real_which = metadata.run, metadata.shutil.which

    def local_run(command, **kwargs):
        if command[0] == "offline-gh":
            assert command[1:4] == ["pr", "view", "762"]
            return json.dumps(pr)
        return real_run(command, **kwargs)

    monkeypatch.setattr(metadata, "run", local_run)
    monkeypatch.setattr(metadata.shutil, "which", lambda name: "offline-gh" if name == "gh" else real_which(name))
    return root, head, before


def test_same_head_detach_and_exact_branch_delete_preserve_all_evidence(merged_candidate):
    root, head, before = merged_candidate
    detach = metadata.command_for(arguments(root, "detach", head), GIT)
    metadata.run(detach, timeout=10)
    assert git(root, "symbolic-ref", "-q", "HEAD", allow=(1,)) == ""
    assert git(root, "rev-parse", "HEAD") == head
    delete = metadata.command_for(arguments(root, "delete", head), GIT)
    metadata.run(delete, timeout=10)
    assert git(root, "show-ref", "--verify", "--quiet", f"refs/heads/{BRANCH}", allow=(1,)) == ""
    assert git(root, "rev-parse", "HEAD") == head
    git(root, "merge-base", "--is-ancestor", head, "HEAD")
    assert {path.name: path.read_bytes() for path in root.iterdir() if path.is_file()} == before


@pytest.mark.parametrize("operation", ["detach", "delete"])
def test_branch_advance_after_plan_is_refused_by_old_sha_cas(merged_candidate, operation):
    root, head, before = merged_candidate
    if operation == "delete":
        metadata.run(metadata.command_for(arguments(root, "detach", head), GIT), timeout=10)
    command = metadata.command_for(arguments(root, operation, head), GIT)
    advanced = git(root, "commit-tree", "HEAD^{tree}", "-p", head, "-m", "Concurrent advance")
    git(root, "update-ref", f"refs/heads/{BRANCH}", advanced, head)
    with pytest.raises(RuntimeError, match="Command failed"):
        metadata.run(command, timeout=10)
    assert git(root, "rev-parse", f"refs/heads/{BRANCH}") == advanced
    if operation == "detach":
        assert git(root, "symbolic-ref", "HEAD") == f"refs/heads/{BRANCH}"
        assert git(root, "rev-parse", "HEAD") == advanced
    else:
        assert git(root, "symbolic-ref", "-q", "HEAD", allow=(1,)) == ""
        assert git(root, "rev-parse", "HEAD") == head
    assert {path.name: path.read_bytes() for path in root.iterdir() if path.is_file()} == before
