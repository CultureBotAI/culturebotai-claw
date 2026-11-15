"""Generated-schema controls for CommunityMech #1996 supplement routing."""

import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema.validators import validator_for
from linkml.generators.jsonschemagen import JsonSchemaGenerator

SCHEMA = (
    Path(__file__).resolve().parents[1]
    / "src/kg_microbe_governance/artifacts/schema/mech_shared.yaml"
)
LOCATOR = {
    "kind": "supplement",
    "asset_id": "table-s1.docx",
    "version": "published",
    "table": 1,
    "row": 12,
    "cell": 2,
}


@pytest.fixture(scope="module")
def validator():
    schema = json.loads(
        JsonSchemaGenerator(str(SCHEMA), top_class="SupportingReference", not_closed=False).serialize()
    )
    validator_type = validator_for(schema)
    validator_type.check_schema(schema)
    return validator_type(schema)


def test_generated_schema_accepts_optional_locator_and_existing_citations(validator):
    for citation in (
        {"reference": "PMID:36472419"},
        {"reference": "PMID:36472419", "snippet": "OAE516"},
        {"reference": "PMID:36472419", "snippet": "OAE516", "source_locator": LOCATOR},
    ):
        validator.validate(citation)


@pytest.mark.parametrize("missing", LOCATOR)
def test_generated_schema_requires_complete_locator(validator, missing):
    locator = deepcopy(LOCATOR)
    del locator[missing]
    assert list(validator.iter_errors({"reference": "PMID:36472419", "source_locator": locator}))


@pytest.mark.parametrize(
    "field,value",
    [
        ("kind", "article"),
        ("asset_id", ""),
        ("version", " \t"),
        ("table", 0),
        ("row", -1),
        ("cell", True),
        ("table", "1"),
        ("row", 1.5),
        ("cell", None),
        ("unknown_field", "ignored"),
    ],
)
def test_generated_schema_rejects_invalid_locator_without_coercion(validator, field, value):
    locator = {**LOCATOR, field: value}
    assert list(validator.iter_errors({"reference": "PMID:36472419", "source_locator": locator}))
