"""Stable identities use the genuine native registry; source science stays separate."""

import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

import pytest
import yaml
from test_mim_owned_name_export import builder, read_rows, sssom_artifacts
from test_mim_owned_name_export import cli as cli  # Explicit pytest fixture re-export.

NATIVE = Path(__file__).parent / "resources/stable_mim/native_stable_ids.py.txt"
CONTRACT = NATIVE.read_bytes()
CONTRACT_SHA = hashlib.sha256(CONTRACT).hexdigest()
MINT_HEADER = "mim_id\tlabel_at_minting\tminted_on\tstatus\treplaced_by\n"
LIFECYCLE = b"mim_id\tstatus\treplaced_by\tchanged_at\treason\n"


def mint(count):
    return (MINT_HEADER + "".join(
        f"MIM:{n:07d}\tOwner {n}\t2026-11-08\tactive\t\n" for n in range(1, count + 1)
    )).encode()


def snapshot(root, records, registry=None, lifecycle=LIFECYCLE):
    return builder._STABLE_PRODUCER.identity_snapshot(
        root, records, registry or mint(len(records)), lifecycle, CONTRACT,
        root / "src/mediaingredientmech/stable_ids.py", CONTRACT_SHA)


@pytest.fixture
def record():
    return {
        "mim_id": "MIM:0000001", "identifier": "kgmicrobe.ingredient:Mixed_Stock",
        "preferred_term": "Stock", "mapping_status": "MAPPED",
        "legacy_identifiers": ["MIM:Sodium_Nitrate_070_M_Stock"],
        "ontology_mapping": {"ontology_id": "CHEBI:9", "ontology_label": "parent",
                             "mapping_quality": "NARROW_MATCH"},
        "curation_history": [{"timestamp": "2026-11-08T00:00:00Z"}],
    }


def test_native_fixture_pin():
    origin = json.loads(NATIVE.with_name("ORIGIN.json").read_bytes())
    assert origin["sha256"] == CONTRACT_SHA


@pytest.mark.parametrize("mode", ["exact", "refusal", "different"])
def test_selected_native_api_child_isolation_and_result_binding(tmp_path, monkeypatch, mode):
    """Protocol double only; genuine MIM scientific validation is tested separately."""
    root, bundle, stage = tmp_path / "mim", tmp_path / "bundle", tmp_path / "stage"
    package = root / "src/mediaingredientmech/export"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text("")
    (package.parent / "__init__.py").write_text("")
    bundle.mkdir()
    stage.mkdir()
    review = root / "review.json"
    review.write_text("protocol fixture, not scientific evidence")
    producer = package / "source_bindings.py"
    code = ("import json\ndef validate_candidate(root, review, output):\n"
            "    assert review == root / 'review.json'\n"
            "    result = json.loads((output / 'manifest.json').read_bytes())\n")
    code += {"exact": "    return result\n",
             "refusal": "    raise ValueError('native protocol refusal')\n",
             "different": "    return {'different': True}\n"}[mode]
    producer.write_text(code)
    product = bundle / "source-decisions.json"
    product.write_text("[]")
    def digest(path):
        return hashlib.sha256(path.read_bytes()).hexdigest()
    manifest = {"inputs": {"review.json": digest(review)},
                "files": {product.name: digest(product)}, "counts": {"supported": 0}}
    (bundle / "manifest.json").write_text(json.dumps(manifest))
    poison = tmp_path / "ambient/mediaingredientmech"
    poison.mkdir(parents=True)
    (poison / "__init__.py").write_text("raise RuntimeError('ambient MIM must never import')")
    monkeypatch.setenv("PYTHONPATH", str(poison.parent))
    snapshot_bytes = {p: p.read_bytes() for p in
                      (review, producer, product, bundle / "manifest.json")}
    def run():
        return builder._STABLE_PRODUCER.validate_source_bindings(
            root, bundle, review, manifest, digest(producer), snapshot_bytes, stage)
    if mode == "exact":
        assert run()["native_validation"] == "passed"
    else:
        with pytest.raises(ValueError, match="Native source-binding validation failed|reconstruction differs"):
            run()
    assert all(path.read_bytes() == content for path, content in snapshot_bytes.items())


def test_genuine_empty_stable_candidate_uses_native_schema(tmp_path):
    path = tmp_path / "empty.tsv"
    prefix = "https://culturebotai.github.io/MediaIngredientMech/ingredient/MIM_"
    builder._write_sssom([], path, mim_prefix=prefix, empty_version="2026-01-01")
    builder._STABLE_PRODUCER.validate_empty_candidate(path, builder.COLUMNS, prefix)


