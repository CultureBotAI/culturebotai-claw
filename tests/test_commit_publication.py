"""Recorded batches need current origin evidence, not stale tracking refs (#938)."""
from __future__ import annotations

import json
import subprocess

import pytest

from kg_microbe_workflows.commit_publication import (
    PublicationError,
    recorded_commits,
    verify_origin_publication,
)


def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()


@pytest.fixture
def repository(tmp_path):
    remote, root = tmp_path / "origin.git", tmp_path / "work"
    subprocess.run(["git", "init", "--bare", "--initial-branch=main", str(remote)], check=True, capture_output=True)
    subprocess.run(["git", "clone", str(remote), str(root)], check=True, capture_output=True)
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "config", "user.name", "Offline fixture")
    (root / "record").write_text("base")
    git(root, "add", "record")
    git(root, "commit", "-m", "base")
    git(root, "push", "origin", "main")
    git(root, "checkout", "-b", "batch")
    (root / "record").write_text("batch")
    git(root, "commit", "-am", "batch")
    return root, remote, git(root, "rev-parse", "HEAD")


class Reader:
    """Only local fixture transport is used; assertions forbid any mutation."""
    def __init__(self, root=None):
        self.calls = []
        self.root = root

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        if args[0] == "gh":
            assert args[:4] == ["gh", "api", "--hostname", "github.com"]
            sha, tip = args[4].split("/compare/")[1].split("?")[0].split("...")
            remote = git(self.root, "remote", "get-url", "origin")
            # The simulated server has its own graph, not the local grafts/refs.
            exists = subprocess.run(["git", "-C", remote, "cat-file", "-e", sha], capture_output=True)
            if exists.returncode:
                return subprocess.CompletedProcess(args, 1, "", "not on server")
            ancestor = subprocess.run(["git", "-C", remote, "merge-base", "--is-ancestor", sha, tip], capture_output=True)
            return subprocess.CompletedProcess(args, 0, json.dumps({"base": sha,
                "status": "ahead" if ancestor.returncode == 0 else "diverged",
                "merge_base": sha if ancestor.returncode == 0 else tip}), "")
        self.root = args[2]
        query = args[3:]
        assert query[0] in {"remote", "ls-remote"}
        if query == ["remote", "get-url", "origin"]:
            return subprocess.CompletedProcess(args, 0, "https://github.com/CultureBotAI/TraitMech.git\n", "")
        return subprocess.run(args, capture_output=True, text=True, **kwargs)


def verify(root, sha, **kwargs):
    return verify_origin_publication([sha], [root], "CultureBotAI/TraitMech", runner=Reader(), **kwargs)


def test_local_only_batch_is_rejected_and_pushed_batch_is_accepted(repository):
    root, _, sha = repository
    with pytest.raises(PublicationError, match="lack current origin"):
        verify(root, sha)
    git(root, "push", "origin", "batch")
    assert verify(root, sha)["proofs"][sha]["method"] == "current_origin_branch_tip"


def test_stale_or_forged_remote_tracking_ref_cannot_prove_publication(repository):
    root, _, sha = repository
    git(root, "update-ref", "refs/remotes/origin/batch", sha)
    assert git(root, "for-each-ref", "--contains", sha, "refs/remotes/origin")
    with pytest.raises(PublicationError, match="lack current origin"):
        verify(root, sha)


def test_deleted_remote_branch_does_not_remain_publication_evidence(repository):
    root, remote, sha = repository
    git(root, "push", "origin", "batch")
    git(remote, "update-ref", "-d", "refs/heads/batch")
    assert git(root, "rev-parse", "refs/remotes/origin/batch") == sha
    with pytest.raises(PublicationError, match="lack current origin"):
        verify(root, sha)


def test_commit_on_origin_branch_ancestry_is_valid_without_fetch(repository):
    root, _, sha = repository
    (root / "record").write_text("later batch")
    git(root, "commit", "-am", "later")
    git(root, "push", "origin", "batch")
    reader = Reader()
    proof = verify_origin_publication([sha], [root], "CultureBotAI/TraitMech", runner=reader)
    assert proof["proofs"][sha]["method"] == "current_origin_branch_ancestor"
    assert not any("fetch" in args or "push" in args for args in reader.calls)


def test_verified_merged_pr_preserves_squashed_source_commits_without_live_refs():
    sha = "a" * 40
    def forbidden(*args, **kwargs):
        pytest.fail("merged-PR proof must not require deleted branch refs")
    assert verify_origin_publication([sha], [], "CultureBotAI/TraitMech",
        verified_merged_pr_commits=[sha], runner=forbidden)["complete"]


@pytest.mark.parametrize("response", [
    subprocess.CompletedProcess([], 1, "", "private credential-bearing failure"),
    subprocess.CompletedProcess([], 0, "", ""),
    subprocess.CompletedProcess([], 0, "broken response", ""),
])
def test_unknown_origin_measurement_never_authorizes_closure(repository, response):
    root, _, sha = repository
    reader = Reader()
    def unavailable(args, **kwargs):
        return response if args[3] == "ls-remote" else reader(args, **kwargs)
    with pytest.raises(PublicationError) as error:
        verify_origin_publication([sha], [root], "CultureBotAI/TraitMech", runner=unavailable)
    assert "credential" not in str(error.value)


def test_origin_identity_mismatch_and_exhausted_budget_hold(repository):
    root, _, sha = repository
    with pytest.raises(PublicationError, match="identity"):
        verify_origin_publication([sha], [root], "CultureBotAI/DUFMech", runner=Reader())
    with pytest.raises(PublicationError, match="budget"):
        verify(root, sha, max_queries=0)


@pytest.mark.parametrize("value", [None, "a" * 40, ["a"], [True], ["a" * 40, "a" * 40]])
def test_recorded_commit_inventory_is_explicit_unique_and_full_length(value):
    with pytest.raises(PublicationError):
        recorded_commits(value)


def test_reviewed_head_cannot_be_omitted():
    with pytest.raises(PublicationError, match="reviewed PR head"):
        recorded_commits(["b" * 40], head="a" * 40)


def test_local_graft_cannot_turn_unpublished_work_into_origin_ancestry(repository):
    root, _, sha = repository
    base = git(root, "rev-parse", "main")
    # Re-parent the local base to the unpushed batch. A local merge-base query
    # now lies; the synthetic origin still has its independent original graph.
    git(root, "replace", "--graft", base, sha)
    assert subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor", sha, base]).returncode == 0
    with pytest.raises(PublicationError, match="lack current origin"):
        verify(root, sha)


@pytest.mark.parametrize("payload", ["not json", "[]", '{"base": "wrong"}'])
def test_malformed_server_comparison_holds(repository, payload):
    root, _, sha = repository
    reader = Reader()
    def broken(args, **kwargs):
        return subprocess.CompletedProcess(args, 0, payload, "") if args[0] == "gh" else reader(args, **kwargs)
    with pytest.raises(PublicationError):
        verify_origin_publication([sha], [root], "CultureBotAI/TraitMech", runner=broken)
