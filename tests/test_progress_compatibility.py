"""Pin the old-reader boundary and the required coordinated upgrade contract."""
from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path

import pytest
from jsonschema.validators import validator_for
from linkml.generators.jsonschemagen import JsonSchemaGenerator
from linkml_runtime.linkml_model.meta import SchemaDefinition
from test_progress_model import KEY, collect, runtime

import kg_microbe_progress as progress
from kg_microbe_workflows import load_document

ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / "tests/fixtures/progress_compatibility"


@lru_cache(maxsize=2)
def old_reader(class_name):
    """Use the frozen base schema, never the current schema with fields removed."""
    source = (FIXTURES / "pre_diagnostics_progress.yaml").read_bytes()
    provenance = json.loads((FIXTURES / "provenance.json").read_text())
    assert hashlib.sha256(source).hexdigest() == provenance["sha256"]
    schema = json.loads(JsonSchemaGenerator(
        SchemaDefinition(**load_document(source.decode())), top_class=class_name,
        not_closed=False, include_null=False,
    ).serialize())
    return validator_for(schema)(schema)


def test_updated_reader_accepts_existing_old_bundle(tmp_path):
    root, _ = runtime(tmp_path)
    history, snapshot = collect(root)

    old_reader("ProgressHistory").validate(history)
    old_reader("ProgressSnapshot").validate(snapshot)
    progress.validate_bundle(history, snapshot)


@pytest.mark.parametrize("count", [0, 2])
def test_old_reader_rejects_diagnostics_despite_matching_version(tmp_path, count):
    root, _ = runtime(tmp_path)
    history, snapshot = collect(
        root, excluded_association_counts={("run-one", KEY): count},
    )

    progress.validate_bundle(history, snapshot)
    assert history["schema_version"] == snapshot["schema_version"] == "1.0.0"
    for class_name, document in (
        ("ProgressHistory", history), ("ProgressSnapshot", snapshot),
    ):
        errors = list(old_reader(class_name).iter_errors(document))
        assert errors
        assert all(error.validator == "additionalProperties" for error in errors)
        assert all("excluded_pr_associations" in error.message for error in errors)


def test_guide_covers_all_readers_and_the_first_write_rollback_boundary():
    guide = (ROOT / "docs/guides/MECH_PROGRESS.md").read_text()
    compatibility = guide.split("### Compatibility and upgrade order\n", 1)[1]
    compatibility = " ".join(compatibility.split("\n### ", 1)[0].split())

    for consumer in (
        "Pages workflow", "publisher", "every checkout",
        "scripts/mech_progress_status.py", "--published", "mech-progress-status",
    ):
        assert consumer in compatibility
    assert 'schema_version: "1.0.0"' in compatibility
    assert "Before the updated publisher first writes" in compatibility
    assert "production state directory or publishes one" in compatibility
    assert "rollback to the old publisher is impossible" in compatibility
    assert "do not strip diagnostic fields, reset history" in compatibility
    assert "replace newer observations with an old bundle" in compatibility

    installation = guide.split("### Installing a reviewed publisher release\n", 1)[1]
    assert installation.index('mkdir -p "$STATE/releases"') < installation.index('mkdir "$RELEASE"')
