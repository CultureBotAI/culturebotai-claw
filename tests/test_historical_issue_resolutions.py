"""Carry-forward proofs use earlier closures, never false current-PR attribution."""
from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import pytest
from test_mech_session_supervisor import (  # noqa: F401 -- shared pytest fixtures
    FIX,
    HEAD,
    CycleGitHubFixture,
    cycle_setup,
    setup,
    supervisor,
    write_goal_evidence,
)

from kg_microbe_workflows import evidence_directory

PRIOR_HEAD, PRIOR_FIX, PRIOR_MERGE, CURRENT_BASE = (digit * 40 for digit in "4567")
PRIOR_RECEIPT = "d" * 64


class HistoricalRemote(CycleGitHubFixture):
    """Every network/Git command is enumerated; no live calls or writes."""
    def __init__(self, state):
        super().__init__(state.repo)
        self.state = state
        github = state.target["github_repository"]
        self.pr["base"].update(sha=CURRENT_BASE, repo={"full_name": github})
        self.pr["head"]["repo"] = {"full_name": github}
        self.pr["merged_at"] = "2026-11-04T15:13:49Z"
        self.prior = {"merged": True, "merged_at": "2026-10-31T10:44:27Z", "commits": 2,
                      "base": {"ref": "main", "repo": {"full_name": github}},
                      "head": {"sha": PRIOR_HEAD, "repo": {"full_name": github}},
                      "merge_commit_sha": PRIOR_MERGE}
        self.prior_commits = [{"sha": PRIOR_HEAD}, {"sha": PRIOR_FIX}]
        self.historical_issue = {"number": 1217, "state": "closed",
                                 "html_url": f"https://github.com/{github}/issues/1217"}
        self.failed_ancestry = set()
        self.snapshot()

    def __call__(self, args, **kwargs):
        github = self.state.target["github_repository"]
        if args[:4] == ["git", "-C", str(self.root), "remote"]:
            self.calls.append(args)
            return SimpleNamespace(stdout=f"https://github.com/{github}.git\n", returncode=0)
        if args[:4] == ["git", "-C", str(self.root), "merge-base"] and args[-2] == PRIOR_MERGE:
            self.calls.append(args)
            return SimpleNamespace(stdout="", returncode=int(args[-1] in self.failed_ancestry))
        if args[:2] == ["gh", "api"]:
            self.calls.append(args)
            endpoint = args[-1]
            if endpoint == f"repos/{github}/pulls/1218":
                out = json.dumps(self.prior)
            elif endpoint == f"repos/{github}/pulls/1218/commits?per_page=100&page=1":
                assert "--include" in args
                out = "HTTP/2.0 200 OK\n\n" + json.dumps(self.prior_commits)
            elif endpoint == f"repos/{github}/issues/1217":
                out = json.dumps(self.historical_issue)
            elif endpoint == f"repos/{github}/pulls/1232":
                out = json.dumps(self.pr)
            elif endpoint == f"repos/{github}/pulls/1232/commits?per_page=100":
                out = json.dumps(self.commits)
            elif endpoint == f"repos/{github}/issues/1230":
                out = json.dumps(self.issue)
            else:
                raise AssertionError(args)
            return SimpleNamespace(stdout=out, returncode=0)
        return super().__call__(args, **kwargs)


