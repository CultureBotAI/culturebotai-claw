"""The four-leg kgscan matrix is an explicit scope decision, not fleet drift."""

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "knowledge-gap-scan.yaml"
SCOPE_DOC = ROOT / "docs" / "KGSCAN_SCOPE.md"


def test_scheduled_scan_has_exactly_the_discussion_bearing_mechs():
    workflow = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    legs = workflow["jobs"]["scan"]["strategy"]["matrix"]["include"]
    assert {leg["mech"] for leg in legs} == {
        "CultureMech",
        "MediaIngredientMech",
        "CommunityMech",
        "TraitMech",
    }


def test_proteintraits_exclusion_is_documented_as_intentional():
    text = SCOPE_DOC.read_text(encoding="utf-8")
    assert "ProteinTraitsMech is intentionally excluded" in text
    assert "no `discussions` field" in text
    assert "more than 1,400 runs" in text
