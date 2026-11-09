"""Exercise workflow shell boundaries without credentials, network, or PR code."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CANON = ROOT / "src/kg_microbe_governance/artifacts/workflows"
AFTER = "a" * 40
BEFORE = "b" * 40


def workflow(name):
    return yaml.safe_load((CANON / f"{name}.yaml").read_text())


def step(name, prefix):
    jobs = workflow(name)["jobs"]
    return next(item for job in jobs.values() for item in job["steps"]
                if item.get("name", "").startswith(prefix))


def shell(tmp_path, task, extra=None, repository="CultureBotAI/TraitMech"):
    runner = tmp_path / "uv"
    runner.write_text(f"#!{sys.executable}\nimport json, os, sys\n"
                      "with open(os.environ['CAPTURE'], 'w') as stream:\n"
                      "    json.dump(sys.argv[1:], stream)\n")
    runner.chmod(0o755)
    git = tmp_path / "git"
    git.write_text(f"#!/bin/sh\nprintf '%s\\n' '{BEFORE}'\n")
    git.chmod(0o755)
    capture = tmp_path / "capture.json"
    env = dict(os.environ, PATH=f"{tmp_path}:{os.environ['PATH']}",
               CAPTURE=str(capture), RUNNER_TEMP=str(tmp_path),
               GITHUB_REPOSITORY=repository, GITHUB_WORKSPACE=str(tmp_path),
               GITHUB_EVENT_NAME="push", GITHUB_SHA=AFTER,
               EVENT_BEFORE=BEFORE, EVENT_AFTER=AFTER,
               INPUT_BEFORE="", INPUT_AFTER="",
               ADMISSION_APPLY="false", GH_MERGE_TOKEN="")
    env.update(extra or {})
    result = subprocess.run(["bash", "-c", task["run"]], cwd=tmp_path, env=env,
                            text=True, capture_output=True, timeout=5)
    return result, json.loads(capture.read_text()) if capture.exists() else None


@pytest.mark.parametrize("name", ["merge-queue-admission", "verify-merge-integrity"])
def test_claw_executes_the_canonical_workflow_bytes(name):
    assert (ROOT / f".github/workflows/{name}.yaml").read_bytes() == (CANON / f"{name}.yaml").read_bytes()


def test_integrity_covers_every_main_push_without_cancellation():
    value = workflow("verify-merge-integrity")
    assert value[True]["push"] == {"branches": ["main"]}
    assert "concurrency" not in value
    job = value["jobs"]["merge-integrity"]
    assert "concurrency" not in job
    assert job["name"] == "merge-integrity"
    assert "github.event.repository.default_branch" in job["if"]
    checkout = step("verify-merge-integrity", "Checkout")
    assert checkout["with"] == {"fetch-depth": 0, "persist-credentials": False}
    assert value["permissions"] == {"contents": "read", "pull-requests": "read", "issues": "write"}


@pytest.mark.parametrize("extra", [
    {}, {"GITHUB_EVENT_NAME": "workflow_dispatch"},
    {"GITHUB_EVENT_NAME": "workflow_dispatch", "INPUT_BEFORE": BEFORE, "INPUT_AFTER": AFTER},
])
@pytest.mark.parametrize("repository,prefix", [
    ("CultureBotAI/TraitMech", "scripts/"),
    ("CultureBotAI/culturebotai-claw", "src/kg_microbe_governance/artifacts/scripts/"),
])
def test_integrity_passes_the_exact_push_or_dispatch_range(tmp_path, extra, repository, prefix):
    result, argv = shell(tmp_path, step("verify-merge-integrity", "Reconstruct"), extra, repository)
    assert result.returncode == 0, result.stderr
    assert argv[:5] == ["run", "--no-project", "--python", "3.13", "python"]
    assert argv[5] == prefix + "verify_merge_integrity.py"
    assert argv[argv.index("--before") + 1] == BEFORE
    assert argv[argv.index("--after") + 1] == AFTER
    assert "--report-issues" in argv


@pytest.mark.parametrize("extra", [
    {"EVENT_AFTER": "c" * 40}, {"EVENT_BEFORE": AFTER}, {"EVENT_BEFORE": "oops"},
    {"GITHUB_EVENT_NAME": "workflow_dispatch", "INPUT_AFTER": "c" * 40},
    {"GITHUB_EVENT_NAME": "workflow_dispatch", "INPUT_AFTER": "$(touch injected)"},
    {"GITHUB_EVENT_NAME": "workflow_dispatch", "INPUT_BEFORE": AFTER},
    {"GITHUB_EVENT_NAME": "workflow_dispatch", "INPUT_BEFORE": "$(touch injected)"},
])
def test_bad_or_unrelated_ranges_never_publish_success_for_current_main(tmp_path, extra):
    result, argv = shell(tmp_path, step("verify-merge-integrity", "Reconstruct"), extra)
    assert result.returncode != 0
    assert argv is None
    assert not (tmp_path / "injected").exists()


def test_admission_credentials_and_execution_are_default_branch_scoped():
    value = workflow("merge-queue-admission")
    assert set(value[True]) == {"schedule", "workflow_dispatch"}
    assert value[True]["workflow_dispatch"]["inputs"]["apply"]["default"] is False
    assert set(value["permissions"].values()) == {"read"}
    assert value["concurrency"]["cancel-in-progress"] is False
    guard = value["jobs"]["admission"]["if"]
    assert "github.ref == format('refs/heads/{0}', github.event.repository.default_branch)" in guard
    assert "vars.MERGE_QUEUE_AUTOMATION_PAUSED != 'true'" in guard
    checkout = step("merge-queue-admission", "Checkout")
    assert checkout["with"] == {"ref": "${{ github.event.repository.default_branch }}",
                                "persist-credentials": False}
    mint = step("merge-queue-admission", "Mint")
    assert mint["if"] == "github.event_name == 'schedule' || inputs.apply"
    assert mint["with"]["repositories"] == "${{ github.event.repository.name }}"
    assert {k: v for k, v in mint["with"].items() if k.startswith("permission-")} == {
        "permission-contents": "write", "permission-pull-requests": "write"}
    inspect = step("merge-queue-admission", "Inspect")
    assert inspect["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert inspect["env"]["GH_MERGE_TOKEN"] == "${{ steps.admission-token.outputs.token }}"


@pytest.mark.parametrize("apply,token,success", [("false", "", True), ("true", "", False),
                                                ("true", "fixture-only-token", True)])
def test_admission_apply_requires_the_separate_token(tmp_path, apply, token, success):
    result, argv = shell(tmp_path, step("merge-queue-admission", "Inspect"),
                         {"ADMISSION_APPLY": apply, "GH_MERGE_TOKEN": token})
    assert (result.returncode == 0) is success
    if success:
        assert ("--apply" in argv) is (apply == "true")
        assert argv[5] == "scripts/auto_merge_ready_prs.py"
        assert argv[argv.index("--repository") + 1] == "CultureBotAI/TraitMech"
        assert token not in argv
    else:
        assert argv is None


def test_admission_passes_optional_repo_configuration_without_shell_expansion(tmp_path):
    (tmp_path / "conf").mkdir()
    (tmp_path / "conf/merge_queue_automation.json").write_text('{"cache_path_globs":["cache/**"]}')
    result, argv = shell(tmp_path, step("merge-queue-admission", "Inspect"),
                         repository="CultureBotAI/culturebotai-claw")
    assert result.returncode == 0
    assert argv[5] == "src/kg_microbe_governance/artifacts/scripts/auto_merge_ready_prs.py"
    assert argv[argv.index("--config") + 1] == "conf/merge_queue_automation.json"
