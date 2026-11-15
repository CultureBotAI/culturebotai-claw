"""Automatic private audit authority is GitHub metadata, never candidate input."""

from __future__ import annotations

import base64
import copy
from datetime import timedelta

import pytest
import test_private_scaleup_audit as fixtures
from test_private_scaleup_audit import APP_ID, NOW, PrivateAPI, PublicAPI

from kg_microbe_governance import automatic_private_audit as auto
from kg_microbe_governance import private_scaleup_audit as manual

MAIN = "c" * 40
HEAD = "a" * 40
MERGE = "e" * 40
PARENT = 201
ATTEMPT = 3


@pytest.fixture
def source():
    return fixtures.source.__wrapped__()


class MetadataAPI(PublicAPI):
    def __init__(self, source):
        self.source = source
        super().__init__({})
        self.current_main = MAIN
        self.parent = {
            "id": PARENT,
            "run_attempt": ATTEMPT,
            "repository": {"id": manual.CONTROL_ID},
            "workflow_id": 501,
            "head_repository": {"id": 700},
            "path": auto.PARENT_WORKFLOW,
            "head_sha": HEAD,
            "head_branch": "feature",
            "event": "pull_request",
            "status": "in_progress",
            "conclusion": None,
            "pull_requests": [{"number": 17}],
        }
        self.pr = {
            "number": 17,
            "state": "open",
            "head": {"sha": HEAD, "ref": "feature", "repo": {"id": 700}},
            "base": {"sha": MAIN, "ref": "main", "repo": {"id": manual.CONTROL_ID}},
            "merge_commit_sha": MERGE,
        }
        self.parent["pull_requests"] = [
            {
                "number": 17,
                "head": copy.deepcopy(self.pr["head"]),
                "base": copy.deepcopy(self.pr["base"]),
            }
        ]
        self.merge = {"sha": MERGE, "parents": [{"sha": MAIN}, {"sha": HEAD}]}
        self.associations = [{"number": 17}]
        self.jobs = {
            "total_count": 2,
            "jobs": [
                {"name": name, "status": "completed", "conclusion": "success"}
                for name in auto.COMPONENT_JOBS
            ],
        }
        self.run.update(
            {
                "workflow_id": 502,
                "event": "workflow_run",
                "path": auto.PRODUCER_WORKFLOW,
            }
        )

    def get(self, path):
        self.calls.append(path)
        if path.endswith("/git/ref/heads/main"):
            return {
                "ref": "refs/heads/main",
                "object": {"type": "commit", "sha": self.current_main},
            }
        if path.endswith("/actions/workflows/governance-fleet-audit.yaml"):
            return {"id": 501, "path": auto.PARENT_WORKFLOW}
        if path.endswith("/actions/workflows/private-scaleup-automatic.yaml"):
            return {"id": 502, "path": auto.PRODUCER_WORKFLOW}
        if path.endswith(f"/runs/{PARENT}/attempts/{ATTEMPT}"):
            return copy.deepcopy(self.parent)
        if path.endswith("/pulls/17"):
            return copy.deepcopy(self.pr)
        if path.endswith("/pulls/18"):
            return {**copy.deepcopy(self.pr), "number": 18}
        if path.endswith("/commits/" + HEAD + "/pulls?per_page=100"):
            return copy.deepcopy(self.associations)
        if path.endswith("/git/commits/" + HEAD):
            return {"sha": HEAD, "parents": [{"sha": MAIN}, {"sha": MAIN}]}
        if path.endswith("/git/commits/" + MERGE):
            return copy.deepcopy(self.merge)
        if path.endswith(f"/attempts/{ATTEMPT}/jobs?per_page=100"):
            return copy.deepcopy(self.jobs)
        if "/contents/" in path:
            raw = self.source[1][manual.CANONICAL_MANIFEST_PATH]
            return {
                "type": "file",
                "encoding": "base64",
                "size": len(raw),
                "content": base64.b64encode(raw).decode(),
            }
        if "/git/ref/heads/gh-readonly-queue/main/" in path:
            return {
                "ref": "refs/heads/" + self.parent["head_branch"],
                "object": {"type": "commit", "sha": self.parent["head_sha"]},
            }
        if "/compare/" in path:
            return {"merge_base_commit": {"sha": self.current_main}, "status": "ahead"}
        return super().get(path)


