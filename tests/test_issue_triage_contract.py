"""Versioned stage keys, frozen issue evidence, severity and shared-budget regressions."""

import copy
import json

import pytest
import yaml

from kg_microbe_workflows import (
    LEGACY_PARENT_PATH,
    LEGACY_SCHEMA_PATH,
    PARENT_PATH,
    SCHEMA_PATH,
    WorkflowError,
    evidence_directory,
    evidence_stage_key,
    load_document,
    load_effective_workflow,
    read_goal_evidence,
    save_goal_evidence,
    sha256,
    stage_count_for_version,
    stage_key,
    stage_keys_for_version,
    validate_goal_evidence,
    validate_parent,
)
from kg_microbe_workflows.issue_triage import (
    issue_triage_blockers,
    severity_from_labels,
    validate_issue_snapshot,
)

REPO = "CultureBotAI/TraitMech"
FROZEN = "2026-11-06T10:00:00Z"


def materialize(root, data, *, inventory=False):
    triage = data["issue_triage"]
    directory = evidence_directory(data["run_id"], data["cycle"], 1, data["revision"])
    payloads = {
        "issue_groups": {"groups": triage["groups"]},
        "group_plans": {"plans": triage["group_plans"]},
        "dispositions": {"dispositions": triage["dispositions"]},
        "validation": {"checks": "offline example validation only"},
    }
    if inventory:
        payloads["issue_inventory"] = {
            "repository": data["github_repository"],
            "frozen_at": data["scope_frozen_at"],
            "issues": [
                {key: item[key] for key in ("number", "title", "labels", "updatedAt")}
                for item in triage["inventory"]
            ],
            "complete": True,
            "total_count": len(triage["inventory"]),
            "pages": 1,
        }
    artifacts = {item["kind"]: item for item in data["artifacts"]}
    for kind, value in payloads.items():
        path = f"{directory}/{kind}.json"
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(value, sort_keys=True) + "\n")
        artifacts[kind] = {"path": path, "sha256": sha256(target.read_bytes()), "kind": kind}
    data["artifacts"] = list(artifacts.values())


