"""Offline, adversarial admission fixtures: no tokens, network, or Git writes."""
from __future__ import annotations

import copy
import importlib.util
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

SOURCE = Path(__file__).parents[1] / "src/kg_microbe_governance/artifacts/scripts/auto_merge_ready_prs.py"
SPEC = importlib.util.spec_from_file_location("queue_admission_controller", SOURCE)
queue = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = queue
SPEC.loader.exec_module(queue)
HEAD = "a" * 40
OTHER = "b" * 40
TREE = "c" * 40
NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)
RULES = queue.Rules((("qc", 15368),), False)


def pr(number=1, **updates):
    return dict({"number": number, "node_id": f"PR_{number}", "state": "open", "base": {"ref": "main"},
                 "draft": False, "assignees": [], "labels": [],
                 "user": {"login": "author"}, "created_at": "2026-09-01T00:00:00Z",
                 "headRefOid": HEAD, "head": {"sha": HEAD}, "commits": 1,
                 "changed_files": 0, "mergeable": "MERGEABLE", "mergeStateStatus": "CLEAN",
                 "reviewDecision": None}, **updates)


def approval(**updates):
    return dict({"id": 1, "state": "APPROVED", "commit_id": HEAD,
                 "user": {"login": "reviewer"}, "author_association": "MEMBER"}, **updates)


def check(**updates):
    return dict({"id": 1, "name": "qc", "head_sha": HEAD,
                 "status": "completed", "conclusion": "success", "app": {"id": 15368}}, **updates)


def commit(sha=HEAD, tree=TREE, date="2026-09-01T00:00:00Z"):
    return {"sha": sha, "commit": {"tree": {"sha": tree}, "committer": {"date": date}}}


def cache_file(path="cache/chebi/terms.csv", **updates):
    return dict({"filename": path, "status": "modified", "additions": 1, "deletions": 0,
                 "patch": "@@ -1 +1,2 @@\n curie,label\n+CHEBI:1,example"}, **updates)


class API:
    """Injectable repository snapshot; each method returns a detached API value."""
    repository = "test/repository"

    def __init__(self, prs=None):
        self.prs = prs or {1: pr()}
        self.review_rows = [approval()]
        self.runs = [check()]
        self.statuses = []
        self.event_rows = []
        self.commit_rows = [commit()]
        self.file_rows = {}
        self.queued = {}
        self.writes = []
        self.failed_writes = set()
        self.integrity = ""
        self.rules_value = RULES
        self.reads = 0

    def rules(self):
        return self.rules_value

    def integrity_reason(self):
        return self.integrity

    def queue(self):
        return dict(self.queued)

    def open_prs(self):
        return copy.deepcopy(list(self.prs.values()))

    def pr(self, number):
        self.reads += 1
        return copy.deepcopy(self.prs[number])

    def reviews(self, number):
        return copy.deepcopy(self.review_rows)

    def checks(self, head):
        return copy.deepcopy((self.runs, self.statuses))

    def history(self, number):
        return copy.deepcopy(self.event_rows)

    def commits(self, number, expected):
        return copy.deepcopy(self.commit_rows)

    def files(self, number, expected):
        return copy.deepcopy(self.file_rows.get(number, []))

    def enqueue(self, number, head, pull_request_id):
        self.writes.append((number, head))
        if number in self.failed_writes:
            raise queue.AdmissionError("test write failed")
        self.queued[number] = head


def run(api, apply=False, count=3):
    return queue.run(api, apply=apply, max_admissions=count, globs=queue.DEFAULT_CACHE_GLOBS)


def test_dry_run_is_default_no_writes_and_orders_oldest_first():
    api = API({2: pr(2), 1: pr(1, created_at="2026-08-01T00:00:00Z")})
    report = run(api, count=1)
    assert [(row["number"], row["status"]) for row in report["rows"]] == [(1, "would_enqueue"), (2, "held")]
    assert report["admitted"] == 1
    assert api.writes == []


