"""The id-label config loader rejects keys it does not read.

A key the validator never reads is a check that never runs, and the failure is
silent: `exclude_key:` for `exclude_keys:` leaves a weaker gate behind a green
build. That is the same class of defect the validator exists to catch in the
data, so the config itself is now validated (#367).

The one exception is a deliberately unread block. A config that shares an
exception list across several targets has nowhere to put it but a top-level key,
anchored and aliased in; MediaIngredientMech does exactly that. Such a key
declares itself with an `x-` or `_` prefix.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = (
    ROOT
    / "src"
    / "kg_microbe_governance"
    / "artifacts"
    / "scripts"
    / "validate_id_label_correspondence.py"
)


def _validator():
    spec = importlib.util.spec_from_file_location("id_label_validator", VALIDATOR)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


MODULE = _validator()

MINIMAL = {
    "adapters": {"ENVO": "sqlite:obo:envo"},
    "targets": [
        {
            "name": "records",
            "kind": "yaml",
            "glob": "data/**/*.yaml",
            "pairs": [["identifier", "label"]],
        }
    ],
}


def _write(tmp_path: Path, document: dict) -> Path:
    path = tmp_path / "id_label_targets.yaml"
    path.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
    return path


def test_a_config_using_only_known_keys_loads(tmp_path: Path) -> None:
    cfg = MODULE.load_config(_write(tmp_path, MINIMAL))
    assert cfg["adapters"] == {"ENVO": "sqlite:obo:envo"}
    assert cfg["synonym_scope"] == "exact_related"


def test_every_documented_key_is_accepted(tmp_path: Path) -> None:
    """The allow-lists must not be narrower than what the validator reads."""
    document = {
        "adapters": {"ENVO": "sqlite:obo:envo"},
        "ignored_prefixes": ["minted"],
        "synonym_scope": "exact",
        "max_accession": {"ENVO": 99999999},
        "plausibility_severity": "warn",
        "targets": [
            {
                "name": "records",
                "kind": "yaml",
                "format": "tsv",
                "glob": ["data/**/*.yaml"],
                "required": True,
                "policy": "canonical_or_synonym",
                "synonym_scope": "all",
                "pairs": [["identifier", "label"]],
                "exclude_keys": ["evidence"],
                "label_waived_keys": ["note"],
                "label_waiver_mode": "id_only",
                "severity": "error",
                "exceptions": [{"id": "ENVO:1", "label": "x", "reason": "y"}],
            }
        ],
    }
    assert MODULE.load_config(_write(tmp_path, document))["targets"]


def test_an_unknown_top_level_key_is_refused(tmp_path: Path) -> None:
    document = dict(MINIMAL, exclude_key=["evidence"])
    with pytest.raises(SystemExit) as caught:
        MODULE.load_config(_write(tmp_path, document))
    assert "exclude_key" in str(caught.value)


def test_an_unknown_target_key_is_refused(tmp_path: Path) -> None:
    """The typo this exists for: singular `exclude_key` silently checked nothing."""
    document = {
        "adapters": MINIMAL["adapters"],
        "targets": [dict(MINIMAL["targets"][0], exclude_key=["evidence"])],
    }
    with pytest.raises(SystemExit) as caught:
        MODULE.load_config(_write(tmp_path, document))
    message = str(caught.value)
    assert "exclude_key" in message and "records" in message


@pytest.mark.parametrize("key", ["x-shared-exceptions", "_shared_exceptions"])
def test_a_declared_unread_block_is_allowed(tmp_path: Path, key: str) -> None:
    document = dict(MINIMAL)
    document[key] = [{"id": "ENVO:1", "label": "x"}]
    assert MODULE.load_config(_write(tmp_path, document))


def test_targets_must_be_a_list_of_mappings(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        MODULE.load_config(_write(tmp_path, {"targets": {"name": "records"}}))
    with pytest.raises(SystemExit):
        MODULE.load_config(_write(tmp_path, {"targets": ["records"]}))


def test_the_allow_lists_cover_what_the_validator_reads() -> None:
    """Pins the two sets, so widening the reader without widening the list fails."""
    assert MODULE.CONFIG_KEYS == {
        "adapters",
        "ignored_prefixes",
        "synonym_scope",
        "targets",
        "max_accession",
        "plausibility_severity",
    }
    assert MODULE.TARGET_KEYS == {
        "name",
        "kind",
        "format",
        "glob",
        "required",
        "policy",
        "synonym_scope",
        "pairs",
        "exclude_keys",
        "label_waived_keys",
        "label_waiver_mode",
        "severity",
        "exceptions",
    }