def binding(public):
    return auto.parent_binding(public, PARENT, ATTEMPT, checkout_sha=MERGE)


def envelope(source, public):
    bound = binding(public)
    context = {
        "sha": MAIN,
        "run_id": 101,
        "run_attempt": 2,
        "workflow": auto.PRODUCER_WORKFLOW,
        "app_id": APP_ID,
        "subject_head": MERGE,
    }
    private = PrivateAPI(*source)
    value = auto.produce(
        public,
        private,
        source[0],
        source[1],
        bound,
        context,
        NOW,
        clock=lambda: NOW + timedelta(seconds=1),
    )
    return value, private


def packaged(source):
    public = MetadataAPI(source)
    value, private = envelope(source, public)
    public.package(value)
    public.artifact["name"] = f"scaleup-automatic-{PARENT}-{ATTEMPT}-101-2"
    return public, value, private


def verify(public, source):
    return auto.verify_producer(
        public,
        source[0],
        binding(public),
        run_id=101,
        attempt=2,
        app_id=APP_ID,
        now=NOW + timedelta(seconds=2),
        clock=lambda: NOW + timedelta(seconds=2),
    )


def test_fork_pr_empty_run_association_uses_exact_commit_association_not_branch_guess(
    source,
):
    public = MetadataAPI(source)
    public.parent["pull_requests"] = []
    result = binding(public)
    assert result["source_head"] == HEAD and result["checkout_sha"] == MERGE
    assert result["source_head"] != result["checkout_sha"]
    assert result["head_repository_id"] == 700 and result["pull_request"] == 17
    assert any("/commits/" + HEAD + "/pulls?" in path for path in public.calls)


@pytest.mark.parametrize(
    "change",
    [
        "attempt",
        "workflow",
        "workflow_id",
        "repository",
        "cancelled",
        "stale_head",
        "closed_pr",
        "base",
        "parent_order",
        "parent_missing",
        "checkout",
        "ambiguous_fork",
        "truncated_fork",
    ],
)
def test_parent_binding_rejects_wrong_or_stale_authority(source, change):
    public = MetadataAPI(source)
    if change == "attempt":
        public.parent["run_attempt"] += 1
    elif change == "workflow":
        public.parent["path"] = ".github/workflows/counterfeit.yaml"
    elif change == "workflow_id":
        public.parent["workflow_id"] += 1
    elif change == "repository":
        public.parent["repository"]["id"] += 1
    elif change == "cancelled":
        public.parent["conclusion"] = "cancelled"
    elif change == "stale_head":
        public.pr["head"]["sha"] = "d" * 40
    elif change == "closed_pr":
        public.pr["state"] = "closed"
    elif change == "base":
        public.pr["base"]["sha"] = "d" * 40
    elif change == "parent_order":
        public.merge["parents"].reverse()
    elif change == "parent_missing":
        public.merge["parents"].pop()
    elif change == "checkout":
        public.pr["merge_commit_sha"] = HEAD
    else:
        public.parent["pull_requests"] = []
        public.associations = (
            [{"number": 17}, {"number": 18}]
            if change == "ambiguous_fork"
            else [{"number": 17}] * 100
        )
    with pytest.raises(manual.AuditError):
        binding(public)


@pytest.mark.parametrize(
    "event", ["push", "schedule", "workflow_dispatch", "merge_group"]
)
def test_supported_non_pr_events_have_exact_subject(source, event):
    public = MetadataAPI(source)
    public.parent.update(event=event, head_sha=MAIN, head_branch="main")
    if event == "merge_group":
        public.parent["head_branch"] = "gh-readonly-queue/main/pr-17-fixture"
    value = auto.parent_binding(public, PARENT, ATTEMPT, checkout_sha=MAIN)
    assert (
        value["event"] == event
        and value["checkout_sha"] == MAIN
        and value["pull_request"] is None
    )
    public.current_main = "d" * 40
    if event != "merge_group":
        with pytest.raises(manual.AuditError):
            auto.parent_binding(public, PARENT, ATTEMPT)


