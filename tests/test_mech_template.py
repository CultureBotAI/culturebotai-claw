"""Exercise real fresh adoption, managed upgrade, provenance and conflicts offline."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path

import pytest

from kg_microbe_skills import template as mod
from kg_microbe_skills.catalogue import canonical_regions, render_adapter
from kg_microbe_skills.template_cli import main

ROOT = Path(__file__).resolve().parents[1]


def git(root, *args):
    env = {**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True,
                          text=True, env=env).stdout.strip()


def commit(root):
    git(root, "add", ".")
    git(root, "-c", "user.name=Template Test", "-c", "user.email=test@example.org",
        "-c", "commit.gpgsign=false", "commit", "-qm", "fixture")
    return git(root, "rev-parse", "HEAD")


def init(root, remote):
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    git(root, "remote", "add", "origin", "https://github.com/" + remote + ".git")
    (root / "README.md").write_text("Native repository content\n")


class Locks:
    @contextmanager
    def lock(self, key, operation):
        assert key in {"assaymech", "scaleupmech"}
        assert operation == "mech-template-adoption"
        yield


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    source = tmp_path / "claw"
    init(source, "CultureBotAI/culturebotai-claw")
    groups = {
        "kg_microbe_skills": ("skills.yaml", "canonical/*.md"),
        "kg_microbe_workflows": ("templates/mech-cycle.yaml", "schema/workflow.yaml"),
    }
    for relative in (
        "src/kg_microbe_skills/skills.yaml",
        "src/kg_microbe_skills/canonical/next-tasks.md",
        "src/kg_microbe_skills/canonical/review-open-issues.md",
        "src/kg_microbe_skills/template.py", "src/kg_microbe_skills/template_cli.py",
        "src/kg_microbe_skills/catalogue.py", *mod.PARENT_SOURCES.values(),
    ):
        destination = source / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
    commit(source)
    monkeypatch.setattr(mod, "AUTHORITY_GROUPS", groups)
    monkeypatch.setattr(mod, "_implementation_root", lambda: source)
    monkeypatch.setattr(mod, "LockManager", Locks)
    baseline = mod.refresh_baseline(source, apply=True)
    implementation_ref = commit(source)
    target = tmp_path / "AssayMech"
    init(target, "CultureBotAI/AssayMech")
    (target / "AGENTS.md").write_text("Native agent instructions\n")
    (target / "CLAUDE.md").symlink_to("AGENTS.md")
    (target / ".claude/skills").mkdir(parents=True)
    (target / ".agents").mkdir()
    (target / ".agents/skills").symlink_to("../.claude/skills")
    commit(target)
    config = {
        "schema_version": 1, "repository": "assaymech", "source_ref": implementation_ref,
        "components": {name: {"action": "adopt", "reason": "Fixture native support inspected",
                               "evidence": ["README.md at fixture HEAD"]}
                       for name in mod.component_names(baseline)},
        "native_checks": [["uv", "run", "python", "-m", "pytest"]],
        "extensions": ["README.md"],
    }
    (target / "workflow").mkdir()
    (target / mod.CONFIG_PATH).write_text(mod.encode(config))
    return source, target, config


def plan(fixture):
    source, target, _ = fixture
    return mod.plan_repository(target, source_root=source)


def test_real_adoption_dry_run_idempotence_and_governance_preservation(fixture):
    source, target, _ = fixture
    (target / "scripts").mkdir()
    pin = target / "scripts/.vendored_canon_ref"
    pin.write_text("a" * 40 + "\n")
    native = (target / "README.md").read_bytes()
    candidate = plan(fixture)
    assert candidate.report["status"] == "drift"
    assert mod.apply_plan(candidate)["applied"] is False
    assert not (target / mod.RECEIPT_PATH).exists()
    result = mod.apply_plan(candidate, apply=True)
    assert result["applied"] is True and Path(result["journal"]).exists()
    assert plan(fixture).report["status"] == "current"
    assert mod.apply_plan(plan(fixture), apply=True)["applied"] is False
    assert pin.read_text() == "a" * 40 + "\n"
    assert (target / "README.md").read_bytes() == native
    assert not (target / "workflow/mech-workflow.yaml").exists()
    receipt = json.loads((target / mod.RECEIPT_PATH).read_text())
    assert receipt["status"] == "candidate"
    assert receipt["canonical_source_ref"] == mod.baseline_document(source)["source_ref"]


def test_first_adoption_preserves_unmanaged_content(fixture):
    source, target, _ = fixture
    relative = ".claude/skills/next-tasks/SKILL.md"
    existing = render_adapter((source / "src/kg_microbe_skills/canonical/next-tasks.md").read_text(), "assaymech")
    path = target / relative
    path.parent.mkdir(parents=True)
    path.write_text(existing + "\nNative scientific policy retained verbatim.\n")
    mod.apply_plan(plan(fixture), apply=True)
    assert path.read_text().endswith("Native scientific policy retained verbatim.\n")


def test_upgrade_changes_managed_region_and_preserves_native_text(fixture):
    source, target, config = fixture
    mod.apply_plan(plan(fixture), apply=True)
    target_skill = target / ".claude/skills/next-tasks/SKILL.md"
    target_skill.write_text(target_skill.read_text() + "\nA native extension.\n")
    canonical = source / "src/kg_microbe_skills/canonical/next-tasks.md"
    content = canonical.read_text()
    region = next(iter(canonical_regions(content)))
    marker = f"<!-- canonical:begin {region} -->"
    canonical.write_text(content.replace(marker, marker + "\nNew canonical invariant.\n"))
    commit(source)
    mod.refresh_baseline(source, version="1.1.0", apply=True)
    config["source_ref"] = commit(source)
    (target / mod.CONFIG_PATH).write_text(mod.encode(config))
    mod.apply_plan(plan(fixture), apply=True)
    assert "New canonical invariant." in target_skill.read_text()
    assert target_skill.read_text().endswith("A native extension.\n")
    assert plan(fixture).report["status"] == "current"


@pytest.mark.parametrize("relative", [".claude/skills/next-tasks/SKILL.md", ".claude/skills/review-open-issues/SKILL.md"])
def test_managed_local_changes_are_refused_for_partial_and_whole_files(fixture, relative):
    mod.apply_plan(plan(fixture), apply=True)
    path = fixture[1] / relative
    text = path.read_text()
    regions = canonical_regions(text)
    if regions:
        name = next(iter(regions))
        marker = f"<!-- canonical:begin {name} -->"
        text = text.replace(marker, marker + "\nLocal incompatible change.\n")
    else:
        text += "Local incompatible change.\n"
    path.write_text(text)
    with pytest.raises(mod.TemplateError, match="managed content changed locally"):
        plan(fixture)
    assert path.read_text() == text


@pytest.mark.parametrize("kind", ["changed", "new", "missing"])
def test_baseline_detects_authority_inventory_drift_including_ignored(fixture, kind):
    source, _, _ = fixture
    path = source / "src/kg_microbe_skills/canonical/next-tasks.md"
    if kind == "changed":
        path.write_text(path.read_text() + "drift")
    elif kind == "new":
        (source / ".gitignore").write_text("hidden-new.md\n")
        path.with_name("hidden-new.md").write_text("ignored canonical component\n")
    else:
        path.unlink()
    with pytest.raises(mod.TemplateError, match="baseline drift"):
        mod.check_baseline(source)


def test_dirty_authority_and_rehashed_lock_cannot_claim_old_source_ref(fixture):
    source, _, _ = fixture
    path = source / "src/kg_microbe_skills/canonical/next-tasks.md"
    path.write_text(path.read_text() + "forged uncommitted authority\n")
    baseline = mod.baseline_document(source)
    baseline["sources"] = mod.source_inventory(source)
    (source / mod.BASELINE_PATH).write_text(mod.encode(baseline))
    with pytest.raises(mod.TemplateError, match="source revision does not authenticate"):
        mod.check_baseline(source)


def test_refresh_after_lock_commit_preserves_bytes_and_existing_version(fixture):
    source, _, _ = fixture
    mod.refresh_baseline(source, version="1.2.3", apply=True)
    commit(source)
    before = (source / mod.BASELINE_PATH).read_bytes()
    returned = mod.refresh_baseline(source, apply=True)
    assert returned["baseline_version"] == "1.2.3"
    assert (source / mod.BASELINE_PATH).read_bytes() == before
    assert git(source, "status", "--porcelain") == ""


def test_deleted_authority_and_removed_inventory_entry_cannot_claim_old_ref(fixture):
    source, _, _ = fixture
    (source / "src/kg_microbe_skills/canonical/next-tasks.md").unlink()
    baseline = mod.baseline_document(source)
    baseline["sources"] = mod.source_inventory(source)
    (source / mod.BASELINE_PATH).write_text(mod.encode(baseline))
    with pytest.raises(mod.TemplateError, match="authority inventory differs"):
        mod.check_baseline(source)


def test_removed_skill_discovery_link_is_drift_after_adoption(fixture):
    mod.apply_plan(plan(fixture), apply=True)
    (fixture[1] / ".agents/skills").unlink()
    with pytest.raises(mod.TemplateError, match="required layout"):
        plan(fixture)


def test_dirty_executing_code_is_not_attributed_to_committed_ref(fixture):
    source, _, _ = fixture
    path = source / "src/kg_microbe_skills/template.py"
    path.write_text(path.read_text() + "\n# uncommitted implementation\n")
    with pytest.raises(mod.TemplateError, match="source revision does not authenticate"):
        plan(fixture)


def test_docs_only_source_advance_preserves_adoption_and_receipt(fixture):
    source, target, config = fixture
    mod.apply_plan(plan(fixture), apply=True)
    receipt = (target / mod.RECEIPT_PATH).read_bytes()
    (source / "README.md").write_text("Unrelated documentation advance.\n")
    assert commit(source) != config["source_ref"]
    assert plan(fixture).report["status"] == "current"
    assert (target / mod.RECEIPT_PATH).read_bytes() == receipt


@pytest.mark.parametrize("kind", ["changed", "new", "deleted", "baseline"])
def test_source_advance_cannot_change_pinned_implementation_bundle(fixture, kind):
    source, _, _ = fixture
    if kind == "changed":
        path = source / "src/kg_microbe_skills/template.py"
        path.write_text(path.read_text() + "\n# committed change\n")
    elif kind == "new":
        (source / "src/kg_microbe_skills/new_component.py").write_text("# new component\n")
    elif kind == "deleted":
        (source / "src/kg_microbe_skills/catalogue.py").unlink()
    else:
        lock = mod.baseline_document(source)
        lock["baseline_version"] = "1.0.1"
        (source / mod.BASELINE_PATH).write_text(mod.encode(lock))
    commit(source)
    with pytest.raises(mod.TemplateError, match="(source revision does not authenticate|implementation revision inventory)"):
        plan(fixture)


def test_target_race_and_symlink_escape_leave_all_outputs_unwritten(fixture, tmp_path):
    _, target, _ = fixture
    pending = plan(fixture)
    (target / mod.CONFIG_PATH).write_text("changed during preflight")
    with pytest.raises(mod.TemplateError, match="changed after planning"):
        mod.apply_plan(pending, apply=True)
    assert not (target / mod.RECEIPT_PATH).exists()
    (target / mod.CONFIG_PATH).write_text(pending.expected[mod.CONFIG_PATH])
    outside = tmp_path / "outside"
    outside.mkdir()
    shutil.rmtree(target / ".claude")
    (target / ".claude").symlink_to(outside, target_is_directory=True)
    with pytest.raises(mod.TemplateError, match="symlink refused"):
        plan(fixture)
    assert not list(outside.iterdir())


@pytest.mark.parametrize("change", ["omit", "escape", "identity", "overlap"])
def test_config_decisions_and_identity_fail_closed(fixture, change):
    _, target, config = fixture
    if change == "omit":
        config["components"].pop("workflow:parent")
    elif change == "escape":
        config["components"]["skill:next-tasks"]["target"] = "data/scientific.yaml"
    elif change == "identity":
        config["repository"] = "unknown"
    else:
        config["extensions"] = [".claude/skills/next-tasks"]
    (target / mod.CONFIG_PATH).write_text(mod.encode(config))
    with pytest.raises(mod.TemplateError):
        plan(fixture)


def test_disabled_fleet_capability_does_not_silently_skip_explicit_adoption(fixture):
    assert not mod.load_fleet_manifest().mechs["assaymech"].capabilities["testing"].is_enabled
    assert ".claude/skills/next-tasks/SKILL.md" in plan(fixture).outputs


def test_private_identity_requires_native_paths_without_public_membership(fixture):
    source, target, config = fixture
    git(target, "remote", "set-url", "origin", "https://github.com/CultureBotAI/ScaleupMech.git")
    config["repository"] = "scaleupmech"
    (target / "schema").mkdir()
    (target / "schema/native.yaml").write_text("id: https://example.org/native\n")
    config["native_identity"] = {"schema_paths": ["schema/native.yaml"], "record_globs": ["data/processes/*.yaml"]}
    (target / mod.CONFIG_PATH).write_text(mod.encode(config))
    candidate = mod.plan_repository(target, source_root=source)
    assert candidate.report["governance"]["private_policy"] is True
    assert "data/processes/*.yaml" in candidate.outputs[".claude/skills/review-open-issues/SKILL.md"]
    assert "scaleupmech" not in mod.load_fleet_manifest().mechs


def test_check_cli_reports_drift_then_current_and_apply_requires_flag(fixture, capsys):
    source, target, _ = fixture
    args = ["--source-root", str(source), "--target-root", str(target)]
    assert main(["check", *args]) == 1
    assert main(["apply", *args]) == 0
    assert not (target / mod.RECEIPT_PATH).exists()
    assert main(["apply", *args, "--apply"]) == 0
    assert main(["check", *args]) == 0
    assert '"runtime_activation": false' in capsys.readouterr().out
