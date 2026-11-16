"""The retained Scaleup proposal describes its inspected scaffold, not deployment."""
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REVIEW = ROOT / "docs/reviews/2026-11-15-scaleup-admission"


def test_scaleup_candidate_is_review_only_and_bound_to_a_nonempty_tree():
    evidence = json.loads((REVIEW / "evidence.json").read_text())
    candidate = yaml.safe_load((REVIEW / "candidate.yaml").read_text())
    assert candidate["authority"] == evidence["authority"] == "review_only"
    assert candidate["evidence_revision"] == evidence["revision"]
    assert evidence["private"] is False
    assert evidence["git_tree"]["sha"] != evidence["revision"]
    assert evidence["git_tree"]["truncated"] is False
    paths = {row["path"] for row in evidence["git_tree"]["entries"]}
    assert "src/scaleupmech/schema/scaleupmech.yaml" in paths
    assert "scripts/.vendored_canon_ref" in paths
    assert all(row["present"] for row in evidence["required_artifacts"])
    assert candidate["admission_holds"]
    assert candidate["public_projection_tags"] == ["exclude-from-public"]


def test_scaleup_candidate_preserves_domain_reasons_and_withholds_execution():
    candidate = yaml.safe_load((REVIEW / "candidate.yaml").read_text())
    entry = candidate["manifest_entry"]
    assert not entry["serialization"]["verified"]
    assert "options" not in entry["serialization"]
    assert {name for name, cap in entry["capabilities"].items()
            if cap["status"] == "enabled"} == {"vendored_sync"}
    for name in ("edison_key_discovery", "environment_coverage",
                 "unmapped_inventory_input", "causal_graph_coverage", "metpo_proposal"):
        reason = entry["capabilities"][name]["reason"].lower()
        assert "assay" not in reason
        assert "scale" in reason
    assert "empty main" not in yaml.safe_dump(candidate)
