"""One validator for every Mech's source catalogue (#132 Phase 6, #223).

Two Mechs wrote their own. ProteinTraitsMech's checks `url` and nothing else
and was never wired into CI; TraitMech adopted it, enforced every required
field, and ran it from `just qc`.

Taking the stronger one as the shared implementation would have been wrong, and
only running it against the other Mech's data showed why: 47 errors, 46 of them
false, because the two repositories write different shapes. TraitMech writes one
block per source; ProteinTraitsMech writes one block per FILE, so `interpro` is
six blocks. Judged block by block, the six look like five duplicate ids and a
pile of missing licences.

Hence the source-group model these tests pin: `name`, `license` and `seeder`
are obligations of the source, met by any block in it; uniqueness is over
(source, file).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from kg_microbe_fleet.roots import MechRootError, resolve_mech_root
from kg_microbe_sources import CatalogueError, load_blocks, validate

ROOT = Path(__file__).resolve().parents[1]


def _catalogue(tmp_path: Path, blocks) -> Path:
    path = tmp_path / "download.yaml"
    path.write_text(yaml.safe_dump(blocks, sort_keys=False), encoding="utf-8")
    return path


def _source(**overrides) -> dict:
    block = {
        "url": "https://example.org/x.tsv",
        "name": "Example",
        "source": "example",
        "license": "CC0-1.0",
        "status": "candidate",
    }
    block.update(overrides)
    return block


# --------------------------------------------------------------------------
# Reading
# --------------------------------------------------------------------------


def test_a_valid_catalogue_passes(tmp_path):
    report = validate(load_blocks(_catalogue(tmp_path, [_source()])))

    assert report.ok
    assert not report.errors


@pytest.mark.parametrize(
    ("content", "message"),
    [
        ("[]\n", "lists no sources"),
        ("\n", "must be a YAML list"),
        ("{a: 1}\n", "must be a YAML list"),
        ("- [unclosed\n", "not valid YAML"),
    ],
)
def test_an_unusable_catalogue_refuses_with_a_diagnostic(tmp_path, content, message):
    """An empty catalogue used to pass green in both Mechs, so deleting every
    source satisfied the gate. And a syntax error must name the file, not raise
    a parser traceback at whoever ran the check."""
    path = tmp_path / "download.yaml"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(CatalogueError, match=message):
        load_blocks(path)


def test_a_missing_catalogue_says_which_file(tmp_path):
    with pytest.raises(CatalogueError, match="cannot read source catalogue"):
        load_blocks(tmp_path / "absent.yaml")


def test_a_mis_indented_block_is_reported_not_raised(tmp_path):
    """A bare `-` with a mis-indented body parses to None, and the file's own
    style makes that a one-keystroke mistake."""
    path = tmp_path / "download.yaml"
    path.write_text("- url: https://example.org\n  source: a\n  name: A\n"
                    "  license: CC0\n  status: candidate\n-\n", encoding="utf-8")

    report = validate(load_blocks(path))

    assert any("not a mapping" in str(f) for f in report.errors)


# --------------------------------------------------------------------------
# The source group
# --------------------------------------------------------------------------


def test_a_group_obligation_is_met_by_any_block(tmp_path):
    """The whole reason the block-by-block validator misreported 46 findings:
    ProteinTraitsMech declares a licence once for six InterPro files."""
    blocks = [
        _source(local_name="a.tsv"),
        {"url": "https://example.org/b.tsv", "source": "example",
         "status": "candidate", "local_name": "b.tsv"},
    ]

    report = validate(load_blocks(_catalogue(tmp_path, blocks)))

    assert report.ok, [str(f) for f in report.errors]


def test_a_group_missing_an_obligation_everywhere_is_an_error(tmp_path):
    blocks = [
        {"url": "https://example.org/a", "source": "example", "status": "candidate",
         "local_name": "a"},
        {"url": "https://example.org/b", "source": "example", "status": "candidate",
         "local_name": "b"},
    ]

    report = validate(load_blocks(_catalogue(tmp_path, blocks)))

    assert {f.message for f in report.errors} == {
        "missing required field: name",
        "missing required field: license",
    }


def test_a_multi_block_source_must_say_which_file_each_block_describes(tmp_path):
    """The genuine defect in ProteinTraitsMech's catalogue: four sources whose
    blocks nothing distinguishes. Which block is which file cannot be answered
    from the catalogue, and its own validator could not see it."""
    blocks = [_source(), _source()]

    report = validate(load_blocks(_catalogue(tmp_path, blocks)))

    assert len(report.errors) == 2
    assert all("must name the file" in f.message for f in report.errors)


def test_two_blocks_naming_the_same_file_is_an_error(tmp_path):
    blocks = [_source(local_name="same.tsv"), _source(local_name="same.tsv")]

    report = validate(load_blocks(_catalogue(tmp_path, blocks)))

    assert any("already describes block" in f.message for f in report.errors)


def test_a_single_block_source_needs_no_file_name(tmp_path):
    """TraitMech writes one block per source and names no file. Requiring one
    unconditionally would fail the catalogue this validator came from."""
    assert validate(load_blocks(_catalogue(tmp_path, [_source()]))).ok


def test_a_block_without_a_source_id_is_reported(tmp_path):
    blocks = [{"url": "https://example.org", "name": "N", "status": "candidate"}]

    report = validate(load_blocks(_catalogue(tmp_path, blocks)))

    assert any("missing required field: source" in f.message for f in report.errors)


# --------------------------------------------------------------------------
# Per-block obligations
# --------------------------------------------------------------------------


@pytest.mark.parametrize("field", ["url", "status"])
def test_every_block_must_carry_its_own_url_and_status(tmp_path, field):
    """These are not group obligations: each file has its own address, and one
    file of a source can be seeded while another is still a candidate."""
    blocks = [_source(local_name="a"), _source(local_name="b", **{field: None})]

    report = validate(load_blocks(_catalogue(tmp_path, blocks)))

    assert any(f"missing {field}" in f.message for f in report.errors)


def test_an_unknown_status_is_refused(tmp_path):
    report = validate(load_blocks(_catalogue(tmp_path, [_source(status="maybe")])))

    assert any("invalid status" in f.message for f in report.errors)


def test_a_non_string_status_is_reported_rather_than_crashing(tmp_path):
    report = validate(load_blocks(_catalogue(tmp_path, [_source(status=3)])))

    assert any("must be a string" in f.message for f in report.errors)


# --------------------------------------------------------------------------
# Seeders
# --------------------------------------------------------------------------


def test_a_seeded_source_must_name_a_seeder(tmp_path):
    report = validate(load_blocks(_catalogue(tmp_path, [_source(status="seeded")])))

    assert any("no seeder is named" in f.message for f in report.errors)


def test_a_seeder_may_be_named_however_the_repository_names_its_scripts(tmp_path):
    """TraitMech's rule was `seed_*.py`, which makes ProteinTraitsMech's real
    `build_chebi_sidecar.py` an error. The rule's purpose was traversal, not
    naming."""
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "build_chebi_sidecar.py").write_text("", encoding="utf-8")
    blocks = [_source(status="seeded", seeder="build_chebi_sidecar.py")]

    report = validate(load_blocks(_catalogue(tmp_path, blocks)), seeder_dir=scripts)

    assert report.ok, [str(f) for f in report.errors]


@pytest.mark.parametrize("seeder", ["../download.yaml", "/etc/passwd", "a/b.py"])
def test_a_seeder_may_not_escape_the_scripts_directory(tmp_path, seeder):
    """Without this, `seeder: ../download.yaml` resolves to a real file and
    passes, which also lets a source dodge the orphan-seeder warning."""
    blocks = [_source(status="seeded", seeder=seeder)]

    report = validate(load_blocks(_catalogue(tmp_path, blocks)))

    assert any("bare Python filename" in f.message for f in report.errors)


def test_a_named_seeder_that_does_not_exist_is_an_error(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    blocks = [_source(status="seeded", seeder="seed_absent.py")]

    report = validate(load_blocks(_catalogue(tmp_path, blocks)), seeder_dir=scripts)

    assert any("seeder script not found" in f.message for f in report.errors)


def test_an_unreferenced_seeder_is_a_warning_not_an_error(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "seed_orphan.py").write_text("", encoding="utf-8")

    report = validate(load_blocks(_catalogue(tmp_path, [_source()])), seeder_dir=scripts)

    assert report.ok
    assert any("not referenced" in f.message for f in report.warnings)


# --------------------------------------------------------------------------
# Licences — what the catalogue exists to carry
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "licence",
    ["CC BY-NC 4.0", "NonCommercial (ELM)", "academic use only, login required"],
)
def test_a_restrictive_licence_is_surfaced(tmp_path, licence):
    report = validate(load_blocks(_catalogue(tmp_path, [_source(license=licence)])))

    assert any("restrictive licence" in f.message for f in report.warnings)
    assert report.ok, "surfaced for a human, not failed"


def test_an_unresolved_licence_is_surfaced(tmp_path):
    report = validate(load_blocks(_catalogue(tmp_path, [_source(license="unknown")])))

    assert any("licence unresolved" in f.message for f in report.warnings)


def test_upstream_licences_on_a_source_in_use_are_surfaced(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    (scripts / "seed_x.py").write_text("", encoding="utf-8")
    blocks = [
        _source(status="seeded", seeder="seed_x.py", upstream_licenses=["CC-BY-4.0"])
    ]

    report = validate(load_blocks(_catalogue(tmp_path, blocks)), seeder_dir=scripts)

    assert any("carry those terms forward" in f.message for f in report.warnings)


# --------------------------------------------------------------------------
# Against the real catalogues
# --------------------------------------------------------------------------


@pytest.mark.parametrize("mech", ["traitmech", "proteintraitsmech"])
def test_the_real_catalogue_parses_and_groups(mech):
    """The acceptance criterion for the whole exercise: one implementation
    reads both shapes. Skips where the checkout is absent rather than passing
    quietly."""
    try:
        root = resolve_mech_root(mech, claw_root=ROOT)
    except MechRootError as exc:
        pytest.skip(f"needs a {mech} checkout: {exc}")
    catalogue = root / "download.yaml"
    if not catalogue.is_file():
        pytest.skip(f"{mech} has no download.yaml")

    blocks = load_blocks(catalogue)
    report = validate(blocks, seeder_dir=root / "scripts")

    assert blocks, "a catalogue with no sources is a broken file"
    # Errors are reported, not asserted away: ProteinTraitsMech has five real
    # ones today (#223), and pinning a count here would fail the day they are
    # fixed, which is backwards.
    for finding in report.errors:
        assert finding.subject and finding.message


# --------------------------------------------------------------------------
# The CLI, and absence as a declared decision
# --------------------------------------------------------------------------


def test_the_capability_declares_who_has_a_catalogue():
    """Absence is a recorded decision, not a missing file. Three Mechs fetch
    each source from its own script; saying so in the manifest is what lets a
    tool tell "not applicable" from "broken"."""
    from kg_microbe_fleet import load_fleet_manifest

    manifest = load_fleet_manifest()
    enabled = set(manifest.with_capability("source_catalogue"))

    assert enabled == {"traitmech", "proteintraitsmech"}
    for key, mech in manifest.mechs.items():
        capability = mech.capabilities["source_catalogue"]
        if key not in enabled:
            assert capability.reason, f"{key} disables it without a reason"


def test_a_mech_without_a_catalogue_says_so_rather_than_failing(capsys):
    """Reporting "No such file or directory" would read as breakage and say
    nothing about why, when the manifest already carries the reason."""
    from kg_microbe_sources.__main__ import main

    assert main(["check", "--mech", "culturemech"]) == 0

    out = capsys.readouterr().out
    assert "declares no source catalogue" in out
    assert "download.yaml" in out, "the reason has to survive into the message"


def test_the_cli_reports_findings_and_exits_nonzero_on_an_error(tmp_path, capsys):
    from kg_microbe_sources.__main__ import main

    try:
        root = resolve_mech_root("proteintraitsmech", claw_root=ROOT)
    except MechRootError as exc:
        pytest.skip(f"needs a ProteinTraitsMech checkout: {exc}")
    if not (root / "download.yaml").is_file():
        pytest.skip("no catalogue to check")

    code = main(["check", "--mech", "proteintraitsmech"])
    out = capsys.readouterr().out

    assert "block(s)" in out
    assert code in (0, 1)
    if code == 1:
        assert "ERROR:" in out and "error(s)." in out