def triage_evidence(root, *, empty=False):
    data = {
        "schema_version": "2.0.0",
        "parent_version": "2.0.0",
        "stage_key": "open_issue_triage",
        "repository_key": "traitmech",
        "github_repository": REPO,
        "run_id": "triage-run",
        "cycle": 1,
        "stage": 1,
        "revision": 1,
        "outcome": "no_findings" if empty else "completed",
        "summary": "Frozen issues assessed.",
        "source_revision": "a" * 40,
        "scope_frozen_at": FROZEN,
        "artifacts": [],
        "findings": [],
        "groups": [],
        "carry_forward_ids": [],
        "infra_tasks": [],
    }
    inventory = (
        []
        if empty
        else [
            {
                "number": number,
                "title": f"Issue {number}",
                "labels": [],
                "updatedAt": "2026-11-06T09:00:00Z",
                "severity": severity,
                "reason": "Measured impact.",
                "assigned_labels": [f"severity:{severity}"],
            }
            for number, severity in [(1, "high"), (2, "medium"), (3, "medium"), (4, "low")]
        ]
    )
    groups = (
        []
        if empty
        else [
            {
                "group_id": "mandatory",
                "issue_numbers": [1],
                "size": 1,
                "shared_cause": "Required correction",
                "tracking_issue_url": f"https://github.com/{REPO}/issues/100",
                "sub_issue_numbers": [1],
            },
            {
                "group_id": "large",
                "issue_numbers": [2, 3],
                "size": 2,
                "shared_cause": "Shared parser",
                "tracking_issue_url": f"https://github.com/{REPO}/issues/101",
                "sub_issue_numbers": [2, 3],
            },
            {"group_id": "small", "issue_numbers": [4], "size": 1, "shared_cause": "Documentation"},
        ]
    )
    validation = evidence_directory("triage-run", 1, 1, 1) + "/validation.json"
    dispositions = (
        []
        if empty
        else [
            {
                "number": 1,
                "group_id": "mandatory",
                "status": "fixed",
                "reason": "Corrected.",
                "resolution_evidence": [validation],
                "pr_urls": [f"https://github.com/{REPO}/pull/10"],
                "commit_sha": "b" * 40,
            },
            {
                "number": 2,
                "group_id": "large",
                "status": "deferred",
                "reason": "Needs follow-up after bounded attempt.",
            },
            {
                "number": 3,
                "group_id": "large",
                "status": "deferred",
                "reason": "Same bounded attempt.",
            },
            {
                "number": 4,
                "group_id": "small",
                "status": "deferred",
                "reason": "Outside this cycle's selected groups.",
            },
        ]
    )
    budget = (
        {
            "limit_seconds": 14400,
            "selected_group_ids": [],
            "work_intervals": [],
            "unused_reason": "No remaining open issues.",
        }
        if empty
        else {
            "limit_seconds": 14400,
            "critical_high_completed_at": "2026-11-06T11:00:00Z",
            "started_at": "2026-11-06T11:00:00Z",
            "ended_at": "2026-11-06T15:00:00Z",
            "selected_group_ids": ["large"],
            "work_intervals": [
                {
                    "group_id": "large",
                    "actor": actor,
                    "started_at": "2026-11-06T11:00:00Z",
                    "ended_at": "2026-11-06T15:00:00Z",
                }
                for actor in ["codex_primary", "agy_secondary"]
            ],
        }
    )
    data["issue_triage"] = {
        "inventory": inventory,
        "groups": groups,
        "group_plans": [
            {"group_id": group["group_id"], "plan": "Implement, validate and independently review."}
            for group in groups
        ],
        "dispositions": dispositions,
        "budget": budget,
        "carry_forward_group_ids": [] if empty else ["large", "small"],
    }
    materialize(root, data, inventory=True)
    return data


def test_v2_parent_preserves_infrastructure_and_closure_policy():
    old, new = (load_document(path.read_bytes()) for path in [LEGACY_PARENT_PATH, PARENT_PATH])
    validate_parent(old, LEGACY_SCHEMA_PATH)
    validate_parent(new)
    assert len(old["stages"]) == 6 and len(new["stages"]) == 7
    assert new["stages"][0]["key"] == "open_issue_triage"
    assert new["infrastructure_policy"] == old["infrastructure_policy"]
    assert new["closure_policy"] == old["closure_policy"]
    assert {key: value for key, value in new["stages"][-1].items() if key != "stage"} == {
        key: value for key, value in old["stages"][-1].items() if key != "stage"
    }


def test_pinned_v1_profile_still_loads_without_rewriting_bytes(tmp_path):
    parent = load_document(LEGACY_PARENT_PATH.read_bytes())
    profile = {
        "schema_version": "1.0.0",
        "profile_id": "legacy",
        "profile_version": "1.0.0",
        "repository_key": "traitmech",
        "github_repository": REPO,
        "adaptation_skill": ".claude/skills/local/SKILL.md",
        "parent": {
            "id": parent["id"],
            "version": parent["version"],
            "sha256": sha256(LEGACY_PARENT_PATH.read_bytes()),
            "schema_sha256": sha256(LEGACY_SCHEMA_PATH.read_bytes()),
            "repository": "CultureBotAI/culturebotai-claw",
            "revision": "a" * 40,
        },
        "stages": [
            {
                "stage": item["stage"],
                "key": item["key"],
                "goal_text": item["goal_text"],
                "applicability": "enabled",
                "skill_paths": [".claude/skills/local/SKILL.md"],
            }
            for item in parent["stages"]
        ],
    }
    path = tmp_path / "profile.yaml"
    path.write_text(yaml.safe_dump(profile))
    before = path.read_bytes()
    effective = load_effective_workflow(LEGACY_PARENT_PATH, path, schema_path=LEGACY_SCHEMA_PATH)
    assert effective["parent_version"] == "1.0.0" and len(effective["stages"]) == 6
    assert path.read_bytes() == before


