"""Read-only PR closure observations, exercised through offline GitHub/Git doubles."""
from __future__ import annotations

import copy
import hashlib
import json
from types import SimpleNamespace

import pytest
import yaml

from kg_microbe_fleet import default_manifest_path
from kg_microbe_workflows import WorkflowError
from kg_microbe_workflows import pr_maintenance_remote as remote

REPO = "CultureBotAI/ExampleMech"
HEAD, BASE, MERGE = "a" * 40, "b" * 40, "c" * 40


def pr(number=1, *, draft=False, **changes):
    return {"number": number, "title": "Bounded change", "updatedAt": "2026-11-01T00:00:00Z",
            "isDraft": draft, "headRefOid": HEAD, "baseRefOid": BASE,
            "headRefName": f"topic/{number}", "baseRefName": "main", "mergeable": "MERGEABLE",
            **changes}


def connection(nodes, *, total=None, cursor=None):
    return {"totalCount": len(nodes) if total is None else total, "nodes": nodes,
            "pageInfo": {"hasNextPage": cursor is not None, "endCursor": cursor}}


def check(number=1, *, conclusion="SUCCESS", status="COMPLETED"):
    return {"id": f"check-{number}", "__typename": "CheckRun", "name": f"test-{number}",
            "status": status, "conclusion": conclusion}


def checks_body(nodes=(), *, head=HEAD, commit=HEAD, total=None, cursor=None, absent=False):
    rollup = None if absent else {"contexts": connection(list(nodes), total=total, cursor=cursor)}
    return {"pullRequest": {"headRefOid": head,
            "commits": {"nodes": [{"commit": {"oid": commit, "statusCheckRollup": rollup}}]}}}


class Graph:
    """An ordered response queue; an accidental external command is a test failure."""
    def __init__(self, *responses, github=REPO):
        self.responses = list(responses)
        self.github = github
        self.calls = []

    def __call__(self, args, **kwargs):
        assert args[:3] == ["gh", "api", "graphql"]
        assert 1 <= kwargs["timeout"] <= 45
        fields = {args[i + 1].split("=", 1)[0]: args[i + 1].split("=", 1)[1]
                  for i in range(3, len(args), 2)}
        assert fields["owner"] + "/" + fields["name"] == self.github
        self.calls.append((fields, kwargs))
        assert self.responses, "unexpected extra query"
        response = self.responses.pop(0)
        if callable(response):
            response = response(fields)
        if isinstance(response, SimpleNamespace):
            return response
        return SimpleNamespace(returncode=0, stdout=json.dumps(
            {"data": {"repository": {"nameWithOwner": self.github, **response}}}))


def test_open_pr_pagination_is_complete_sorted_and_includes_drafts():
    first = [pr(number, draft=number == 1) for number in range(100, 0, -1)]
    runner = Graph({"pullRequests": connection(first, total=101, cursor="page-two")},
                   {"pullRequests": connection([pr(101)], total=101)})
    rows, pages = remote.Observer(REPO, runner).open_prs()
    assert pages == 2 and [row["number"] for row in rows] == list(range(1, 102))
    assert rows[0]["isDraft"] is True
    assert runner.calls[1][0]["cursor"] == "page-two" and not runner.responses


@pytest.mark.parametrize("responses", [
    [{"pullRequests": connection([pr()], total=2)}],
    [{"pullRequests": connection([pr(), pr()], total=2)}],
    [{"pullRequests": connection([pr()], total=True)}],
    [{"pullRequests": connection([], total=1, cursor="next")}],
    [{"pullRequests": connection([pr()], total=2, cursor="same")},
     {"pullRequests": connection([pr(2)], total=2, cursor="same")}],
    [{"pullRequests": connection([pr()], total=2, cursor="next")},
     {"pullRequests": connection([pr(2)], total=3)}],
    [{"pullRequests": {"totalCount": 0, "nodes": [], "pageInfo": {"hasNextPage": "false"}}}],
    [{"pullRequests": None}],
])
def test_open_inventory_never_turns_truncation_duplicates_or_drift_into_completeness(responses):
    with pytest.raises(WorkflowError):
        remote.Observer(REPO, Graph(*responses)).open_prs()