@pytest.mark.parametrize("alter", [
    lambda raw: raw + "\n",
    lambda raw: raw + "\t" * 12 + "\n",
    lambda raw: raw + "MIM:0000001\tlabel\n",
    lambda raw: raw.replace("subject_id\tsubject_label", "subject_id\tsubject_id"),
    lambda raw: "\n".join(line for line in raw.splitlines() if not line.startswith("# license:")) + "\n",
    lambda raw: raw.replace("/ingredient/MIM_", "/wrong/MIM_"),
])
def test_empty_candidate_never_hides_blank_malformed_or_unbound_rows(tmp_path, alter):
    path = tmp_path / "empty.tsv"
    prefix = "https://culturebotai.github.io/MediaIngredientMech/ingredient/MIM_"
    builder._write_sssom([], path, mim_prefix=prefix, empty_version="2026-01-01")
    path.write_text(alter(path.read_text()))
    with pytest.raises(ValueError, match="physical header|explicit stable metadata"):
        builder._STABLE_PRODUCER.validate_empty_candidate(path, builder.COLUMNS, prefix)


@pytest.mark.parametrize("field,value", [
    ("mim_id", None), ("mim_id", "MIM:1"), ("mim_id", "MIM:0000000"),
    ("mim_id", "MIM:0000002"), ("mim_id", "mim:0000001"),
    ("mim_id", "MIM:００００００１"), ("legacy_identifiers", "not-a-list"),
])
def test_native_registry_rejects_missing_malformed_unregistered(tmp_path, record, field, value):
    record[field] = value
    with pytest.raises(ValueError):
        snapshot(tmp_path, {tmp_path / "data/ingredients/mapped/A.yaml": record})


def test_native_registry_rejects_duplicate_and_missing_current_owners(tmp_path, record):
    a = tmp_path / "data/ingredients/mapped/A.yaml"
    b = tmp_path / "data/ingredients/unmapped/B.yaml"
    with pytest.raises(ValueError, match="Duplicate"):
        snapshot(tmp_path, {a: record, b: deepcopy(record)})
    with pytest.raises(ValueError, match="exactly one"):
        snapshot(tmp_path, {a: record}, mint(2))


def test_native_registry_refuses_retired_current_owner(tmp_path, record):
    history = LIFECYCLE + b"MIM:0000001\tmerged\tMIM:0000002\t2026-11-09T00:00:00Z\treplaced\n"
    with pytest.raises(ValueError, match="retired"):
        snapshot(tmp_path, {tmp_path / "data/ingredients/mapped/A.yaml": record}, mint(2), history)


def test_contract_digest_cannot_be_replaced(tmp_path, record):
    with pytest.raises(ValueError, match="digest"):
        builder._STABLE_PRODUCER.identity_snapshot(
            tmp_path, {}, mint(1), LIFECYCLE, CONTRACT + b"\n", NATIVE, CONTRACT_SHA)


def test_stable_subject_survives_filename_label_directory_and_mapping_changes(tmp_path, record):
    for directory, filename, label, target in [
        ("mapped", "Original", "Stock", "CHEBI:9"),
        ("unmapped", "Renamed", "Corrected stock", "CHEBI:10"),
    ]:
        path = tmp_path / "data/ingredients" / directory / (filename + ".yaml")
        record["preferred_term"] = label
        record["ontology_mapping"]["ontology_id"] = target
        subjects, _, prefix = snapshot(tmp_path, {path: record})
        rows = builder._row_from_yaml(path, {}, {}, {}, {}, record=record,
                                     owners={label.casefold(): frozenset(subjects.values())},
                                     stable_subject=subjects[path])
        assert {row["subject_id"] for row in rows} == {"MIM:0000001"}
        assert rows[0]["object_id"] == target
        assert prefix.endswith("/ingredient/MIM_")


@pytest.mark.parametrize("quality,predicate", [
    ("EXACT_MATCH", "skos:exactMatch"), ("CLOSE_MATCH", "skos:closeMatch"),
    ("NARROW_MATCH", "skos:broadMatch"),
])
def test_external_predicates_remain_distinct(tmp_path, record, quality, predicate):
    record["ontology_mapping"]["mapping_quality"] = quality
    rows = builder._row_from_yaml(tmp_path / "Stock.yaml", {}, {}, {}, {}, record=record,
                                 owners={}, stable_subject=record["mim_id"])
    assert rows[0]["predicate_id"] == predicate
    assert rows[1]["object_id"] == record["identifier"]
    assert all("0000001" not in row["object_id"] for row in rows)


