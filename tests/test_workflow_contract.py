"""The contract must reject weakened policy and stale or disappearing review evidence."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from kg_microbe_workflows import (
    PARENT_PATH,
    SCHEMA_PATH,
    WorkflowError,
    evidence_directory,
    load_document,
    load_effective_workflow,
    read_goal_evidence,
    sha256,
    validate_goal_evidence,
    validate_parent,
)
from kg_microbe_workflows.__main__ import main


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return path


@pytest.fixture
def profile(tmp_path):
    parent = load_document(PARENT_PATH.read_bytes())
    data = {
        "schema_version": "1.0.0", "profile_id": "traitmech-workflow", "profile_version": "1.0.0",
        "repository_key": "traitmech", "github_repository": "CultureBotAI/TraitMech",
        "adaptation_skill": ".claude/skills/traitmech-evolve-workflow/SKILL.md",
        "parent": {"id": parent["id"], "version": parent["version"],
                   "sha256": sha256(PARENT_PATH.read_bytes()),
                   "schema_sha256": sha256(SCHEMA_PATH.read_bytes()),
                   "repository": "CultureBotAI/culturebotai-claw", "revision": "a" * 40},
        "stages": [{"stage": stage["stage"], "key": stage["key"],
                    "goal_text": stage["goal_text"], "skill_paths": [".claude/skills/local/SKILL.md"],
                    "applicability": "enabled"} for stage in parent["stages"]],
    }
    return write(tmp_path / "workflow/mech-workflow.yaml", data), data


def evidence(tmp_path, stage=4, cycle=1, revision=1):
    directory = evidence_directory("run-1", cycle, stage, revision)
    kinds = {4: ["review_report", "review_findings"], 5: ["issue_map", "validation"],
             6: ["infra_snapshot", "implementation_plan", "validation"]}.get(stage, ["validation"])
    artifacts = []
    for kind in kinds:
        path = f"{directory}/{kind}.md"
        target = tmp_path / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("<!-- mech-infra-tasks:start -->\n```yaml\nschema_version: '1.0.0'\ntasks: []\n```\n<!-- mech-infra-tasks:end -->\n" if kind == "infra_snapshot" else "Explicitly reviewed; no findings.\n")
        artifacts.append({"path": path, "sha256": sha256(target.read_bytes()), "kind": kind})
    data = {"schema_version": "1.0.0", "repository_key": "traitmech",
            "github_repository": "CultureBotAI/TraitMech", "run_id": "run-1", "cycle": cycle,
            "stage": stage, "revision": revision, "outcome": "no_findings", "summary": "Reviewed.",
            "source_revision": "b" * 40, "artifacts": artifacts, "findings": [], "groups": [],
            "carry_forward_ids": [], "infra_tasks": []}
    if stage in {5, 6}:
        data["scope_frozen_at"] = "2026-10-20T00:00:00Z"
    return data


def save_evidence(root, data):
    directory = evidence_directory(data["run_id"], data["cycle"], data["stage"], data["revision"])
    return write(root / directory / "evidence.yaml", data)


def resolution(root):
    prior = evidence(root)
    prior.update(outcome="completed", findings=[{"finding_id": "F-1", "status": "open",
                                                "summary": "A missing example"}],
                 carry_forward_ids=["F-1"])
    path = save_evidence(root, prior)
    data = evidence(root, 5)
    issue = "https://github.com/CultureBotAI/TraitMech/issues/12"
    data.update(outcome="completed", findings=[{"finding_id": "F-1", "status": "resolved",
        "summary": "A missing example", "group_id": "G-1", "issue_url": issue,
        "carried_from": "F-1"}], groups=[{"group_id": "G-1", "finding_ids": ["F-1"],
        "issue_url": issue, "status": "resolved", "summary": "Examples",
        "resolution_evidence": [data["artifacts"][1]["path"]]}],
        previous_evidence={"path": path.relative_to(root).as_posix(),
                           "sha256": sha256(path.read_bytes())})
    return prior, data


def test_packaged_parent_and_profile_resolve_exactly_six_stages(profile):
    path, data = profile
    result = load_effective_workflow(PARENT_PATH, path, "traitmech")
    assert [s["stage"] for s in result["stages"]] == [1, 2, 3, 4, 5, 6]
    assert result["cycle_policy"]["restart_stage"] == 1
    assert result["schema_sha256"] == data["parent"]["schema_sha256"]
    assert len(result["sources"]) == 3
    assert all(Path(item["path"]).is_absolute() for item in result["sources"])


@pytest.mark.parametrize("key", ["sha256", "schema_sha256", "version", "id", "repository"])
def test_parent_pins_fail_closed(profile, key):
    path, data = profile
    data["parent"][key] = "0" * 64 if "sha256" in key else "unexpected"
    write(path, data)
    with pytest.raises(WorkflowError):
        load_effective_workflow(PARENT_PATH, path)


@pytest.mark.parametrize("change", ["reorder", "remove", "duplicate", "skip_review", "no_skills",
                                    "traversal", "override", "unknown"])
def test_profile_cannot_weaken_goal_contract(profile, change):
    path, data = profile
    if change == "reorder":
        data["stages"][0], data["stages"][1] = data["stages"][1], data["stages"][0]
    elif change == "remove":
        data["stages"].pop()
    elif change == "duplicate":
        data["stages"].append(data["stages"][0].copy())
    elif change == "skip_review":
        data["stages"][3].update(applicability="not_applicable", applicability_reason="Too large")
    elif change == "no_skills":
        data["stages"][0]["skill_paths"] = []
    elif change == "traversal":
        data["adaptation_skill"] = "../other/SKILL.md"
    elif change == "override":
        data["closure_policy"] = {"every_goal": False}
    else:
        data["surprise"] = True
    write(path, data)
    with pytest.raises(WorkflowError):
        load_effective_workflow(PARENT_PATH, path)


@pytest.mark.parametrize("policy,key", [
    ("closure_policy", "independent_review"), ("closure_policy", "rereview_after_fixes"),
    ("review_policy", "immutable_versions"), ("review_policy", "require_tracked_committed"),
    ("infrastructure_policy", "freeze_scope_at_stage_start"),
    ("cycle_policy", "restart_after_final_closure"),
])
def test_parent_cannot_weaken_required_invariants(policy, key):
    parent = load_document(PARENT_PATH.read_bytes())
    parent[policy][key] = False
    with pytest.raises(WorkflowError, match="weakened"):
        validate_parent(parent)


def test_weakened_supplied_schema_does_not_replace_canonical_shape(profile, tmp_path):
    path, data = profile
    schema = load_document(SCHEMA_PATH.read_bytes())
    schema["classes"]["WorkflowProfile"]["attributes"]["adaptation_skill"]["required"] = False
    schema_path = write(tmp_path / "weakened.yaml", schema)
    data["parent"]["schema_sha256"] = sha256(schema_path.read_bytes())
    del data["adaptation_skill"]
    write(path, data)
    with pytest.raises(WorkflowError):
        load_effective_workflow(PARENT_PATH, path, schema_path=schema_path)


def test_nonapplicable_domain_stage_requires_reason(profile):
    path, data = profile
    data["stages"][1]["applicability"] = "not_applicable"
    write(path, data)
    with pytest.raises(WorkflowError, match="reason"):
        load_effective_workflow(PARENT_PATH, path)
    data["stages"][1]["applicability_reason"] = "No native graph storage; revisit when added"
    write(path, data)
    assert load_effective_workflow(PARENT_PATH, path)["stages"][1]["applicability_reason"]


def test_local_extension_is_validated_and_never_merges_parent_policy(profile):
    path, data = profile
    schema = {"id": "https://example.org/local", "name": "local", "default_range": "string",
              "types": {"string": {"base": "str", "uri": "http://www.w3.org/2001/XMLSchema#string"}},
              "classes": {"LocalAdaptation": {"attributes": {
                  "domain": {"range": "string", "required": True}}}}}
    schema_path = write(path.parent / "schema/local.yaml", schema)
    data_path = write(path.parent / "adaptation.yaml", {"domain": "Traits"})
    data["extension"] = {"schema_path": "schema/local.yaml", "schema_sha256": sha256(schema_path.read_bytes()),
        "class_name": "LocalAdaptation", "data_path": "adaptation.yaml", "data_sha256": sha256(data_path.read_bytes())}
    write(path, data)
    result = load_effective_workflow(PARENT_PATH, path)
    assert result["adaptation"] == {"domain": "Traits"}
    assert len(result["sources"]) == 5
    write(data_path, {"closure_policy": {"every_goal": False}})
    data["extension"]["data_sha256"] = sha256(data_path.read_bytes())
    write(path, data)
    with pytest.raises(WorkflowError, match="extension validation"):
        load_effective_workflow(PARENT_PATH, path)


@pytest.mark.parametrize("raw", ["x: 1\nx: 2\n", "x: &x 1\ny: *x\n", "x: .nan\n", "[]", "1: x"])
def test_rejects_ambiguous_yaml(raw):
    with pytest.raises(WorkflowError):
        load_document(raw)


@pytest.mark.parametrize("stage", [1, 2, 3, 4, 6])
def test_explicit_empty_goal_evidence_validates_and_preserves_identity(tmp_path, stage):
    data = evidence(tmp_path, stage)
    path = save_evidence(tmp_path, data)
    assert read_goal_evidence(path, repository_root=tmp_path, expected={"stage": stage}) == data


def test_stage_five_empty_review_requires_real_prior_evidence(tmp_path):
    prior, data = evidence(tmp_path), evidence(tmp_path, 5)
    path = save_evidence(tmp_path, prior)
    data["previous_evidence"] = {"path": path.relative_to(tmp_path).as_posix(),
                                 "sha256": sha256(path.read_bytes())}
    validate_goal_evidence(data, repository_root=tmp_path, previous=prior)
    with pytest.raises(WorkflowError, match="requires the pinned"):
        validate_goal_evidence(data)


@pytest.mark.parametrize("failure", ["missing_report", "hash", "mutable_path", "wrong_cycle",
                                     "hidden_finding", "duplicate_artifact", "skip", "carry"])
def test_review_evidence_rejects_invalid_claims(tmp_path, failure):
    data = evidence(tmp_path)
    expected = None
    if failure == "missing_report":
        data["artifacts"].pop()
    elif failure == "hash":
        (tmp_path / data["artifacts"][0]["path"]).write_text("Changed")
    elif failure == "mutable_path":
        data["artifacts"][0]["path"] = "reviews/workflow/latest.md"
    elif failure == "wrong_cycle":
        expected = {"cycle": 2}
    elif failure == "hidden_finding":
        data["findings"] = [{"finding_id": "F-1", "status": "resolved", "summary": "Hidden"}]
    elif failure == "duplicate_artifact":
        data["artifacts"].append(data["artifacts"][0])
    elif failure == "skip":
        data["outcome"] = "not_applicable"
    elif failure == "carry":
        data["outcome"] = "completed"
        data["findings"] = [{"finding_id": "F-1", "status": "open", "summary": "Missing"}]
    with pytest.raises(WorkflowError):
        validate_goal_evidence(data, repository_root=tmp_path, expected=expected)


def test_resolved_review_groups_preserve_full_issue_traceability(tmp_path):
    prior, data = resolution(tmp_path)
    validate_goal_evidence(data, repository_root=tmp_path, previous=prior)


@pytest.mark.parametrize("failure", ["disappear", "remap", "ungrouped", "duplicate_group", "wrong_repo",
                                     "no_fix_evidence", "open", "defer_without_reason", "stale", "scope"])
def test_review_resolution_rejects_broken_lineage(tmp_path, failure):
    prior, data = resolution(tmp_path)
    if failure == "disappear":
        data["findings"] = []
    elif failure == "remap":
        data["findings"][0]["carried_from"] = "OTHER"
    elif failure == "ungrouped":
        data["groups"] = []
    elif failure == "duplicate_group":
        data["groups"][0]["finding_ids"].append("F-1")
    elif failure == "wrong_repo":
        data["groups"][0]["issue_url"] = "https://github.com/other/repo/issues/1"
    elif failure == "no_fix_evidence":
        data["groups"][0]["resolution_evidence"] = []
    elif failure in {"open", "defer_without_reason"}:
        status = "open" if failure == "open" else "deferred"
        data["groups"][0]["status"] = data["findings"][0]["status"] = status
        data["carry_forward_ids"] = ["F-1"]
    elif failure == "stale":
        prior["cycle"] = 2
    elif failure == "scope":
        del data["scope_frozen_at"]
    with pytest.raises(WorkflowError):
        validate_goal_evidence(data, repository_root=tmp_path, previous=prior)


def test_next_cycle_review_keeps_unresolved_ids_and_prior_pin(tmp_path):
    prior = evidence(tmp_path)
    prior.update(outcome="completed", findings=[{"finding_id": "F-1", "status": "open", "summary": "Open"}],
                 carry_forward_ids=["F-1"])
    prior_path = save_evidence(tmp_path, prior)
    data = evidence(tmp_path, cycle=2)
    data.update(outcome="completed", findings=[{"finding_id": "F-1", "status": "open", "summary": "Open", "carried_from": "F-1"}],
                carry_forward_ids=["F-1"], previous_evidence={"path": prior_path.relative_to(tmp_path).as_posix(),
                                                            "sha256": sha256(prior_path.read_bytes())})
    validate_goal_evidence(data, repository_root=tmp_path, previous=prior)
    data["findings"] = []
    data["carry_forward_ids"] = []
    with pytest.raises(WorkflowError, match="disappeared"):
        validate_goal_evidence(data, repository_root=tmp_path, previous=prior)


def test_infrastructure_plan_requires_issue_and_fix_artifacts(tmp_path):
    data = evidence(tmp_path, 6)
    data.update(outcome="completed", infra_tasks=[{"task_id": "INFRA-1", "issue_url": "https://github.com/CultureBotAI/TraitMech/issues/1",
        "status": "resolved", "summary": "Upgrade validator", "resolution_evidence": [data["artifacts"][-1]["path"]]}])
    snapshot = tmp_path / data["artifacts"][0]["path"]
    snapshot.write_text("<!-- mech-infra-tasks:start -->\n```yaml\nschema_version: '1.0.0'\ntasks:\n- task_id: INFRA-1\n  summary: Upgrade validator\n  status: note\n```\n<!-- mech-infra-tasks:end -->\n")
    data["artifacts"][0]["sha256"] = sha256(snapshot.read_bytes())
    validate_goal_evidence(data, repository_root=tmp_path)
    data["infra_tasks"][0]["resolution_evidence"] = []
    with pytest.raises(WorkflowError, match="resolution evidence"):
        validate_goal_evidence(data, repository_root=tmp_path)


def test_nonregular_artifact_does_not_block(tmp_path):
    import os
    data = evidence(tmp_path)
    target = tmp_path / data["artifacts"][0]["path"]
    target.unlink()
    os.mkfifo(target)
    with pytest.raises(WorkflowError, match="regular"):
        validate_goal_evidence(data, repository_root=tmp_path)


def test_external_artifact_symlink_rejected(tmp_path):
    data = evidence(tmp_path)
    target = tmp_path / data["artifacts"][0]["path"]
    target.unlink()
    target.symlink_to("/etc/passwd")
    with pytest.raises(WorkflowError):
        validate_goal_evidence(data, repository_root=tmp_path)


def test_manifest_cannot_be_saved_under_another_cycle_identity(tmp_path):
    data = evidence(tmp_path)
    path = write(tmp_path / "wrong.yaml", data)
    with pytest.raises(WorkflowError, match="manifest path"):
        read_goal_evidence(path, repository_root=tmp_path)


def test_cli_runs_from_source_without_console_install(profile, capsys):
    path, _ = profile
    assert main(["validate", "--profile", str(path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["repository_key"] == "traitmech"
    assert main(["validate-parent"]) == 0
    assert main(["validate", "--profile", str(path), "--repository-key", "wrong"]) == 1


def test_real_linkml_classes_compile_in_fresh_process():
    result = subprocess.run([sys.executable, "-c", "from kg_microbe_workflows import validate_parent,load_document,PARENT_PATH;validate_parent(load_document(PARENT_PATH.read_bytes()))"],
                            capture_output=True, text=True, env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")})
    assert result.returncode == 0, result.stderr


def test_append_only_evidence_writer_rejects_overwrite(tmp_path):
    from kg_microbe_workflows import save_goal_evidence
    data = evidence(tmp_path)
    saved = save_goal_evidence(tmp_path, data)
    before = saved.read_bytes()
    with pytest.raises(WorkflowError, match="already exists"):
        save_goal_evidence(tmp_path, data)
    assert saved.read_bytes() == before


def test_infrastructure_cannot_hide_frozen_task_as_empty_plan(tmp_path):
    data = evidence(tmp_path, 6)
    snapshot = tmp_path / data["artifacts"][0]["path"]
    snapshot.write_text("<!-- mech-infra-tasks:start -->\n```yaml\nschema_version: '1.0.0'\ntasks:\n- task_id: INFRA-1\n  summary: Upgrade validator\n  status: note\n```\n<!-- mech-infra-tasks:end -->\n")
    data["artifacts"][0]["sha256"] = sha256(snapshot.read_bytes())
    with pytest.raises(WorkflowError, match="entire frozen notebook"):
        validate_goal_evidence(data, repository_root=tmp_path)


@pytest.mark.parametrize("task", [
    {"task_id": "I-1", "summary": "Upgrade", "status": "open"},
    {"task_id": "I-1", "summary": "Upgrade", "status": "deferred", "issue_url": "https://github.com/CultureBotAI/TraitMech/issues/1"},
    {"task_id": "I-1", "summary": "Upgrade", "status": "open", "issue_url": "https://github.com/other/repo/issues/1"},
])
def test_actionable_infrastructure_notes_require_issue_provenance(task):
    from kg_microbe_workflows import validate_infra_notebook
    raw = "<!-- mech-infra-tasks:start -->\n```yaml\n" + yaml.safe_dump({"schema_version": "1.0.0", "tasks": [task]}) + "```\n<!-- mech-infra-tasks:end -->\n"
    with pytest.raises(WorkflowError):
        validate_infra_notebook(raw, "CultureBotAI/TraitMech")


def test_duplicate_task_ids_and_yaml_keys_rejected_in_notebook():
    from kg_microbe_workflows import validate_infra_notebook
    for body in ["schema_version: '1.0.0'\ntasks: []\ntasks: []\n", "schema_version: '1.0.0'\ntasks:\n- task_id: I-1\n  summary: Upgrade\n  status: note\n- task_id: I-1\n  summary: Different\n  status: note\n"]:
        raw = "<!-- mech-infra-tasks:start -->\n```yaml\n" + body + "```\n<!-- mech-infra-tasks:end -->\n"
        with pytest.raises(WorkflowError):
            validate_infra_notebook(raw, "CultureBotAI/TraitMech")


def test_next_cycle_review_uses_prior_resolution_state(tmp_path):
    prior_review, prior_resolution = resolution(tmp_path)
    prior_resolution["groups"][0].update(status="deferred", disposition="Blocked on evidence")
    prior_resolution["findings"][0].update(status="deferred", disposition="Blocked on evidence")
    prior_resolution["carry_forward_ids"] = ["F-1"]
    prior_path = save_evidence(tmp_path, prior_resolution)
    data = evidence(tmp_path, cycle=2)
    data.update(outcome="completed", findings=[{"finding_id": "F-1", "status": "open", "summary": "Revisited", "carried_from": "F-1"}],
                carry_forward_ids=["F-1"], previous_evidence={"path": prior_path.relative_to(tmp_path).as_posix(), "sha256": sha256(prior_path.read_bytes())})
    validate_goal_evidence(data, repository_root=tmp_path, previous=prior_resolution)


def test_contract_has_no_governance_source_dependency(tmp_path):
    import shutil
    package = Path(__file__).resolve().parents[1] / "src/kg_microbe_workflows"
    shutil.copytree(package, tmp_path / "kg_microbe_workflows")
    code = "import sys; sys.path.insert(0, " + repr(str(tmp_path)) + "); from kg_microbe_workflows import validate_parent,load_document,PARENT_PATH; validate_parent(load_document(PARENT_PATH.read_bytes())); assert not any(k.startswith('kg_microbe_governance') for k in sys.modules)"
    result = subprocess.run([sys.executable, "-I", "-c", code], cwd=tmp_path,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_pure_linkml_loader_restores_original_after_failure():
    import importlib

    from kg_microbe_workflows import _pure_linkml_loader
    loader = importlib.import_module("linkml_runtime.loaders.yaml_loader")
    original = loader.DupCheckYamlLoader
    with pytest.raises(RuntimeError):
        with _pure_linkml_loader():
            assert loader.DupCheckYamlLoader is not original
            raise RuntimeError("Synthetic generator failure")
    assert loader.DupCheckYamlLoader is original


def test_packaged_examples_have_valid_hash_bound_artifacts():
    root = PARENT_PATH.parent.parent / "examples"
    previous = None
    for stage in [4, 5, 6]:
        path = root / evidence_directory("example-run", 1, stage, 1) / "evidence.yaml"
        data = read_goal_evidence(path, repository_root=root,
                                  previous=previous if stage == 5 else None)
        if stage == 4:
            previous = data
        assert data["outcome"] == "no_findings"


def test_published_linkml_review_classes_have_distinct_stage_constraints(tmp_path):
    from kg_microbe_workflows import _validator
    data = evidence(tmp_path, stage=4)
    assert not list(_validator(SCHEMA_PATH.read_text(), "ReviewReport").iter_errors(data))
    assert list(_validator(SCHEMA_PATH.read_text(), "FindingGroupResolution").iter_errors(data))
    assert list(_validator(SCHEMA_PATH.read_text(), "InfrastructurePlan").iter_errors(data))