@pytest.mark.parametrize("response", [
    SimpleNamespace(returncode=1, stdout=""),
    SimpleNamespace(returncode=0, stdout="not-json"),
    SimpleNamespace(returncode=0, stdout=json.dumps({"data": {"repository": None}})),
    SimpleNamespace(returncode=0, stdout=json.dumps({"data": {"repository": {"nameWithOwner": "wrong/repo"}}})),
    SimpleNamespace(returncode=0, stdout=json.dumps({"errors": [{"message": "partial"}],
        "data": {"repository": {"nameWithOwner": REPO}}})),
])
def test_query_failure_partial_graphql_and_wrong_repository_refuse(response):
    with pytest.raises(WorkflowError):
        remote.Observer(REPO, Graph(response)).open_prs()


def test_deadline_prevents_any_query_after_expiry(monkeypatch):
    times = iter([10.0, 12.0])
    monkeypatch.setattr(remote.time, "monotonic", lambda: next(times))
    runner = Graph()
    with pytest.raises(WorkflowError, match="deadline"):
        remote.Observer(REPO, runner, seconds=1).open_prs()
    assert runner.calls == []


def test_checks_paginate_and_bind_both_head_and_commit():
    runner = Graph(checks_body([check(i) for i in range(100)], total=101, cursor="later"),
                   checks_body([check(100, conclusion="FAILURE")], total=101))
    value = remote.Observer(REPO, runner).checks(17, HEAD)
    assert value == {"checks_state": "failing", "checks_complete": True,
                     "check_count": 101, "failing_checks": ["test-100"]}
    assert runner.calls[0][0]["number"] == "17"
    assert runner.calls[1][0]["cursor"] == "later"


@pytest.mark.parametrize("second", [
    checks_body([check(2)], head="d" * 40, total=2),
    checks_body([check(2)], commit="d" * 40, total=2),
    checks_body(absent=True),
    checks_body([check(1)], total=2),
    checks_body([check(2)], total=3),
])
def test_check_head_races_and_incomplete_pages_refuse(second):
    runner = Graph(checks_body([check(1)], total=2, cursor="next"), second)
    with pytest.raises(WorkflowError):
        remote.Observer(REPO, runner).checks(1, HEAD)


@pytest.mark.parametrize("absent", [False, True])
def test_no_check_rollup_or_zero_checks_cannot_claim_green(absent):
    value = remote.Observer(REPO, Graph(checks_body(absent=absent))).checks(1, HEAD)
    assert value["checks_state"] == "unknown" and value["check_count"] == 0


@pytest.mark.parametrize("rows,state,complete", [
    ([check()], "green", True),
    ([check(conclusion="SKIPPED")], "unknown", True),
    ([check(conclusion="NEUTRAL")], "unknown", True),
    ([check(), check(2, status="IN_PROGRESS", conclusion=None)], "pending", True),
    ([check(), check(2, conclusion="CANCELLED")], "failing", True),
    ([check(), check(2, conclusion="TIMED_OUT")], "failing", True),
    ([check(), check(2, conclusion="UNRECOGNIZED")], "unknown", False),
    ([check(), {"id": "other", "__typename": "FutureCheck"}], "unknown", False),
    ([{"id": "s", "__typename": "StatusContext", "context": "legacy", "state": "SUCCESS"}], "green", True),
    ([check(), {"id": "s", "__typename": "StatusContext", "context": "legacy", "state": "ERROR"}], "failing", True),
    ([check(), {"id": "s", "__typename": "StatusContext", "context": "legacy", "state": "EXPECTED"}], "pending", True),
])
def test_check_summary_requires_actual_success_without_failed_pending_or_unknown_contexts(rows, state, complete):
    result = remote.check_summary(rows)
    assert result["checks_state"] == state and result["checks_complete"] is complete


