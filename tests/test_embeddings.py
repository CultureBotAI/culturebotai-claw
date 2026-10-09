"""Set isolation, provenance failures, transactional output and a real PaCMAP canary."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import yaml

from kg_microbe_embeddings import project
from kg_microbe_embeddings.__main__ import main
from kg_microbe_embeddings.registry import EmbeddingError, canonical, digest, load_registry
from kg_microbe_embeddings.rollout import load_rollout
from kg_microbe_fleet import load_fleet_manifest


def fixture_set(root: Path, name="record-text", *, modality="text", rows=32, dims=8):
    folder = root / name
    folder.mkdir()
    ids = [f"entity:{i}" for i in range(rows)]
    (folder / "ids.json").write_text(json.dumps(ids))
    np.save(folder / "vectors.npy", np.random.default_rng(dims).normal(size=(rows, dims)))
    return {
        "id": name,
        "label": name,
        "modality": modality,
        "entity_type": "protein" if modality == "protein_language_model" else "record",
        "status": "ready",
        "encoder": {
            "name": "fixture/encoder",
            "revision": "a" * 40,
            "dimension": dims,
            "input_recipe": "fixture vectors; no scientific claim",
            "parameters": {"pooling": "fixture", "normalized": False},
            "library_versions": {"numpy": np.__version__},
        },
        "source": {"revision": "b" * 40, "input_sha256": "c" * 64},
        "ids": {"path": f"{name}/ids.json", "sha256": digest(folder / "ids.json")},
        "vectors": {"path": f"{name}/vectors.npy", "sha256": digest(folder / "vectors.npy")},
        "coverage": {"total": rows + 9, "eligible": rows + 3},
        "projection": {
            "method": "pacmap",
            "neighbors": 15,
            "MN_ratio": 0.5,
            "FP_ratio": 2.0,
            "seed": 42,
            "init": "pca",
            "apply_pca": True,
            "preprocessing": "l2",
            "max_points": 0,
        },
    }


def registry(root: Path, sets: list[dict]) -> Path:
    path = root / "registry.json"
    path.write_bytes(
        canonical(
            {
                "format_version": 1,
                "repository": "CultureBotAI/proteintraitsmech",
                "default_set": sets[0]["id"],
                "sets": sets,
            }
        )
    )
    return path


@pytest.fixture
def fake_pacmap(monkeypatch):
    calls = []

    class Reducer:
        def __init__(self, **kwargs):
            self.settings = kwargs
            self.n_neighbors, self.n_MN, self.n_FP = 3, 2, 6

        def fit_transform(self, vectors, *, init):
            calls.append((vectors.copy(), self.settings, init))
            return vectors[:, :2]

    monkeypatch.setitem(sys.modules, "pacmap", SimpleNamespace(PaCMAP=Reducer))
    monkeypatch.setattr(project.importlib.metadata, "version", lambda name: "fixture-version")
    return calls


def test_two_sets_keep_dimensions_entities_coverage_and_provenance(tmp_path, fake_pacmap):
    text = fixture_set(tmp_path, rows=32, dims=7)
    proteins = fixture_set(
        tmp_path, "protein-sequence", modality="protein_language_model", rows=48, dims=13
    )
    proteins["projection"].update(
        {"preprocessing": "center_l2", "apply_pca": False, "neighbors": 10}
    )
    planned = {
        "id": "future-text",
        "label": "Next model",
        "modality": "text",
        "representation": "whole_record",
        "entity_type": "record",
        "status": "planned",
        "reason": "No vectors for this model yet",
    }
    path = registry(tmp_path, [text, proteins, planned])
    result = project.build(path, tmp_path / "release")
    assert result["default_set"] == "record-text"
    assert result["sets"][2] == planned
    assert [call[0].shape for call in fake_pacmap] == [(32, 7), (48, 13)]
    for matrix, settings, init in fake_pacmap:
        np.testing.assert_allclose(np.linalg.norm(matrix, axis=1), 1, atol=1e-6)
        assert init == "pca" and settings["random_state"] == 42
    assert fake_pacmap[1][1]["apply_pca"] is False
    raw_proteins = np.load(tmp_path / proteins["vectors"]["path"]).astype(np.float32)
    centered = raw_proteins - raw_proteins.mean(axis=0, keepdims=True, dtype=np.float64).astype(
        np.float32
    )
    centered /= np.linalg.norm(centered.astype(np.float64), axis=1, keepdims=True)
    np.testing.assert_allclose(fake_pacmap[1][0], centered, atol=1e-6)
    for entry, spec in zip(result["sets"][:2], [text, proteins], strict=True):
        artifact = tmp_path / "release" / entry["path"]
        assert digest(artifact) == entry["sha256"]
        data = json.loads(artifact.read_text())
        assert data["set_id"] == spec["id"] and data["entity_type"] == spec["entity_type"]
        assert "representation" not in entry and "representation" not in data
        assert data["encoder"] == spec["encoder"] and data["source"] == spec["source"]
        assert data["coverage"]["total"] != data["coverage"]["shown"]
        assert data["coverage"]["shown"] == data["coverage"]["embedded"]
        # Requested count and the actual reducer-adjusted counts differ.
        assert data["projection"]["neighbors"] != data["projection"]["effective_neighbors"]
        assert data["projection"]["effective_neighbors"] == 3
        assert data["projection"]["effective_mid_near_pairs"] == 2
        assert data["projection"]["effective_further_pairs"] == 6


def test_text_variants_chemistry_and_future_modality_build_without_proteins(tmp_path, fake_pacmap):
    whole = fixture_set(tmp_path, "whole-record-text")
    definition = fixture_set(tmp_path, "definition-text")
    chemical = fixture_set(tmp_path, "chemical-structure", modality="chemical", rows=24, dims=16)
    future = fixture_set(tmp_path, "abundance-profile", modality="metabolomic", rows=14, dims=5)
    specs = [whole, definition, chemical, future]
    for spec, representation in zip(
        specs,
        ["whole_record", "definition", "molecular_fingerprint", "abundance_profile"],
        strict=True,
    ):
        spec["representation"] = representation
        spec["encoder"]["input_recipe"] = f"fixture/{representation}/v1"
    chemical["entity_type"] = "compound"
    future["entity_type"] = "sample"
    # Same text model, entity IDs and dimensions, but different selected input
    # fields and vectors. Grouping either by model or modality would lose a view.
    definition_path = tmp_path / definition["vectors"]["path"]
    np.save(definition_path, np.random.default_rng(55).normal(size=(32, 8)))
    definition["vectors"]["sha256"] = digest(definition_path)
    definition["source"]["input_sha256"] = "d" * 64
    output = tmp_path / "release"
    result = project.build(registry(tmp_path, specs), output)
    assert len(fake_pacmap) == len(result["sets"]) == 4
    payloads = []
    for entry, spec in zip(result["sets"], specs, strict=True):
        data = json.loads((output / entry["path"]).read_text())
        payloads.append(data)
        assert entry["representation"] == data["representation"] == spec["representation"]
        assert entry["modality"] == data["modality"] == spec["modality"]
        assert data["encoder"] == spec["encoder"] and data["source"] == spec["source"]
        assert data["inputs"]["vectors"] == spec["vectors"]
        assert data["projection"]["method"] == "pacmap"
    assert payloads[0]["points"] != payloads[1]["points"]
    assert payloads[0]["encoder"]["name"] == payloads[1]["encoder"]["name"]


@pytest.mark.parametrize(
    "change",
    [
        lambda s: s.update(id="../escape"),
        lambda s: s.update(status="published"),
        lambda s: s.update(modality=[]),
        lambda s: s.update(modality=""),
        lambda s: s.update(modality="protein language model"),
        lambda s: s.update(representation=[]),
        lambda s: s.update(representation=""),
        lambda s: s["projection"].update(method="umap"),
        lambda s: s["projection"].update(seed=True),
        lambda s: s["projection"].update(seed=2**32),
        lambda s: s["projection"].update(FP_ratio=0),
        lambda s: s["projection"].update(max_points=3),
        lambda s: s["encoder"].update(revision="main"),
        lambda s: s["encoder"].pop("parameters"),
        lambda s: s["encoder"].update(library_versions={}),
        lambda s: s["source"].update(revision="latest"),
        lambda s: s["ids"].update(path="../ids.json"),
        lambda s: s["coverage"].update(eligible=100000),
    ],
)
def test_invalid_ready_registry_refused(tmp_path, change):
    spec = fixture_set(tmp_path)
    change(spec)
    with pytest.raises(EmbeddingError):
        load_registry(registry(tmp_path, [spec]))


def test_nonfinite_metadata_refused(tmp_path):
    spec = fixture_set(tmp_path)
    path = registry(tmp_path, [spec])
    doc = json.loads(path.read_text())
    doc["sets"][0]["encoder"]["parameters"]["value"] = float("nan")
    path.write_text(json.dumps(doc))
    with pytest.raises(EmbeddingError, match="finite JSON"):
        load_registry(path)


def test_duplicate_json_keys_and_set_ids_refused(tmp_path):
    spec = fixture_set(tmp_path)
    with pytest.raises(EmbeddingError, match="duplicate embedding set"):
        load_registry(registry(tmp_path, [spec, spec]))
    path = tmp_path / "registry.json"
    path.write_text('{"format_version":1,"format_version":1}')
    with pytest.raises(EmbeddingError, match="duplicate JSON key"):
        load_registry(path)


def test_vector_files_cannot_be_shared_between_sets(tmp_path):
    first = fixture_set(tmp_path)
    second = copy.deepcopy(first)
    second["id"] = "second"
    with pytest.raises(EmbeddingError, match="independent vector artifact"):
        load_registry(registry(tmp_path, [first, second]))


def test_input_symlink_escape_refused(tmp_path):
    spec = fixture_set(tmp_path)
    original = tmp_path / spec["vectors"]["path"]
    original.unlink()
    original.symlink_to("/dev/null")
    with pytest.raises(EmbeddingError, match="escapes"):
        load_registry(registry(tmp_path, [spec]))


def test_planned_sets_require_a_reason_and_cannot_publish(tmp_path):
    spec = {
        "id": "record-text",
        "label": "Text",
        "modality": "text",
        "representation": "definition",
        "entity_type": "record",
        "status": "planned",
        "reason": "Awaiting vectors",
    }
    path = registry(tmp_path, [spec])
    assert load_registry(path)["sets"] == [spec]
    with pytest.raises(EmbeddingError, match="no ready"):
        project.build(path, tmp_path / "release")
    spec.pop("reason")
    with pytest.raises(EmbeddingError, match="reason"):
        load_registry(registry(tmp_path, [spec]))


@pytest.mark.parametrize(
    "defect",
    ["hash", "duplicate_ids", "row_count", "dimension", "nan", "zero", "object", "coverage"],
)
def test_input_integrity_failures(tmp_path, defect):
    spec = fixture_set(tmp_path)
    if defect == "hash":
        spec["vectors"]["sha256"] = "0" * 64
    elif defect == "duplicate_ids":
        path = tmp_path / spec["ids"]["path"]
        path.write_text(json.dumps(["same"] * 32))
        spec["ids"]["sha256"] = digest(path)
    elif defect == "coverage":
        spec["coverage"] = {"total": 31, "eligible": 31}
    else:
        matrix = np.ones((31 if defect == "row_count" else 32, 4 if defect == "dimension" else 8))
        if defect == "nan":
            matrix[0, 0] = np.nan
        if defect == "zero":
            matrix[0] = 0
        if defect == "object":
            matrix = matrix.astype(object)
        path = tmp_path / spec["vectors"]["path"]
        np.save(path, matrix)
        spec["vectors"]["sha256"] = digest(path)
    with pytest.raises(EmbeddingError):
        project.check_inputs(registry(tmp_path, [spec]))


def test_sampling_is_repeatable_and_coverage_is_explicit(tmp_path, fake_pacmap):
    spec = fixture_set(tmp_path, rows=60)
    spec["projection"]["max_points"] = 20
    first = project.project_set(spec, tmp_path)
    second = project.project_set(spec, tmp_path)
    assert first == second
    assert first["coverage"] == {
        "total": 69,
        "eligible": 63,
        "embedded": 60,
        "shown": 20,
        "sampling": "uniform_without_replacement",
    }
    assert len(first["points"]) == 20 and len({p[0] for p in first["points"]}) == 20


@pytest.mark.parametrize("rows", [3, 9])
def test_small_cohorts_fail_without_claiming_pacmap(tmp_path, rows, fake_pacmap):
    spec = fixture_set(tmp_path, rows=rows)
    with pytest.raises(EmbeddingError, match="at least 10"):
        project.build(registry(tmp_path, [spec]), tmp_path / "release")
    assert not fake_pacmap and not (tmp_path / "release").exists()


def test_direct_project_api_rejects_false_method_and_impossible_pairs(tmp_path, fake_pacmap):
    spec = fixture_set(tmp_path)
    spec["projection"]["method"] = "pca"
    with pytest.raises(EmbeddingError, match="primary projection"):
        project.project_set(spec, tmp_path)
    spec["projection"].update(method="pacmap", FP_ratio=0.001)
    with pytest.raises(EmbeddingError, match="pair settings"):
        project.project_set(spec, tmp_path)
    assert not fake_pacmap


def test_mid_build_input_change_is_not_published(tmp_path, monkeypatch, fake_pacmap):
    spec = fixture_set(tmp_path)
    real_project = project.project_set

    def project_then_corrupt(item, root):
        result = real_project(item, root)
        (root / item["ids"]["path"]).write_text("[]")
        return result

    monkeypatch.setattr(project, "project_set", project_then_corrupt)
    with pytest.raises(EmbeddingError, match="changed ids"):
        project.build(registry(tmp_path, [spec]), tmp_path / "release")
    assert not (tmp_path / "release").exists()
    assert not list(tmp_path.glob(".embedding-build-*"))


def test_later_set_failure_preserves_previous_release(tmp_path, monkeypatch, fake_pacmap):
    first = fixture_set(tmp_path)
    second = fixture_set(tmp_path, "second", rows=3)
    existing = tmp_path / "old-release"
    existing.mkdir()
    (existing / "index.json").write_text("old")
    with pytest.raises(EmbeddingError, match="already exists"):
        project.build(registry(tmp_path, [first]), existing)
    with pytest.raises(EmbeddingError, match="at least 10"):
        project.build(registry(tmp_path, [first, second]), tmp_path / "new-release")
    assert (existing / "index.json").read_text() == "old"
    assert not (tmp_path / "new-release").exists()
    assert not list(tmp_path.glob(".embedding-build-*"))


def test_fleet_rollout_covers_canonical_members_and_retains_pending_work():
    doc = load_rollout()
    assert set(doc["mechs"]) == set(load_fleet_manifest().keys)
    assert doc["mechs"]["proteintraitsmech"]["sets"]["protein-sequence"]["state"] == "native"
    assert doc["mechs"]["dufmech"]["sets"]["protein-sequence"]["state"] == "conditional"
    assert "protein-sequence" not in doc["mechs"]["cmmmech"]["sets"]
    assert "protein-sequence" not in doc["mechs"]["habitatmech"]["sets"]
    for key in ("antibioticmech", "naturalproductmech"):
        chemical = doc["mechs"][key]["sets"]["chemical-fingerprint"]
        assert chemical["state"] == "native" and chemical["modality"] == "chemical"
        assert chemical["representation"] == "molecular_fingerprint"
    text_sets = doc["mechs"]["proteintraitsmech"]["sets"]
    assert text_sets["record-text"]["representation"] == "whole_record"
    assert text_sets["definition-text"]["representation"] == "definition"
    assert doc["policy"]["registry_adoption"] == "planned"


def test_rollout_accepts_domain_specific_sets_and_future_modalities(tmp_path):
    doc = load_rollout()
    # A corpus may choose only chemical structure, or a new domain. Neither a
    # text set nor a placeholder protein set is required by the infrastructure.
    for key, modality in [("cmmmech", "chemical"), ("habitatmech", "metabolomic")]:
        doc["mechs"][key]["sets"] = {
            "domain-view": {
                "modality": modality,
                "representation": "domain_features",
                "entity_type": "record",
                "state": "planned",
                "notes": "Test applicability",
            }
        }
    path = tmp_path / "rollout.yaml"
    path.write_text(yaml.safe_dump(doc))
    assert load_rollout(path) == doc


@pytest.mark.parametrize(
    "defect",
    [
        "missing_mech",
        "extra_mech",
        "method",
        "multiple",
        "empty_sets",
        "revision",
        "modality",
        "representation",
    ],
)
def test_rollout_cannot_silently_drop_a_mech_or_multi_set_requirement(tmp_path, defect):
    doc = load_rollout()
    if defect == "missing_mech":
        doc["mechs"].pop("cmmmech")
    if defect == "extra_mech":
        doc["mechs"]["phantommech"] = doc["mechs"]["cmmmech"]
    if defect == "method":
        doc["policy"]["primary_projection"] = "umap"
    if defect == "multiple":
        doc["policy"]["multiple_sets"] = False
    if defect == "empty_sets":
        doc["mechs"]["cmmmech"]["sets"].clear()
    if defect == "revision":
        doc["mechs"]["cmmmech"]["revision"] = "main"
    if defect in {"modality", "representation"}:
        doc["mechs"]["cmmmech"]["sets"]["record-text"][defect] = []
    path = tmp_path / "rollout.yaml"
    path.write_text(yaml.safe_dump(doc))
    with pytest.raises(EmbeddingError):
        load_rollout(path)


def test_cli_is_nonzero_for_failure_and_does_not_import_pacmap_on_check(
    tmp_path, monkeypatch, capsys
):
    spec = fixture_set(tmp_path)
    path = registry(tmp_path, [spec])
    monkeypatch.setitem(sys.modules, "pacmap", None)
    assert main(["check", str(path), "--artifacts"]) == 0
    assert main(["build", str(path), "--output", str(tmp_path / "release")]) == 1
    assert "embeddings extra" in capsys.readouterr().err
    assert not (tmp_path / "release").exists()
    assert main(["rollout"]) == 0


def test_real_pacmap_two_set_canary(tmp_path):
    pytest.importorskip("pacmap")
    text = fixture_set(tmp_path, rows=40, dims=7)
    proteins = fixture_set(
        tmp_path, "protein-sequence", modality="protein_language_model", rows=48, dims=11
    )
    proteins["projection"].update(preprocessing="center_l2", apply_pca=False)
    output = tmp_path / "release"
    result = project.build(registry(tmp_path, [text, proteins]), output)
    for entry in result["sets"]:
        data = json.loads((output / entry["path"]).read_text())
        assert len(data["points"]) == data["coverage"]["embedded"]
        assert np.isfinite([p[1:] for p in data["points"]]).all()
        assert data["projection"]["library_versions"]["pacmap"] == "0.9.1"
        assert data["projection"]["effective_further_pairs"] > 0