@pytest.mark.parametrize(
    "conclusion", ["failure", "cancelled", "skipped", "neutral", "timed_out"]
)
def test_component_failure_is_never_a_skipped_required_success(source, conclusion):
    public = MetadataAPI(source)
    public.jobs["jobs"][0]["conclusion"] = conclusion
    with pytest.raises(manual.AuditError):
        auto.component_state(public, binding(public))


def test_production_rechecks_private_tip_and_never_fetches_private_records(source):
    public = MetadataAPI(source)
    value, private = envelope(source, public)
    assert private.ref_reads == 3
    assert value["private_tip_recheck"]["sha"] == private.head
    assert not any(private.secret_tree in path for path in private.calls)


def test_actual_automatic_artifact_passes_only_exact_parent_attempt_and_fresh_tip(
    source,
):
    public, _, _ = packaged(source)
    result = verify(public, source)
    assert result.parent["run_attempt"] == ATTEMPT and result.producer_attempt == 2
    assert result.receipt["state"] == "installed"
    assert all(manual.PRIVATE not in path for path in public.calls)


@pytest.mark.parametrize(
    "change",
    [
        "parent_attempt",
        "producer_attempt",
        "producer_workflow",
        "producer_event",
        "producer_head",
        "digest",
        "extra",
        "old_tip",
        "future_tip",
        "tip_sha",
        "source_head",
        "merge_sha",
    ],
)
def test_automatic_receipt_rejects_replay_and_counterfeits(source, change):
    public, value, _ = packaged(source)
    if change == "producer_attempt":
        public.run["run_attempt"] += 1
    elif change == "producer_workflow":
        public.run["path"] = manual.WORKFLOW
    elif change == "producer_event":
        public.run["event"] = "workflow_dispatch"
    elif change == "producer_head":
        public.run["head_sha"] = "d" * 40
    elif change == "digest":
        public.artifact["digest"] = "sha256:" + "0" * 64
    else:
        if change == "parent_attempt":
            value["parent"]["run_attempt"] += 1
        elif change == "extra":
            value["unapproved"] = "synthetic private detail"
        elif change == "old_tip":
            value["private_tip_recheck"]["checked_at"] = (
                NOW - timedelta(seconds=121)
            ).isoformat()
        elif change == "future_tip":
            value["private_tip_recheck"]["checked_at"] = (
                NOW + timedelta(seconds=3)
            ).isoformat()
        elif change == "tip_sha":
            value["private_tip_recheck"]["sha"] = "d" * 40
        elif change == "source_head":
            value["parent"]["source_head"] = MERGE
        else:
            value["parent"]["checkout_sha"] = HEAD
        public.package(value)
        public.artifact["name"] = f"scaleup-automatic-{PARENT}-{ATTEMPT}-101-2"
    with pytest.raises(manual.AuditError):
        verify(public, source)


def test_verifier_refreshes_parent_before_and_after_artifact(source):
    public, _, _ = packaged(source)
    frozen = binding(public)
    public.pr["state"] = "closed"
    with pytest.raises(manual.AuditError):
        auto.verify_producer(
            public,
            source[0],
            frozen,
            run_id=101,
            attempt=2,
            app_id=APP_ID,
            now=NOW + timedelta(seconds=2),
            clock=lambda: NOW + timedelta(seconds=2),
        )
    public.pr["state"] = "open"
    original_request = public.request

    def moved_after_download(path, *, archive=False):
        raw = original_request(path, archive=archive)
        public.pr["head"]["sha"] = "f" * 40
        return raw

    public.request = moved_after_download
    with pytest.raises(manual.AuditError):
        auto.verify_producer(
            public,
            source[0],
            frozen,
            run_id=101,
            attempt=2,
            app_id=APP_ID,
            now=NOW + timedelta(seconds=2),
            clock=lambda: NOW + timedelta(seconds=2),
        )


@pytest.mark.parametrize("identity", [701, None, True])
def test_fork_association_requires_the_actual_run_source_repository(source, identity):
    public = MetadataAPI(source)
    public.parent["pull_requests"] = []
    public.parent["head_repository"] = {"id": identity}
    with pytest.raises(manual.AuditError):
        binding(public)


