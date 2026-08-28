"""The cross-repo validation workflow's repo set is a declared input set.

Its three Mechs are not fleet membership — they are the corpora
`scripts/inventory_unmapped_ingredients.py` defines loaders for. That
distinction is declared in the packaged manifest as `unmapped_inventory_input`,
and these tests fail if the workflow and the declaration diverge (#131).

They also pin that the workflow cannot go fail-open again (#161): the step used
to end in `|| true`, which swallowed crashes, while every source loader returns
silently when its root is absent — so the report shrank without saying so.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import yaml

from kg_microbe_fleet import load_fleet_manifest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "cross-repo-validation.yaml"
SCRIPT = ROOT / "scripts" / "inventory_unmapped_ingredients.py"
CAPABILITY = "unmapped_inventory_input"


def _workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _steps() -> list[dict]:
    return _workflow()["jobs"]["validate"]["steps"]


def _inventory_step() -> dict:
    return next(
        step for step in _steps() if "inventory_unmapped_ingredients.py" in
        str(step.get("run", ""))
    )


def _script():
    """Import the script without executing main()."""
    spec = importlib.util.spec_from_file_location("_inventory_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_the_workflow_checks_out_exactly_the_declared_input_set():
    """Adding a Mech to the capability without checking it out, or the reverse,
    must fail rather than quietly changing what the nightly report covers."""
    manifest = load_fleet_manifest()
    declared = {
        manifest.mechs[key].github
        for key in manifest.with_capability(CAPABILITY)
    }

    checked_out = {
        step["with"]["repository"]
        for step in _steps()
        if step.get("uses", "").startswith("actions/checkout")
        and "repository" in step.get("with", {})
    }

    assert declared, "the capability is declared for no Mech; the test is vacuous"
    assert checked_out == declared


def test_the_excluded_mechs_are_declared_not_applicable_with_a_reason():
    """A Mech absent from the input set is a recorded decision, not an omission."""
    manifest = load_fleet_manifest()
    excluded = set(manifest.mechs) - set(manifest.with_capability(CAPABILITY))

    assert excluded, "nothing is excluded; this test would be vacuous"
    for key in excluded:
        capability = manifest.mechs[key].capabilities[CAPABILITY]
        assert capability.status == "not_applicable", key
        assert capability.reason and capability.reason.strip(), key


def test_the_inventory_step_is_not_fail_open():
    """#161: `|| true` swallowed crashes and hid a missing checkout."""
    run = _inventory_step()["run"]
    executable = [
        line for line in run.splitlines() if line.strip()
        and not line.strip().startswith("#")
    ]
    joined = "\n".join(executable)

    assert "|| true" not in joined
    assert _inventory_step().get("continue-on-error") is not True


def test_the_workflow_requires_every_source_it_checks_out():
    """A checkout regression must fail the run, not shrink the report."""
    run = _inventory_step()["run"]
    module = _script()
    checked_out_roots = {"MEDIAINGREDIENTMECH_ROOT", "CULTUREMECH_ROOT",
                         "COMMUNITYMECH_ROOT"}

    expected = {
        label
        for label, _, _, variable in module.SOURCES
        if variable in checked_out_roots
    }

    assert expected, "no source maps to a checked-out root; the test is vacuous"
    for label in expected:
        assert f"--require-sources {label}" in run, label


def test_a_source_the_workflow_does_not_check_out_is_not_required():
    """kg-microbe is an external corpus this workflow does not clone. Requiring
    it would fail every run; ignoring it silently is what #161 was about, so it
    must be reported ABSENT instead."""
    run = _inventory_step()["run"]
    module = _script()

    external = {
        label for label, _, _, variable in module.SOURCES
        if variable == "KGMICROBE_ROOT"
    }

    assert external, "no external source declared; the test is vacuous"
    for label in external:
        assert f"--require-sources {label}" not in run, label


def test_every_source_declares_the_root_it_reads():
    """Coverage reporting depends on each source naming its own root."""
    module = _script()

    assert module.SOURCES
    for entry in module.SOURCES:
        label, loader, root, variable = entry
        assert isinstance(label, str) and label
        assert callable(loader)
        assert isinstance(root, Path)
        assert isinstance(variable, str) and variable.endswith("_ROOT")


# --------------------------------------------------------------------------
# #163: coverage must not change the shape of the published inventory TSV
# --------------------------------------------------------------------------


def _run_inventory(tmp_path: Path, monkeypatch) -> object:
    """Run the inventory against a one-record MIM tree and nothing else."""
    ingredients = tmp_path / "mim" / "data" / "ingredients" / "unmapped"
    ingredients.mkdir(parents=True)
    (ingredients / "t.yaml").write_text(
        "preferred_term: Test Substance\nidentifier: UNMAPPED_0001\n",
        encoding="utf-8",
    )
    for variable, value in (
        ("MEDIAINGREDIENTMECH_ROOT", str(tmp_path / "mim")),
        ("KGMICROBE_ROOT", str(tmp_path / "absent")),
        ("CULTUREMECH_ROOT", str(tmp_path / "absent")),
        ("COMMUNITYMECH_ROOT", str(tmp_path / "absent")),
    ):
        monkeypatch.setenv(variable, value)
    module = _script()
    # REPO_ROOT too: the script prints its outputs with `relative_to(REPO_ROOT)`,
    # which raises when they are redirected outside the repository.
    monkeypatch.setattr(module, "REPO_ROOT", tmp_path)
    monkeypatch.setattr(module, "OUT_DIR", tmp_path / "out")
    monkeypatch.setattr(module, "OUT_TSV", tmp_path / "out" / "inventory.tsv")
    monkeypatch.setattr(module, "OUT_MD", tmp_path / "out" / "inventory.md")
    monkeypatch.setattr(
        module, "OUT_COVERAGE_TSV", tmp_path / "out" / "coverage.tsv"
    )
    assert module.main([]) == 0
    return module


def test_the_inventory_tsv_header_is_still_the_first_row(tmp_path, monkeypatch):
    """#163: coverage rows were prepended into this file, displacing the header.

    `complex-ingredient-resolver` consumes this TSV as input, so its shape is a
    published contract.
    """
    import csv

    _run_inventory(tmp_path, monkeypatch)
    rows = list(
        csv.reader((tmp_path / "out" / "inventory.tsv").open(), delimiter="\t")
    )

    assert rows[0][0] == "source"
    assert len(rows[0]) == 8
    assert not any(row and row[0].startswith("#") for row in rows)


def test_coverage_is_a_well_formed_sidecar(tmp_path, monkeypatch):
    import csv

    _run_inventory(tmp_path, monkeypatch)
    rows = list(
        csv.reader((tmp_path / "out" / "coverage.tsv").open(), delimiter="\t")
    )

    assert rows[0] == ["source", "state", "root_or_missing_variable", "rows"]
    assert all(len(row) == 4 for row in rows), "every row must have four columns"
    states = {row[1] for row in rows[1:]}
    assert states <= {"read", "empty", "ABSENT"}
    assert "ABSENT" in states, "the fixture leaves three roots absent"


def test_the_workflow_uploads_the_coverage_sidecar():
    """An archived artifact set that omits coverage is back to square one."""
    upload = next(
        step for step in _steps()
        if step.get("uses", "").startswith("actions/upload-artifact")
    )

    assert "unmapped_inventory_coverage.tsv" in upload["with"]["path"]