def test_stage_identity_comes_from_parent_version_not_number():
    assert stage_keys_for_version("1.2.3")[0] == "add_records"
    assert stage_count_for_version("1.0.0") == 6
    assert stage_count_for_version("2.0.0") == 7
    assert stage_key({"parent_version": "1.0.0"}, 6) == "infrastructure"
    assert stage_key({"parent_version": "2.0.0"}, 6) == "resolve_review_findings"
    assert evidence_stage_key({"schema_version": "1.0.0", "stage": 4}) == "record_review"
    with pytest.raises(WorkflowError):
        stage_keys_for_version("3.0.0")
    with pytest.raises(WorkflowError):
        evidence_stage_key({"schema_version": "2.0.0", "stage": 4})


@pytest.mark.parametrize("empty", [True, False])
def test_frozen_triage_and_parallel_shared_four_hour_budget_validate(tmp_path, empty):
    data = triage_evidence(tmp_path, empty=empty)
    path = save_goal_evidence(tmp_path, data)
    assert read_goal_evidence(path, repository_root=tmp_path) == data
    assert issue_triage_blockers(data) == []


@pytest.mark.parametrize(
    "repo,label,severity",
    [
        *(
            ("cellstructuremech", f"P{i}", value)
            for i, value in enumerate(("critical", "high", "medium", "low"))
        ),
        *(
            ("habitatmech", f"priority: P{i}", value)
            for i, value in enumerate(("critical", "high", "medium"))
        ),
    ],
)
def test_existing_priority_labels_map_without_new_priority_labels(repo, label, severity):
    assert severity_from_labels([label], repo) == severity
    assert severity_from_labels([label], "traitmech") is None


@pytest.mark.parametrize(
    "labels",
    [["severity:high", "severity:low"], ["severity:unknown"], ["P0", "P1"], ["P0", "severity:low"]],
)
def test_conflicting_existing_priority_labels_require_resolution(labels):
    with pytest.raises(WorkflowError):
        severity_from_labels(labels, "cellstructuremech")