def test_capture_rechecks_inventory_and_binds_serialized_bytes():
    inventory = {"pullRequests": connection([pr(draft=True)])}
    scope = remote.capture_pr_scope({"github_repository": REPO},
        Graph(inventory, checks_body([check()]), inventory), limit=3, limit_source="manifest")
    snapshot = remote.validate_frozen_pr_scope(scope, REPO)
    assert snapshot["total_count"] == 1 and snapshot["prs"][0]["is_draft"] is True
    assert snapshot["open_non_draft_limit"] == 3 and scope["limit_source"] == "manifest"
    assert scope["sha256"] == hashlib.sha256(scope["content"].encode()).hexdigest()
    altered = copy.deepcopy(scope)
    altered["content"] += "\n"
    with pytest.raises(WorkflowError, match="checksum"):
        remote.validate_frozen_pr_scope(altered, REPO)
    altered = copy.deepcopy(scope)
    altered["prs"][0]["title"] = "unbound metadata"
    with pytest.raises(WorkflowError, match="metadata"):
        remote.validate_frozen_pr_scope(altered, REPO)


@pytest.mark.parametrize("change", [{"headRefOid": "d" * 40}, {"baseRefOid": "d" * 40},
                                     {"isDraft": True}, {"title": "Changed"}])
def test_capture_never_accepts_inventory_changed_while_collecting_checks(change):
    runner = Graph({"pullRequests": connection([pr()])}, checks_body([check()]),
                   {"pullRequests": connection([pr(**change)])})
    with pytest.raises(WorkflowError, match="inventory changed"):
        remote.capture_pr_scope({"github_repository": REPO}, runner)


@pytest.mark.parametrize("override,expected", [(None, (25, "default")), (7, (7, "manifest"))])
def test_limit_comes_from_validated_manifest_not_a_redeclared_repo_list(tmp_path, override, expected):
    manifest = yaml.safe_load(default_manifest_path().read_bytes())
    entry = manifest["mechs"]["culturemech"]
    entry.pop("open_pr_limit", None)
    if override is not None:
        entry["open_pr_limit"] = override
    path = tmp_path / "manifest.yaml"
    path.write_text(yaml.safe_dump(manifest))
    assert remote.resolve_limit("culturemech", "CultureBotAI/CultureMech", path) == expected
    with pytest.raises(WorkflowError, match="differs"):
        remote.resolve_limit("culturemech", "CultureBotAI/Impostor", path)
    assert remote.resolve_limit("claw", "CultureBotAI/culturebotai-claw", path) == (25, "default")
    with pytest.raises(WorkflowError, match="differs"):
        remote.resolve_limit("claw", REPO, path)


def live_pr(number=1, *, state="OPEN", github=REPO, **changes):
    return {**pr(number), "state": state, "merged": state == "MERGED",
            "mergeCommit": {"oid": MERGE} if state == "MERGED" else None,
            "url": f"https://github.com/{github}/pull/{number}", **changes}