def test_apply_pins_verified_head_and_deduplicates_queue():
    api = API({1: pr(), 2: pr(2)})
    api.queued[1] = HEAD
    report = run(api, apply=True)
    assert api.writes == [(2, HEAD)]
    assert report["rows"][0]["status"] == "already_queued"


@pytest.mark.parametrize("change,reason", [
    ({"draft": True}, "draft"),
    ({"assignees": [{"login": "alice", "type": "User"}]}, "human"),
    ({"assignees": [{"login": "looks-like-a[bot]", "type": "User"}]}, "human"),
    ({"labels": [{"name": "Do-Not-Merge"}]}, "hold label"),
    ({"base": {"ref": "release"}}, "targeting main"),
    ({"mergeable": "UNKNOWN"}, "not mergeable"),
    ({"mergeStateStatus": "BLOCKED"}, "not mergeable"),
])
def test_human_holds_and_server_guards(change, reason):
    api = API({1: pr(**change)})
    assert reason in run(api, apply=True)["rows"][0]["reason"]
    assert not api.writes


@pytest.mark.parametrize("reviews,reason", [
    ([], "no trusted"),
    ([approval(commit_id=OTHER)], "current head"),
    ([approval(author_association="NONE")], "no trusted"),
    ([approval(user={"login": "author"})], "no trusted"),
    ([approval(), approval(id=2, state="DISMISSED")], "no trusted"),
    ([approval(), approval(id=2, state="COMMENTED")], "no trusted"),
    ([approval(), approval(id=2, user={"login": "other"}, state="CHANGES_REQUESTED")], "changes requested"),
    ([approval(), approval(id=2, user={"login": "other"}, state="CHANGES_REQUESTED"),
      approval(id=3, user={"login": "other"}, state="COMMENTED")], "changes requested"),
])
def test_approval_is_explicit_latest_head_bound_trusted_and_no_requested_changes(reviews, reason):
    api = API()
    api.review_rows = reviews
    assert reason in run(api, apply=True)["rows"][0]["reason"]
    assert not api.writes


def test_new_approval_clears_same_reviewers_changes_request():
    reviews = [approval(id=1, state="CHANGES_REQUESTED"), approval(id=2)]
    assert queue.review_reason(reviews, pr(), RULES) == ""


def test_required_reviews_still_require_github_approval_decision():
    api = API()
    api.rules_value = queue.Rules(RULES.checks, True)
    assert "requirements" in run(api)["rows"][0]["reason"]
    api.prs[1]["reviewDecision"] = "APPROVED"
    assert run(api)["admitted"] == 1


@pytest.mark.parametrize("runs", [[], [check(head_sha=OTHER)], [check(app={"id": 999})],
                                  [check(status="in_progress", conclusion=None)],
                                  [check(conclusion="failure")], [check(conclusion="skipped")],
                                  [check(), check(id=2, conclusion="failure")]])
def test_required_checks_need_success_at_current_head_from_trusted_app(runs):
    api = API()
    api.runs = runs
    # A spoofed legacy green context cannot satisfy an app-bound requirement.
    api.statuses = [{"context": "qc", "id": 1, "state": "success"}]
    assert run(api, apply=True)["admitted"] == 0
    assert not api.writes


def test_legacy_latest_status_is_used_only_for_unbound_rule():
    rules = queue.Rules((("legacy", None),), False)
    assert not queue.check_reason([], [{"id": 2, "context": "legacy", "state": "success"},
                                      {"id": 1, "context": "legacy", "state": "failure"}], rules, HEAD)
    assert queue.check_reason([], [{"id": 2, "context": "legacy", "state": "pending"}], rules, HEAD)


def test_head_changed_during_final_reads_never_admits(monkeypatch):
    api = API()
    original = api.pr

    def moved(number):
        value = original(number)
        if api.reads >= 4:
            value["headRefOid"] = OTHER
        return value

    monkeypatch.setattr(api, "pr", moved)
    assert "head changed" in run(api, apply=True)["rows"][0]["reason"]
    assert not api.writes


