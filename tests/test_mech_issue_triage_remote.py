"""Independent remote truth for stage-one claims, including optional fixes (#852)."""
import copy
import hashlib
import json
import re
from types import SimpleNamespace

import pytest
from test_issue_triage_contract import materialize
from test_mech_cycle_v2_migration import stage_one_receipt
from test_mech_session_supervisor import (
    FIX,
    HEAD,
    MERGE,
    supervisor,
)
from test_mech_session_supervisor import (
    cycle_setup as cycle_setup,
)
from test_mech_session_supervisor import (
    setup as setup,
)


class TriageRemote:
    def __init__(self, data, base=None):
        self.repository = data["github_repository"]
        self.calls = []
        self.base = base
        triage = data["issue_triage"]
        dispositions = {item["number"]: item["status"] for item in triage["dispositions"]}
        self.issues = {item["number"]: self.issue(item["number"], item["assigned_labels"],
                      "CLOSED" if dispositions[item["number"]] in {"fixed", "duplicate", "wont_fix"} else "OPEN")
                       for item in triage["inventory"]}
        self.children = {}
        self.page_override = {}
        numbers = {int(url.rsplit("/", 1)[-1]) for item in triage["dispositions"] for url in item.get("pr_urls", [])}
        prototype = base.pr if base else {"merged": True, "merged_at": "2026-11-06T01:00:00Z",
                                         "base": {"repo": {"full_name": self.repository}}}
        self.prs = {number: {**copy.deepcopy(prototype), "number": number,
                            "merge_commit_sha": MERGE if number == 42 else format(number, "040x")} for number in numbers | {42}}
        self.commits = {number: [HEAD, FIX] for number in numbers}
        self.nonancestor = set()
        for item in triage["dispositions"]:
            if item.get("duplicate_of"):
                number = int(item["duplicate_of"].rsplit("/", 1)[-1])
                self.issues.setdefault(number, self.issue(number, [], "CLOSED"))
        for group in triage["groups"]:
            if group.get("tracking_issue_url"):
                number = int(group["tracking_issue_url"].rsplit("/", 1)[-1])
                self.issues[number] = self.issue(number, [], "OPEN")
                self.children[number] = group["sub_issue_numbers"]

    def issue(self, number, labels, state):
        return {"__typename": "Issue", "number": number, "state": state,
                "url": f"https://github.com/{self.repository}/issues/{number}",
                "labels": {"totalCount": len(labels), "nodes": [{"name": value} for value in labels],
                           "pageInfo": {"hasNextPage": False}}}

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        if args[:1] == ["git"] and args[3:5] == ["merge-base", "--is-ancestor"] and args[5] in self.nonancestor:
            return SimpleNamespace(returncode=1, stdout="", stderr="")
        if args[:3] == ["gh", "api", "graphql"]:
            query = next(value.removeprefix("query=") for value in args if value.startswith("query="))
            requested = [int(value) for value in re.findall(r"i(\d+):issue", query)]
            source = {"nameWithOwner": self.repository,
                      **{f"i{number}": self.issues.get(number) for number in requested}}
            return SimpleNamespace(returncode=0, stdout=json.dumps({"data": {"repository": source}}), stderr="")
        if args[:3] == ["gh", "api", "--include"]:
            endpoint = args[-1]
            commits = re.fullmatch(r"repos/" + re.escape(self.repository) + r"/pulls/(\d+)/commits\?per_page=100&page=(\d+)", endpoint)
            if commits:
                number, page = map(int, commits.groups())
                items = self.commits[number]
                link = (f'Link: <https://api.github.com/repos/{self.repository}/pulls/{number}/commits?per_page=100&page={page + 1}>; rel="next"\n'
                        if page * 100 < len(items) else "")
                body = json.dumps([{"sha": value} for value in items[(page - 1) * 100:page * 100]])
                return SimpleNamespace(returncode=0, stdout="HTTP/2.0 200 OK\n" + link + "\n" + body, stderr="")
            match = re.fullmatch(r"repos/" + re.escape(self.repository) + r"/issues/(\d+)/sub_issues\?per_page=100&page=(\d+)", endpoint)
            assert match, args
            number, page = map(int, match.groups())
            if (number, page) in self.page_override:
                return SimpleNamespace(returncode=0, stdout=self.page_override[number, page], stderr="")
            children = self.children[number]
            items = children[(page - 1) * 100:page * 100]
            link = (f'Link: <https://api.github.com/repos/{self.repository}/issues/{number}/sub_issues?per_page=100&page={page + 1}>; rel="next"\n'
                    if page * 100 < len(children) else "")
            body = json.dumps([{"number": child, "html_url": f"https://github.com/{self.repository}/issues/{child}"} for child in items])
            return SimpleNamespace(returncode=0, stdout="HTTP/2.0 200 OK\n" + link + "\n" + body, stderr="")
        if args[:2] == ["gh", "api"] and re.search(r"/issues/\d+$", args[-1]):
            issue = self.issues[int(args[-1].rsplit("/", 1)[-1])]
            return SimpleNamespace(returncode=0, stdout=json.dumps({"state": issue["state"].lower()}), stderr="")
        if args[:2] == ["gh", "api"] and re.search(r"/pulls/\d+$", args[-1]):
            return SimpleNamespace(returncode=0, stdout=json.dumps(self.prs[int(args[-1].rsplit("/", 1)[-1])]), stderr="")
        assert self.base is not None, args
        return self.base(args, **kwargs)