@pytest.fixture(params=[("proteintraitsmech", "proteintraitsmech", 5), ("taxonmech", "TaxonMech", 4)])
def carry_forward(cycle_setup, request):  # noqa: F811 -- pytest fixture injection
    state = cycle_setup
    key, slug, cycle = request.param
    state.target.update(repository_key=key, github_repository=f"CultureBotAI/{slug}")
    state.ledger.update(repository_key=key, cycle=cycle-1, stage=4)
    state.receipt.update(repository_key=key, pr={"number": 1232, "branch": "curation/current", "base": "main", "head_sha": HEAD})
    url = f"https://github.com/{state.target['github_repository']}/issues/1217"
    finding = {"finding_id": "F25", "summary": "Same stable source-definition finding", "status": "resolved",
               "group_id": "G5", "issue_url": url, "disposition": "Previously repaired and re-reviewed"}

    def retain(receipt, **extra):
        descriptor = receipt["goal_outputs"]["goal_evidence"]
        data = json.loads((state.repo / descriptor["path"]).read_text())
        record = {"cycle": state.ledger["cycle"], "stage": state.ledger["stage"], "completion_authority": "native_completed",
                  "goal_evidence": descriptor, "goal_evidence_snapshot": data, **extra}
        state.ledger["completed_stages"].append(record)
        return record

    for earlier_cycle in range(1, cycle - 1):
        state.ledger.update(cycle=earlier_cycle, stage=4)
        retain(write_goal_evidence(state, state.ledger))
        state.ledger["stage"] = 5
        retain(write_goal_evidence(state, state.ledger))
    state.ledger.update(cycle=cycle-1, stage=4)
    prior_review = write_goal_evidence(state, state.ledger, findings=[finding])
    retain(prior_review)
    state.ledger["stage"] = 5
    prior_group = {"group_id": "G5", "finding_ids": ["F25"], "summary": "Previously resolved group",
                   "status": "resolved", "issue_url": url, "disposition": "Confirmed fixed",
                   "resolution_evidence": [evidence_directory(state.ledger["run_id"], cycle-1, 5, 1)+"/validation.md"]}
    prior = write_goal_evidence(state, state.ledger, findings=[finding], groups=[prior_group])
    verification = {"status": "merged", "pr_number": 1218, "head_sha": PRIOR_HEAD,
                    "merge_commit_sha": PRIOR_MERGE, "merged_at": "2026-10-31T10:44:27Z"}
    state.prior_record = retain(prior, receipt_sha256=PRIOR_RECEIPT, verification=verification)
    state.ledger.update(cycle=cycle, stage=4)
    new_finding = {"finding_id": "F31", "summary": "A new finding", "status": "open"}
    reviewed = write_goal_evidence(state, state.ledger, findings=[finding, new_finding])
    state.previous_record = retain(reviewed)
    state.ledger["stage"] = 5
    group = copy.deepcopy(prior_group)
    group["resolution_evidence"] = [evidence_directory(state.ledger["run_id"], cycle, 5, 1)+"/validation.md"]
    current_url = f"https://github.com/{state.target['github_repository']}/issues/1230"
    new_group = {**group, "group_id": "G6", "finding_ids": ["F31"], "issue_url": current_url}
    resolved = {**new_finding, "status": "resolved", "carried_from": "F31", "group_id": "G6",
                "issue_url": current_url, "disposition": "Repaired in current PR"}
    state.receipt = write_goal_evidence(state, state.ledger, findings=[finding, resolved], groups=[group, new_group])
    historical = {"github_repository": state.target["github_repository"], "pr_number": 1218, "base": "main",
                  "head_sha": PRIOR_HEAD, "merge_commit_sha": PRIOR_MERGE, "receipt_sha256": PRIOR_RECEIPT}
    state.receipt["issues"] = [{"number": 1217, "disposition": "addressed", "fix_commit_sha": PRIOR_FIX,
                                "historical_resolution": historical},
                               {"number": 1230, "disposition": "addressed", "fix_commit_sha": FIX}]
    state.remote = HistoricalRemote(state)
    return state


def test_prior_cycle_issue_is_carried_without_attributing_it_to_current_pr(carry_forward):
    state = carry_forward
    assert supervisor.validate_receipt(state.receipt, state.ledger, state.target, state.runtime) == []
    prior = copy.deepcopy(state.ledger["completed_stages"])
    proof = supervisor.verify_remote_receipt(state.receipt, state.ledger, state.target, state.remote)
    assert proof["pr_number"] == 1232
    assert proof["historical_issue_resolutions"][0]["pr_number"] == 1218
    assert proof["historical_issue_resolutions"][0]["fix_commit_sha"] == PRIOR_FIX
    assert state.ledger["completed_stages"] == prior
    assert PRIOR_FIX not in {item["sha"] for item in state.remote.commits[0]}
    assert {args[-1] for args in state.remote.calls if args[:4] == ["git", "-C", str(state.repo), "merge-base"]} >= {HEAD, CURRENT_BASE, "HEAD"}


