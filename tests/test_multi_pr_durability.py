"""Publication must compose with, never weaken, ordered closure proof (#938/#978)."""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest
from test_multi_pr_receipts import (  # noqa: F401 -- shared pytest fixtures
    EARLY_FIX,
    FIRST,
    LAST,
    cycle_setup,
    duf,
    setup,
    supervisor,
    verify,
    write_registry,
)

from kg_microbe_progress import prs
from kg_microbe_workflows.commit_publication import PublicationError

EXTRA = "f" * 40


def declared_batches(state):
    """The first squash's source/fix commits are absent from the last PR."""
    commits = [EARLY_FIX, FIRST["head_sha"], LAST["head_sha"]]
    assert not set(commits[:-1]) & {item["sha"] for item in state.remote.commits[367]}
    state.receipt["deliverable_commits"] = commits
    return commits


class PublicationRemote:
    """Keep all ordered proof reads real; simulate only fresh origin transport."""

    def __init__(self, ordered, *, published=False):
        self.ordered = ordered
        self.published = published
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append((args, kwargs))
        if args[0] == "git" and args[3:] == ["ls-remote", "--heads", "origin"]:
            output = LAST["merge_commit_sha"] + "\trefs/heads/main\n"
            if self.published:
                output += EXTRA + "\trefs/heads/pushed-batch\n"
            return SimpleNamespace(returncode=0, stdout=output, stderr="")
        if args[:4] == ["gh", "api", "--hostname", "github.com"] and "/compare/" in args[4]:
            return SimpleNamespace(returncode=1, stdout="", stderr="unknown comparison")
        return self.ordered(args, **kwargs)


def test_all_verified_squash_members_prove_declared_batches_after_branch_deletion(duf):  # noqa: F811
    expected = declared_batches(duf)
    proof = verify(duf)["commit_publication"]
    assert proof["complete"] and proof["commits"] == expected
    assert proof["proofs"] == {sha: {"method": "verified_merged_pr"} for sha in expected}
    # Branch-deletion checks still run for every member, although none of the
    # source commits need be an ancestor of the squash merge on main.
    for member in (FIRST, LAST):
        branch = "refs/heads/" + member["branch"]
        assert any(args[0] == "git" and "ls-remote" in args and args[-1] == branch
                   for args in duf.remote.calls)
        assert any(args[0] == "git" and "show-ref" in args and args[-1] == branch
                   for args in duf.remote.calls)
    assert not any(args[0] == "git" and args[3:] == ["ls-remote", "--heads", "origin"]
                   for args in duf.remote.calls)


def test_extra_local_only_batch_is_not_covered_by_merged_members(duf):  # noqa: F811
    declared_batches(duf)
    assert EXTRA not in {item["sha"] for commits in duf.remote.commits.values() for item in commits}
    duf.receipt["deliverable_commits"].append(EXTRA)
    duf.remote = PublicationRemote(duf.remote)
    with pytest.raises(PublicationError, match="1 recorded deliverable commits lack current origin"):
        verify(duf)
    assert any("/compare/" in " ".join(args) for args, _ in duf.remote.calls)


def test_extra_batch_uses_fresh_origin_with_its_tighter_query_timeout(duf):  # noqa: F811
    declared_batches(duf)
    duf.receipt["deliverable_commits"].append(EXTRA)
    duf.remote = PublicationRemote(duf.remote, published=True)
    proof = verify(duf)["commit_publication"]
    assert proof["proofs"][EXTRA] == {"method": "current_origin_branch_tip", "tip": EXTRA}
    inventory = [(args, kwargs) for args, kwargs in duf.remote.calls
                 if args[0] == "git" and args[3:] == ["ls-remote", "--heads", "origin"]]
    assert len(inventory) == 1
    assert 0 < inventory[0][1]["timeout"] <= 5


@pytest.mark.parametrize("defect,message", [
    ("unmerged", "not actually merged"),
    ("failed_checks", "CI evidence"),
    ("truncated_commits", "inventory"),
    ("missing_association", "current goal registry association"),
    ("unproduced_evidence", "not produced"),
    ("lost_fix", "earlier reviewed fix"),
])
def test_ordered_gates_finish_before_publication_authority(duf, monkeypatch, defect, message):  # noqa: F811
    declared_batches(duf)
    if defect == "unmerged":
        duf.remote.prs[365]["merged"] = False
    elif defect == "failed_checks":
        duf.remote.checks[365][0]["bucket"] = "fail"
    elif defect == "truncated_commits":
        duf.remote.prs[365]["commits"] += 1
    elif defect == "missing_association":
        path = duf.session / prs.REGISTRY_NAME
        write_registry(duf, [json.loads(line) for line in path.read_text().splitlines()][:1])
    elif defect == "unproduced_evidence":
        duf.remote.raw_changes[LAST["head_sha"]] = ""
    elif defect == "lost_fix":
        duf.remote.trees[LAST["head_sha"]]["src/fixed.py"] = "d" * 40

    def forbidden_publication(*args, **kwargs):
        pytest.fail("Publication authority was considered before ordered gates completed")

    monkeypatch.setattr(supervisor, "verify_receipt_publication", forbidden_publication)
    with pytest.raises(supervisor.SupervisorError, match=message):
        verify(duf)


def test_legacy_ordered_receipt_remains_compatible_without_new_policy(duf):  # noqa: F811
    assert "deliverable_commits" not in duf.receipt
    assert not duf.ledger["workflow"]["effective"].get("session_state_policy")
    assert supervisor.validate_receipt(duf.receipt, duf.ledger, duf.target, duf.session) == []
    proof = verify(duf)
    assert [item["pr_number"] for item in proof["prs"]] == [365, 367]
    assert proof["commit_publication"]["commits"] == [LAST["head_sha"]]


def test_new_policy_requires_explicit_batch_inventory_for_ordered_receipt(duf):  # noqa: F811
    duf.ledger["workflow"]["effective"]["session_state_policy"] = {
        "require_origin_publication_at_closure": True,
    }
    errors = supervisor.validate_receipt(duf.receipt, duf.ledger, duf.target, duf.session)
    assert any("deliverable_commits" in error for error in errors)
    declared_batches(duf)
    assert supervisor.validate_receipt(duf.receipt, duf.ledger, duf.target, duf.session) == []
