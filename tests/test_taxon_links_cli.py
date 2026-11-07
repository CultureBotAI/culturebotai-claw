"""`kg-microbe-links taxa` reads the real manifest's declarations against fake roots."""

from __future__ import annotations

import io
import json
import os
import tarfile
from pathlib import Path

import pytest
import yaml

from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_links import __main__ as cli
from kg_microbe_links.__main__ import main
from tests.test_taxon_links import taxonmech  # noqa: F401  (fixture)

MANIFEST = load_fleet_manifest()
ENABLED = sorted(k for k, m in MANIFEST.mechs.items()
                 if (c := m.capabilities.get("taxon_links")) is not None and c.is_enabled)


def _nested(dotted: str, value: object) -> dict:
    """A record holding `value` at the slot path, one element per list."""
    node: object = value
    for part in reversed(dotted.split(".")):
        lists = part.count("[]")
        name = part[: len(part) - 2 * lists]
        for _ in range(lists):
            node = [node]
        node = {name: node}
    assert isinstance(node, dict)
    return node


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


@pytest.mark.parametrize("value", ["NCBITaxon:424242", "NCBITaxon:bogus"])
def test_strict_fails_on_an_absent_or_malformed_id(tmp_path, taxonmech, value):  # noqa: F811
    root = _mech(tmp_path, "dufmech", {"data/families/a.yaml": {"causal_graphs": [{"taxon": value}]}})
    assert main(["taxa", "--mech", "dufmech", "--root", str(root), "--taxonmech-root", str(taxonmech), "--strict"]) == 1
    assert main(["taxa", "--mech", "dufmech", "--root", str(root), "--taxonmech-root", str(taxonmech)]) == 0


def test_an_unusable_mech_root_is_exit_two(tmp_path, taxonmech, capsys):  # noqa: F811
    assert main(["taxa", "--mech", "dufmech", "--root", str(tmp_path / "nowhere"), "--taxonmech-root", str(taxonmech)]) == 2
    assert "not a directory" in capsys.readouterr().err


def test_a_taxdump_needed_only_for_names_that_is_missing_is_exit_two(tmp_path, taxonmech, capsys):  # noqa: F811
    """names.dmp is read only in as_dict, for a strain outside the inventory; a tarball without it is exit 2.

    A missing conf file or nodes.dmp fails inside collect, which cannot tell where the guard ends.
    """
    tar_path = taxonmech / "data" / "source_snapshots" / "taxdump.tar.gz"
    with tarfile.open(tar_path, "r:gz") as tar:
        kept = [(info, tar.extractfile(info).read()) for info in tar.getmembers() if info.name != "names.dmp"]
    with tarfile.open(tar_path, "w:gz") as tar:
        for info, payload in kept:
            tar.addfile(info, io.BytesIO(payload))
    root = _mech(tmp_path, "dufmech", {"data/families/a.yaml": {"causal_graphs": [{"taxon": "NCBITaxon:511145"}]}})
    assert main(["taxa", "--mech", "dufmech", "--root", str(root), "--taxonmech-root", str(taxonmech)]) == 2
    assert "names.dmp" in capsys.readouterr().err


def test_a_taxdump_that_is_not_a_tarball_is_exit_two(tmp_path, taxonmech, capsys):  # noqa: F811
    (taxonmech / "data" / "source_snapshots" / "taxdump.tar.gz").write_bytes(b"not a tarball")
    root = _mech(tmp_path, "dufmech", {"data/families/a.yaml": {"causal_graphs": [{"taxon": "NCBITaxon:511145"}]}})
    assert main(["taxa", "--mech", "dufmech", "--root", str(root), "--taxonmech-root", str(taxonmech)]) == 2
    assert "cannot be read as a gzipped tar" in capsys.readouterr().err


def _rewrite_tarball(root: Path, **members: bytes | None) -> None:
    """Replace (bytes) or drop (None) members of the fixture tarball under `root`, keeping the rest."""
    tar_path = root / "data" / "source_snapshots" / "taxdump.tar.gz"
    with tarfile.open(tar_path, "r:gz") as tar:
        kept = [(info, tar.extractfile(info).read()) for info in tar.getmembers()]
    with tarfile.open(tar_path, "w:gz") as tar:
        for info, payload in kept:
            if info.name in members:
                if members[info.name] is None:
                    continue
                payload = members[info.name]
                info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads a mode-0 file")
def test_an_unreadable_taxdump_tarball_is_exit_two(tmp_path, taxonmech, capsys):  # noqa: F811
    """PermissionError is an OSError, the branch gzip.BadGzipFile also takes: exit 2, not a traceback."""
    tar_path = taxonmech / "data" / "source_snapshots" / "taxdump.tar.gz"
    tar_path.chmod(0)
    root = _mech(tmp_path, "dufmech", {"data/families/a.yaml": {"causal_graphs": [{"taxon": "NCBITaxon:511145"}]}})
    try:
        assert main(["taxa", "--mech", "dufmech", "--root", str(root), "--taxonmech-root", str(taxonmech)]) == 2
    finally:
        tar_path.chmod(0o644)
    assert "cannot be read as a gzipped tar" in capsys.readouterr().err


def test_a_member_that_is_not_taxdump_shaped_is_exit_two(tmp_path, taxonmech, capsys):  # noqa: F811
    """Without a pinned digest, a nodes.dmp holding garbage is refused at the row parse, not a ValueError traceback."""
    _rewrite_tarball(taxonmech, **{"nodes.dmp": b"garbage\n"})
    root = _mech(tmp_path, "dufmech", {"data/families/a.yaml": {"causal_graphs": [{"taxon": "NCBITaxon:511145"}]}})
    assert main(["taxa", "--mech", "dufmech", "--root", str(root), "--taxonmech-root", str(taxonmech)]) == 2
    assert "is not in taxdump format" in capsys.readouterr().err