@pytest.fixture
def live(monkeypatch):
    state = SimpleNamespace(prs={(REPO, 1): live_pr()}, issues={},
        checks={(REPO, 1): {"checks_state": "pending", "checks_complete": True,
                           "check_count": 1, "failing_checks": []}}, current=[pr()], calls=[])
    class Observations:
        def __init__(self, github, runner):
            self.github = github
        def live_pr(self, number):
            state.calls.append((self.github, "pr", number))
            return copy.deepcopy(state.prs[(self.github, number)])
        def live_issue(self, number):
            state.calls.append((self.github, "issue", number))
            return copy.deepcopy(state.issues[(self.github, number)])
        def checks(self, number, head):
            assert state.prs[(self.github, number)]["headRefOid"] == head
            return copy.deepcopy(state.checks[(self.github, number)])
        def open_prs(self):
            return copy.deepcopy(state.current), 1
    monkeypatch.setattr(remote, "Observer", Observations)
    state.evidence = {"pr_maintenance": {"inventory": [{"number": 1, "is_draft": False}],
        "dispositions": [{"number": 1, "head_sha": HEAD, "status": "retained"}],
        "shared_check_fixes": [], "remaining_open_non_draft": [1], "open_non_draft_limit": 25}}
    state.receipt = {"pr": {"number": 1, "head_sha": HEAD, "branch": "topic/1"}}
    state.proof = {"status": "merged", "pr_number": 1, "head_sha": HEAD, "merge_commit_sha": MERGE}
    state.target = {"github_repository": REPO}
    def verify():
        return remote.verify_dispositions_live(state.evidence, state.target, state.receipt,
                                               state.proof, lambda *_a, **_k: pytest.fail("unexpected command"))
    state.verify = verify
    return state


def merged(live):
    live.evidence["pr_maintenance"]["dispositions"][0].update(
        status="merged", final_head_sha=HEAD, merge_sha=MERGE)
    live.evidence["pr_maintenance"]["remaining_open_non_draft"] = []
    live.current = []
    live.prs[(REPO, 1)] = live_pr(state="MERGED")


def test_retained_pending_pr_is_read_back_and_counted(live):
    assert live.verify()["remaining_open_non_draft"] == [1]


@pytest.mark.parametrize("change", [{"headRefOid": "d" * 40}, {"number": 2},
                                     {"url": "https://github.com/wrong/repo/pull/1"},
                                     {"state": "CLOSED"}, {"isDraft": True}, {"mergeable": "CONFLICTING"}])
def test_retained_pr_cannot_change_identity_close_or_become_draft_to_evade_limit(live, change):
    live.prs[(REPO, 1)].update(change)
    with pytest.raises(WorkflowError):
        live.verify()


def test_newly_green_retained_pr_requires_its_closure_policy(live):
    live.checks[(REPO, 1)]["checks_state"] = "green"
    with pytest.raises(WorkflowError, match="newly green"):
        live.verify()


def test_merged_pr_requires_matching_live_head_merge_and_existing_closure(live):
    merged(live)
    assert live.verify()["prs"] == [{"number": 1, "state": "MERGED", "head_sha": HEAD}]
    live.proof = {}
    with pytest.raises(WorkflowError, match="closure"):
        live.verify()


@pytest.mark.parametrize("which", ["live-merge", "receipt-head", "live-head", "not-merged"])
def test_merged_disposition_cannot_reuse_another_head_or_merge(live, which):
    merged(live)
    if which == "live-merge":
        live.prs[(REPO, 1)]["mergeCommit"]["oid"] = "d" * 40
    elif which == "receipt-head":
        live.receipt["pr"]["head_sha"] = "d" * 40
    elif which == "live-head":
        live.prs[(REPO, 1)]["headRefOid"] = "d" * 40
    else:
        live.prs[(REPO, 1)]["merged"] = False
    with pytest.raises(WorkflowError):
        live.verify()


@pytest.mark.parametrize("field,value", [("pr_number", 99), ("head_sha", "d" * 40),
                                         ("merge_commit_sha", "d" * 40), ("status", "no_changes")])
def test_merged_disposition_needs_the_same_independently_verified_proof(live, field, value):
    merged(live)
    live.proof[field] = value
    with pytest.raises(WorkflowError, match="closure|proof"):
        live.verify()


@pytest.mark.parametrize("replacement_state", ["OPEN", "MERGED"])
def test_superseded_pr_requires_actual_closed_state_and_existing_successor(live, replacement_state):
    item = live.evidence["pr_maintenance"]["dispositions"][0]
    item.update(status="closed_superseded", replacement_pr_url=f"https://github.com/{REPO}/pull/2")
    live.prs[(REPO, 1)] = live_pr(state="CLOSED")
    live.prs[(REPO, 2)] = live_pr(2, state=replacement_state)
    live.current = []
    live.evidence["pr_maintenance"]["remaining_open_non_draft"] = []
    assert live.verify()["prs"][0]["state"] == "CLOSED"
    live.prs[(REPO, 2)]["state"] = "CLOSED"
    with pytest.raises(WorkflowError, match="replacement"):
        live.verify()