def test_human_hold_arriving_during_review_read_never_admits(monkeypatch):
    api = API()

    def reviews(number):
        api.prs[number]["draft"] = True
        return [approval()]

    monkeypatch.setattr(api, "reviews", reviews)
    assert "draft" in run(api, apply=True)["rows"][0]["reason"]
    assert not api.writes


def test_queue_change_immediately_before_action_never_admits(monkeypatch):
    api = API()
    calls = 0

    def changed():
        nonlocal calls
        calls += 1
        return {} if calls < 4 else {22: OTHER}

    monkeypatch.setattr(api, "queue", changed)
    assert "queue changed" in run(api, apply=True)["rows"][0]["reason"]
    assert not api.writes


def events(*dates):
    return [{"createdAt": day, "reason": "failed_checks"} for day in dates]


def test_two_ejections_hold_one_retries_and_new_content_resets():
    history = events("2026-09-03T00:00:00Z", "2026-09-04T00:00:00Z")
    assert queue.retry_reason([commit()], history, HEAD, NOW)
    assert not queue.retry_reason([commit()], history[:1], HEAD, NOW)
    assert not queue.retry_reason([commit(tree="d" * 40, date="2026-09-05T00:00:00Z")], history, HEAD, NOW)


def test_empty_commit_or_tree_revert_does_not_clear_retry_hold():
    history = events("2026-09-03T00:00:00Z", "2026-09-04T00:00:00Z")
    commits = [commit(OTHER), commit(date="2026-09-05T00:00:00Z")]
    assert queue.retry_reason(commits, history, HEAD, NOW)
    # Pushing an old SHA retains its old date, so failures still count.
    assert queue.retry_reason([commit(OTHER)], history, OTHER, NOW)


@pytest.mark.parametrize("commits,history", [
    ([commit(OTHER)], []),
    ([commit(date="2099-01-01T00:00:00Z")], []),
    ([commit(date="garbage")], []),
    ([commit()], [{"createdAt": "2026-09-03T00:00:00Z", "reason": None}]),
    ([commit()], [{"createdAt": "garbage", "reason": "failed_checks"}]),
])
def test_missing_or_invalid_retry_evidence_fails_closed(commits, history):
    with pytest.raises(queue.AdmissionError):
        queue.retry_reason(commits, history, HEAD, NOW)


@pytest.mark.parametrize("path", ["cache/chebi/terms.csv", "deep/cache/terms.csv",
                                  "references_cache/PMID_1.md", "deep/references_cache/a.json",
                                  "ontology_cache.tsv", "data/term_cache.csv"])
def test_heterogeneous_cache_formats_use_path_reservation(path):
    assert queue.cache_claims([cache_file(path)], queue.DEFAULT_CACHE_GLOBS) == {path}


def test_cache_conflicts_cover_already_queued_and_same_sweep():
    api = API({1: pr(), 2: pr(2), 3: pr(3)})
    api.file_rows = {1: [cache_file()], 2: [cache_file()], 3: [cache_file("references_cache/a.md")]}
    api.queued[1] = HEAD
    report = run(api, apply=True)
    assert api.writes == [(3, HEAD)]
    assert "#1 (cache/" in report["rows"][1]["reason"]
    api = API({1: pr(), 2: pr(2)})
    api.file_rows = {1: [cache_file()], 2: [cache_file()]}
    assert run(api, apply=True)["admitted"] == 1
    assert api.writes == [(1, HEAD)]


def test_cache_rename_reserves_both_names():
    row = cache_file("references_cache/new.md", previous_filename="references_cache/old.md")
    assert queue.cache_claims([row], queue.DEFAULT_CACHE_GLOBS) == {
        "references_cache/new.md", "references_cache/old.md"}