@pytest.mark.parametrize("status", ["UNMAPPED", "REJECTED", "AMBIGUOUS"])
def test_concept_is_not_falsely_mapped_or_a_canonical_self_loop(tmp_path, record, status):
    original = deepcopy(record)
    record["mapping_status"] = status
    expected = deepcopy(record)
    rows = builder._row_from_yaml(tmp_path / "Stock.yaml", {}, {}, {}, {}, record=record,
                                 owners={}, stable_subject=record["mim_id"])
    assert rows == []
    assert record == expected and original["mapping_status"] == "MAPPED"


def test_stable_direct_call_requires_complete_snapshot(tmp_path):
    with pytest.raises(ValueError, match="complete inventory"):
        builder._row_from_yaml(tmp_path / "missing.yaml", {}, {}, {}, {}, stable_subject="MIM:0000001")


def compatibility(tmp_path, record, rows):
    path = tmp_path / "data/ingredients/mapped/Renamed.yaml"
    records = {path: record}
    subjects, index, _ = snapshot(tmp_path, records)
    canonical = ("subject_id\tpredicate_id\tobject_id\n" + rows).encode()
    return builder._STABLE_PRODUCER.compatibility_registry_objects(records, subjects, index, canonical)


def test_literal_registry_aliases_survive_without_numeric_or_renamed_slug(tmp_path, record):
    aliases = compatibility(tmp_path, record,
        "MIM:Sodium_Nitrate_070_M_Stock\tskos:exactMatch\tkgmicrobe.ingredient:sodium_nitrate_070_m_stock\n")
    assert aliases == {"MIM:0000001": (
        "kgmicrobe.ingredient:Mixed_Stock", "kgmicrobe.ingredient:sodium_nitrate_070_m_stock")}
    rows = builder._row_from_yaml(tmp_path / "Renamed.yaml", {}, {}, {}, {}, record=record,
                                 owners={}, stable_subject=record["mim_id"],
                                 registry_objects=aliases[record["mim_id"]])
    assert {r["object_id"] for r in rows} == {"CHEBI:9", *aliases[record["mim_id"]]}
    assert not any("renamed" in r["object_id"] for r in rows)


@pytest.mark.parametrize("object_id", ["kgmicrobe.compound:other", "kgmicrobe.ingredient:0000001"])
def test_competing_namespace_and_numeric_registry_refused(tmp_path, record, object_id):
    with pytest.raises(ValueError, match="Competing|Numeric"):
        compatibility(tmp_path, record, f"MIM:0000001\tskos:exactMatch\t{object_id}\n")


def test_ambiguous_historical_mim_alias_never_chooses_an_owner(tmp_path, record):
    second = deepcopy(record)
    second["mim_id"] = "MIM:0000002"
    records = {tmp_path / "data/ingredients/mapped/A.yaml": record,
               tmp_path / "data/ingredients/mapped/B.yaml": second}
    subjects, index, _ = snapshot(tmp_path, records)
    with pytest.raises(ValueError, match="ambiguous"):
        builder._STABLE_PRODUCER.compatibility_registry_objects(
            records, subjects, index,
            b"subject_id\tpredicate_id\tobject_id\nMIM:Sodium_Nitrate_070_M_Stock\tskos:exactMatch\tkgmicrobe.ingredient:stock\n")


def test_unowned_historical_registry_row_is_not_silently_dropped(tmp_path, record):
    with pytest.raises(ValueError, match="no current stable owner"):
        compatibility(tmp_path, record,
                      "MIM:Unbound_Historical_Owner\tskos:exactMatch\tkgmicrobe.ingredient:literal_alias\n")


@pytest.fixture
def stable_cli(cli):
    root = cli["root"]
    (root / "data/ingredients/unmapped").mkdir()
    for n, path in enumerate(sorted(cli["records"].glob("*.yaml")), 1):
        record = yaml.safe_load(path.read_bytes())
        record.update(mim_id=f"MIM:{n:07d}", legacy_identifiers=["MIM:" + path.stem])
        path.write_text(yaml.safe_dump(record))
    ids = root / "data/ids"
    ids.mkdir()
    (ids / "mim_id_registry.tsv").write_bytes(mint(2))
    (ids / "mim_id_lifecycle.tsv").write_bytes(LIFECYCLE)
    source = root / "src/mediaingredientmech/stable_ids.py"
    source.parent.mkdir(parents=True)
    source.write_bytes(CONTRACT)
    def run(*flags):
        return cli["run"]("--identity-mode", "stable", "--mim-stable-id-contract-sha256", CONTRACT_SHA, *flags)
    return {**cli, "run": run, "contract": source}