@pytest.mark.parametrize(
    "fault",
    [
        "scope_missing",
        "scope_added",
        "scope_mutated",
        "missing_label",
        "duplicate_label",
        "reason",
        "missing_plan",
        "wrong_group",
        "duplicate_members",
        "high_deferred",
        "blocked_missing_prerequisite",
        "hidden_blocker",
        "no_fix_proof",
        "wrong_pr",
        "cap",
        "sum_of_agents",
        "before_mandatory",
        "smaller_group",
        "third_group",
        "missing_work",
        "carry",
        "missing_tracking",
        "subissues",
        "hidden_no_findings",
        "missing_parent",
        "wrong_key",
    ],
)
def test_triage_rejects_unfrozen_unaccounted_or_unbounded_work(tmp_path, fault):
    data = triage_evidence(tmp_path)
    triage = data["issue_triage"]
    budget = triage["budget"]
    if fault == "scope_missing":
        triage["inventory"].pop()
    elif fault == "scope_added":
        triage["inventory"].append({**triage["inventory"][-1], "number": 5})
    elif fault == "scope_mutated":
        triage["inventory"][0]["title"] = "Changed frozen title"
    elif fault == "missing_label":
        triage["inventory"][0]["assigned_labels"] = []
    elif fault == "duplicate_label":
        triage["inventory"][0]["assigned_labels"].append("severity:low")
    elif fault == "reason":
        triage["inventory"][0]["reason"] = " "
    elif fault == "missing_plan":
        triage["group_plans"].pop()
    elif fault == "wrong_group":
        triage["dispositions"][0]["group_id"] = "large"
    elif fault == "duplicate_members":
        triage["groups"][1]["issue_numbers"] = [2, 2]
    elif fault in {"high_deferred", "blocked_missing_prerequisite", "hidden_blocker"}:
        triage["dispositions"][0]["status"] = "deferred" if fault == "high_deferred" else "blocked"
        triage["carry_forward_group_ids"].append("mandatory")
        if fault == "hidden_blocker":
            triage["dispositions"][0]["prerequisite"] = "Requires reviewed upstream fix."
    elif fault == "no_fix_proof":
        triage["dispositions"][0]["resolution_evidence"] = []
    elif fault == "wrong_pr":
        triage["dispositions"][0]["pr_urls"] = ["https://github.com/elsewhere/repo/pull/10"]
    elif fault == "cap":
        budget["limit_seconds"] = 28800
    elif fault == "sum_of_agents":
        budget["ended_at"] = "2026-11-06T19:00:00Z"
        budget["work_intervals"][1].update(
            started_at="2026-11-06T15:00:00Z", ended_at="2026-11-06T19:00:00Z"
        )
    elif fault == "before_mandatory":
        budget["critical_high_completed_at"] = "2026-11-06T12:00:00Z"
    elif fault == "smaller_group":
        budget["selected_group_ids"] = ["small"]
    elif fault == "third_group":
        budget["selected_group_ids"] = ["large", "small", "mandatory"]
    elif fault == "missing_work":
        budget["work_intervals"] = []
    elif fault == "carry":
        triage["carry_forward_group_ids"] = []
    elif fault == "missing_tracking":
        del triage["groups"][0]["tracking_issue_url"]
    elif fault == "subissues":
        triage["groups"][1]["sub_issue_numbers"] = [2]
    elif fault == "hidden_no_findings":
        data["outcome"] = "no_findings"
    elif fault == "missing_parent":
        del data["parent_version"]
    elif fault == "wrong_key":
        data["stage_key"] = "add_records"
    materialize(tmp_path, data)
    with pytest.raises(WorkflowError):
        validate_goal_evidence(data, repository_root=tmp_path)


def test_mandatory_blocker_is_retained_and_holds_closure(tmp_path):
    data = triage_evidence(tmp_path)
    triage = data["issue_triage"]
    triage["dispositions"][0].update(status="blocked", prerequisite="Upstream schema decision")
    triage["carry_forward_group_ids"].append("mandatory")
    triage["budget"] = {
        "limit_seconds": 14400,
        "selected_group_ids": [],
        "work_intervals": [],
        "unused_reason": "Critical/high work blocked before budget starts.",
    }
    data["outcome"] = "blocked"
    materialize(tmp_path, data)
    validate_goal_evidence(data, repository_root=tmp_path)
    assert issue_triage_blockers(data) == [1]


@pytest.mark.parametrize("fault", ["count", "pages", "complete", "repo", "timestamp", "duplicate"])
def test_frozen_snapshot_proves_complete_scope(tmp_path, fault):
    data = triage_evidence(tmp_path)
    path = next(item["path"] for item in data["artifacts"] if item["kind"] == "issue_inventory")
    snapshot = json.loads((tmp_path / path).read_text())
    if fault == "count":
        snapshot["total_count"] += 1
    elif fault == "pages":
        snapshot["pages"] = 0
    elif fault == "complete":
        snapshot["complete"] = False
    elif fault == "repo":
        snapshot["repository"] = "Elsewhere/repo"
    elif fault == "timestamp":
        snapshot["issues"][0]["updatedAt"] = "2026-11-06T11:00:00Z"
    else:
        snapshot["issues"][1] = copy.deepcopy(snapshot["issues"][0])
    with pytest.raises(WorkflowError):
        validate_issue_snapshot(snapshot, REPO)