@pytest.mark.parametrize("row", [cache_file(patch=None), cache_file(patch=""),
                                  cache_file(additions=2), cache_file(patch="+bad")])
def test_missing_or_truncated_cache_patch_blocks(row):
    with pytest.raises(queue.AdmissionError):
        queue.cache_claims([row], queue.DEFAULT_CACHE_GLOBS)


def test_unreadable_queued_cache_diff_blocks_later_admission():
    api = API({1: pr(), 2: pr(2)})
    api.queued[1] = HEAD
    api.file_rows[1] = [cache_file(patch=None)]
    assert run(api, apply=True)["rows"][1]["status"] == "error"
    assert not api.writes


def test_failed_enqueue_does_not_claim_success_and_stops_apply_sweep():
    api = API({1: pr(), 2: pr(2)})
    api.failed_writes = {1}
    api.file_rows = {1: [cache_file()], 2: [cache_file()]}
    report = run(api, apply=True, count=1)
    assert api.writes == [(1, HEAD)]
    assert report["admitted"] == 0
    assert [row["status"] for row in report["rows"]] == ["error", "held"]


def test_api_failure_never_becomes_empty_success(monkeypatch):
    api = API()

    def unavailable():
        raise queue.AdmissionError("queue unavailable")

    monkeypatch.setattr(api, "queue", unavailable)
    report = run(api, apply=True)
    assert report["errors"] == ["queue unavailable"]
    assert not api.writes


def test_rest_paginates_and_detects_count_truncation(monkeypatch):
    api = queue.GitHub("test/repository")
    endpoints = []

    def get(endpoint):
        endpoints.append(endpoint)
        return {"total_count": 101, "check_runs": [{"id": n} for n in range(100)]
                if endpoint.endswith("page=1") else [{"id": 100}]}

    monkeypatch.setattr(api, "get", get)
    assert len(api.pages("checks?filter=latest", key="check_runs")) == 101
    assert endpoints[-1] == "checks?filter=latest&per_page=100&page=2"
    monkeypatch.setattr(api, "get", lambda endpoint: {"total_count": 3, "check_runs": []})
    with pytest.raises(queue.AdmissionError, match="truncated"):
        api.pages("checks", key="check_runs")


def test_plain_rest_pagination_does_not_stop_at_100(monkeypatch):
    api = queue.GitHub("test/repository")
    monkeypatch.setattr(api, "get", lambda endpoint: [{}] * (100 if endpoint.endswith("page=1") else 1))
    assert len(api.pages("reviews")) == 101


def connection(nodes, total, more=False, cursor=None):
    return {"nodes": nodes, "totalCount": total,
            "pageInfo": {"hasNextPage": more, "endCursor": cursor}}


def test_queue_graphql_pagination_is_complete_and_rejects_truncation(monkeypatch):
    api = queue.GitHub("test/repository")
    calls = []

    def query(body, **variables):
        calls.append((body, variables))
        page = connection([{"pullRequest": {"number": 2, "headRefOid": HEAD}}], 2)
        if "cursor" not in variables:
            page = connection([{"pullRequest": {"number": 1, "headRefOid": HEAD}}], 2, True, "next")
        return {"mergeQueue": {"entries": page}}

    monkeypatch.setattr(api, "graphql", query)
    assert api.queue() == {1: HEAD, 2: HEAD}
    assert calls[1][1] == {"cursor": "next"}
    monkeypatch.setattr(api, "graphql", lambda *a, **kw: {"mergeQueue": {"entries": connection([], 1)}})
    with pytest.raises(queue.AdmissionError, match="truncated"):
        api.queue()


def test_missing_queue_and_truncated_files_or_commits_are_errors(monkeypatch):
    api = queue.GitHub("test/repository")
    monkeypatch.setattr(api, "graphql", lambda *a, **kw: {"mergeQueue": None})
    with pytest.raises(queue.AdmissionError):
        api.queue()
    monkeypatch.setattr(api, "pages", lambda *a, **kw: [])
    with pytest.raises(queue.AdmissionError, match="truncated"):
        api.files(1, 1)
    with pytest.raises(queue.AdmissionError, match="truncated"):
        api.commits(1, 1)