def add_source_fix(live):
    source = "CultureBotAI/culturebotai-claw"
    live.evidence["pr_maintenance"]["shared_check_fixes"] = [{
        "status": "fixed", "source_repository": source,
        "source_issue_url": f"https://github.com/{source}/issues/10",
        "source_fix_pr_url": f"https://github.com/{source}/pull/11"}]
    live.issues[(source, 10)] = {"number": 10, "url": f"https://github.com/{source}/issues/10", "state": "OPEN"}
    live.prs[(source, 11)] = live_pr(11, github=source, state="MERGED")
    return source


def test_shared_check_fix_requires_actual_source_issue_and_merged_source_pr(live):
    source = add_source_fix(live)
    result = live.verify()
    assert result["source_fixes"] == [{"repository": source, "pr_number": 11, "merge_sha": MERGE}]
    assert (source, "issue", 10) in live.calls and (source, "pr", 11) in live.calls


@pytest.mark.parametrize("which", ["null-issue", "wrong-issue-number", "wrong-issue-url", "not-issue",
                                   "unmerged-fix", "missing-merge", "wrong-fix-url"])
def test_unverified_shared_source_issue_or_fix_blocks_closure(live, which):
    source = add_source_fix(live)
    issue, fix = live.issues[(source, 10)], live.prs[(source, 11)]
    if which == "null-issue":
        live.issues[(source, 10)] = None
    elif which == "wrong-issue-number":
        issue["number"] = 11
    elif which == "wrong-issue-url":
        issue["url"] = f"https://github.com/{REPO}/issues/10"
    elif which == "not-issue":
        issue["state"] = "MERGED"
    elif which == "unmerged-fix":
        fix.update(state="OPEN", merged=False)
    elif which == "missing-merge":
        fix["mergeCommit"] = None
    else:
        fix["url"] = f"https://github.com/{REPO}/pull/11"
    with pytest.raises(WorkflowError):
        live.verify()


@pytest.mark.parametrize("current,declared,limit", [([pr(), pr(2)], [1], 25),
                                                   ([pr(), pr(2)], [1, 2], 1),
                                                   ([pr(draft=True)], [1], 25)])
def test_final_inventory_cannot_underreport_or_evade_the_limit(live, current, declared, limit):
    live.current = current
    live.evidence["pr_maintenance"].update(remaining_open_non_draft=declared, open_non_draft_limit=limit)
    with pytest.raises(WorkflowError, match="count"):
        live.verify()