@pytest.mark.parametrize(
    "side,field", [("head", "sha"), ("base", "sha"), ("head", "repo"), ("base", "ref")]
)
def test_recorded_parent_pr_snapshot_cannot_be_replaced_by_current_api_metadata(
    source, side, field
):
    public = MetadataAPI(source)
    record = public.parent["pull_requests"][0][side]
    record[field] = (
        {"id": 999} if field == "repo" else "d" * 40 if field == "sha" else "other"
    )
    with pytest.raises(manual.AuditError):
        binding(public)


def test_private_observation_time_precedes_slow_public_revalidation(source):
    public = MetadataAPI(source)
    frozen = binding(public)
    private = PrivateAPI(*source)
    clock = {"now": NOW, "private_read": False}
    original_private_get, original_public_get = private.get, public.get

    def private_get(path):
        value = original_private_get(path)
        if private.ref_reads == 3:
            clock["private_read"] = True
        return value

    def public_get(path):
        if clock["private_read"]:
            clock["now"] = NOW + timedelta(seconds=180)
        return original_public_get(path)

    private.get, public.get = private_get, public_get
    context = {
        "sha": MAIN,
        "run_id": 101,
        "run_attempt": 2,
        "workflow": auto.PRODUCER_WORKFLOW,
        "app_id": APP_ID,
        "subject_head": MERGE,
    }
    value = auto.produce(
        public,
        private,
        source[0],
        source[1],
        frozen,
        context,
        NOW,
        clock=lambda: clock["now"],
    )
    assert manual.utc(value["private_tip_recheck"]["checked_at"]) == NOW
    with pytest.raises(manual.AuditError):
        auto.validate_envelope(
            auto.canonical(value),
            source[0],
            frozen,
            auto.private_obligation(public, frozen, source[0]),
            app_id=APP_ID,
            producer_run_id=101,
            producer_attempt=2,
            now=clock["now"],
        )


def test_verification_rechecks_age_after_slow_artifact_and_parent_metadata(source):
    public, _, _ = packaged(source)
    frozen = binding(public)
    clock = {"now": NOW + timedelta(seconds=2)}
    original_request = public.request

    def slow_download(path, *, archive=False):
        raw = original_request(path, archive=archive)
        clock["now"] = NOW + timedelta(seconds=122)
        return raw

    public.request = slow_download
    with pytest.raises(manual.AuditError):
        auto.verify_producer(
            public,
            source[0],
            frozen,
            run_id=101,
            attempt=2,
            app_id=APP_ID,
            now=NOW + timedelta(seconds=2),
            clock=lambda: clock["now"],
        )


@pytest.mark.parametrize("state", ["ready", "setup", "failed", "missing", "duplicate"])
def test_private_mint_waits_until_final_verifier_has_finished_setup(source, state):
    public = MetadataAPI(source)
    bound = binding(public)
    job = {
        "name": "fleet-audit",
        "status": "in_progress",
        "steps": [
            {
                "name": "Verify exact full coverage or public-only bootstrap",
                "status": "in_progress",
            }
        ],
    }
    if state == "setup":
        job["steps"][0]["status"] = "queued"
    elif state == "failed":
        job["status"] = "completed"
    if state != "missing":
        public.jobs["jobs"].append(job)
    if state == "duplicate":
        public.jobs["jobs"].append(copy.deepcopy(job))
    public.jobs["total_count"] = len(public.jobs["jobs"])
    tick = iter([0, 11])
    if state == "ready":
        auto.wait_verifier_ready(
            public,
            bound,
            timeout=10,
            sleep=lambda n: None,
            monotonic=lambda: next(tick),
        )
    else:
        with pytest.raises(manual.AuditError):
            auto.wait_verifier_ready(
                public,
                bound,
                timeout=10,
                sleep=lambda n: None,
                monotonic=lambda: next(tick),
            )


def test_public_expected_app_id_must_match_the_protected_producer(source):
    public, _, _ = packaged(source)
    with pytest.raises(manual.AuditError):
        auto.verify_producer(
            public,
            source[0],
            binding(public),
            run_id=101,
            attempt=2,
            app_id=APP_ID + 1,
            now=NOW + timedelta(seconds=2),
            clock=lambda: NOW + timedelta(seconds=2),
        )