def test_read_token_and_write_token_are_isolated(monkeypatch):
    calls = []
    monkeypatch.setenv("GH_TOKEN", "reader-test")
    monkeypatch.setenv("GH_MERGE_TOKEN", "writer-test")

    def process(args, **kwargs):
        calls.append((args, kwargs["env"]))
        return SimpleNamespace(stdout=json.dumps({"data": {"enqueuePullRequest": {"mergeQueueEntry": {
            "pullRequest": {"id": "PR_test", "number": 1, "headRefOid": HEAD, "isInMergeQueue": True}}}}}))

    monkeypatch.setattr(queue.subprocess, "run", process)
    api = queue.GitHub("test/repository")
    api.get("test")
    api.enqueue(1, HEAD, "PR_test")
    assert calls[0][1]["GH_TOKEN"] == "reader-test"
    assert calls[1][1]["GH_TOKEN"] == "writer-test"
    assert all("GH_MERGE_TOKEN" not in env for _, env in calls)
    assert calls[1][0][:3] == ["gh", "api", "graphql"]
    assert f"head={HEAD}" in calls[1][0]
    assert os.environ["GH_TOKEN"] == "reader-test"


def test_write_token_missing_refuses_subprocess(monkeypatch):
    monkeypatch.delenv("GH_MERGE_TOKEN", raising=False)
    monkeypatch.setattr(queue.subprocess, "run", lambda *a, **kw: pytest.fail("unexpected write"))
    with pytest.raises(queue.AdmissionError, match="requires GH_MERGE_TOKEN"):
        queue.GitHub("test/repository").enqueue(1, HEAD, "PR_test")


def test_subprocess_error_redacts_stderr(monkeypatch):
    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, args, stderr="sensitive-test-value")

    monkeypatch.setattr(queue.subprocess, "run", fail)
    with pytest.raises(queue.AdmissionError, match="GitHub read failed") as error:
        queue.GitHub("test/repository").get("test")
    assert "sensitive" not in str(error.value)


def test_config_is_strict_and_cli_default_dry_run(monkeypatch, tmp_path):
    api = API()
    monkeypatch.setattr(queue, "GitHub", lambda repo: api)
    report = tmp_path / "report.json"
    assert queue.main(["--repository", api.repository, "--report", str(report)]) == 0
    assert json.loads(report.read_text())["mode"] == "dry-run"
    assert not api.writes
    path = tmp_path / "config.json"
    path.write_text('{"cache_path_globs":["references_cache/**"]}')
    assert queue.config(path) == ("references_cache/**",)
    path.write_text('{"cache_path_globs":[],"allow_direct_merge":true}')
    with pytest.raises(queue.AdmissionError):
        queue.config(path)


@pytest.mark.parametrize("reason", ["main_integrity_pending", "main_integrity_failed"])
def test_unverified_current_main_holds_all_admissions(reason):
    api = API()
    api.integrity = reason
    report = run(api, apply=True)
    assert report["rows"][0]["reason"] == reason
    assert not api.writes


def test_main_integrity_rechecked_before_action(monkeypatch):
    api = API()
    reads = 0

    def integrity():
        nonlocal reads
        reads += 1
        return "" if reads == 1 else "main_integrity_failed"

    monkeypatch.setattr(api, "integrity_reason", integrity)
    assert run(api, apply=True)["rows"][0]["reason"] == "main_integrity_failed"
    assert not api.writes