@pytest.fixture
def cleanup(tmp_path):
    root = tmp_path / "main"
    root.mkdir()
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    removed = tmp_path / "owned-feature"
    path = root / "cleanup.json"
    retained = runtime / "retained-note.txt"
    retained.write_text("Synthetic ignored valuable note retained before cleanup\n")
    preservation_path = root / "preservation.json"
    preservation = {"inventory_includes_ignored": True, "worktree_paths": [str(removed)],
                    "retained_files": [{"artifact": str(retained),
                        "sha256": hashlib.sha256(retained.read_bytes()).hexdigest()}]}
    value = {"repository": REPO, "head_sha": HEAD, "branch": "topic/1", "worktree_paths": [str(removed)],
             "preservation_manifest_sha256": "d" * 64}
    member = {"number": 1, "head_sha": HEAD, "branch": "topic/1", "cleanup": {
        "worktree_paths": [str(removed)], "worktree_cleanup": {"artifact": "cleanup.json", "sha256": ""}}}
    state = SimpleNamespace(root=root, runtime=runtime, removed=removed, path=path, value=value, member=member,
        receipt={"pr": member}, target={"root": str(root), "github_repository": REPO},
        stdout=f"worktree {root}\nHEAD {BASE}\nbranch refs/heads/main\n\n", calls=[],
        retained=retained, preservation_path=preservation_path, preservation=preservation)
    def write():
        state.path.write_text(json.dumps(state.value))
        member["cleanup"]["worktree_cleanup"]["sha256"] = hashlib.sha256(state.path.read_bytes()).hexdigest()
    def write_preservation():
        state.preservation_path.write_text(json.dumps(state.preservation))
        digest = hashlib.sha256(state.preservation_path.read_bytes()).hexdigest()
        state.value.update(preservation_manifest={"artifact": str(state.preservation_path), "sha256": digest},
                           preservation_manifest_sha256=digest)
        write()
    def runner(args, **kwargs):
        assert args == ["git", "-C", str(root), "worktree", "list", "--porcelain"]
        state.calls.append(args)
        return SimpleNamespace(returncode=0, stdout=state.stdout)
    def verify():
        return remote.verify_worktree_cleanup(state.receipt, state.target, runner, runtime)
    state.write, state.verify, state.write_preservation = write, verify, write_preservation
    write_preservation()
    return state


def test_removed_owned_worktree_requires_bound_retained_audit(cleanup):
    result = cleanup.verify()
    assert result == [{"pr_number": 1, "head_sha": HEAD, "worktree_paths": [str(cleanup.removed)],
                       "audit_sha256": hashlib.sha256(cleanup.path.read_bytes()).hexdigest()}]
    assert not cleanup.removed.exists() and len(cleanup.calls) == 1


@pytest.mark.parametrize("change", [{"repository": "wrong/repo"}, {"head_sha": "e" * 40},
    {"branch": "someone-elses-topic"}, {"worktree_paths": []}, {"preservation_manifest_sha256": "missing"},
    {"preservation_manifest_sha256": None}])
def test_cleanup_audit_identity_and_preservation_digest_must_match(cleanup, change):
    cleanup.value.update(change)
    cleanup.write()
    with pytest.raises(WorkflowError):
        cleanup.verify()


def test_cleanup_changed_bytes_are_not_accepted_by_old_pin(cleanup):
    cleanup.path.write_bytes(cleanup.path.read_bytes() + b"\n")
    with pytest.raises(WorkflowError, match="bytes changed"):
        cleanup.verify()


@pytest.mark.parametrize("kind", ["present", "symlink", "registered", "ancestor", "noncanonical"])
def test_cleanup_cannot_claim_present_symlink_registered_or_protected_worktree_removed(cleanup, kind):
    if kind == "present":
        cleanup.removed.mkdir()
    elif kind == "symlink":
        cleanup.removed.symlink_to(cleanup.root, target_is_directory=True)
    elif kind == "registered":
        cleanup.stdout += f"worktree {cleanup.removed}\nHEAD {HEAD}\nbranch refs/heads/topic/1\n\n"
    else:
        candidate = cleanup.root.parent if kind == "ancestor" else cleanup.root / ".." / "owned-feature"
        cleanup.value["worktree_paths"] = [str(candidate)]
        cleanup.member["cleanup"]["worktree_paths"] = [str(candidate)]
        cleanup.write()
    with pytest.raises(WorkflowError):
        cleanup.verify()


def test_cleanup_audit_symlink_is_not_a_retained_regular_artifact(cleanup):
    real = cleanup.root / "actual.json"
    cleanup.path.rename(real)
    cleanup.path.symlink_to(real)
    with pytest.raises(WorkflowError):
        cleanup.verify()


def test_cleanup_audit_cannot_escape_owned_evidence_roots(cleanup, tmp_path):
    other = tmp_path / "external.json"
    other.write_bytes(cleanup.path.read_bytes())
    cleanup.member["cleanup"]["worktree_cleanup"]["artifact"] = str(other)
    with pytest.raises(WorkflowError, match="escapes"):
        cleanup.verify()