def test_deferred_group_identity_survives_next_cycle(tmp_path):
    prior = triage_evidence(tmp_path)
    old = save_goal_evidence(tmp_path, prior)
    data = copy.deepcopy(prior)
    data["cycle"] = 2
    data["previous_evidence"] = {
        "path": old.relative_to(tmp_path).as_posix(),
        "sha256": sha256(old.read_bytes()),
    }
    data["issue_triage"]["dispositions"][0]["resolution_evidence"] = [
        evidence_directory("triage-run", 2, 1, 1) + "/validation.json"
    ]
    materialize(tmp_path, data, inventory=True)
    validate_goal_evidence(data, repository_root=tmp_path)
    for group in data["issue_triage"]["groups"]:
        if group["group_id"] == "small":
            group["group_id"] = "renamed"
    for plan in data["issue_triage"]["group_plans"]:
        if plan["group_id"] == "small":
            plan["group_id"] = "renamed"
    data["issue_triage"]["dispositions"][-1]["group_id"] = "renamed"
    data["issue_triage"]["carry_forward_group_ids"][-1] = "renamed"
    materialize(tmp_path, data)
    with pytest.raises(WorkflowError, match="stable IDs"):
        validate_goal_evidence(data, repository_root=tmp_path)


def test_new_v2_review_can_reference_unchanged_v1_resolution(tmp_path):
    from test_workflow_contract import evidence, resolution, save_evidence

    _, previous = resolution(tmp_path)
    previous_path = save_evidence(tmp_path, previous)
    old_bytes = previous_path.read_bytes()
    data = evidence(tmp_path, stage=4, cycle=2)
    data.update(schema_version="2.0.0", parent_version="2.0.0", stage_key="record_review", stage=5)
    for artifact in data["artifacts"]:
        old_path = tmp_path / artifact["path"]
        artifact["path"] = artifact["path"].replace("/stage-04/", "/stage-05/")
        new_path = tmp_path / artifact["path"]
        new_path.parent.mkdir(parents=True, exist_ok=True)
        new_path.write_bytes(old_path.read_bytes())
    data["previous_evidence"] = {
        "path": previous_path.relative_to(tmp_path).as_posix(),
        "sha256": sha256(old_bytes),
    }
    validate_goal_evidence(data, repository_root=tmp_path)
    assert previous_path.read_bytes() == old_bytes


@pytest.mark.parametrize(
    "field,value",
    [
        ("deferred_budget_seconds", 28800),
        ("carry_unused_budget", True),
        ("max_deferred_groups", 3),
        ("severity_labels", ["priority:high"]),
    ],
)
def test_parent_cannot_weaken_issue_triage_policy(field, value):
    parent = load_document(PARENT_PATH.read_bytes())
    parent["issue_triage_policy"][field] = value
    with pytest.raises(WorkflowError):
        validate_parent(parent)


def test_new_schema_class_is_stage_key_and_version_bound(tmp_path):
    from kg_microbe_workflows import _validator

    data = triage_evidence(tmp_path)
    assert not list(_validator(SCHEMA_PATH.read_text(), "IssueTriageEvidence").iter_errors(data))
    assert list(_validator(SCHEMA_PATH.read_text(), "ReviewReport").iter_errors(data))


def test_all_optional_groups_blocked_records_zero_work_with_prerequisites(tmp_path):
    data = triage_evidence(tmp_path)
    triage = data["issue_triage"]
    for item in triage["dispositions"][1:]:
        item.update(status="blocked", prerequisite="Awaiting source license decision")
    triage["budget"] = {
        "limit_seconds": 14400,
        "selected_group_ids": [],
        "work_intervals": [],
        "unused_reason": "Every remaining group has a recorded prerequisite.",
    }
    materialize(tmp_path, data)
    validate_goal_evidence(data, repository_root=tmp_path)