def test_stable_cli_native_transaction_full_snapshot_and_no_stamp_transfer(stable_cli):
    output, sidecar, manifest = stable_cli["run"]()
    rows = read_rows(output.read_bytes())
    assert rows and all(r["subject_id"].startswith("MIM:000000") for r in rows)
    assert all(r["validation_method"] == "" for r in rows)
    assert b"/ingredient/MIM_" in output.read_bytes()
    assert b"MIM:000000" in sidecar.read_bytes()
    evidence = json.loads(manifest.read_bytes())
    assert evidence["identity_mode"] == "stable"
    assert len(evidence["owner_subjects"]) == 2
    assert evidence["source_binding_candidate"] is None
    assert evidence["validation_replay"].startswith("disabled")
    pins = {v["path"]: v["sha256"] for v in evidence["source_inputs"]}
    assert pins[str(stable_cli["contract"])] == CONTRACT_SHA
    assert pins[str(stable_cli["root"] / "data/ids/mim_id_registry.tsv")]
    assert stable_cli["canonical"].read_text().endswith("prior-reviewed-stamp\n")


def test_stable_changed_science_cannot_replay_a_matching_numeric_triple(stable_cli):
    canonical = stable_cli["canonical"]
    canonical.write_text(canonical.read_text().replace("MIM:Subject", "MIM:0000002"))
    owner = stable_cli["records"] / "Subject.yaml"
    record = yaml.safe_load(owner.read_bytes())
    record["synonyms"].append({"synonym_text": "new science", "synonym_type": "RAW_TEXT"})
    owner.write_text(yaml.safe_dump(record))
    output, _, _ = stable_cli["run"]()
    assert all(row["validation_method"] == "" for row in read_rows(output.read_bytes()))
    assert "prior-reviewed-stamp" in canonical.read_text()


@pytest.mark.parametrize("kind", ["mint", "lifecycle", "producer", "unmapped-added"])
def test_late_stable_inputs_refuse_with_old_artifacts_intact(stable_cli, monkeypatch, kind):
    paths = stable_cli["run"]()
    before = [p.read_bytes() for p in paths]
    native = sssom_artifacts.ValidatedWriteTransaction
    class Drift(native):
        def commit(self, **kwargs):
            root = stable_cli["root"]
            path = {"mint": root / "data/ids/mim_id_registry.tsv",
                    "lifecycle": root / "data/ids/mim_id_lifecycle.tsv",
                    "producer": stable_cli["contract"],
                    "unmapped-added": root / "data/ingredients/unmapped/New.yaml"}[kind]
            path.write_bytes((path.read_bytes() if path.exists() else b"") + b"# changed\n")
            return super().commit(**kwargs)
    monkeypatch.setattr(sssom_artifacts, "ValidatedWriteTransaction", Drift)
    with pytest.raises(builder._load_producer("kg_microbe_write.transaction").ValidationFailed,
                       match="changed during generation"):
        stable_cli["run"]()
    assert [p.read_bytes() for p in paths] == before


@pytest.mark.parametrize("flags", [[], ["--identity-mode", "stable"],
                                  ["--identity-mode", "legacy", "--mim-stable-id-contract-sha256", "a" * 64]])
def test_cli_requires_an_explicit_consistent_identity_mode(monkeypatch, flags):
    monkeypatch.setattr(sys, "argv", ["builder", *flags])
    with pytest.raises(SystemExit) as raised:
        builder.main()
    assert raised.value.code == 2


def source_manifest():
    return {"required_capabilities": ["reviewed-source-bindings-v1"],
            "semantic_status": "REVIEWED_CANDIDATE_ONLY", "production_authorized": False,
            "inputs": {"review.json": "a" * 64},
            "files": {"source-bindings.sssom.tsv": "b" * 64}}


@pytest.mark.parametrize("change", ["capability", "status", "approval", "path", "digest", "empty"])
def test_source_binding_transport_refuses_unclosed_inputs(tmp_path, change):
    manifest = source_manifest()
    if change == "capability":
        manifest["required_capabilities"] = ["unknown-source-binding-v2"]
    elif change == "status":
        manifest["semantic_status"] = "PUBLISHED"
    elif change == "approval":
        manifest["production_authorized"] = True
    elif change == "path":
        manifest["inputs"] = {"../outside.json": "a" * 64}
    elif change == "digest":
        manifest["files"] = {"data.tsv": "bad"}
    else:
        manifest["inputs"] = {}
    raw = json.dumps(manifest).encode()
    with pytest.raises(ValueError):
        builder._STABLE_PRODUCER.source_binding_inputs(
            tmp_path, tmp_path / "bundle", tmp_path / "review.json", raw,
            hashlib.sha256(raw).hexdigest())


