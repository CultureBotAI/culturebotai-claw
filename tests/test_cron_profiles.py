"""Tests for the agent cadence config and its applier.

Config that nothing reads is worse than no config, because it invites trust —
that is the lesson of claw#37, where a retired compatibility manifest looked
like the source of truth and was referenced nowhere. These pin the properties
that make cron-profiles.yaml real.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG = REPO_ROOT / ".github" / "cron-profiles.yaml"
AGENT_CONFIG = REPO_ROOT / ".github" / "agent-config.yaml"
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import apply_cron_profile as cron_profiles  # noqa: E402
from apply_cron_profile import (  # noqa: E402
    check_active_profile,
    check_profiles_complete,
    managed_workflows,
    rewrite,
    schedule_crons,
)


@pytest.fixture(scope="module")
def config() -> dict:
    return yaml.safe_load(CONFIG.read_text())


def test_active_profile_exists(config: dict) -> None:
    assert config["active"] in config["profiles"]


def test_kill_switch_exists_and_is_empty(config: dict) -> None:
    """`off` must schedule nothing — it is the whole point of the file."""
    off = config["profiles"]["off"]["workflows"]
    assert off, "the off profile must still name every managed workflow"
    for name, entries in off.items():
        assert entries in ([], None), f"{name} is scheduled under the kill switch"


def test_every_profile_names_every_managed_workflow(config: dict) -> None:
    """An omission would silently leave a workflow on its previous cadence."""
    assert check_profiles_complete(config) == []


def test_knowledge_gap_scan_is_not_managed(config: dict) -> None:
    """It spends no tokens, so an agent kill switch must not disable it.

    This one is load-bearing: managing it meant `off` would have taken down a
    wanted nightly job that has no model in the loop.
    """
    assert "knowledge-gap-scan" not in managed_workflows(config)


def test_no_sub_hourly_crons(config: dict) -> None:
    """Overlapping runs would just cancel each other via the concurrency group."""
    for pname, profile in config["profiles"].items():
        for wname, entries in (profile.get("workflows") or {}).items():
            for entry in entries or []:
                minute = entry["cron"].split()[0]
                assert minute != "*", f"{pname}/{wname} runs every minute"


def test_agent_config_models_are_known(config: dict) -> None:
    """A typo'd model id fails at run time, in a scheduled job nobody is watching."""
    known = {
        "claude-opus-5",
        "claude-sonnet-5",
        "claude-haiku-4-5-20251001",
        "claude-fable-5",
    }
    ac = yaml.safe_load(AGENT_CONFIG.read_text())
    assert ac["default_model"] in known
    for name, wf in ac["workflows"].items():
        if "model" in wf:
            assert wf["model"] in known, f"{name}: unknown model {wf['model']}"
        for leg in wf.get("matrix", []):
            assert leg["model"] in known, f"{name}: unknown model {leg['model']}"


def test_effort_selectors_are_mutually_exclusive() -> None:
    """An issue must match exactly one tier, or it gets worked twice."""
    ac = yaml.safe_load(AGENT_CONFIG.read_text())
    legs = ac["workflows"]["issue-scanner"]["matrix"]
    efforts = [leg["effort"] for leg in legs]
    assert efforts == ["low_effort", "medium_effort", "high_effort"]
    # each tier below the top must be excluded by the ones above it
    assert "-label:low_effort" in legs[1]["selector"]
    assert "-label:low_effort" in legs[2]["selector"]
    assert "-label:medium_effort" in legs[2]["selector"]
    for leg in legs:
        assert "label:agent-ok" in leg["selector"], "every tier must be opt-in"


# --------------------------------------------------------------------------
# rewrite() — the part that actually edits workflow files
# --------------------------------------------------------------------------

WF = '''name: demo

on:
  schedule:
    - cron: "0 7 * * *"   # daily
  workflow_dispatch:

permissions:
  contents: read

jobs:
  a:
    runs-on: ubuntu-latest
'''


def test_rewrite_removes_schedule_but_keeps_dispatch() -> None:
    out, what = rewrite(WF, [])
    assert "schedule:" not in out
    assert "workflow_dispatch:" in out
    assert "jobs:" in out and "permissions:" in out
    assert "removed" in what


def test_rewrite_replaces_cron_entries() -> None:
    out, _ = rewrite(WF, [{"cron": "0 3 * * 1", "comment": "weekly"}])
    assert '- cron: "0 3 * * 1"   # weekly' in out
    assert '0 7 * * *' not in out
    assert "workflow_dispatch:" in out


def test_rewrite_adds_schedule_when_absent() -> None:
    no_sched = WF.replace('  schedule:\n    - cron: "0 7 * * *"   # daily\n', "")
    out, what = rewrite(no_sched, [{"cron": "0 3 * * *"}])
    assert '- cron: "0 3 * * *"' in out
    assert "added" in what