@pytest.mark.parametrize("mutation", [
    lambda s: s.receipt["issues"][0]["historical_resolution"].update(fix_commit_sha=PRIOR_FIX),
    lambda s: s.receipt["issues"][0]["historical_resolution"].update(pr_number=1232),
    lambda s: s.receipt["issues"][0]["historical_resolution"].update(github_repository="Other/Repo"),
    lambda s: s.receipt["issues"][0]["historical_resolution"].update(base="other"),
    lambda s: s.receipt["issues"][0]["historical_resolution"].update(receipt_sha256="e"*64),
    lambda s: s.ledger["completed_stages"].append(copy.deepcopy(s.prior_record)),
    lambda s: s.prior_record.update(cycle=s.ledger["cycle"]),
    lambda s: s.prior_record.update(stage=4),
    lambda s: s.prior_record.update(completion_authority="unverified"),
    lambda s: s.prior_record["verification"].update(status="open"),
    lambda s: s.prior_record["verification"].update(head_sha="e"*40),
    lambda s: s.receipt.update(prs=[]),
])
def test_historical_descriptor_never_relaxes_ordinary_context(carry_forward, mutation):
    mutation(carry_forward)
    assert supervisor.validate_receipt(carry_forward.receipt, carry_forward.ledger, carry_forward.target, carry_forward.runtime)


@pytest.mark.parametrize("mutation", [
    lambda s: s.prior_record["goal_evidence_snapshot"]["groups"][0].update(status="deferred"),
    lambda s: (s.repo/s.prior_record["goal_evidence"]["path"]).write_text("{}"),
    lambda s: s.previous_record["goal_evidence_snapshot"]["findings"][0].update(status="open"),
])
def test_prior_evidence_or_resolved_scope_cannot_be_rewritten(carry_forward, mutation):
    mutation(carry_forward)
    assert supervisor.validate_receipt(carry_forward.receipt, carry_forward.ledger, carry_forward.target, carry_forward.runtime)


@pytest.mark.parametrize("mutation,match", [
    (lambda s: s.receipt["issues"][0].update(fix_commit_sha="e"*40), "commit inventory"),
    (lambda s: s.remote.historical_issue.update(state="open"), "actually closed"),
    (lambda s: s.remote.historical_issue.update(pull_request={}), "actually closed"),
    (lambda s: s.remote.historical_issue.update(number=999), "actually closed"),
    (lambda s: s.remote.prior.update(merged=False), "pinned verified merge"),
    (lambda s: s.remote.prior.update(merge_commit_sha="e"*40), "pinned verified merge"),
    (lambda s: s.remote.prior["head"].update(sha="e"*40), "pinned verified merge"),
    (lambda s: s.remote.prior.update(commits=251), "commit inventory"),
    (lambda s: s.remote.prior_commits.append(s.remote.prior_commits[0]), "commit inventory"),
    (lambda s: s.remote.failed_ancestry.add(HEAD), "absent from"),
    (lambda s: s.remote.failed_ancestry.add(CURRENT_BASE), "absent from"),
    (lambda s: s.remote.failed_ancestry.add("HEAD"), "absent from"),
    (lambda s: s.remote.checks[0].update(bucket="fail"), "required CI"),
    (lambda s: s.remote.issue.update(state="open"), "not closed"),
    (lambda s: setattr(s.remote, "remote_code", 0), "remote branch"),
])
def test_remote_historical_and_current_gates_remain_closed(carry_forward, mutation, match):
    mutation(carry_forward)
    with pytest.raises(supervisor.SupervisorError, match=match):
        supervisor.verify_remote_receipt(carry_forward.receipt, carry_forward.ledger, carry_forward.target, carry_forward.remote)


def test_future_v2_remediation_uses_stage_key_not_v1_number(carry_forward):
    state = carry_forward
    state.ledger["workflow"]["effective"]["stages"] = [{"stage": 6, "key": "resolve_review_findings"}]
    state.ledger["stage"] = 6
    assert supervisor.historical_resolution_record(state.receipt["issues"][0], state.receipt, state.ledger, state.target) is state.prior_record
    state.ledger["workflow"]["effective"]["stages"][0]["key"] = "infrastructure"
    with pytest.raises(supervisor.SupervisorError, match="remediation receipt"):
        supervisor.historical_resolution_record(state.receipt["issues"][0], state.receipt, state.ledger, state.target)
