"""No script may hardcode a path that only exists on one machine.

#193. `generate_kgm_xref_patches.py` hardcoded an absolute workspace path, so
it only ran on one developer's laptop and, run from a git worktree, wrote its
output into a *different* checkout. Fifty-four scripts shared the shape.

`test_scripts_verify_mech_roots.py` could not see any of them: it finds scripts
by the honest `REPO_ROOT.parent` idiom and asks whether they verify. A script
with a literal absolute path never resolves a root at all, so the guard that
exists for exactly this class of bug structurally skips the worst offenders.

These two lists are burn-down ledgers, not exemptions (#198). A new script may
not join them, and a fixed one must be removed -- the tests below fail either
way, so the count can only go down.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

# Scripts that still embed a home-directory path. Shrink this; never grow it.
HARDCODED_PATHS = {
    "add_remaining_culturebotht.py",
    "analyze_mim_chebi_duplicates.py",
    "apply_culturemech_grounding_fixes.py",
    "apply_hydrate_siblings.py",
    "apply_medium_unmapped_candidates.py",
    "apply_mim_chebi_fixes.py",
    "apply_mim_merges.py",
    "apply_mim_wrong_fixes.py",
    "apply_p44_hydration_routing.py",
    "apply_p44_synonym_enrichment.py",
    "build_complex_ingredients_tsv.py",
    "build_mim_ingredient_sssom.py",
    "cas_chebi_lookup_pubchem.py",
    "categorize_residual_p25.py",
    "chebi_semantic_audit.py",
    "convert_to_mim_format.py",
    "curate_environments.py",
    "curate_envo_candidates.py",
    "curate_unmapped_kgm_antibiotics.py",
    "disambiguate_p44_hydration.py",
    "emit_low_curator_queue.py",
    "extract_complex_media_from_agar.py",
    "extract_complex_media_synonyms.py",
    "fix_deprecated_chebi.py",
    "fix_label_drift.py",
    "fix_wrong_chebi_mappings.py",
    "generate_kg_microbe_review.py",
    "generate_mapping_taxonomy_report.py",
    "generate_residual_p25_sssom.py",
    "import_ingredients.py",
    "integrate_culturebotht_ingredients.py",
    "merge_sssom_shard_reviews.py",
    "plan_mim_merges.py",
    "propose_chebi_for_unmapped.py",
    "propose_hydrate_siblings.py",
    "prune_residual_for_chebi_fixes.py",
    "publish_sssom.py",
    "recurate_deprecated_and_removed.py",
    "repair_damaged_ingredient_names.py",
    "report_mim_chebi_duplicates.py",
    "resolve_label_plausibility_defects.py",
    "resolve_mediadive_backlog.py",
    "resolve_residual_defects.py",
    "resolve_risky_cas_rn.py",
    "review_p44_synonym_enrichment.py",
    "review_sssom_synonyms.py",
    "round_trip_true_bugs.py",
    "route_chebi_collision_synonyms.py",
    "shard_sssom_for_review.py",
    "sweep_kg_microbe_rules.py",
    "triage_p25_findings.py",
    "verify_31.py",
}

# Scripts whose shebang names an interpreter by absolute path. Same ledger,
# different symptom: `#!/usr/bin/env /opt/homebrew/bin/python3.13` is a Mac
# with Homebrew and that exact Python.
ABSOLUTE_INTERPRETER = {
    "add_remaining_culturebotht.py",
    "analyze_mim_chebi_duplicates.py",
    "apply_culturemech_grounding_fixes.py",
    "apply_evidence_proposals.py",
    "apply_hydrate_siblings.py",
    "apply_medium_unmapped_candidates.py",
    "apply_mim_chebi_fixes.py",
    "apply_mim_merges.py",
    "apply_mim_wrong_fixes.py",
    "apply_p44_hydration_routing.py",
    "backfill_cas_chemistry.py",
    "backfill_chebi_chemistry.py",
    "backfill_parent_terms.py",
    "build_complex_ingredients_tsv.py",
    "cas_chebi_lookup_pubchem.py",
    "chebi_adjudicate.py",
    "chebi_semantic_audit.py",
    "classify_ingredient_type.py",
    "curate_unmapped_kgm_antibiotics.py",
    "detect_specificity_loss.py",
    "disambiguate_p44_hydration.py",
    "emit_low_curator_queue.py",
    "extract_complex_media_from_agar.py",
    "extract_complex_media_synonyms.py",
    "fetch_pubmed_abstracts.py",
    "fix_deprecated_chebi.py",
    "fix_label_drift.py",
    "foodon_pass.py",
    "generate_kg_microbe_review.py",
    "generate_mapping_taxonomy_report.py",
    "import_ingredients.py",
    "integrate_culturebotht_ingredients.py",
    "merge_resolve_unmapped.py",
    "merge_resolve_unmapped_v2.py",
    "mint_kgm_ingredient.py",
    "plan_mim_merges.py",
    "propose_chebi_for_unmapped.py",
    "propose_evidence.py",
    "propose_hydrate_siblings.py",
    "recurate_deprecated_and_removed.py",
    "repair_damaged_ingredient_names.py",
    "report_mim_chebi_duplicates.py",
    "resolve_label_plausibility_defects.py",
    "resolve_mediadive_backlog.py",
    "resolve_residual_defects.py",
    "resolve_risky_cas_rn.py",
    "resolve_unmapped.py",
    "resolve_unmapped_v2.py",
    "review_ingredient_classifications.py",
    "route_chebi_collision_synonyms.py",
    "sync_kgm_dependencies.py",
    "upgrade_placeholders.py",
    "validate_evidence_references.py",
    "verify_31.py",
}


def _scripts():
    return sorted(SCRIPTS.glob("*.py"))


def _has_home_path(path: Path) -> bool:
    source = path.read_text(encoding="utf-8")
    return "/Users/" in source or "/home/" in source


def test_there_are_scripts_to_check():
    """Guards the parametrization: an empty glob would pass everything."""
    assert len(_scripts()) >= 100, f"only {len(_scripts())} scripts found"


@pytest.mark.parametrize("path", _scripts(), ids=lambda p: p.name)
def test_no_new_script_hardcodes_a_home_directory_path(path):
    if path.name in HARDCODED_PATHS:
        pytest.skip("known offender; tracked in #198")
    assert not _has_home_path(path), (
        f"{path.name} embeds a home-directory path, so it runs on one machine "
        f"and writes wherever that literal points rather than into the "
        f"checkout it was invoked from. Derive paths from "
        f"Path(__file__).resolve().parent.parent and resolve Mech roots with "
        f"require_mech_roots"
    )


@pytest.mark.parametrize("path", _scripts(), ids=lambda p: p.name)
def test_no_new_script_pins_an_absolute_interpreter(path):
    if path.name in ABSOLUTE_INTERPRETER:
        pytest.skip("known offender; tracked in #198")
    first = path.read_text(encoding="utf-8").split("\n", 1)[0]
    assert not first.startswith("#!/usr/bin/env /"), (
        f"{path.name} pins {first[len('#!/usr/bin/env '):]}; use "
        f"#!/usr/bin/env python3 so the active environment decides"
    )


@pytest.mark.parametrize("name", sorted(HARDCODED_PATHS))
def test_a_fixed_script_leaves_the_path_ledger(name):
    """A cleaned-up script must be removed from the list, or the ledger stops
    describing anything and the burn-down cannot be read."""
    path = SCRIPTS / name
    assert path.is_file(), f"{name} is listed but does not exist; remove it"
    assert _has_home_path(path), (
        f"{name} no longer hardcodes a home path -- remove it from "
        f"HARDCODED_PATHS so the remaining count stays honest"
    )


@pytest.mark.parametrize("name", sorted(ABSOLUTE_INTERPRETER))
def test_a_fixed_script_leaves_the_interpreter_ledger(name):
    path = SCRIPTS / name
    assert path.is_file(), f"{name} is listed but does not exist; remove it"
    assert path.read_text(encoding="utf-8").startswith("#!/usr/bin/env /"), (
        f"{name} no longer pins an absolute interpreter -- remove it from "
        f"ABSOLUTE_INTERPRETER"
    )
