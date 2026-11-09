"""Exercise label rulings through the YAML/CSV loaders and the CLI export path."""

import csv
import importlib.util
import sys
from pathlib import Path

import yaml

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
_SPEC = importlib.util.spec_from_file_location(
    "unified_label_index_integration_builder",
    _SCRIPTS / "build_unified_ingredient_mapping.py",
)
b = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(b)


def _write_record(root, filename, identifier, preferred, status="MAPPED", **extra):
    path = root / "data/ingredients/mapped" / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump({
        "identifier": identifier,
        "preferred_term": preferred,
        "mapping_status": status,
        **extra,
    }), encoding="utf-8")


def _write_labels(root, rows):
    path = root / "docs/data/label_index.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as output:
        writer = csv.writer(output)
        writer.writerow([
            "label", "match_type", "identifier", "preferred_term", "ontology_id",
            "mapping_status", "ambiguity",
        ])
        writer.writerows(rows)


def _build(root, name, term_id):
    indexes = b.load_mim_index(root)
    row, = b.build_unified_rows(
        {name: {"term_id": term_id, "count": 1, "example_media": []}},
        *indexes,
        label_index=b.load_mim_label_index(root),
    )
    return row


def test_main_exports_label_ruling_through_real_loaders_and_tsv(monkeypatch, tmp_path):
    mim, cm = tmp_path / "mim", tmp_path / "cm"
    _write_record(mim, "Anhydrous.yaml", "CHEBI:1", "Anhydrous")
    _write_record(mim, "Hydrate.yaml", "CHEBI:2", "Hydrate",
                  synonyms=[{"synonym_text": "Hydrate synonym"}])
    # Only the published index connects this exact label to the hydrate.
    _write_labels(mim, [[
        "Exact hydrate label", "synonym", "CHEBI:2", "Hydrate", "CHEBI:2",
        "MAPPED", "unique",
    ]])
    recipe = cm / "data/normalized_yaml/test/recipe.yaml"
    recipe.parent.mkdir(parents=True)
    recipe.write_text(yaml.safe_dump({"id": "CM:1", "ingredients": [
        {"preferred_term": "Exact hydrate label", "term": {"id": "CHEBI:1"}},
    ]}), encoding="utf-8")

    # These are isolated fixture roots; no real downstream checkout is opened.
    validated_roots = []
    monkeypatch.setattr(
        b, "require_mech_roots", lambda *args, **kwargs: validated_roots.append(args),
    )
    output = tmp_path / "output/unified.tsv"
    monkeypatch.setattr(sys, "argv", [
        "builder", "--mim", str(mim), "--culturemech", str(cm),
        "--output", str(output), "--format", "both",
    ])
    b.main()

    with output.open(newline="", encoding="utf-8") as source:
        reader = csv.DictReader(source, delimiter="\t")
        assert reader.fieldnames == [
            "ingredient_name", "occurrence_count", "chebi_id", "cas_rn",
            "kg_microbe_node_id", "mim_id", "culturemech_term_id", "mapping_status",
            "synonyms", "example_media",
        ]
        row, = list(reader)
    assert validated_roots == [("culturemech", "mediaingredientmech")]
    assert row["mim_id"] == row["chebi_id"] == "CHEBI:2"
    assert row["culturemech_term_id"] == ""
    assert row["occurrence_count"] == "1"
    assert row["example_media"] == "CM:1"
    assert row["synonyms"] == "Hydrate synonym"
    summary = yaml.safe_load(output.with_suffix(".yaml").read_text(encoding="utf-8"))
    assert summary["total_unique_ingredients"] == 1

    # The existing TSV consumer must see the corrected grounding too.
    sync_spec = importlib.util.spec_from_file_location(
        "unified_label_index_integration_sync", _SCRIPTS / "sync_mim_to_culturemech.py",
    )
    sync = importlib.util.module_from_spec(sync_spec)
    sync_spec.loader.exec_module(sync)
    exported = sync.load_mim_chebi_index(output)
    assert exported[sync._normalize("Exact hydrate label")] == "CHEBI:2"