@pytest.mark.parametrize("output", ["not a porcelain inventory\n", "", "worktree relative/path\nHEAD bogus\n"])
def test_cleanup_requires_a_complete_parseable_registration_inventory(cleanup, output):
    cleanup.stdout = output
    with pytest.raises(WorkflowError, match="worktree|inventory|registration"):
        cleanup.verify()


@pytest.mark.parametrize("payload", ["not-json", "[]", "null"])
def test_malformed_cleanup_audit_fails_closed(cleanup, payload):
    cleanup.path.write_text(payload)
    cleanup.member["cleanup"]["worktree_cleanup"]["sha256"] = hashlib.sha256(cleanup.path.read_bytes()).hexdigest()
    with pytest.raises((WorkflowError, ValueError, TypeError, AttributeError)):
        cleanup.verify()


def test_ordered_closure_proofs_are_matched_to_the_correct_pr(live):
    merged(live)
    member_proof = copy.deepcopy(live.proof)
    live.proof = {"prs": [{"pr_number": 2, "status": "merged", "head_sha": "d" * 40,
                           "merge_commit_sha": "e" * 40}, member_proof]}
    assert live.verify()["prs"][0]["number"] == 1
    live.proof["prs"].pop()
    with pytest.raises(WorkflowError, match="closure"):
        live.verify()


@pytest.mark.parametrize("change", [{"inventory_includes_ignored": False}, {"inventory_includes_ignored": 1},
                                    {"worktree_paths": []}, {"retained_files": None}])
def test_preservation_manifest_requires_exact_ignored_inclusive_inventory(cleanup, change):
    cleanup.preservation.update(change)
    cleanup.write_preservation()
    with pytest.raises(WorkflowError, match="inventory"):
        cleanup.verify()


def test_preservation_manifest_is_read_and_all_three_hash_references_agree(cleanup):
    cleanup.preservation_path.write_bytes(cleanup.preservation_path.read_bytes() + b"\n")
    with pytest.raises(WorkflowError, match="manifest bytes"):
        cleanup.verify()
    cleanup.write_preservation()
    cleanup.value["preservation_manifest_sha256"] = "e" * 64
    cleanup.write()
    with pytest.raises(WorkflowError, match="manifest bytes"):
        cleanup.verify()


@pytest.mark.parametrize("kind", ["missing", "changed", "symlink", "escaped", "bad-descriptor"])
def test_retained_valuable_files_are_reopened_not_trusted_from_the_manifest(cleanup, tmp_path, kind):
    if kind == "missing":
        cleanup.retained.unlink()
    elif kind == "changed":
        cleanup.retained.write_text("Changed after evidence was recorded")
    elif kind == "symlink":
        original = cleanup.runtime / "original.txt"
        cleanup.retained.rename(original)
        cleanup.retained.symlink_to(original)
    elif kind == "escaped":
        outside = tmp_path / "unowned.txt"
        outside.write_bytes(cleanup.retained.read_bytes())
        cleanup.preservation["retained_files"][0]["artifact"] = str(outside)
        cleanup.write_preservation()
    else:
        cleanup.preservation["retained_files"] = ["not a descriptor"]
        cleanup.write_preservation()
    with pytest.raises(WorkflowError):
        cleanup.verify()


@pytest.mark.parametrize("kind", ["absent", "symlink", "escaped"])
def test_preservation_manifest_must_be_retained_regular_bytes_inside_owned_roots(cleanup, tmp_path, kind):
    if kind == "absent":
        cleanup.preservation_path.unlink()
    elif kind == "symlink":
        original = cleanup.root / "actual-preservation.json"
        cleanup.preservation_path.rename(original)
        cleanup.preservation_path.symlink_to(original)
    else:
        outside = tmp_path / "unowned-preservation.json"
        outside.write_bytes(cleanup.preservation_path.read_bytes())
        cleanup.value["preservation_manifest"]["artifact"] = str(outside)
        cleanup.write()
    with pytest.raises(WorkflowError):
        cleanup.verify()