def test_rewrite_preserves_everything_outside_the_schedule() -> None:
    out, _ = rewrite(WF, [{"cron": "0 3 * * *"}])
    for keep in ("name: demo", "permissions:", "contents: read", "jobs:", "runs-on: ubuntu-latest"):
        assert keep in out


def test_rewrite_rejects_a_workflow_with_no_on_block() -> None:
    with pytest.raises(ValueError):
        rewrite("name: x\njobs: {}\n", [])


def test_rewrite_output_is_valid_yaml() -> None:
    for entries in ([], [{"cron": "0 3 * * *", "comment": "c"}]):
        out, _ = rewrite(WF, entries)
        yaml.safe_load(out)


# --------------------------------------------------------------------------
# #39 — the applier must not eat comments it does not own
# --------------------------------------------------------------------------

WF_TRAILING_COMMENT = '''name: demo

on:
  schedule:
    - cron: "0 7 * * *"

  # This comment explains workflow_dispatch, not the schedule.
  workflow_dispatch:

jobs:
  a:
    runs-on: ubuntu-latest
'''


def test_removing_a_schedule_keeps_the_next_keys_comment() -> None:
    """The whole reason this edits lines instead of dumping YAML is comments."""
    out, _ = rewrite(WF_TRAILING_COMMENT, [])
    assert "explains workflow_dispatch" in out
    assert "workflow_dispatch:" in out
    assert "schedule:" not in out


def test_replacing_a_schedule_keeps_the_next_keys_comment() -> None:
    out, _ = rewrite(WF_TRAILING_COMMENT, [{"cron": "0 3 * * *"}])
    assert "explains workflow_dispatch" in out
    assert '- cron: "0 3 * * *"' in out


def test_comments_inside_the_schedule_block_are_replaced() -> None:
    """Those genuinely belong to the schedule and should go with it."""
    wf = WF_TRAILING_COMMENT.replace(
        '  schedule:\n    - cron: "0 7 * * *"',
        '  schedule:\n    # why this hour\n    - cron: "0 7 * * *"',
    )
    out, _ = rewrite(wf, [{"cron": "0 3 * * *"}])
    assert "why this hour" not in out
    assert "explains workflow_dispatch" in out


def test_output_stays_valid_yaml_with_trailing_comment() -> None:
    for entries in ([], [{"cron": "0 3 * * *"}]):
        yaml.safe_load(rewrite(WF_TRAILING_COMMENT, entries)[0])


def _profile_config(tmp_path: Path, active: str = "off") -> Path:
    path = tmp_path / "cron-profiles.yaml"
    path.write_text(yaml.safe_dump({
        "active": active,
        "profiles": {
            "off": {"workflows": {"agent": []}},
            "slow": {"workflows": {"agent": [{"cron": "0 3 * * 1"}]}},
        },
    }, sort_keys=False))
    return path


def test_apply_updates_active_and_check_detects_later_manual_drift(
    tmp_path, monkeypatch
) -> None:
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    workflow = workflows / "agent.yaml"
    workflow.write_text(WF)
    config_path = _profile_config(tmp_path)
    monkeypatch.setattr(cron_profiles, "WORKFLOW_DIR", workflows)

    assert cron_profiles.main(["slow", "--config", str(config_path)]) == 0
    config = yaml.safe_load(config_path.read_text())
    assert config["active"] == "slow"
    assert schedule_crons(workflow.read_text()) == ["0 3 * * 1"]
    assert check_active_profile(config) == []

    workflow.write_text(rewrite(workflow.read_text(), [])[0])
    assert check_active_profile(config) == [
        "agent: active=slow expects ['0 3 * * 1'], found []"
    ]


def test_incomplete_nonempty_profile_does_not_change_active(tmp_path, monkeypatch) -> None:
    config_path = _profile_config(tmp_path)
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    monkeypatch.setattr(cron_profiles, "WORKFLOW_DIR", workflows)

    assert cron_profiles.main(["slow", "--config", str(config_path)]) == 1
    assert yaml.safe_load(config_path.read_text())["active"] == "off"


def test_missing_workflow_agrees_with_off_profile(tmp_path, monkeypatch) -> None:
    config_path = _profile_config(tmp_path, active="slow")
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    monkeypatch.setattr(cron_profiles, "WORKFLOW_DIR", workflows)

    assert cron_profiles.main(["off", "--config", str(config_path)]) == 0
    config = yaml.safe_load(config_path.read_text())
    assert config["active"] == "off"
    assert check_active_profile(config) == []


def test_active_is_not_updated_when_post_apply_verification_fails(
    tmp_path, monkeypatch
) -> None:
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    (workflows / "agent.yaml").write_text(WF)
    config_path = _profile_config(tmp_path)
    monkeypatch.setattr(cron_profiles, "WORKFLOW_DIR", workflows)
    monkeypatch.setattr(
        cron_profiles,
        "rewrite",
        lambda original, entries: (original, "claimed success without changing"),
    )

    assert cron_profiles.main(["slow", "--config", str(config_path)]) == 1
    assert yaml.safe_load(config_path.read_text())["active"] == "off"
