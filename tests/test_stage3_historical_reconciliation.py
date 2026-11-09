"""Synthetic NPM C4S3: historical closure and external work remain distinct."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from test_historical_goal_reconciliation import new_record, tree
from test_mech_session_supervisor import (  # noqa: F401 -- shared offline fixtures
    HEAD,
    CycleGitHubFixture,
    cycle_instance,
    cycle_setup,
    setup,
    supervisor,
)

from kg_microbe_progress import prs
from kg_microbe_workflows import reconciliation as rec

REPOSITORY = "CultureBotAI/NaturalProductMech"


class Stage3Remote(CycleGitHubFixture):
    """Allowlisted read-only synthetic Git and GitHub responses."""
    def __init__(self, state):
        super().__init__(state.repo)
        self.state = state
        self.ancestry_fail = set()
        self.pr.update(created_at="2026-10-25T02:00:00Z", merged_at="2026-10-26T01:00:00Z")
        self.pr["base"]["repo"]["full_name"] = REPOSITORY
        self.pr["head"]["repo"]["full_name"] = REPOSITORY
        self.externals = {
            item["number"]: {
                "number": item["number"], "merged": True,
                "created_at": f"2026-10-30T0{index}:00:00Z",
                "merged_at": f"2026-10-30T0{index}:30:00Z",
                "merge_commit_sha": item["merge_commit_sha"],
                "head": {"sha": item["head_sha"], "ref": item["branch"], "repo": {"full_name": REPOSITORY}},
                "base": {"ref": "main", "repo": {"full_name": REPOSITORY}},
            } for index, item in enumerate(state.external_prs, 1)
        }
        self.snapshot()

    def __call__(self, args, **kwargs):
        output = None
        code = 0
        if args[:3] == ["git", "-C", str(supervisor.ROOT)]:
            assert args[3:] in [["rev-parse", "HEAD"], ["status", "--porcelain=v1", "--untracked-files=all"]]
            output = "f" * 40 if args[3] == "rev-parse" else ""
        elif args[:1] == ["git"] and args[3:] == ["remote", "get-url", "origin"]:
            output = f"https://github.com/{REPOSITORY}.git\n"
        elif args[:1] == ["git"] and args[3:5] == ["merge-base", "--is-ancestor"]:
            output, code = "", int(tuple(args[-2:]) in self.ancestry_fail)
        elif args[:2] == ["gh", "api"]:
            endpoint = args[-1]
            if endpoint == f"repos/{REPOSITORY}/pulls/1054":
                output = json.dumps(self.pr)
            elif endpoint.startswith(f"repos/{REPOSITORY}/pulls/") and endpoint.rsplit("/", 1)[-1].isdigit():
                output = json.dumps(self.externals[int(endpoint.rsplit("/", 1)[-1])])
            elif endpoint in {f"repos/{REPOSITORY}/issues/1055", f"repos/{REPOSITORY}/issues/1056"}:
                output = json.dumps(self.issue)
        if output is not None:
            self.calls.append(args)
            return SimpleNamespace(stdout=output, stderr="", returncode=code)
        return super().__call__(args, **kwargs)


def write_record(state):
    state.record_path.write_text(json.dumps(state.record, indent=2) + "\n")


def refresh(state):
    """Refresh test attestation after intentional fixture changes, not live state."""
    (state.session / "completion.json").write_text(json.dumps(state.receipt))
    state.record["fingerprints"] = rec.fingerprints(state.config_path, state.session, state.target, state.proof)
    write_record(state)


def apply(state):
    return rec.prepare(state.instance, supervisor, state.config_path, state.record_path,
                       rec.sha(state.record_path.read_bytes()), apply=True)


def ledger(state):
    return json.loads((state.session / "ledger.json").read_text())


def stage3_record(state, operation="close_historical_goal", prior=None):
    record = new_record(state, operation, prior)
    record.pop("external_pr")
    record.update(schema_version="2.0.0", transition="v1_protein_examples_to_record_review",
                  native_proof_mode="checkpoint_before_external",
                  required_infra_tasks=[], external_prs=copy.deepcopy(state.external_prs))
    return record


@pytest.fixture
def npm(cycle_setup, monkeypatch):  # noqa: F811 -- imported fixture
    state = cycle_setup
    profile_path = Path(state.target["workflow_profile_path"])
    profile = json.loads(profile_path.read_text())
    profile.update(repository_key="naturalproductmech", github_repository=REPOSITORY, profile_id="synthetic-npm-workflow")
    profile_path.write_text(json.dumps(profile))
    state.target.update(repository_key="naturalproductmech", github_repository=REPOSITORY, initial_stage=3,
                        native_session_id="synthetic-npm")
    effective = supervisor.load_effective(state.config, state.target)
    state.target.update(_workflow=effective, stages=effective["stages"])
    state.ledger = supervisor.new_ledger(state.config, state.target)
    historical = {"conversation_id": "synthetic-npm", "start_step_index": 13623, "started_at": "2026-10-25T01:00:00Z"}
    state.current = {**historical, "start_step_index": 14303, "started_at": "2026-10-29T01:00:00Z"}
    state.ledger.update(cycle=4, adopted_goal=historical, baseline_status="", baseline_head=HEAD,
                        phase="requires_intervention")
    state.ledger["actions"] = {
        f"repair-{index}": {"kind": "repair_closure", "stage": 3, "cycle": 4, "state": "accepted",
                           "goal_identity": copy.deepcopy(historical), "reserved_epoch_ms": index}
        for index in range(3)
    }
    state.ledger["completed_stages"] = [{"stage": 2, "cycle": 4, "stage_key": "causal_graphs", "parent_version": "1.0.0",
        "goal_identity": {**historical, "start_step_index": 13000}, "verification": {"pr_number": 1000},
        "workflow_sha256": state.ledger["workflow"]["sha256"]}]
    state.external_prs = [
        {"number": number, "head_sha": head * 40, "merge_commit_sha": merge * 40,
         "branch": f"synthetic-chelators-{index}", "goal_identity": copy.deepcopy(state.current),
         "native_statement": {"step_index": 16985, "text_sha256": "1" * 64}}
        for index, (number, head, merge) in enumerate([(1057, "d", "e"), (1062, "1", "2")], 1)
    ]
    state.external = {}  # Legacy helper field; removed from schema2 below.
    state.receipt.update(repository_key="naturalproductmech", cycle=4, stage=3, goal_identity=copy.deepcopy(historical),
                         workflow_sha256=state.ledger["workflow"]["sha256"])
    state.receipt["pr"]["number"] = 1054
    state.receipt["issues"] = [{"number": number, "disposition": "addressed", "fix_commit_sha": "c" * 40}
                               for number in (1055, 1056)]
    state.remote = Stage3Remote(state)
    state.instance = cycle_instance(state, monkeypatch, send=lambda *_: pytest.fail("must not send"))
    state.instance.notifier = object()
    state.proof = {"historical_goal_identity": historical, "current_goal_identity": state.current,
                   "historical_completions": [{"step_index": 14275}], "current_completions": [{"step_index": 16985}]}
    state.native_calls = []
    def prove(*args, **kwargs):
        state.native_calls.append((args, copy.deepcopy(kwargs)))
        assert kwargs["github_repository"] == REPOSITORY
        assert kwargs["native_proof_mode"] == state.record["native_proof_mode"]
        assert kwargs["external_prs"] == state.record["external_prs"]
        return copy.deepcopy(state.proof)
    state.instance.native = SimpleNamespace(reconciliation_evidence=prove)
    state.session = state.instance.directory(state.target)
    state.instance.save(state.target, state.ledger)
    state.config_path = state.runtime / "config.json"
    state.config_path.write_text(json.dumps(state.config))
    (state.session / "completion.json").write_text(json.dumps(state.receipt))
    row = {**prs._context(state.ledger), "schema_version": 1, "pr_number": 1054, "reported_at": "2026-10-29T00:00:00Z"}
    (state.session / prs.REGISTRY_NAME).write_text(json.dumps(row) + "\n")
    (state.runtime / "STOP").write_text("synthetic maintenance hold\n")
    state.review = state.runtime / "independent-review.md"
    state.review.write_text("Synthetic exact-record independent review.\n")
    state.record_path = state.runtime / "assessment.json"
    state.record = stage3_record(state)
    write_record(state)
    return state


def test_stage3_dry_run_and_apply_preserve_both_external_prs_without_stage_credit(npm):
    before = tree(npm.runtime)
    registry = (npm.session / prs.REGISTRY_NAME).read_bytes()
    result = rec.prepare(npm.instance, supervisor, npm.config_path, npm.record_path)
    assert result["status"] == "dry_run" and result["to_stage"] == 4 and not result["sent_input"]
    assert tree(npm.runtime) == before
    result = apply(npm)
    after = ledger(npm)
    assert (after["cycle"], after["stage"], supervisor.workflow_stage_key(after)) == (4, 4, "record_review")
    assert after["phase"] == "blocked" and after["awaiting_goal"]
    assert "infra_scope" not in after
    for key in ("adopted_goal", "actions", "workflow"):
        assert after[key] == npm.ledger[key]
    assert after["completed_stages"][:-1] == npm.ledger["completed_stages"]
    closed = after["completed_stages"][-1]
    assert closed["goal_identity"]["start_step_index"] == 13623 and closed["verification"]["pr_number"] == 1054
    audit = after["historical_reconciliations"][result["reconciliation_sha256"]]
    assert [item["number"] for item in audit["external_pr_verifications"]] == [1057, 1062]
    assert all(item["goal_identity"] == npm.current for item in audit["external_pr_verifications"])
    assert audit["assessment"]["external_prs"] == npm.external_prs
    assert after["historical_goal_boundary"]["released_by"] is None
    assert (npm.session / prs.REGISTRY_NAME).read_bytes() == registry
    assert (npm.runtime / "STOP").read_bytes() == before["STOP"]
    repeated = tree(npm.runtime)
    assert apply(npm)["status"] == "already_applied" and tree(npm.runtime) == repeated
    assert len(npm.native_calls) >= 4


def release_record(state):
    prior = apply(state)["reconciliation_sha256"]
    state.record = stage3_record(state, "release_boundary", prior)
    state.record_path = state.runtime / "release.json"
    write_record(state)


def test_separate_release_retains_new_native_goal_acceptance_guard(npm):
    apply(npm)
    held = ledger(npm)
    observation = copy.deepcopy(npm.observation)
    observation.update(goal_identity=npm.current)
    assert supervisor.decide(held, observation)["phase"] == "blocked"
    release_record(npm)
    apply(npm)
    released = ledger(npm)
    assert rec.boundary_goal(released) == npm.current
    decision = supervisor.decide(released, observation)
    assert decision["action"] == "start_goal"
    assert supervisor.decide(released, {**observation, "ready": False})["phase"] == "waiting"
    assert supervisor.decide(released, {**observation, "goal_state": "active"})["phase"] == "blocked"
    released["actions"][decision["action_id"]] = {
        "kind": "start_goal", "stage": 4, "cycle": 4, "goal_identity": released["adopted_goal"],
        "state": "sent", "marker": "synthetic-next-stage", "native_session_id": "synthetic-npm", "reserved_epoch_ms": 0}
    observation["native"]["current_goal"]["goal_text"] = "synthetic-next-stage"
    npm.instance.reconcile(npm.target, released, observation)
    assert released["awaiting_goal"] and released["adopted_goal"]["start_step_index"] == 13623
    next_goal = {**npm.current, "start_step_index": 17000, "started_at": "2026-11-01T01:00:00Z"}
    observation["goal_identity"] = next_goal
    observation["native"]["current_goal"]["goal_text"] = "no accepted instruction"
    npm.instance.reconcile(npm.target, released, observation)
    assert released["awaiting_goal"]
    observation["native"]["current_goal"]["goal_text"] = "synthetic-next-stage"
    npm.instance.reconcile(npm.target, released, observation)
    assert released["adopted_goal"] == next_goal and not released["awaiting_goal"]
    assert "historical_goal_boundary" not in released
    assert len(released["completed_stages"]) == len(npm.ledger["completed_stages"]) + 1


@pytest.mark.parametrize("mutation", ["reorder", "remove", "head", "statement", "schema", "mode"])
def test_release_cannot_change_external_attribution_or_version(npm, mutation):
    release_record(npm)
    if mutation == "reorder":
        npm.record["external_prs"].reverse()
    elif mutation == "remove":
        npm.record["external_prs"].pop()
    elif mutation == "head":
        npm.record["external_prs"][0]["head_sha"] = "9" * 40
    elif mutation == "statement":
        npm.record["external_prs"][0]["native_statement"]["text_sha256"] = "9" * 64
    elif mutation == "mode":
        npm.record["native_proof_mode"] = "retained_public_attestation"
    else:
        npm.record["schema_version"] = "1.0.0"
    write_record(npm)
    before = tree(npm.runtime)
    with pytest.raises(rec.ReconciliationError):
        apply(npm)
    assert tree(npm.runtime) == before


@pytest.mark.parametrize("failure", ["open_issue", "review", "review_head", "head", "evidence", "final_head_evidence", "cleanup", "dirty", "failed_check", "unmerged", "fix_missing"])
def test_stage3_preserves_ordinary_acceptance_gates(npm, failure):
    if failure == "open_issue":
        npm.remote.issue = {"state": "open"}
    elif failure == "review":
        npm.receipt["review"]["remaining_findings"] = 1
    elif failure == "review_head":
        npm.receipt["review"]["head_sha"] = "9" * 40
    elif failure == "head":
        npm.remote.pr["head"]["sha"] = "9" * 40
    elif failure == "evidence":
        npm.receipt["coverage"]["sha256"] = "9" * 64
    elif failure == "final_head_evidence":
        npm.remote.tree["INFRA_TASKS.md"] = "9" * 40
    elif failure == "cleanup":
        npm.remote.remote_code = 0
    elif failure == "dirty":
        npm.remote.dirty = " M data/synthetic.yaml\n"
    elif failure == "failed_check":
        npm.remote.checks = [{"bucket": "fail", "state": "FAILURE"}]
    elif failure == "unmerged":
        npm.remote.pr["merged"] = False
    else:
        npm.remote.commits = [[{"sha": HEAD}]]
    refresh(npm)
    before = tree(npm.runtime)
    with pytest.raises((rec.ReconciliationError, supervisor.SupervisorError)):
        apply(npm)
    assert tree(npm.runtime) == before


@pytest.mark.parametrize("failure", ["stage", "key", "parent", "no_changes", "ordered", "duplicate", "duplicate_merge", "overlap", "external_goal"])
def test_stage3_contract_cannot_be_repurposed(npm, failure):
    if failure == "stage":
        npm.record["stage"] = 5
    elif failure == "key":
        npm.record["transition"] = "v1_causal_graphs_to_record_review"
    elif failure == "parent":
        npm.record["parent_version"] = "2.0.0"
    elif failure == "no_changes":
        npm.receipt.update(status="no_changes", pr=None, issues=[])
    elif failure == "ordered":
        from kg_microbe_workflows.closure import multi_pr_members
        last = {**copy.deepcopy(npm.receipt["pr"]), "merge_commit_sha": "b" * 40,
                **{key: copy.deepcopy(npm.receipt[key]) for key in ("review", "validation", "cleanup")}}
        first = copy.deepcopy(last)
        first.update(number=1053, head_sha="7" * 40, merge_commit_sha="8" * 40, branch="synthetic-first")
        first["review"]["head_sha"] = first["head_sha"]
        first["validation"][0]["head_sha"] = first["head_sha"]
        npm.receipt["prs"] = [first, last]
        npm.receipt["evidence_attributions"] = []
        for issue in npm.receipt["issues"]:
            issue["pr_number"] = 1054
        assert len(multi_pr_members(npm.receipt)) == 2
    elif failure == "duplicate":
        npm.record["external_prs"][1] = copy.deepcopy(npm.record["external_prs"][0])
    elif failure == "duplicate_merge":
        npm.record["external_prs"][1]["merge_commit_sha"] = npm.record["external_prs"][0]["merge_commit_sha"]
    elif failure == "overlap":
        npm.record["external_prs"][0]["number"] = 1054
    else:
        npm.record["external_prs"][0]["goal_identity"] = copy.deepcopy(npm.ledger["adopted_goal"])
    refresh(npm)
    before = tree(npm.runtime)
    with pytest.raises((rec.ReconciliationError, supervisor.SupervisorError),
                       match="ordinary single-PR" if failure in {"ordered", "no_changes"} else None):
        apply(npm)
    assert tree(npm.runtime) == before


@pytest.mark.parametrize("failure", ["repo", "head_repo", "base", "branch", "head", "merge", "unmerged", "created_before_goal", "merged_before_created", "future", "order", "not_ancestor", "missing_from_main"])
def test_external_pr_facts_and_chronology_fail_closed(npm, failure):
    remote = npm.remote.externals[1057]
    if failure in {"repo", "head_repo"}:
        remote["base" if failure == "repo" else "head"]["repo"]["full_name"] = "Other/NaturalProductMech"
    elif failure == "base":
        remote["base"]["ref"] = "feature"
    elif failure == "branch":
        remote["head"]["ref"] += "-wrong"
    elif failure == "head":
        remote["head"]["sha"] = "9" * 40
    elif failure == "merge":
        remote["merge_commit_sha"] = "9" * 40
    elif failure == "unmerged":
        remote["merged"] = False
    elif failure == "created_before_goal":
        remote["created_at"] = "2026-10-28T01:00:00Z"
    elif failure == "merged_before_created":
        remote["merged_at"] = "2026-10-29T02:00:00Z"
    elif failure == "future":
        remote["merged_at"] = "2099-01-01T00:00:00Z"
    elif failure == "order":
        npm.record["external_prs"].reverse()
    elif failure == "not_ancestor":
        npm.remote.ancestry_fail.add(("e" * 40, "2" * 40))
    else:
        npm.remote.ancestry_fail.add(("e" * 40, "HEAD"))
    write_record(npm)
    before = tree(npm.runtime)
    with pytest.raises(rec.ReconciliationError):
        apply(npm)
    assert tree(npm.runtime) == before


@pytest.mark.parametrize("mutation", ["historical_key", "next_key", "effective_parent"])
def test_protocol_checks_actual_pinned_transition_not_just_record_labels(npm, mutation):
    changed = ledger(npm)
    effective = changed["workflow"]["effective"]
    if mutation == "effective_parent":
        effective["parent_version"] = "2.0.0"
    else:
        number = 3 if mutation == "historical_key" else 4
        next(item for item in effective["stages"] if item["stage"] == number)["key"] = "causal_graphs"
    changed["workflow"]["sha256"] = supervisor.digest(effective)
    npm.instance.save(npm.target, changed)
    npm.record["workflow_sha256"] = changed["workflow"]["sha256"]
    npm.receipt["workflow_sha256"] = changed["workflow"]["sha256"]
    refresh(npm)
    before = tree(npm.runtime)
    with pytest.raises(rec.ReconciliationError, match="actual pinned v1"):
        apply(npm)
    assert tree(npm.runtime) == before
