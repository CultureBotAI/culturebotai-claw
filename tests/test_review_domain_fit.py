"""Synthetic shape tests derived from the pinned fleet inventory, not real reviews."""

import pytest
from test_record_review import action, finding
from test_record_review import review as review  # noqa: F401

from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_governance.artifacts.scripts.record_review import (
    ReviewError,
    render_markdown,
    validate_review,
)

# Domains are test cases, never a runtime fleet-membership registry.
CASES = {
    "aimech": ("provenance", "ontology-release", "Synthetic pinned AIO release", "concept", "Imported ontology assertion, not experimental evidence"),
    "culturemech": ("quantity", "medium-variant", "Synthetic variant", "g/L", "Ingredient concentration"),
    "mediaingredientmech": ("identity", "hydration-state", "Synthetic salt hydrate", "percent", "Local mapping score"),
    "communitymech": ("graph", "interaction-context", "Synthetic community", "edge", "Inspected causal edges"),
    "traitmech": ("grounding", "trait-context", "Synthetic condition", "percent", "Claim support within this sample"),
    "proteintraitsmech": ("provenance", "source-category", "Synthetic measurement source", "degree Celsius", "Measurement temperature"),
    "antibioticmech": ("quantity", "susceptibility-method", "Synthetic broth assay", "ug/mL", "Exact compound/strain MIC"),
    "cellstructuremech": ("evidence", "localization-method", "Synthetic microscopy assay", "claim", "Inspected localization claims"),
    "habitatmech": ("ownership", "grounding-decision", "Synthetic maintained overlay", "claim", "Inspected grounding claims"),
    "naturalproductmech": ("identity", "structure-identity", "Synthetic stereochemical identity", "claim", "Inspected structure claims"),
    "taxonmech": ("nomenclature", "taxon-rank", "Synthetic subspecies", "reference", "Inspected authority records"),
    "pathwaymech": ("graph", "evidence-tier", "Synthetic computational tier", "edge", "Inspected pathway edges"),
    "dufmech": ("evidence", "functional-evidence-tier", "Synthetic prediction, not experiment", "family", "Inspected frozen families"),
    "cmmmech": ("scope", "criticality-authority-edition", "Synthetic authority / jurisdiction / edition", "percent", "Solubilized fraction, not recovered product"),
}


def test_domain_cases_cover_the_actual_manifest():
    assert set(CASES) == set(load_fleet_manifest().mechs)


@pytest.mark.parametrize("key", sorted(CASES))
def test_local_context_scores_and_rules_round_trip_without_flattening(review, key):
    area, dimension, value, unit, meaning = CASES[key]
    review["repository"] = load_fleet_manifest().mechs[key].github
    review["title"] = f"Synthetic {key} contract fit; no scientific assertion"
    assessment = review["assessments"][0]
    assessment.update(area=area, topic=meaning, outcome="concern",
                      dimensions=[{"name": dimension, "value": value,
                                   "definition": meaning, "evidence_ids": ["record"]}],
                      metrics=[{"name": meaning, "value": 2.0, "unit": unit,
                                "definition": "Synthetic test measurement; " + meaning,
                                "denominator": 5}],
                      details="Keep the original local scientific rationale and uncertainty here.")
    review["verdict"] = "needs_curation"
    review["findings"] = [finding()]
    review["findings"][0].update(category=area, rule_id="local-example-rule", native_severity="P2",
                                 normalization_reason="Synthetic material gap maps to major.",
                                 tags=[key, dimension])
    review["actions"] = [action()]
    for item in [*review["targets"], *review["findings"], *review["actions"]]:
        for owner in item["owner_paths"]:
            owner["repository"] = review["repository"]
    validate_review(review)
    markdown = render_markdown(review)
    assert dimension in markdown and value in markdown and meaning in markdown
    assessment["dimensions"][0]["evidence_ids"] = ["invented-evidence"]
    with pytest.raises(ReviewError, match="dangling"):
        validate_review(review)