def test_severity_mix_breaks_equal_group_size_ties(tmp_path):
    data = triage_evidence(tmp_path)
    triage = data["issue_triage"]
    triage["groups"][1]["issue_numbers"] = [2]
    triage["groups"][1]["size"] = 1
    triage["groups"][1]["sub_issue_numbers"] = [2]
    triage["groups"][-1]["issue_numbers"] = [3, 4]
    triage["groups"][-1]["size"] = 2
    triage["dispositions"][2]["group_id"] = "small"
    materialize(tmp_path, data)
    with pytest.raises(WorkflowError, match="largest first"):
        validate_goal_evidence(data, repository_root=tmp_path)
    # Drop the third issue from this fixture's frozen universe, leaving one
    # medium issue against one low issue. The medium group wins the true tie.
    triage["inventory"] = [item for item in triage["inventory"] if item["number"] != 3]
    triage["dispositions"] = [item for item in triage["dispositions"] if item["number"] != 3]
    triage["groups"][-1]["issue_numbers"] = [4]
    triage["groups"][-1]["size"] = 1
    materialize(tmp_path, data, inventory=True)
    validate_goal_evidence(data, repository_root=tmp_path)


def test_revised_triage_cannot_restart_budget_or_refreeze_inventory(tmp_path):
    prior = triage_evidence(tmp_path)
    previous_path = save_goal_evidence(tmp_path, prior)
    data = copy.deepcopy(prior)
    data["revision"] = 2
    data["supersedes_evidence"] = {
        "path": previous_path.relative_to(tmp_path).as_posix(),
        "sha256": sha256(previous_path.read_bytes()),
    }
    data["issue_triage"]["dispositions"][0]["resolution_evidence"] = [
        evidence_directory(data["run_id"], 1, 1, 2) + "/validation.json"
    ]
    materialize(tmp_path, data, inventory=True)
    validate_goal_evidence(data, repository_root=tmp_path)
    data["issue_triage"]["budget"]["started_at"] = "2026-11-06T11:01:00Z"
    for interval in data["issue_triage"]["budget"]["work_intervals"]:
        interval["started_at"] = "2026-11-06T11:01:00Z"
    materialize(tmp_path, data)
    with pytest.raises(WorkflowError, match="restart the shared budget"):
        validate_goal_evidence(data, repository_root=tmp_path)


def test_v2_packaged_empty_triage_example_validates():
    root = PARENT_PATH.parent.parent / "examples"
    path = root / evidence_directory("example-triage-run", 1, 1, 1) / "evidence.yaml"
    data = read_goal_evidence(path, repository_root=root)
    assert data["outcome"] == "no_findings" and data["issue_triage"]["inventory"] == []


def test_smaller_group_cannot_replace_larger_even_with_consistent_work_claims(tmp_path):
    data = triage_evidence(tmp_path)
    triage = data["issue_triage"]
    triage["budget"]["selected_group_ids"] = ["small"]
    for interval in triage["budget"]["work_intervals"]:
        interval["group_id"] = "small"
    triage["groups"][-1].update(
        tracking_issue_url=f"https://github.com/{REPO}/issues/102", sub_issue_numbers=[4]
    )
    materialize(tmp_path, data)
    with pytest.raises(WorkflowError, match="largest first"):
        validate_goal_evidence(data, repository_root=tmp_path)


def test_priority_mapping_cannot_be_downgraded_by_assessed_severity(tmp_path):
    data = triage_evidence(tmp_path)
    data["repository_key"] = "cellstructuremech"
    item = data["issue_triage"]["inventory"][0]
    item["labels"] = ["P0"]
    item["assigned_labels"] = ["P0", "severity:high"]
    materialize(tmp_path, data, inventory=True)
    with pytest.raises(WorkflowError, match="mapped priority"):
        validate_goal_evidence(data, repository_root=tmp_path)


