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

WF = """name: demo

on:
  schedule:
    - cron: "0 7 * * *"   # daily
  workflow_dispatch:

permissions:
  contents: read

jobs:
  a:
    runs-on: ubuntu-latest
"""


def test_rewrite_removes_schedule_but_keeps_dispatch() -> None:
    out, what = rewrite(WF, [])
    assert "schedule:" not in out
    assert "workflow_dispatch:" in out
    assert "jobs:" in out and "permissions:" in out
    assert "removed" in what


def test_rewrite_replaces_cron_entries() -> None:
    out, _ = rewrite(WF, [{"cron": "0 3 * * 1", "comment": "weekly"}])
    assert '- cron: "0 3 * * 1"   # weekly' in out
    assert "0 7 * * *" not in out
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

WF_TRAILING_COMMENT = """name: demo

on:
  schedule:
    - cron: "0 7 * * *"

  # This comment explains workflow_dispatch, not the schedule.
  workflow_dispatch:

jobs:
  a:
    runs-on: ubuntu-latest
"""


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


@pytest.fixture
def canonical(tmp_path, monkeypatch):
    """A source checkout: canonical payloads and manifest, no downstream writes."""
    import hashlib
    import json

    source = "src/kg_microbe_governance/artifacts/workflows/agent.yaml"
    workflow = tmp_path / source
    workflow.parent.mkdir(parents=True)
    workflow.write_text(WF)
    manifest = tmp_path / "src/kg_microbe_governance/vendored_artifacts.json"
    manifest.write_text(
        json.dumps(
            {
                "version": 1,
                "canonical_repository": "CultureBotAI/culturebotai-claw",
                "pin_path": "scripts/.vendored_canon_ref",
                "consumers": {
                    "traitmech": {
                        "github": "CultureBotAI/TraitMech",
                        "package_path": "src/traitmech",
                    }
                },
                "artifacts": [
                    {
                        "id": "agent_workflow",
                        "source": source,
                        "target": ".github/workflows/agent.yaml",
                        "consumers": "all",
                        "sha256": hashlib.sha256(workflow.read_bytes()).hexdigest(),
                        "mode": "0644",
                    }
                ],
            },
            indent=2,
        )
        + "\n"
    )
    config = tmp_path / "cron-profiles.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "active": "off",
                "targets": {
                    "agent": {"state": "governed", "artifact": "agent_workflow"},
                    "future": {"state": "planned", "reason": "Not implemented yet."},
                },
                "profiles": {
                    "off": {"workflows": {"agent": [], "future": []}},
                    "slow": {
                        "workflows": {
                            "agent": [{"cron": "0 3 * * 1"}],
                            "future": [{"cron": "0 4 * * 1"}],
                        }
                    },
                },
            },
            sort_keys=False,
        )
    )
    monkeypatch.setattr(cron_profiles, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(cron_profiles, "WORKFLOW_DIR", tmp_path / ".github/workflows")
    monkeypatch.setattr(cron_profiles, "CANONICAL_WORKFLOW_DIR", workflow.parent)
    monkeypatch.setattr(cron_profiles, "MANIFEST_PATH", manifest)
    return config, workflow, manifest


def _digest(manifest: Path, workflow: Path) -> None:
    import hashlib
    import json

    data = json.loads(manifest.read_text())
    data["artifacts"][0]["sha256"] = hashlib.sha256(workflow.read_bytes()).hexdigest()
    manifest.write_text(json.dumps(data, indent=2) + "\n")


def test_real_off_profile_reaches_existing_governed_workflow(config) -> None:
    targets = cron_profiles.resolve_targets(config)
    assert "pr-shepherd" in targets
    assert targets["pr-shepherd"].path.is_file()
    assert check_active_profile(config) == []


def test_apply_updates_active_checksum_and_reports_planned(canonical, capsys) -> None:
    import hashlib
    import json

    config_path, workflow, manifest = canonical
    original = workflow.read_text()
    assert cron_profiles.main(["slow", "--config", str(config_path)]) == 0
    config = cron_profiles.load_config(config_path)
    assert config["active"] == "slow"
    assert schedule_crons(workflow.read_text()) == ["0 3 * * 1"]
    assert check_active_profile(config) == []
    assert (
        json.loads(manifest.read_text())["artifacts"][0]["sha256"]
        == hashlib.sha256(workflow.read_bytes()).hexdigest()
    )
    assert rewrite(original, [])[0] == rewrite(workflow.read_text(), [])[0]
    output = capsys.readouterr().out
    assert "planned future" in output
    assert "1 governed, 1 planned, 1 workflow changes" in output
    assert "fleet re-pin" in output
    assert not cron_profiles.WORKFLOW_DIR.exists()

    # Drift detected even when a manual edit also updates the manifest digest.
    workflow.write_text(rewrite(workflow.read_text(), [])[0])
    _digest(manifest, workflow)
    assert check_active_profile(config) == ["agent: active=slow expects ['0 3 * * 1'], found []"]


def test_dry_run_preserves_payload_manifest_and_active(canonical) -> None:
    originals = {path: path.read_bytes() for path in canonical}
    assert cron_profiles.main(["slow", "--config", str(canonical[0]), "--dry-run"]) == 0
    assert {path: path.read_bytes() for path in canonical} == originals


def test_off_removes_actual_canonical_schedule_and_updates_checksum(canonical) -> None:
    config_path, workflow, manifest = canonical
    assert cron_profiles.main(["off", "--config", str(config_path)]) == 0
    assert schedule_crons(workflow.read_text()) == []
    assert "workflow_dispatch:" in workflow.read_text()
    assert check_active_profile(cron_profiles.load_config(config_path)) == []
    before = {path: path.read_bytes() for path in canonical}
    assert cron_profiles.main(["off", "--config", str(config_path)]) == 0
    assert {path: path.read_bytes() for path in canonical} == before


@pytest.mark.parametrize("profile", ["off", "slow"])
def test_missing_canonical_workflow_fails_even_when_off(canonical, profile) -> None:
    config_path, workflow, manifest = canonical
    original_config, original_manifest = config_path.read_bytes(), manifest.read_bytes()
    workflow.unlink()
    assert cron_profiles.main([profile, "--config", str(config_path)]) == 1
    assert cron_profiles.main(["--check-active", "--config", str(config_path)]) == 1
    assert config_path.read_bytes() == original_config
    assert manifest.read_bytes() == original_manifest


def test_resolver_follows_manifest_source_path_after_rename(canonical) -> None:
    import json

    config_path, workflow, manifest = canonical
    renamed = workflow.with_name("canonical-agent.yaml")
    workflow.rename(renamed)
    data = json.loads(manifest.read_text())
    data["artifacts"][0]["source"] = str(renamed.relative_to(cron_profiles.REPO_ROOT))
    manifest.write_text(json.dumps(data))
    assert cron_profiles.main(["slow", "--config", str(config_path)]) == 0
    assert schedule_crons(renamed.read_text()) == ["0 3 * * 1"]
    assert not workflow.exists()


def test_stale_checksum_refuses_apply_without_overwriting_evidence(canonical) -> None:
    config_path, workflow, manifest = canonical
    workflow.write_text(workflow.read_text() + "# unreviewed change\n")
    originals = {path: path.read_bytes() for path in canonical}
    assert cron_profiles.main(["off", "--config", str(config_path)]) == 1
    assert {path: path.read_bytes() for path in canonical} == originals


@pytest.mark.parametrize("stem", ["future", "unregistered"])
def test_new_canonical_workflow_cannot_bypass_off_even_if_ignored(canonical, stem) -> None:
    config_path, workflow, manifest = canonical
    workflow.write_text(rewrite(workflow.read_text(), [])[0])
    _digest(manifest, workflow)
    assert cron_profiles.main(["--check-active", "--config", str(config_path)]) == 0
    (workflow.parent / ".gitignore").write_text("*.yml\n")
    (workflow.parent / f"{stem}.yml").write_text(WF)
    assert cron_profiles.main(["--check-active", "--config", str(config_path)]) == 1


@pytest.mark.parametrize("resource_directory", ["workflows", "other-workflows"])
def test_new_registered_workflow_requires_profile_target(canonical, resource_directory) -> None:
    import json

    config_path, workflow, manifest = canonical
    workflow.write_text(rewrite(workflow.read_text(), [])[0])
    _digest(manifest, workflow)
    assert cron_profiles.main(["--check-active", "--config", str(config_path)]) == 0
    future = workflow.parent.parent / resource_directory / "future.yaml"
    future.parent.mkdir(exist_ok=True)
    future.write_text(workflow.read_text())
    data = json.loads(manifest.read_text())
    added = {
        **data["artifacts"][0],
        "id": "future_workflow",
        "source": str(future.relative_to(cron_profiles.REPO_ROOT)),
        "target": ".github/workflows/future.yaml",
    }
    data["artifacts"].append(added)
    manifest.write_text(json.dumps(data))
    assert cron_profiles.main(["--check-active", "--config", str(config_path)]) == 1


def test_local_copy_cannot_replace_governed_target(canonical) -> None:
    config_path, workflow, manifest = canonical
    workflow.write_text(rewrite(workflow.read_text(), [])[0])
    _digest(manifest, workflow)
    assert cron_profiles.main(["--check-active", "--config", str(config_path)]) == 0
    cron_profiles.WORKFLOW_DIR.mkdir(parents=True)
    (cron_profiles.WORKFLOW_DIR / "agent.yml").write_text(WF)
    assert cron_profiles.main(["--check-active", "--config", str(config_path)]) == 1


def test_all_planned_is_not_a_working_kill_switch(canonical) -> None:
    import json

    config_path, workflow, manifest = canonical
    config = cron_profiles.load_config(config_path)
    config["targets"]["agent"] = {"state": "planned", "reason": "Not implemented."}
    config_path.write_text(yaml.safe_dump(config))
    data = json.loads(manifest.read_text())
    data["artifacts"] = []
    manifest.write_text(json.dumps(data))
    workflow.unlink()
    assert cron_profiles.main(["--check-active", "--config", str(config_path)]) == 1


def test_prepare_failure_does_not_apply_other_workflow(canonical) -> None:
    import hashlib
    import json

    config_path, workflow, manifest = canonical
    config = cron_profiles.load_config(config_path)
    config["targets"]["future"] = {"state": "governed", "artifact": "future_workflow"}
    config_path.write_text(yaml.safe_dump(config))
    malformed = workflow.with_name("future.yaml")
    malformed.write_text("name: invalid\njobs: {}\n")
    data = json.loads(manifest.read_text())
    data["artifacts"].append(
        {
            **data["artifacts"][0],
            "id": "future_workflow",
            "source": str(malformed.relative_to(cron_profiles.REPO_ROOT)),
            "target": ".github/workflows/future.yaml",
            "sha256": hashlib.sha256(malformed.read_bytes()).hexdigest(),
        }
    )
    manifest.write_text(json.dumps(data))
    originals = {path: path.read_bytes() for path in (*canonical, malformed)}
    assert cron_profiles.main(["slow", "--config", str(config_path)]) == 1
    assert {path: path.read_bytes() for path in originals} == originals


def test_failed_manifest_write_restores_workflow(canonical, monkeypatch) -> None:
    config_path, workflow, manifest = canonical
    originals = {path: path.read_bytes() for path in canonical}
    real_write = cron_profiles._atomic_write

    def fail_manifest(path, data):
        if path == manifest:
            raise OSError("injected manifest write failure")
        real_write(path, data)

    monkeypatch.setattr(cron_profiles, "_atomic_write", fail_manifest)
    assert cron_profiles.main(["slow", "--config", str(config_path)]) == 1
    assert {path: path.read_bytes() for path in canonical} == originals


def test_active_is_not_updated_when_post_apply_verification_fails(canonical, monkeypatch) -> None:
    originals = {path: path.read_bytes() for path in canonical}
    monkeypatch.setattr(
        cron_profiles, "check_active_profile", lambda config: ["injected post-apply failure"]
    )
    assert cron_profiles.main(["slow", "--config", str(canonical[0])]) == 1
    assert {path: path.read_bytes() for path in canonical} == originals


@pytest.mark.parametrize(
    "events",
    [
        'on: {schedule: [{cron: "0 7 * * *"}], workflow_dispatch: {}}',
        "'on':\n  schedule:\n    - cron: 0 7 * * *\n  workflow_dispatch:",
        'on:\n  schedule:\n  - cron: "0 7 * * *"\n  workflow_dispatch:',
        'on:\n  "schedule": [{cron: "0 7 * * *"}]\n  workflow_dispatch:',
    ],
)
def test_yaml_schedule_variants_cannot_hide_from_off(canonical, events) -> None:
    config_path, workflow, manifest = canonical
    workflow.write_text("name: alternate\n" + events + "\njobs: {}\n")
    _digest(manifest, workflow)
    assert schedule_crons(workflow.read_text()) == ["0 7 * * *"]
    assert cron_profiles.main(["--check-active", "--config", str(config_path)]) == 1


@pytest.mark.parametrize(
    "text",
    [
        "on:\n  schedule: []\n",
        "on:\n  schedule: null\n",
        "on:\n  schedule:\n    - cron: '0 7 * * *'\n  schedule: []\n",
        "on: {workflow_dispatch: {}}\non: {schedule: [{cron: '0 7 * * *'}]}\n",
    ],
)
def test_malformed_or_duplicate_schedule_fails_closed(text) -> None:
    with pytest.raises(ValueError):
        schedule_crons(text)


def test_runtime_rejects_scheduled_off_profile(canonical) -> None:
    config_path, workflow, manifest = canonical
    config = cron_profiles.load_config(config_path)
    config["profiles"]["off"]["workflows"]["agent"] = [{"cron": "0 3 * * 1"}]
    config_path.write_text(yaml.safe_dump(config))
    assert cron_profiles.main(["off", "--config", str(config_path)]) == 1


@pytest.mark.parametrize("name", ['slow"broken', "slow\nactive: fast", "", "slow profile"])
def test_invalid_profile_names_fail_before_any_write(canonical, name) -> None:
    config_path, workflow, manifest = canonical
    config = cron_profiles.load_config(config_path)
    config["profiles"][name] = config["profiles"].pop("slow")
    config_path.write_text(yaml.safe_dump(config))
    originals = {path: path.read_bytes() for path in canonical}
    assert cron_profiles.main([name, "--config", str(config_path)]) == 1
    assert {path: path.read_bytes() for path in canonical} == originals


def test_active_scalar_rendering_escapes_special_characters() -> None:
    name = 'slow"broken\nvalue'
    rendered = cron_profiles.render_active_profile('active: "off"\n', name)
    assert yaml.safe_load(rendered)["active"] == name


def test_concurrent_profile_edit_is_preserved_and_owned_changes_rolled_back(
    canonical, monkeypatch, capsys
) -> None:
    config_path, workflow, manifest = canonical
    originals = {path: path.read_bytes() for path in canonical}
    real_write = cron_profiles._atomic_write
    concurrent_config = None

    def change_profile_during_apply(path, data):
        nonlocal concurrent_config
        real_write(path, data)
        if path == workflow and concurrent_config is None:
            config = cron_profiles.load_config(config_path)
            config["profiles"]["slow"]["workflows"]["agent"] = [{"cron": "0 9 * * *"}]
            concurrent_config = yaml.safe_dump(config).encode()
            config_path.write_bytes(concurrent_config)

    monkeypatch.setattr(cron_profiles, "_atomic_write", change_profile_during_apply)
    assert cron_profiles.main(["slow", "--config", str(config_path)]) == 1
    assert config_path.read_bytes() == concurrent_config
    assert workflow.read_bytes() == originals[workflow]
    assert manifest.read_bytes() == originals[manifest]
    assert "concurrent change detected" in capsys.readouterr().err


def test_active_write_failure_after_promotion_restores_every_file(canonical, monkeypatch) -> None:
    config_path, workflow, manifest = canonical
    originals = {path: path.read_bytes() for path in canonical}
    real_write = cron_profiles._atomic_write
    injected = False

    def fail_after_active_promotion(path, data):
        nonlocal injected
        real_write(path, data)
        if path == config_path and not injected:
            injected = True
            raise OSError("injected failure after active replacement")

    monkeypatch.setattr(cron_profiles, "_atomic_write", fail_after_active_promotion)
    assert cron_profiles.main(["slow", "--config", str(config_path)]) == 1
    assert injected
    assert {path: path.read_bytes() for path in canonical} == originals


def test_rollback_continues_after_one_restore_fails(canonical, monkeypatch, capsys) -> None:
    config_path, workflow, manifest = canonical
    originals = {path: path.read_bytes() for path in canonical}
    real_write = cron_profiles._atomic_write

    def fail_restoring_manifest(path, data):
        if path == manifest and data == originals[manifest]:
            raise OSError("injected restoration failure")
        real_write(path, data)

    monkeypatch.setattr(cron_profiles, "_atomic_write", fail_restoring_manifest)
    monkeypatch.setattr(cron_profiles, "check_active_profile", lambda config: ["verify failed"])
    assert cron_profiles.main(["slow", "--config", str(config_path)]) == 1
    assert config_path.read_bytes() == originals[config_path]
    assert workflow.read_bytes() == originals[workflow]
    assert manifest.read_bytes() != originals[manifest]
    error = capsys.readouterr().err
    assert "rollback incomplete" in error
    assert str(manifest) in error
    assert "injected restoration failure" in error


def test_rollback_preserves_intervening_workflow_bytes(canonical, monkeypatch, capsys) -> None:
    config_path, workflow, manifest = canonical
    originals = {path: path.read_bytes() for path in canonical}
    real_write = cron_profiles._atomic_write
    concurrent_workflow = None

    def edit_workflow_after_manifest_write(path, data):
        nonlocal concurrent_workflow
        real_write(path, data)
        if path == manifest and concurrent_workflow is None:
            concurrent_workflow = workflow.read_bytes() + b"# independent concurrent edit\n"
            workflow.write_bytes(concurrent_workflow)

    monkeypatch.setattr(cron_profiles, "_atomic_write", edit_workflow_after_manifest_write)
    assert cron_profiles.main(["slow", "--config", str(config_path)]) == 1
    assert workflow.read_bytes() == concurrent_workflow
    assert manifest.read_bytes() == originals[manifest]
    assert config_path.read_bytes() == originals[config_path]
    error = capsys.readouterr().err
    assert "rollback incomplete" in error
    assert "intervening bytes preserved" in error
    assert str(workflow) in error