def test_real_yaml_rejected_label_metadata_reaches_the_label_ruling(tmp_path):
    label = "Old trihydrate label"
    _write_record(tmp_path, "Survivor.yaml", "CHEBI:1", "Dihydrate", synonyms=[
        {"synonym_text": label, "synonym_type": "REJECTED_LABEL"},
    ])
    _write_record(tmp_path, "Old.yaml", "CHEBI:8", label, "REJECTED",
                  representative="CHEBI:1")
    _write_record(tmp_path, "Trihydrate.yaml", "CHEBI:9", "Trihydrate")
    _write_labels(tmp_path, [[
        label, "preferred_term", "CHEBI:1", label, "CHEBI:1", "REJECTED", "unique",
    ]])

    row = _build(tmp_path, label, "CHEBI:9")

    assert row["mim_id"] == row["chebi_id"] == "CHEBI:9"


def test_non_merge_rejection_cannot_be_reanimated_by_shared_identifier(tmp_path):
    _write_record(tmp_path, "A_invalid.yaml", "CHEBI:1", "invalid ingredient", "REJECTED",
                  curation_history=[{"action": "REJECTED", "new_status": "REJECTED"}])
    _write_record(tmp_path, "B_valid.yaml", "CHEBI:1", "valid ingredient")
    _write_labels(tmp_path, [[
        "invalid ingredient", "preferred_term", "CHEBI:1", "invalid ingredient",
        "CHEBI:1", "REJECTED", "unique",
    ]])

    row = _build(tmp_path, "invalid ingredient", "CHEBI:1")

    assert row["mapping_status"] == "REJECTED"
    assert row["mim_id"] == row["chebi_id"] == row["culturemech_term_id"] == ""


def test_documented_merge_label_still_resolves_to_its_live_survivor(tmp_path):
    _write_record(tmp_path, "Old.yaml", "FOODON:old", "Old ingredient", "REJECTED",
                  representative="CHEBI:2")
    _write_record(tmp_path, "Survivor.yaml", "CHEBI:2", "Survivor ingredient",
                  chemical_properties={"cas_rn": "123-45-6"})
    _write_labels(tmp_path, [[
        "Old ingredient", "preferred_term", "CHEBI:2", "Old ingredient", "CHEBI:2",
        "REJECTED", "unique",
    ]])

    row = _build(tmp_path, "Old ingredient", "FOODON:old")

    assert row["mapping_status"] == "MAPPED"
    assert row["mim_id"] == row["chebi_id"] == "CHEBI:2"
    assert row["culturemech_term_id"] == ""
    assert row["cas_rn"] == "123-45-6"


def test_label_owner_survives_lossy_name_and_identifier_indexes(tmp_path):
    # The first record claims the second one's name and identifier; only its
    # own source record can supply the correct CAS and KG node for Tryptone.
    _write_record(tmp_path, "A_Casamino.yaml", "MICRO:0000182", "Casamino acids",
                  synonyms=["Tryptone"], chemical_properties={"cas_rn": "65072-00-6"},
                  kg_microbe_node_id="CHEBI:78020")
    _write_record(tmp_path, "B_Tryptone.yaml", "MICRO:0000182", "Tryptone",
                  chemical_properties={"cas_rn": "91079-40-2"},
                  kg_microbe_node_id="MICRO:0000182")
    _write_labels(tmp_path, [[
        "Tryptone", "preferred_term", "MICRO:0000182", "Tryptone", "",
        "MAPPED", "unique",
    ]])

    row = _build(tmp_path, "Tryptone", "")

    assert row["mim_id"] == row["kg_microbe_node_id"] == "MICRO:0000182"
    assert row["cas_rn"] == "91079-40-2"
