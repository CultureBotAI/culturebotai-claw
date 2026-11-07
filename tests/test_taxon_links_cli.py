"""`kg-microbe-links taxa` reads the real manifest's declarations against fake roots."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_links.__main__ import main
from tests.test_taxon_links import taxonmech  # noqa: F401  (fixture)

MANIFEST = load_fleet_manifest()


def _mech(tmp_path: Path, key: str, records: dict[str, object]) -> Path:
    """A fake checkout of `key`, with records under its first manifest glob's directory."""
    root = tmp_path / key
    package = root / MANIFEST.mechs[key].package_path
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("", encoding="utf-8")
    for name, content in records.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(content), encoding="utf-8")
    return root


def test_dufmech_taxa_are_judged_through_its_declared_slot(tmp_path, taxonmech, capsys):  # noqa: F811
    root = _mech(tmp_path, "dufmech", {
        "data/families/a.yaml": {"causal_graphs": [{"taxon": "NCBITaxon:511145"}, {"taxon": "NCBITaxon:46170"}]},
    })

    assert main(["taxa", "--mech", "dufmech", "--root", str(root), "--taxonmech-root", str(taxonmech)]) == 0

    out, err = capsys.readouterr()
    report = json.loads(out)
    assert report["mech"] == "dufmech" and report["records"] == 1
    assert report["verdicts"]["species_of_strain"]["occurrences"] == 1
    assert report["verdicts"]["retired"]["occurrences"] == 1
    assert "dufmech: 1 records" in err and "retired 1" in err


def test_strict_fails_on_a_retired_id_and_passes_without_one(tmp_path, taxonmech):  # noqa: F811
    stale = _mech(tmp_path / "stale", "dufmech", {"data/families/a.yaml": {"causal_graphs": [{"taxon": "NCBITaxon:46170"}]}})
    clean = _mech(tmp_path / "clean", "dufmech", {"data/families/a.yaml": {"causal_graphs": [{"taxon": "NCBITaxon:562"}]}})
    assert main(["taxa", "--mech", "dufmech", "--root", str(stale), "--taxonmech-root", str(taxonmech), "--strict"]) == 1
    assert main(["taxa", "--mech", "dufmech", "--root", str(clean), "--taxonmech-root", str(taxonmech), "--strict"]) == 0


def test_a_mech_without_an_enabled_declaration_says_so_and_exits_zero(tmp_path, taxonmech, capsys):  # noqa: F811
    assert main(["taxa", "--mech", "aimech", "--taxonmech-root", str(taxonmech)]) == 0
    out, _ = capsys.readouterr()
    assert out.startswith("aimech declares no taxon links:")


def test_a_missing_taxonmech_file_is_exit_two(tmp_path, taxonmech, capsys):  # noqa: F811
    (taxonmech / "curation" / "seed_scope.tsv").unlink()
    assert main(["taxa", "--mech", "dufmech", "--root", str(tmp_path), "--taxonmech-root", str(taxonmech)]) == 2
    assert "seed_scope.tsv" in capsys.readouterr().err


def test_root_cannot_go_with_all(taxonmech):  # noqa: F811
    with pytest.raises(SystemExit) as caught:
        main(["taxa", "--all", "--root", "/nowhere", "--taxonmech-root", str(taxonmech)])
    assert caught.value.code == 2


def test_every_enabled_declaration_names_slots_the_schema_shape_allows():
    """A declared slot path is well-formed; an empty list cannot pass the manifest (required_when_enabled)."""
    from kg_microbe_links.taxa import resolve_all
    for key, mech in MANIFEST.mechs.items():
        capability = mech.capabilities.get("taxon_links")
        if capability is not None and capability.is_enabled:
            slots = capability.settings.get("slots", ())
            assert slots, key
            for slot in slots:
                resolve_all({}, slot)