def blocked_then_active_revision(root):
    """#853: optional coordination is added only after a mandatory blocker clears."""
    prior = triage_evidence(root)
    active_budget = copy.deepcopy(prior["issue_triage"]["budget"])
    prior["outcome"] = "blocked"
    prior["issue_triage"]["dispositions"][0].update(
        status="blocked", prerequisite="Awaiting approved identifier definition"
    )
    prior["issue_triage"]["carry_forward_group_ids"].append("mandatory")
    prior["issue_triage"]["budget"] = {
        "limit_seconds": 14400,
        "selected_group_ids": [],
        "work_intervals": [],
        "unused_reason": "Mandatory prerequisite blocks optional work.",
    }
    for field in ("tracking_issue_url", "sub_issue_numbers"):
        prior["issue_triage"]["groups"][1].pop(field)
    materialize(root, prior, inventory=True)
    path = save_goal_evidence(root, prior)
    original = path.read_bytes()
    data = copy.deepcopy(prior)
    data.update(
        revision=2,
        outcome="completed",
        supersedes_evidence={"path": path.relative_to(root).as_posix(), "sha256": sha256(original)},
    )
    triage = data["issue_triage"]
    triage["dispositions"][0]["status"] = "fixed"
    triage["dispositions"][0].pop("prerequisite")
    triage["dispositions"][0]["resolution_evidence"] = [
        evidence_directory(data["run_id"], 1, 1, 2) + "/validation.json"
    ]
    triage["carry_forward_group_ids"].remove("mandatory")
    triage["budget"] = active_budget
    triage["groups"][1].update(
        tracking_issue_url=f"https://github.com/{REPO}/issues/101", sub_issue_numbers=[2, 3]
    )
    materialize(root, data, inventory=True)
    return prior, path, original, data


def test_blocked_revision_can_activate_group_without_changing_frozen_scope(tmp_path):
    prior, old_path, old_bytes, data = blocked_then_active_revision(tmp_path)
    new_path = save_goal_evidence(tmp_path, data)
    assert old_path.read_bytes() == old_bytes
    assert read_goal_evidence(new_path, repository_root=tmp_path) == data
    assert issue_triage_blockers(prior) == [1] and issue_triage_blockers(data) == []
    assert "started_at" not in prior["issue_triage"]["budget"]
    assert data["issue_triage"]["budget"]["started_at"] == "2026-11-06T11:00:00Z"
    assert next(a["sha256"] for a in prior["artifacts"] if a["kind"] == "issue_inventory") == next(
        a["sha256"] for a in data["artifacts"] if a["kind"] == "issue_inventory"
    )


@pytest.mark.parametrize(
    "change", ["cause", "membership_order", "existing_tracking", "inactive_metadata"]
)
def test_activation_does_not_allow_frozen_scope_or_tracking_replacement(tmp_path, change):
    _, _, _, data = blocked_then_active_revision(tmp_path)
    groups = data["issue_triage"]["groups"]
    if change == "cause":
        groups[1]["shared_cause"] = "Unrelated work substituted"
    elif change == "membership_order":
        groups[1]["issue_numbers"] = [3, 2]
    elif change == "existing_tracking":
        groups[0]["tracking_issue_url"] = f"https://github.com/{REPO}/issues/999"
    else:
        groups[2].update(
            tracking_issue_url=f"https://github.com/{REPO}/issues/102", sub_issue_numbers=[4]
        )
    materialize(tmp_path, data)
    with pytest.raises(WorkflowError):
        save_goal_evidence(tmp_path, data)


