"""Fail-closed contracts for the deep-research profile loader.

These tests exercise only local parsing and validation.  They never discover,
authenticate to, or invoke a research provider.
"""

from __future__ import annotations

import copy
import math
import textwrap
from typing import Any

import pytest

from kg_microbe_research import ProfileError, load_profile, parse_profile, rank_stage

VALID_YAML = textwrap.dedent(
    """\
    mech: TestMech
    target: test evidence
    evidence_policy: cite every material claim
    default_focus: primary
    focuses:
      primary:
        label: Primary
        objective: Find test evidence
        source_priorities:
          - peer-reviewed literature
        provider_adjustments:
          asta: 1
        stages:
          discovery:
            objective: Find evidence
            capabilities:
              academic_search: 1
            speed_weight: 1
    """
)


def valid_document() -> dict[str, Any]:
    """Return an independent, fully valid in-memory profile document."""

    return {
        "mech": "TestMech",
        "target": "test evidence",
        "evidence_policy": "cite every material claim",
        "default_focus": "primary",
        "focuses": {
            "primary": {
                "label": "Primary",
                "objective": "Find test evidence",
                "source_priorities": ["peer-reviewed literature"],
                "provider_adjustments": {"asta": 1},
                "stages": {
                    "discovery": {
                        "objective": "Find evidence",
                        "capabilities": {"academic_search": 1},
                        "speed_weight": 1,
                    }
                },
            }
        },
    }


@pytest.mark.parametrize(
    ("needle", "replacement"),
    [
        ("mech: TestMech\n", "mech: EarlierMech\nmech: TestMech\n"),
        (
            "    label: Primary\n",
            "    label: Earlier label\n    label: Primary\n",
        ),
        (
            "        objective: Find evidence\n",
            "        objective: Earlier objective\n        objective: Find evidence\n",
        ),
        (
            "      asta: 1\n",
            "      asta: 2\n      asta: 1\n",
        ),
        (
            "          academic_search: 1\n",
            "          academic_search: 2\n          academic_search: 1\n",
        ),
    ],
    ids=["top-level", "focus", "stage", "adjustment", "capability"],
)
def test_duplicate_yaml_mapping_keys_are_rejected_at_every_depth(
    tmp_path, needle: str, replacement: str
) -> None:
    assert VALID_YAML.count(needle) == 1
    path = tmp_path / "profile.yaml"
    path.write_text(VALID_YAML.replace(needle, replacement), encoding="utf-8")

    with pytest.raises(ProfileError, match="duplicate mapping key"):
        load_profile(path)


@pytest.mark.parametrize("scope", ["top", "focus", "stage"])
def test_unknown_schema_keys_are_rejected(scope: str) -> None:
    document = valid_document()
    if scope == "top":
        document["evidence_polciy"] = "typo"
    elif scope == "focus":
        document["focuses"]["primary"]["source_priority"] = []
    else:
        document["focuses"]["primary"]["stages"]["discovery"]["fast_weight"] = 1

    with pytest.raises(ProfileError, match="unknown key"):
        parse_profile(document)


def test_unknown_capability_is_rejected_with_the_known_vocabulary() -> None:
    document = valid_document()
    document["focuses"]["primary"]["stages"]["discovery"]["capabilities"] = {"telepathy": 1}

    with pytest.raises(ProfileError) as excinfo:
        parse_profile(document)
    assert "telepathy" in str(excinfo.value)
    assert "academic_search" in str(excinfo.value)


def test_unknown_provider_adjustment_is_rejected() -> None:
    document = valid_document()
    document["focuses"]["primary"]["provider_adjustments"] = {"imaginary_provider": 1}

    with pytest.raises(ProfileError, match="unknown provider"):
        parse_profile(document)


@pytest.mark.parametrize("field", ["mech", "target", "evidence_policy"])
@pytest.mark.parametrize("value", [None, "", "  "])
def test_core_profile_strings_are_required_and_non_empty(field: str, value: Any) -> None:
    document = valid_document()
    document[field] = value

    with pytest.raises(ProfileError, match=rf"{field} must be a non-empty string"):
        parse_profile(document)


@pytest.mark.parametrize("value", [None, "", "  ", 1, [], {}])
def test_default_focus_must_be_a_non_empty_string(value: Any) -> None:
    document = valid_document()
    document["default_focus"] = value

    with pytest.raises(ProfileError, match="default_focus must be a non-empty string"):
        parse_profile(document)


def test_default_focus_must_name_a_declared_focus() -> None:
    document = valid_document()
    document["default_focus"] = "missing"

    with pytest.raises(ProfileError, match="is not defined under focuses"):
        parse_profile(document)


def test_default_focus_must_not_be_normalized_into_a_declared_focus() -> None:
    document = valid_document()
    document["default_focus"] = " primary "

    with pytest.raises(ProfileError, match="must not have surrounding whitespace"):
        parse_profile(document)


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf, 10**400])
@pytest.mark.parametrize("location", ["capability", "stage", "adjustment"])
def test_non_finite_numeric_weights_are_rejected(location: str, value: Any) -> None:
    document = copy.deepcopy(valid_document())
    focus = document["focuses"]["primary"]
    stage = focus["stages"]["discovery"]
    if location == "capability":
        stage["capabilities"]["academic_search"] = value
    elif location == "stage":
        stage["speed_weight"] = value
    else:
        focus["provider_adjustments"]["asta"] = value

    with pytest.raises(ProfileError, match="must be a finite number"):
        parse_profile(document)


def test_finite_weights_that_overflow_during_scoring_fail_cleanly() -> None:
    document = valid_document()
    document["focuses"]["primary"]["stages"]["discovery"]["speed_weight"] = 1e308
    profile = parse_profile(document)

    with pytest.raises(ProfileError, match="produced a non-finite result"):
        rank_stage(profile.focus(), "discovery", environ={})


def test_large_finite_adjustment_does_not_overflow_fit_normalization() -> None:
    document = valid_document()
    document["focuses"]["primary"]["provider_adjustments"]["asta"] = 1e307
    profile = parse_profile(document)

    rows = rank_stage(profile.focus(), "discovery", environ={})

    assert rows[0].provider == "asta"
    assert rows[0].fit == 100
    assert all(0 <= row.fit <= 100 for row in rows)


@pytest.mark.parametrize(
    ("location", "value"),
    [("label", []), ("focus objective", {}), ("stage objective", 7)],
)
def test_declared_text_fields_are_not_silently_string_coerced(location: str, value: Any) -> None:
    document = valid_document()
    focus = document["focuses"]["primary"]
    if location == "label":
        focus["label"] = value
    elif location == "focus objective":
        focus["objective"] = value
    else:
        focus["stages"]["discovery"]["objective"] = value

    with pytest.raises(ProfileError, match="must be a string"):
        parse_profile(document)


def test_non_utf8_profile_fails_as_a_profile_error(tmp_path) -> None:
    path = tmp_path / "profile.yaml"
    path.write_bytes(b"\xff\xfe")

    with pytest.raises(ProfileError, match="Cannot read research profile"):
        load_profile(path)