def test_a_tarball_that_does_not_match_the_pinned_sha256_is_exit_two(tmp_path, taxonmech, capsys):  # noqa: F811
    """TaxonMech's conf pins the snapshot's sha256; a corrupt, truncated or wrong file fails that check first."""
    import hashlib
    tar_path = taxonmech / "data" / "source_snapshots" / "taxdump.tar.gz"
    conf = taxonmech / "conf" / "ncbi_taxdump.yaml"
    conf.write_text(conf.read_text(encoding="utf-8") + f"sha256: {hashlib.sha256(tar_path.read_bytes()).hexdigest()}\n",
                    encoding="utf-8")
    root = _mech(tmp_path, "dufmech", {"data/families/a.yaml": {"causal_graphs": [{"taxon": "NCBITaxon:511145"}]}})
    assert main(["taxa", "--mech", "dufmech", "--root", str(root), "--taxonmech-root", str(taxonmech)]) == 0
    _rewrite_tarball(taxonmech, **{"nodes.dmp": b"garbage\n"})  # same shape of damage, now caught before any parse
    assert main(["taxa", "--mech", "dufmech", "--root", str(root), "--taxonmech-root", str(taxonmech)]) == 2
    assert "does not match the sha256" in capsys.readouterr().err


def test_a_truncated_taxdump_tarball_is_exit_two(tmp_path, taxonmech, capsys):  # noqa: F811
    """gzip fails mid-stream, not at open: still exit 2."""
    tar_path = taxonmech / "data" / "source_snapshots" / "taxdump.tar.gz"
    payload = tar_path.read_bytes()
    tar_path.write_bytes(payload[: len(payload) // 2])
    root = _mech(tmp_path, "dufmech", {"data/families/a.yaml": {"causal_graphs": [{"taxon": "NCBITaxon:511145"}]}})
    assert main(["taxa", "--mech", "dufmech", "--root", str(root), "--taxonmech-root", str(taxonmech)]) == 2
    assert "cannot be read as a gzipped tar" in capsys.readouterr().err


def test_an_absent_taxdump_tarball_is_exit_two(tmp_path, taxonmech, capsys):  # noqa: F811
    """TaxonMech gitignores data/source_snapshots/, so a fresh clone has the conf and no tarball."""
    (taxonmech / "data" / "source_snapshots" / "taxdump.tar.gz").unlink()
    root = _mech(tmp_path, "dufmech", {"data/families/a.yaml": {"causal_graphs": [{"taxon": "NCBITaxon:511145"}]}})
    assert main(["taxa", "--mech", "dufmech", "--root", str(root), "--taxonmech-root", str(taxonmech)]) == 2
    assert "is not present" in capsys.readouterr().err


def test_strict_passes_on_every_non_blocking_verdict(tmp_path, taxonmech):  # noqa: F811
    """A strain, a genus, an animal, a metagenome and an unattested bacterium: none fails --strict."""
    taxa = ["NCBITaxon:511145", "NCBITaxon:561", "NCBITaxon:9606", "NCBITaxon:999", "NCBITaxon:1423"]
    root = _mech(tmp_path, "dufmech", {"data/families/a.yaml": {"causal_graphs": [{"taxon": t} for t in taxa]}})
    assert main(["taxa", "--mech", "dufmech", "--root", str(root), "--taxonmech-root", str(taxonmech), "--strict"]) == 0

def test_strict_fails_when_the_only_record_will_not_parse(tmp_path, taxonmech):  # noqa: F811
    root = tmp_path / "dufmech"
    (root / MANIFEST.mechs["dufmech"].package_path).mkdir(parents=True)
    (root / "data" / "families").mkdir(parents=True)
    (root / "data" / "families" / "a.yaml").write_text("causal_graphs: [unclosed", encoding="utf-8")
    assert main(["taxa", "--mech", "dufmech", "--root", str(root), "--taxonmech-root", str(taxonmech), "--strict"]) == 1
    assert main(["taxa", "--mech", "dufmech", "--root", str(root), "--taxonmech-root", str(taxonmech)]) == 0


def test_sample_is_honoured_and_recorded(tmp_path, taxonmech, capsys):  # noqa: F811
    root = _mech(tmp_path, "dufmech", {f"data/families/{n}.yaml": {"causal_graphs": [{"taxon": "NCBITaxon:562"}]}
                                        for n in "abc"})
    assert main(["taxa", "--mech", "dufmech", "--root", str(root), "--taxonmech-root", str(taxonmech), "--sample", "2"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert (report["records"], report["sample"]) == (2, 2)


def test_all_reports_every_enabled_mech_and_skips_the_rest(tmp_path, taxonmech, monkeypatch, capsys):  # noqa: F811
    roots = {}
    for key in ENABLED:
        mech = MANIFEST.mechs[key]
        slot = mech.capabilities["taxon_links"].settings["slots"][0]
        glob = mech.record_globs[0]
        roots[key] = _mech(tmp_path, key, {glob.split("*")[0] + "one.yaml": _nested(slot, "NCBITaxon:562")})

    def fake_root(key, *, claw_root, environ=None, manifest=None, explicit=None):
        return Path(explicit) if explicit else roots[key]

    monkeypatch.setattr(cli, "resolve_mech_root", fake_root)

    assert main(["taxa", "--all", "--taxonmech-root", str(taxonmech)]) == 0

    out, err = capsys.readouterr()
    reports = json.loads(out)
    assert sorted(reports) == ENABLED
    assert all(reports[k]["verdicts"]["record"]["occurrences"] == 1 for k in ENABLED)
    for key in sorted(set(MANIFEST.mechs) - set(ENABLED)):
        assert f"{key}: skipped" in err


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