def save_data(setup, receipt, data):
    materialize(setup.repo, data)
    path = setup.repo / receipt["goal_outputs"]["goal_evidence"]["path"]
    path.write_text(json.dumps(data))
    receipt["goal_outputs"]["goal_evidence"]["sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()


def optional_fixed(setup):
    ledger, receipt, data = stage_one_receipt(setup)
    issue = data["issue_triage"]["dispositions"][1]
    issue.update(status="fixed", reason="Parser fixed", resolution_evidence=[data["issue_triage"]["dispositions"][0]["resolution_evidence"][0]],
                 pr_urls=[f"https://github.com/{setup.target['github_repository']}/pull/42"], commit_sha=FIX)
    receipt["issues"].append({"number": 2, "disposition": "addressed", "fix_commit_sha": FIX})
    save_data(setup, receipt, data)
    return ledger, receipt, data


def test_stage_one_remote_verifier_checks_every_issue_and_actual_group_membership(cycle_setup):
    ledger, receipt, data = optional_fixed(cycle_setup)
    remote = TriageRemote(data, cycle_setup.remote)
    cycle_setup.remote.snapshot()
    assert supervisor.validate_receipt(receipt, ledger, cycle_setup.target, cycle_setup.runtime) == []
    result = supervisor.verify_remote_receipt(receipt, ledger, cycle_setup.target, runner=remote)
    assert result["status"] == "merged"
    assert result["issue_triage"]["issues_checked"] == 4
    assert result["issue_triage"]["tracking_issues_checked"] == 2
    assert result["issue_triage"]["severity_labels_verified"] is True
    assert result["issue_triage"]["sub_issue_relationships_verified"] is True


@pytest.mark.parametrize("fault", ["optional_open", "deferred_closed", "severity_missing", "two_severities", "labels_truncated", "tracking_missing", "tracking_pr", "missing_edge", "foreign_edge", "unknown_http", "bad_next"])
def test_remote_claim_disagreement_blocks_advance(cycle_setup, fault):
    ledger, receipt, data = optional_fixed(cycle_setup)
    remote = TriageRemote(data, cycle_setup.remote)
    if fault == "optional_open":
        remote.issues[2]["state"] = "OPEN"
    elif fault == "deferred_closed":
        remote.issues[3]["state"] = "CLOSED"
    elif fault == "severity_missing":
        remote.issues[3]["labels"] = {"totalCount": 0, "nodes": [], "pageInfo": {"hasNextPage": False}}
    elif fault == "two_severities":
        remote.issues[3] = remote.issue(3, ["severity:medium", "severity:low"], "OPEN")
    elif fault == "labels_truncated":
        remote.issues[3]["labels"]["pageInfo"]["hasNextPage"] = True
    elif fault == "tracking_missing":
        remote.issues.pop(101)
    elif fault == "tracking_pr":
        remote.issues[101]["__typename"] = "PullRequest"
    elif fault == "missing_edge":
        remote.children[101] = [3]
    elif fault == "foreign_edge":
        remote.page_override[101, 1] = 'HTTP/2.0 200 OK\n\n[{"html_url":"https://github.com/Other/Repo/issues/2"},{"html_url":"https://github.com/CultureBotAI/TraitMech/issues/3"}]'
    elif fault == "unknown_http":
        remote.page_override[101, 1] = "HTTP/2.0 403 Forbidden\n\n[]"
    else:
        remote.page_override[101, 1] = 'HTTP/2.0 200 OK\nLink: <https://other.example/sub_issues?page=2>; rel="next"\n\n[{"html_url":"https://github.com/CultureBotAI/TraitMech/issues/2"}]'
    cycle_setup.remote.snapshot()
    assert supervisor.validate_receipt(receipt, ledger, cycle_setup.target, cycle_setup.runtime) == []
    with pytest.raises(supervisor.SupervisorError, match="triage|severity|sub-issue|group"):
        supervisor.verify_remote_receipt(receipt, ledger, cycle_setup.target, runner=remote)


def test_optional_terminal_issue_is_verified_even_outside_current_receipt_issue_list(cycle_setup):
    ledger, receipt, data = optional_fixed(cycle_setup)
    receipt["issues"] = receipt["issues"][:1]
    remote = TriageRemote(data, cycle_setup.remote)
    cycle_setup.remote.snapshot()
    result = supervisor.verify_remote_receipt(receipt, ledger, cycle_setup.target, runner=remote)
    assert {item["number"] for item in result["issue_triage"]["fix_provenance"]["fixed_issues"]} == {1, 2}


def test_fixed_issue_commit_must_belong_to_its_referenced_merged_pr(cycle_setup):
    ledger, receipt, data = optional_fixed(cycle_setup)
    data["issue_triage"]["dispositions"][1]["commit_sha"] = "d" * 40
    save_data(cycle_setup, receipt, data)
    remote = TriageRemote(data, cycle_setup.remote)
    cycle_setup.remote.snapshot()
    with pytest.raises(supervisor.SupervisorError, match="claimed fix commit is absent"):
        supervisor.verify_remote_receipt(receipt, ledger, cycle_setup.target, runner=remote)


def test_subissue_verification_follows_complete_bounded_pagination(cycle_setup):
    _, _, data = stage_one_receipt(cycle_setup)
    remote = TriageRemote(data)
    remote.children[101] = list(range(1000, 1100)) + [2, 3]
    result = supervisor.verify_remote_issue_triage(data, cycle_setup.target["github_repository"], remote)
    assert result["tracking_issues_checked"] == 2
    assert any(args[-1].endswith("/101/sub_issues?per_page=100&page=2") for args in remote.calls)


def test_repeated_subissue_page_fails_closed(cycle_setup):
    _, _, data = stage_one_receipt(cycle_setup)
    remote = TriageRemote(data)
    remote.children[101] = [2] * 101
    with pytest.raises(supervisor.SupervisorError, match="repeated sub-issue"):
        supervisor.verify_remote_issue_triage(data, cycle_setup.target["github_repository"], remote)


def test_no_change_receipt_still_checks_optional_deferred_labels(cycle_setup):
    _, _, data = stage_one_receipt(cycle_setup)
    remote = TriageRemote(data)
    remote.issues[4] = remote.issue(4, [], "OPEN")
    with pytest.raises(supervisor.SupervisorError, match="recorded severity"):
        supervisor.verify_remote_issue_triage(data, cycle_setup.target["github_repository"], remote)


def test_shared_tracking_issue_cannot_hide_a_second_groups_edges(cycle_setup):
    _, _, data = stage_one_receipt(cycle_setup)
    duplicate = copy.deepcopy(data)
    duplicate["issue_triage"]["groups"][1]["tracking_issue_url"] = duplicate["issue_triage"]["groups"][0]["tracking_issue_url"]
    with pytest.raises(supervisor.SupervisorError, match="distinct tracking"):
        supervisor.verify_remote_issue_triage(duplicate, cycle_setup.target["github_repository"], TriageRemote(data))


def test_remote_verification_deadline_does_not_expand_with_issue_count(cycle_setup, monkeypatch):
    _, _, data = stage_one_receipt(cycle_setup)
    remote = TriageRemote(data)
    ticks = iter([0, 181])
    monkeypatch.setattr(supervisor.time, "monotonic", lambda: next(ticks))
    with pytest.raises(supervisor.SupervisorError, match="180-second deadline"):
        supervisor.verify_remote_issue_triage(data, cycle_setup.target["github_repository"], remote)
    assert remote.calls == []


def prior_fixed(setup, *, merge_sha=False):
    ledger, receipt, data = stage_one_receipt(setup)
    issue = data["issue_triage"]["dispositions"][0]
    issue.update(pr_urls=["https://github.com/CultureBotAI/TraitMech/pull/77"],
                 commit_sha=format(77, "040x") if merge_sha else FIX)
    receipt["issues"] = []  # This goal's PR publishes assessment; it did not create the old fix.
    save_data(setup, receipt, data)
    remote = TriageRemote(data, setup.remote)
    setup.remote.snapshot()
    return ledger, receipt, data, remote


@pytest.mark.parametrize("merge_sha", [False, True])
def test_prior_merged_fix_is_verified_without_reassigning_it_to_current_pr(cycle_setup, merge_sha):
    ledger, receipt, data, remote = prior_fixed(cycle_setup, merge_sha=merge_sha)
    assert supervisor.validate_receipt(receipt, ledger, cycle_setup.target, cycle_setup.runtime) == []
    result = supervisor.verify_remote_receipt(receipt, ledger, cycle_setup.target, runner=remote)
    proof = result["issue_triage"]["fix_provenance"]
    assert proof["fixed_issues"] == [{"number": 1, "commit_sha": data["issue_triage"]["dispositions"][0]["commit_sha"], "pr_numbers": [77]}]
    assert result["pr_number"] == 42 and receipt["issues"] == []
    assert any(args[:5] == ["git", "-C", str(cycle_setup.repo), "merge-base", "--is-ancestor"]
               and args[5:] == [format(77, "040x"), HEAD] for args in remote.calls)
    if merge_sha:
        assert not any("pulls/77/commits?" in args[-1] for args in remote.calls)


@pytest.mark.parametrize("fault", ["unmerged", "wrong_repository", "nonancestor", "wrong_commit", "wrong_pr_number"])
def test_prior_fix_provenance_is_fail_closed(cycle_setup, fault):
    ledger, receipt, _, remote = prior_fixed(cycle_setup)
    if fault == "unmerged":
        remote.prs[77]["merged"] = False
    elif fault == "wrong_repository":
        remote.prs[77]["base"]["repo"]["full_name"] = "Other/Repo"
    elif fault == "nonancestor":
        remote.nonancestor.add(format(77, "040x"))
    elif fault == "wrong_commit":
        remote.commits[77] = [HEAD]
    else:
        remote.prs[77]["number"] = 78
    with pytest.raises(supervisor.SupervisorError, match="triage fix|claimed fix commit"):
        supervisor.verify_remote_receipt(receipt, ledger, cycle_setup.target, runner=remote)


def test_prior_fix_commit_inventory_is_paginated(cycle_setup):
    ledger, receipt, _, remote = prior_fixed(cycle_setup)
    remote.commits[77] = [format(number, "040x") for number in range(1000, 1100)] + [FIX]
    result = supervisor.verify_remote_receipt(receipt, ledger, cycle_setup.target, runner=remote)
    assert result["issue_triage"]["fix_provenance"]["fixed_issues"][0]["pr_numbers"] == [77]
    assert any(args[-1].endswith("pulls/77/commits?per_page=100&page=2") for args in remote.calls)


def duplicate_disposition(setup, *, mandatory=True):
    ledger, receipt, data = stage_one_receipt(setup)
    number = 1 if mandatory else 2
    item = data["issue_triage"]["dispositions"][number - 1]
    item.update(status="duplicate", reason="Same underlying defect", duplicate_of="https://github.com/CultureBotAI/TraitMech/issues/999",
                resolution_evidence=data["issue_triage"]["dispositions"][0]["resolution_evidence"])
    item.pop("pr_urls", None)
    item.pop("commit_sha", None)
    if not mandatory:
        # The larger group still contains one deferred issue and remains selected.
        data["issue_triage"]["budget"]["selected_group_ids"] = ["large"]
    receipt["issues"] = [] if mandatory else receipt["issues"]
    save_data(setup, receipt, data)
    remote = TriageRemote(data, setup.remote)
    setup.remote.snapshot()
    return ledger, receipt, data, remote


@pytest.mark.parametrize("fault", ["missing", "pull_request", "mandatory_open"])
def test_duplicate_target_must_be_real_and_mandatory_work_resolved(cycle_setup, fault):
    ledger, receipt, _, remote = duplicate_disposition(cycle_setup)
    if fault == "missing":
        remote.issues.pop(999)
    elif fault == "pull_request":
        remote.issues[999]["__typename"] = "PullRequest"
    else:
        remote.issues[999]["state"] = "OPEN"
    assert supervisor.validate_receipt(receipt, ledger, cycle_setup.target, cycle_setup.runtime) == []
    with pytest.raises(supervisor.SupervisorError, match="triage|duplicate"):
        supervisor.verify_remote_receipt(receipt, ledger, cycle_setup.target, runner=remote)


def test_optional_duplicate_can_retain_open_surviving_issue(cycle_setup):
    ledger, receipt, _, remote = duplicate_disposition(cycle_setup, mandatory=False)
    remote.issues[999]["state"] = "OPEN"
    assert supervisor.validate_receipt(receipt, ledger, cycle_setup.target, cycle_setup.runtime) == []
    result = supervisor.verify_remote_receipt(receipt, ledger, cycle_setup.target, runner=remote)
    assert result["issue_triage"]["duplicate_targets_checked"] == 1


def test_optional_duplicate_target_must_exist(cycle_setup):
    ledger, receipt, _, remote = duplicate_disposition(cycle_setup, mandatory=False)
    remote.issues.pop(999)
    with pytest.raises(supervisor.SupervisorError, match="triage"):
        supervisor.verify_remote_receipt(receipt, ledger, cycle_setup.target, runner=remote)
