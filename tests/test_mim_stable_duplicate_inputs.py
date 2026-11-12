"""Reject ambiguous stable inputs before any guarded artifact publication.

Synthetic contract fixtures only; repository/label-provider transport is adapted
by the shared fixture, while capture and artifact transactions remain native.
"""

import pytest
from test_mim_owned_name_export import cli as cli  # Explicit fixture re-export.
from test_mim_stable_identity import builder
from test_mim_stable_identity import stable_cli as stable_cli


def artifact_before(fixture, existing):
    paths = builder.artifact_paths(fixture["output"])
    if existing:
        assert fixture["run"]() == paths
    return paths, [p.read_bytes() if p.exists() else None for p in paths]


def assert_artifacts(paths, before):
    assert [p.read_bytes() if p.exists() else None for p in paths] == before


@pytest.mark.parametrize("existing", [False, True], ids=["new", "existing-triplet"])
@pytest.mark.parametrize("field", ["mim_id", "ontology_id", "mapping_quality", "history"])
def test_duplicate_yaml_keys_refuse_without_publishing(stable_cli, existing, field):
    paths, before = artifact_before(stable_cli, existing)
    owner = stable_cli["records"] / "Subject.yaml"
    original = owner.read_text()
    if field == "mim_id":
        changed = "mim_id: MIM:9999999\n" + original
        key = "mim_id"
    elif field == "ontology_id":
        assert "  ontology_id: CHEBI:1\n" in original
        changed = original.replace("  ontology_id: CHEBI:1\n",
                                   "  ontology_id: CHEBI:9999999\n  ontology_id: CHEBI:1\n")
        key = "ontology_id"
    elif field == "mapping_quality":
        assert "  mapping_quality: EXACT_MATCH\n" in original
        changed = original.replace("  mapping_quality: EXACT_MATCH\n",
                                   "  mapping_quality: NARROW_MATCH\n  mapping_quality: EXACT_MATCH\n")
        key = "mapping_quality"
    else:
        marker = "- timestamp: '2026-10-01T00:00:00Z'\n"
        assert marker in original
        changed = original.replace(marker,
                                   "- timestamp: '2000-01-01T00:00:00Z'\n"
                                   "  timestamp: '2026-10-01T00:00:00Z'\n")
        key = "timestamp"
    owner.write_text(changed)
    with pytest.raises(ValueError, match=f"Duplicate YAML key: {key}"):
        stable_cli["run"]()
    assert_artifacts(paths, before)
    assert owner.read_text() == changed  # No attempted input repair or rollback.


@pytest.mark.parametrize("existing", [False, True], ids=["new", "existing-triplet"])
@pytest.mark.parametrize("field", ["subject_id", "predicate_id", "object_id"])
def test_duplicate_canonical_headers_refuse_without_publishing(stable_cli, existing, field):
    paths, before = artifact_before(stable_cli, existing)
    columns = ["subject_id", "predicate_id", "object_id"]
    row = ["MIM:Subject", "skos:exactMatch", "kgmicrobe.ingredient:literal_alias"]
    offset = columns.index(field)
    columns.insert(offset, field)
    row.insert(offset, {
        "subject_id": "MIM:UNRESOLVED_OWNER",
        "predicate_id": "skos:broadMatch",
        "object_id": "kgmicrobe.ingredient:0000002",
    }[field])
    raw = "\t".join(columns) + "\n" + "\t".join(row) + "\n"
    stable_cli["canonical"].write_text(raw)
    with pytest.raises(ValueError, match="Duplicate canonical compatibility column name"):
        stable_cli["run"]()
    assert_artifacts(paths, before)
    assert stable_cli["canonical"].read_text() == raw


def test_repeated_nonidentity_header_is_also_ambiguous(stable_cli):
    stable_cli["canonical"].write_text(
        "subject_id\tpredicate_id\tobject_id\tcomment\tcomment\n")
    with pytest.raises(ValueError, match="Duplicate canonical compatibility column name"):
        stable_cli["run"]()
    assert not any(path.exists() for path in builder.artifact_paths(stable_cli["output"]))


def test_stable_duplicate_in_unmapped_population_refuses(stable_cli):
    owner = stable_cli["records"] / "Owned.yaml"
    target = stable_cli["root"] / "data/ingredients/unmapped/Owned.yaml"
    target.write_bytes(b"mim_id: MIM:9999999\n" + owner.read_bytes())
    owner.unlink()
    with pytest.raises(ValueError, match="Duplicate YAML key: mim_id"):
        stable_cli["run"]()
    assert not any(path.exists() for path in builder.artifact_paths(stable_cli["output"]))


def test_duplicate_policy_does_not_change_explicit_legacy_mode(cli):
    owner = cli["records"] / "Subject.yaml"
    owner.write_bytes(b"mim_id: MIM:9999999\nmim_id: MIM:0000002\n" + owner.read_bytes())
    assert builder._read_mapped_records(cli["records"])[owner]["mim_id"] == "MIM:0000002"
    paths = cli["run"]()
    assert all(path.is_file() for path in paths)