def test_preservation_evidence_can_live_in_explicit_runtime_root(cleanup):
    destination = cleanup.runtime / "preservation.json"
    cleanup.preservation_path.rename(destination)
    cleanup.value["preservation_manifest"]["artifact"] = str(destination)
    cleanup.write()
    assert cleanup.verify()[0]["head_sha"] == HEAD


@pytest.mark.parametrize("suffix", ["garbage after a valid record\n", "worktree /another\nHEAD not-a-sha\n"])
def test_partial_or_malformed_extra_worktree_blocks_are_not_silently_discarded(cleanup, suffix):
    cleanup.stdout += suffix
    with pytest.raises(WorkflowError, match="inventory|worktree|registration"):
        cleanup.verify()


def test_registered_owned_worktree_in_another_declared_checkout_still_blocks(cleanup):
    sibling = cleanup.root.parent / "same-repository-clone"
    cleanup.target["session_repository_roots"] = [str(sibling), str(cleanup.root)]
    calls = []
    def runner(args, **kwargs):
        assert args[:2] == ["git", "-C"] and args[3:] == ["worktree", "list", "--porcelain"]
        calls.append(args[2])
        output = cleanup.stdout if args[2] == str(cleanup.root) else (
            f"worktree {sibling}\nHEAD {BASE}\nbranch refs/heads/main\n\n"
            f"worktree {cleanup.removed}\nHEAD {HEAD}\nbranch refs/heads/topic/1\n\n")
        return SimpleNamespace(returncode=0, stdout=output)
    with pytest.raises(WorkflowError, match="registered"):
        remote.verify_worktree_cleanup(cleanup.receipt, cleanup.target, runner, cleanup.runtime)
    assert calls == [str(cleanup.root), str(sibling)]


def test_failed_worktree_inventory_is_not_treated_as_absence(cleanup):
    with pytest.raises(WorkflowError, match="unavailable"):
        remote.verify_worktree_cleanup(cleanup.receipt, cleanup.target,
            lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout=cleanup.stdout), cleanup.runtime)


def test_one_removed_worktree_cannot_be_claimed_for_two_prs(cleanup):
    another = copy.deepcopy(cleanup.member)
    another["number"] = 2
    cleanup.receipt["prs"] = [cleanup.member, another]
    with pytest.raises(WorkflowError, match="repeated"):
        cleanup.verify()



def test_check_rollup_union_selects_ids_only_on_concrete_types():
    # GitHub StatusCheckRollupContext is a union, not a shared Node interface.
    # Selecting id directly fails the actual API before any inventory can freeze.
    fields = remote.CONTEXT_FIELDS
    assert "nodes{\n __typename ... on CheckRun{id name status conclusion}" in fields
    assert "... on StatusContext{id context state}" in fields
    assert "nodes{\n id" not in fields



def test_terminal_draft_reopened_at_final_inventory_cannot_claim_closure(live):
    live.evidence["pr_maintenance"]["dispositions"][0]["status"] = "closed_stale"
    live.evidence["pr_maintenance"]["remaining_open_non_draft"] = []
    live.prs[(REPO, 1)] = live_pr(state="CLOSED")
    live.current = [pr(draft=True)]
    with pytest.raises(WorkflowError, match="terminal PR reappeared"):
        live.verify()


@pytest.mark.parametrize("field,value", [("headRefOid", "e" * 40), ("baseRefOid", "d" * 40),
    ("updatedAt", "2026-11-15T13:00:00Z"), ("mergeable", "CONFLICTING")])
def test_final_inventory_must_retain_observed_pr_identity(live, field, value):
    live.current[0][field] = value
    with pytest.raises(WorkflowError, match="final inventory"):
        live.verify()