def test_source_binding_manifest_pin_and_full_closure(tmp_path):
    raw = json.dumps(source_manifest()).encode()
    with pytest.raises(ValueError, match="digest"):
        builder._STABLE_PRODUCER.source_binding_inputs(
            tmp_path, tmp_path / "bundle", tmp_path / "review.json", raw, "f" * 64)
    paths, manifest = builder._STABLE_PRODUCER.source_binding_inputs(
        tmp_path, tmp_path / "bundle", tmp_path / "review.json", raw,
        hashlib.sha256(raw).hexdigest())
    assert paths == {tmp_path / "review.json", tmp_path / "bundle/manifest.json",
                     tmp_path / "bundle/source-bindings.sssom.tsv"}
    assert manifest == source_manifest()


def test_native_source_validation_requires_producer_and_captured_product_pins(tmp_path):
    native = builder._STABLE_PRODUCER
    root, bundle = tmp_path / "mim", tmp_path / "bundle"
    producer = root / "src/mediaingredientmech/export/source_bindings.py"
    snapshot = {producer: b"producer", root / "review.json": b"review",
                bundle / "source-bindings.sssom.tsv": b"changed"}
    manifest = source_manifest()
    with pytest.raises(ValueError, match="producer digest"):
        native.validate_source_bindings(root, bundle, root / "review.json", manifest,
                                        "0" * 64, snapshot, tmp_path)
    with pytest.raises(ValueError, match="captured input/product"):
        native.validate_source_bindings(root, bundle, root / "review.json", manifest,
                                        hashlib.sha256(b"producer").hexdigest(), snapshot, tmp_path)


def test_source_binding_partial_or_legacy_invocation_refused(monkeypatch):
    for mode in ("legacy", "stable"):
        flags = ["builder", "--identity-mode", mode, "--source-bindings-bundle", "/unused"]
        if mode == "stable":
            flags += ["--mim-stable-id-contract-sha256", CONTRACT_SHA]
        monkeypatch.setattr(sys, "argv", flags)
        with pytest.raises(SystemExit) as raised:
            builder.main()
        assert raised.value.code == 2


def test_unmapped_owner_names_participate_in_stable_suppression(stable_cli):
    path = stable_cli["records"] / "Owned.yaml"
    record = yaml.safe_load(path.read_bytes())
    record["mapping_status"] = "UNMAPPED"
    destination = stable_cli["root"] / "data/ingredients/unmapped/Other-name.yaml"
    destination.write_text(yaml.safe_dump(record))
    path.unlink()
    output, sidecar, manifest = stable_cli["run"]()
    assert "owned" not in read_rows(output.read_bytes())[0]["other"].casefold()
    assert b"MIM:0000001" in sidecar.read_bytes()
    report = json.loads(manifest.read_bytes())
    assert len(report["owner_subjects"]) == 2
    assert str(destination) in report["owner_subjects"]
    assert next(row for row in report["owner_candidate_accounting"]
                if row["path"] == str(destination))["external_candidate_rows"] == 0


def test_empty_stable_canonical_requires_actual_native_source_product(stable_cli):
    for path in stable_cli["records"].glob("*.yaml"):
        record = yaml.safe_load(path.read_bytes())
        record["mapping_status"] = "UNMAPPED"
        path.write_text(yaml.safe_dump(record))
    with pytest.raises(ValueError, match="genuine native source-binding"):
        stable_cli["run"]()
    assert not stable_cli["output"].exists()


def test_actual_git_head_change_without_owner_change_refuses(stable_cli, monkeypatch):
    paths = stable_cli["run"]()
    before = [p.read_bytes() for p in paths]
    native = sssom_artifacts.ValidatedWriteTransaction
    class Drift(native):
        def commit(self, **kwargs):
            root = str(stable_cli["root"])
            subprocess.run(["git", "init", "-q", root], check=True)
            subprocess.run(["git", "-C", root, "-c", "user.name=Fixture", "-c",
                            "user.email=fixture@example.invalid", "commit", "--allow-empty",
                            "-qm", "Private head-drift control"], check=True)
            return super().commit(**kwargs)
    monkeypatch.setattr(sssom_artifacts, "ValidatedWriteTransaction", Drift)
    with pytest.raises(builder._load_producer("kg_microbe_write.transaction").ValidationFailed,
                       match="revisions changed"):
        stable_cli["run"]()
    assert [p.read_bytes() for p in paths] == before