@pytest.mark.parametrize("runs,reason", [
    ([], "main_integrity_pending"),
    ([check(name="merge-integrity", app={"id": 55})], "main_integrity_pending"),
    ([check(name="merge-integrity", status="in_progress")], "main_integrity_pending"),
    ([check(name="merge-integrity", conclusion="failure")], "main_integrity_failed"),
    ([check(name="merge-integrity")], ""),
])
def test_integrity_check_must_be_github_actions_current_main_success(monkeypatch, runs, reason):
    api = queue.GitHub("test/repository")
    monkeypatch.setattr(api, "get", lambda endpoint: {"sha": HEAD})
    monkeypatch.setattr(api, "checks", lambda head: (runs, []))
    assert api.integrity_reason().startswith(reason)


def test_history_total_count_is_unfiltered_but_every_filtered_page_is_read(monkeypatch):
    api = queue.GitHub("test/repository")
    calls = []

    def query(body, **variables):
        calls.append(variables)
        node = {"createdAt": "2026-09-03T00:00:00Z", "reason": "failed_checks"}
        page = connection([node], 93, "cursor" not in variables, "next")
        return {"pullRequest": {"timelineItems": page}}

    monkeypatch.setattr(api, "graphql", query)
    assert len(api.history(1)) == 2
    assert calls == [{"number": 1}, {"number": 1, "cursor": "next"}]


def test_history_invalid_cursor_is_error_not_an_empty_history(monkeypatch):
    api = queue.GitHub("test/repository")
    monkeypatch.setattr(api, "graphql", lambda *a, **kw: {
        "pullRequest": {"timelineItems": connection([], 93, True, None)}})
    with pytest.raises(queue.AdmissionError, match="cursor"):
        api.history(1)


def effective_rules():
    return [{"type": "merge_queue"},
            {"type": "pull_request", "parameters": {"required_approving_review_count": 0}},
            {"type": "required_status_checks", "parameters": {
                "required_status_checks": [{"context": "qc", "integration_id": 15368}]}}]


def test_effective_and_classic_rules_preserve_check_sources(monkeypatch):
    api = queue.GitHub("test/repository")
    monkeypatch.setattr(api, "pages", lambda endpoint: effective_rules())
    monkeypatch.setattr(api, "graphql", lambda *a, **kw: {"ref": {"branchProtectionRule": {
        "requiresApprovingReviews": True, "requiresCodeOwnerReviews": False,
        "requireLastPushApproval": False,
        "requiredStatusChecks": [{"context": "external", "app": {"databaseId": 444}}]}}})
    assert api.rules() == queue.Rules((("external", 444), ("qc", 15368)), True)


@pytest.mark.parametrize("drop", ["merge_queue", "pull_request", "required_status_checks"])
def test_absent_queue_pr_or_checks_rules_fail_closed(monkeypatch, drop):
    api = queue.GitHub("test/repository")
    monkeypatch.setattr(api, "pages", lambda endpoint: [r for r in effective_rules() if r["type"] != drop])
    monkeypatch.setattr(api, "graphql", lambda *a, **kw: {"ref": {"branchProtectionRule": None}})
    with pytest.raises(queue.AdmissionError):
        api.rules()


def test_unreadable_classic_protection_fails_closed(monkeypatch):
    api = queue.GitHub("test/repository")
    monkeypatch.setattr(api, "pages", lambda endpoint: effective_rules())
    monkeypatch.setattr(api, "graphql", lambda *a, **kw: {"ref": None})
    with pytest.raises(queue.AdmissionError, match="unreadable"):
        api.rules()


def test_cli_api_error_is_nonzero_and_reported(monkeypatch, tmp_path):
    api = API()

    def unavailable():
        raise queue.AdmissionError("fixture API outage")

    monkeypatch.setattr(api, "rules", unavailable)
    monkeypatch.setattr(queue, "GitHub", lambda repo: api)
    report = tmp_path / "report.json"
    assert queue.main(["--repository", api.repository, "--report", str(report)]) == 1
    assert json.loads(report.read_text())["errors"] == ["fixture API outage"]


