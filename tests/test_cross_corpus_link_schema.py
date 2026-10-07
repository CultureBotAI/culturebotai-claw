"""Exercise the shared link shape and a consumer's narrower relation contract."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import jsonschema
import pytest
import yaml

SCHEMA = (
    Path(__file__).resolve().parents[1]
    / "src/kg_microbe_governance/artifacts/schema/mech_shared.yaml"
)
LEGACY_LINK = {
    "corpus": "AntibioticMech",
    "identifier": "CHEBI:42355",
    "relation": "SAME_STRUCTURE",
    "basis": "SAME_INCHIKEY",
}


def _validator(path: Path, target: str) -> jsonschema.Draft201909Validator:
    # Coverage's dotted-source discovery can damage PyYAML's C loader in this
    # process (#233/#263). Generate with real LinkML in a fresh interpreter so
    # these schema assertions do not inherit that import-order defect.
    generated = subprocess.run(
        [
            sys.executable,
            "-c",
            "from linkml.generators.jsonschemagen import JsonSchemaGenerator\n"
            "import sys\n"
            "print(JsonSchemaGenerator(sys.argv[1], top_class=sys.argv[2], "
            "not_closed=False).serialize())\n",
            str(path),
            target,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return jsonschema.Draft201909Validator(json.loads(generated.stdout))


@pytest.fixture(scope="module")
def validator() -> jsonschema.Draft201909Validator:
    return _validator(SCHEMA, "CrossCorpusLink")


def test_existing_natural_product_links_remain_valid(validator) -> None:
    validator.validate(LEGACY_LINK)
    validator.validate({**LEGACY_LINK, "source_version": "0123456789ab"})


def test_pathway_relation_and_verbatim_target_are_consumer_owned(validator) -> None:
    validator.validate(
        {
            "corpus": "PathwayMech",
            "identifier": "gomodel:YeastPathways_GLYCOLYSIS",
            "relation": "PARTICIPATES_IN",
            "basis": "Reviewed evidence for this record's role in the named pathway.",
            "source_version": "a" * 40,
        }
    )


@pytest.mark.parametrize("field", ["corpus", "identifier", "relation", "basis"])
def test_required_fields_cannot_be_omitted(validator, field) -> None:
    link = {key: value for key, value in LEGACY_LINK.items() if key != field}
    assert not validator.is_valid(link)


@pytest.mark.parametrize("field", [*LEGACY_LINK, "source_version"])
def test_link_fields_remain_strings(validator, field) -> None:
    assert not validator.is_valid({**LEGACY_LINK, field: {"unexpected": "object"}})


def test_unknown_fields_are_rejected(validator) -> None:
    assert not validator.is_valid({**LEGACY_LINK, "confidence": 0.9})


def test_schema_generation_is_isolated_from_a_damaged_parent_loader(monkeypatch) -> None:
    """Model CI's null-tag loader even on platforms where libyaml is sound."""
    import importlib

    class NullTagLoader(yaml.SafeLoader):
        def resolve(self, kind, value, implicit):
            return None

    with pytest.raises(yaml.constructor.ConstructorError, match="tag None"):
        yaml.load("id: broken", Loader=NullTagLoader)
    loader = importlib.import_module("linkml_runtime.loaders.yaml_loader")
    monkeypatch.setattr(loader, "DupCheckYamlLoader", NullTagLoader)

    isolated = _validator(SCHEMA, "CrossCorpusLink")
    isolated.validate(LEGACY_LINK)
    assert not isolated.is_valid({key: value for key, value in LEGACY_LINK.items() if key != "basis"})


def test_consumer_subclass_retains_its_relation_enum(tmp_path) -> None:
    """A typo must fail locally even though the generic parent accepts strings."""
    schema = {
        "id": "https://example.org/link-consumer",
        "name": "link_consumer",
        "prefixes": {"linkml": "https://w3id.org/linkml/"},
        "imports": [str(SCHEMA.with_suffix(""))],
        "enums": {
            "LocalRelation": {"permissible_values": {"SAME_STRUCTURE": {}, "PARENT_OF": {}}}
        },
        "classes": {
            "LocalLink": {
                "is_a": "CrossCorpusLink",
                "slot_usage": {"relation": {"range": "LocalRelation"}},
            }
        },
    }
    path = tmp_path / "consumer.yaml"
    path.write_text(yaml.safe_dump(schema), encoding="utf-8")
    local_validator = _validator(path, "LocalLink")
    local_validator.validate(LEGACY_LINK)
    local_validator.validate({**LEGACY_LINK, "relation": "PARENT_OF"})
    assert not local_validator.is_valid({**LEGACY_LINK, "relation": "MISSPELLED"})
    assert not local_validator.is_valid({"relation": "SAME_STRUCTURE"})