def cumulative_budget_revision(root):
    """#863: a worked group becomes blocked but keeps its cycle-wide allocation."""
    prior = triage_evidence(root)
    triage = prior["issue_triage"]
    triage["inventory"].append(
        {
            "number": 5,
            "title": "Third optional group",
            "labels": [],
            "updatedAt": "2026-11-06T09:00:00Z",
            "severity": "low",
            "reason": "Independent documentation issue",
            "assigned_labels": ["severity:low"],
        }
    )
    triage["groups"].append(
        {"group_id": "tiny", "issue_numbers": [5], "size": 1, "shared_cause": "Independent docs"}
    )
    triage["group_plans"].append(
        {"group_id": "tiny", "plan": "Check and correct the stale example."}
    )
    triage["dispositions"].append(
        {
            "number": 5,
            "group_id": "tiny",
            "status": "deferred",
            "reason": "Outside selected groups.",
        }
    )
    triage["carry_forward_group_ids"].append("tiny")
    triage["budget"]["ended_at"] = "2026-11-06T12:00:00Z"
    triage["budget"]["work_intervals"] = [
        {
            "group_id": "large",
            "actor": "codex_primary",
            "started_at": "2026-11-06T11:00:00Z",
            "ended_at": "2026-11-06T12:00:00Z",
        }
    ]
    materialize(root, prior, inventory=True)
    first = save_goal_evidence(root, prior)
    data = copy.deepcopy(prior)
    data.update(
        revision=2,
        supersedes_evidence={
            "path": first.relative_to(root).as_posix(),
            "sha256": sha256(first.read_bytes()),
        },
    )
    triage = data["issue_triage"]
    triage["dispositions"][0]["resolution_evidence"] = [
        evidence_directory(data["run_id"], 1, 1, 2) + "/validation.json"
    ]
    for item in triage["dispositions"]:
        if item["number"] in [2, 3]:
            item.update(
                status="blocked", prerequisite="Upstream decision discovered during attempted fix"
            )
    triage["groups"][2].update(
        tracking_issue_url=f"https://github.com/{REPO}/issues/102", sub_issue_numbers=[4]
    )
    triage["budget"]["selected_group_ids"].append("small")
    triage["budget"]["ended_at"] = "2026-11-06T14:00:00Z"
    triage["budget"]["work_intervals"].append(
        {
            "group_id": "small",
            "actor": "agy_secondary",
            "started_at": "2026-11-06T12:00:00Z",
            "ended_at": "2026-11-06T14:00:00Z",
        }
    )
    materialize(root, data, inventory=True)
    return prior, first, data


def test_revision_retains_blocked_worked_group_and_adds_only_one_new_group(tmp_path):
    prior, first, data = cumulative_budget_revision(tmp_path)
    before = first.read_bytes()
    saved = save_goal_evidence(tmp_path, data)
    assert first.read_bytes() == before
    assert read_goal_evidence(saved, repository_root=tmp_path) == data
    assert data["issue_triage"]["budget"]["selected_group_ids"] == ["large", "small"]
    assert (
        data["issue_triage"]["budget"]["work_intervals"][0]
        == prior["issue_triage"]["budget"]["work_intervals"][0]
    )


def test_revision_cannot_rotate_three_worked_groups_through_two_group_cap(tmp_path):
    _, _, data = cumulative_budget_revision(tmp_path)
    triage = data["issue_triage"]
    triage["groups"][-1].update(
        tracking_issue_url=f"https://github.com/{REPO}/issues/103", sub_issue_numbers=[5]
    )
    triage["budget"]["selected_group_ids"] = ["small", "tiny"]
    triage["budget"]["work_intervals"] = [
        {
            "group_id": group_id,
            "actor": actor,
            "started_at": "2026-11-06T12:00:00Z",
            "ended_at": "2026-11-06T14:00:00Z",
        }
        for group_id, actor in [("small", "codex_primary"), ("tiny", "agy_secondary")]
    ]
    materialize(tmp_path, data)
    with pytest.raises(WorkflowError, match="cycle-wide group selection is cumulative"):
        save_goal_evidence(tmp_path, data)


@pytest.mark.parametrize("change", ["erase", "retime", "end_backwards", "required_done"])
def test_revision_cannot_erase_or_retime_recorded_budget_history(tmp_path, change):
    _, _, data = cumulative_budget_revision(tmp_path)
    budget = data["issue_triage"]["budget"]
    if change == "erase":
        budget["work_intervals"] = budget["work_intervals"][1:]
    elif change == "retime":
        budget["work_intervals"][0]["started_at"] = "2026-11-06T11:01:00Z"
    elif change == "end_backwards":
        budget["ended_at"] = "2026-11-06T11:30:00Z"
    else:
        budget["critical_high_completed_at"] = "2026-11-06T10:30:00Z"
    materialize(tmp_path, data)
    with pytest.raises(WorkflowError):
        save_goal_evidence(tmp_path, data)