def test_writer_uses_queue_only_atomic_mutation_and_never_merge_command(monkeypatch):
    calls = []
    api = queue.GitHub("test/repository")

    def gh(args, *, write=False):
        calls.append((args, write))
        return json.dumps({"data": {"enqueuePullRequest": {"mergeQueueEntry": {
            "pullRequest": {"id": "PR_test", "number": 1, "headRefOid": HEAD, "isInMergeQueue": True}}}}})

    monkeypatch.setattr(api, "gh", gh)
    api.enqueue(1, HEAD, "PR_test")
    args, write = calls[0]
    assert write is True
    assert args[:2] == ["api", "graphql"]
    query = next(value for value in args if value.startswith("query="))
    assert "enqueuePullRequest" in query
    assert "expectedHeadOid:$head" in query
    assert "pullRequestId:$id" in query
    assert f"head={HEAD}" in args
    assert "id=PR_test" in args
    assert not any("mergePullRequest" in arg for arg in args)


@pytest.mark.parametrize("payload", [
    {"errors": [{"message": "queue removed"}]},
    {"data": {"enqueuePullRequest": None}},
    {"data": {"enqueuePullRequest": {"mergeQueueEntry": {"pullRequest": {
        "id": "PR_test", "number": 1, "headRefOid": OTHER, "isInMergeQueue": True}}}}},
])
def test_queue_only_mutation_failure_never_falls_back(monkeypatch, payload):
    api = queue.GitHub("test/repository")
    calls = []

    def gh(args, *, write=False):
        calls.append(args)
        return json.dumps(payload)

    monkeypatch.setattr(api, "gh", gh)
    with pytest.raises(queue.AdmissionError):
        api.enqueue(1, HEAD, "PR_test")
    assert len(calls) == 1
    assert calls[0][:2] == ["api", "graphql"]


def test_same_tree_force_push_cannot_reset_two_strikes():
    history = events("2026-09-03T00:00:00Z", "2026-09-04T00:00:00Z")
    history.append({"__typename": "HeadRefForcePushedEvent", "createdAt": "2026-09-05T00:00:00Z",
                    "beforeCommit": {"oid": OTHER, "committedDate": "2026-09-01T00:00:00Z",
                                     "tree": {"oid": TREE}},
                    "afterCommit": {"oid": HEAD, "committedDate": "2026-09-05T00:00:00Z",
                                    "tree": {"oid": TREE}}})
    assert queue.retry_reason([commit(date="2026-09-05T00:00:00Z")], history, HEAD, NOW)


@pytest.mark.parametrize("change,reason", [("main", "main_integrity_failed"), ("review", "changes requested")])
def test_late_main_failure_or_review_veto_during_final_file_read_blocks(monkeypatch, change, reason):
    api = API()
    reads = 0

    def files(number, expected):
        nonlocal reads
        reads += 1
        if reads == 2:
            if change == "main":
                api.integrity = "main_integrity_failed"
            else:
                api.review_rows.append(approval(id=2, state="CHANGES_REQUESTED", user={"login": "other"}))
        return []

    monkeypatch.setattr(api, "files", files)
    report = run(api, apply=True)
    assert report["admitted"] == 0
    assert not api.writes
    assert reason in report["rows"][0]["reason"]


def test_accepted_enqueue_with_lost_response_stops_sweep_even_if_queue_lags(monkeypatch):
    api = API({1: pr(), 2: pr(2)})
    api.file_rows = {1: [cache_file()], 2: [cache_file()]}

    def accepted_but_response_lost(number, head, pull_request_id):
        api.writes.append((number, head))  # Server accepted; queue reads still lag.
        raise queue.AdmissionError("response timed out after server accepted")

    monkeypatch.setattr(api, "enqueue", accepted_but_response_lost)
    report = run(api, apply=True, count=1)
    assert api.writes == [(1, HEAD)]
    assert report["rows"][1]["status"] == "held"
    assert "unknown" in report["rows"][1]["reason"]
