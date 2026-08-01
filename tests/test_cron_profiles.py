"""Tests for the agent cadence config and its applier.

Config that nothing reads is worse than no config, because it invites trust —
that is the lesson of claw#37, where shared/idlabel/MANIFEST looked like the
source of truth and was referenced nowhere. These pin the properties that make
cron-profiles.yaml real.
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

from apply_cron_profile import (  # noqa: E402
    check_profiles_complete,
    managed_workflows,
    rewrite,
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
