"""Offline contrasts for quote occurrence, source identity and gate failures."""
from __future__ import annotations

import json
import subprocess

import pytest

from kg_microbe_evidence import (
    EvidenceConfig,
    EvidenceError,
    EvidenceValidator,
    exit_code,
    iter_evidence,
    normalize,
    validate_corpus,
)
from kg_microbe_evidence.__main__ import main


@pytest.fixture
def source(tmp_path):
    cache = tmp_path / "references_cache"
    cache.mkdir()
    (cache / "PMID_1.md").write_text(
        "# PMID:1\n\n**Title:** Metadata must not validate a quotation.\n\n"
        "## Abstract\n\nA measured result showed increased growth.\n\n"
        "## Curator notes\nAn invented annotation is not source text.\n"
    )
    return tmp_path


def checker(root):
    return EvidenceValidator(root, EvidenceConfig("references_cache"))


def test_matching_quote_and_nonmatching_paraphrase(source):
    valid = checker(source).check_item({"pmid": "1", "snippet": "MEASURED  result\nshowed increased growth"})
    invalid = checker(source).check_item({"pmid": "1", "snippet": "Growth was increased in every species."})
    assert valid.verdict == "OK"
    assert valid.cache_sha256 and valid.quote_sha256 and valid.cache_path == "references_cache/PMID_1.md"
    assert invalid.verdict == "SNIPPET_NOT_IN_SOURCE"


@pytest.mark.parametrize("quote", ["Metadata must not validate a quotation.", "An invented annotation is not source text."])
def test_metadata_cannot_substitute_for_source_body(source, quote):
    assert checker(source).check_item({"reference": "PMID:1", "snippet": quote}).verdict == "SNIPPET_NOT_IN_SOURCE"


def test_cache_source_identity_not_just_filename(source):
    p = source / "references_cache/PMID_1.md"
    p.write_text(p.read_text().replace("# PMID:1", "# PMID:2"))
    assert checker(source).check_item({"pmid": "1", "snippet": "increased growth"}).verdict == "INVALID_CACHE"


@pytest.mark.parametrize("body", ["# PMID:1\nA measured result showed increased growth.",
    "# PMID:1\n## Abstract\n", "# PMID:1\n## Abstract\ngrowth\n## Abstract\ngrowth\n"])
def test_ambiguous_or_empty_cache_body_is_not_success(source, body):
    (source / "references_cache/PMID_1.md").write_text(body)
    assert checker(source).check_item({"pmid": "1", "snippet": "growth"}).verdict == "INVALID_CACHE"


@pytest.mark.parametrize(("item", "verdict"), [
    ({"pmid": "1"}, "NO_QUOTE"),
    ({"pmid": "1", "snippet": " \n "}, "NO_QUOTE"),
    ({"snippet": "increased growth"}, "MISSING_REFERENCE"),
    ({"pmid": "2", "snippet": "increased growth"}, "MISSING_CACHE"),
    ({"doi": "10.123/example", "snippet": "increased growth"}, "MISSING_CACHE"),
    ({"doi": "not a doi", "snippet": "increased growth"}, "UNSUPPORTED_REFERENCE"),
    ({"reference": "GITHUB:owner/project", "snippet": "increased growth"}, "UNSUPPORTED_REFERENCE"),
    ({"reference": "https://example.org/10.1/x", "snippet": "increased growth"}, "UNSUPPORTED_REFERENCE"),
    ({"pmid": "../../outside", "snippet": "increased growth"}, "INVALID_EVIDENCE"),
    ({"pmid": 1, "snippet": "increased growth"}, "INVALID_EVIDENCE"),
    ({"pmid": "1", "snippet": ["growth"]}, "INVALID_EVIDENCE"),
    ({"pmid": "1", "reference": "PMID:2", "snippet": "growth"}, "INVALID_EVIDENCE"),
    ({"pmid": "1", "snippet": "growth", "excerpt": "elsewhere"}, "INVALID_EVIDENCE"),
    ("PMID:1", "INVALID_EVIDENCE"),
])
def test_unverified_and_malformed_are_explicit(source, item, verdict):
    assert checker(source).check_item(item).verdict == verdict


def test_configured_native_aliases(source):
    config = EvidenceConfig.from_settings({"cache_dir": "references_cache", "reference_fields": ["source_ref"], "snippet_fields": ["quote"]})
    assert EvidenceValidator(source, config).check_item({"source_ref": "PMID:1", "quote": "increased growth"}).verdict == "OK"
    assert checker(source).check_item({"source_ref": "PMID:1", "quote": "increased growth"}).verdict == "NO_QUOTE"


@pytest.mark.parametrize("field", ["doi", "reference"])
def test_numeric_identifier_does_not_invent_a_pmid(source, field):
    result = checker(source).check_item({field: "1", "snippet": "increased growth"})
    assert result.verdict == "UNSUPPORTED_REFERENCE"
    assert "PMID" not in result.reference


@pytest.mark.parametrize("settings", [
    {}, {"cache_dir": "../elsewhere"}, {"cache_dir": "/tmp/cache"},
    {"cache_dir": "references_cache", "snippet_fields": "snippet"},
    {"cache_dir": "references_cache", "reference_fields": []},
    {"cache_dir": "references_cache", "snippet_fields": ["quote", "quote"]},
    {"cache_dir": "references_cache", "unknown": True},
    {"cache_dir": "references_cache", "evidence_paths": ["evidence[]"]},
    {"cache_dir": "references_cache", "evidence_paths": ["*.evidence"]},
    {"cache_dir": "references_cache", "evidence_paths": ["other.not_evidence"]},
])
def test_bad_config_fails_closed(settings):
    with pytest.raises(EvidenceError):
        EvidenceConfig.from_settings(settings)


def test_unicode_normalization_is_explicit():
    assert normalize("Ａ  measured\nRESULT") == "a measured result"


def test_symlink_cannot_select_an_external_source(source, tmp_path_factory):
    external = tmp_path_factory.mktemp("outside") / "source.md"
    external.write_text("# PMID:1\n## Abstract\nincreased growth\n")
    path = source / "references_cache/PMID_1.md"
    path.unlink()
    path.symlink_to(external)
    assert checker(source).check_item({"pmid": "1", "snippet": "increased growth"}).verdict == "INVALID_CACHE"


def test_walks_all_nested_evidence_without_promoting_explanations(source):
    records = source / "data"
    records.mkdir()
    (records / "item.yaml").write_text(
        "items:\n- evidence:\n  - pmid: '1'\n    snippet: increased growth\n"
        "- evidence:\n  - pmid: '1'\n    snippet: does not occur\n"
        "  - pmid: '1'\n    explanation: increased growth\n"
    )
    report = validate_corpus(source, ["data/*.yaml"], EvidenceConfig("references_cache"))
    assert report["evidence_items"] == 3
    assert report["quote_validated_items"] == 1
    assert report["verdicts"]["SNIPPET_NOT_IN_SOURCE"] == 1
    assert report["verdicts"]["NO_QUOTE"] == 1
    assert exit_code(report, strict=False) == 2


def test_declared_schema_slots_are_distinct_from_unmeasured_evidence(source):
    (source / "item.yaml").write_text(
        "ontology_mapping:\n  evidence:\n  - pmid: '1'\n    snippet: increased growth\n"
        "roles:\n- evidence:\n  - excerpt: database text\n    url: https://example.invalid\n"
        "culturemech_reference:\n  evidence: Explanation, not a quotation.\n"
    )
    config = EvidenceConfig("references_cache", evidence_paths=("ontology_mapping.evidence",))
    report = validate_corpus(source, ["*.yaml"], config)
    assert report["evidence_items"] == report["quote_validated_items"] == 1
    assert report["unmeasured_items"] == 2
    assert report["evidence_paths"] == ["ontology_mapping.evidence"]
    assert exit_code(report, strict=True) == 0
    assert EvidenceConfig("references_cache", evidence_paths=("roles[].evidence",)).selects("$.roles[3].evidence[2]")
    assert not config.selects("$.other.ontology_mapping.evidence[0]")


@pytest.mark.parametrize("document", [
    "ontology_mapping:\n- evidence:\n  - pmid: '1'\n    snippet: invented quotation\n",
    "role_assignments:\n  evidence:\n  - pmid: '1'\n    snippet: invented quotation\n",
    "role_assignments:\n- not an object\n",
])
def test_wrong_declared_container_shape_is_not_out_of_scope(source, document):
    (source / "item.yaml").write_text(document)
    config = EvidenceConfig("references_cache", evidence_paths=(
        "ontology_mapping.evidence", "role_assignments[].evidence",
    ))
    report = validate_corpus(source, ["*.yaml"], config)
    assert len(report["errors"]) == 1
    assert exit_code(report, strict=True) == 2


def test_declared_selectors_apply_to_each_record_in_a_collection(source):
    (source / "items.yaml").write_text(
        "- ontology_mapping:\n    evidence:\n    - pmid: '1'\n      snippet: invented quotation\n"
    )
    report = validate_corpus(source, ["*.yaml"], EvidenceConfig(
        "references_cache", evidence_paths=("ontology_mapping.evidence",),
    ))
    assert report["verdicts"]["SNIPPET_NOT_IN_SOURCE"] == 1
    assert report["unmeasured_items"] == 0
    assert exit_code(report, strict=True) == 2


@pytest.mark.parametrize("document", ["invalid: [", "evidence: []\nevidence: []\n", "", "just a string", "- just a string\n", "date: 2025-06-31\n", "a: &a\n  b: *a\n"])
def test_bad_record_cannot_disappear_from_gate(source, document):
    (source / "item.yaml").write_text(document)
    report = validate_corpus(source, ["*.yaml"], EvidenceConfig("references_cache"))
    assert len(report["errors"]) == 1
    assert exit_code(report, strict=False) == 2


def test_empty_corpus_does_not_pass(source):
    with pytest.raises(EvidenceError, match="no files"):
        validate_corpus(source, ["data/*.yaml"], EvidenceConfig("references_cache"))


def test_broken_selected_record_is_a_reported_error(source):
    (source / "good.yaml").write_text("evidence:\n- pmid: '1'\n  snippet: increased growth\n")
    (source / "broken.yaml").symlink_to(source / "missing.yaml")
    report = validate_corpus(source, ["*.yaml"], EvidenceConfig("references_cache"))
    assert report["records"] == 2
    assert len(report["errors"]) == 1
    assert report["errors"][0]["record"] == "broken.yaml"
    assert exit_code(report, strict=True) == 2


@pytest.mark.parametrize("nested", [
    "  evidence:\n  - pmid: '1'\n    snippet: invented quotation\n",
    "  recursive: *item\n",
])
def test_evidence_item_does_not_hide_nested_failures(source, nested):
    (source / "item.yaml").write_text(
        "evidence:\n- &item\n  pmid: '1'\n  snippet: increased growth\n" + nested
    )
    report = validate_corpus(source, ["*.yaml"], EvidenceConfig("references_cache"))
    assert exit_code(report, strict=True) == 2
    assert report["errors"] or report["verdicts"]["SNIPPET_NOT_IN_SOURCE"] == 1


def test_recursive_alias_is_rejected_but_shared_finite_values_are_counted():
    item = {"evidence": [{"pmid": "1", "snippet": "growth"}]}
    assert len(list(iter_evidence([item, item], ["evidence"]))) == 2
    item["recursive"] = item
    with pytest.raises(EvidenceError, match="recursive"):
        list(iter_evidence(item, ["evidence"]))


def test_strict_blocks_missing_cache_while_citation_only_is_not_a_quote(source):
    (source / "item.yaml").write_text("evidence:\n- pmid: '2'\n  snippet: growth\n- pmid: '1'\n")
    report = validate_corpus(source, ["*.yaml"], EvidenceConfig("references_cache"))
    assert exit_code(report, strict=False) == 0
    assert exit_code(report, strict=True) == 2
    assert report["quote_validated_items"] == 0


def init_repo(root, origin="CultureBotAI/MediaIngredientMech"):
    def git(*args):
        return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True)
    git("init", "-q")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    git("remote", "add", "origin", "https://github.com/" + origin + ".git")
    git("-c", "core.hooksPath=/dev/null", "commit", "--allow-empty", "-qm", "fixture")


def test_cli_binds_active_root_and_writes_only_its_reports(source, capsys):
    init_repo(source)
    path = source / "data/ingredients/mapped/item.yaml"
    path.parent.mkdir(parents=True)
    path.write_text("ontology_mapping:\n  evidence:\n  - pmid: '1'\n    snippet: increased growth\n")
    assert main(["--mech", "mediaingredientmech", "--root", str(source), "--strict"]) == 0
    report = json.loads((source / "workspace/reports/evidence_reference_validation.json").read_text())
    assert report["quote_validated_items"] == 1
    assert report["repository"] == "CultureBotAI/MediaIngredientMech"
    assert "claim" in report["limits"]
    assert "increased growth" not in (source / "workspace/reports/evidence_reference_validation.tsv").read_text()
    path.write_text("ontology_mapping:\n  evidence:\n  - pmid: '1'\n    snippet: invented quotation\n")
    assert main(["--mech", "mediaingredientmech", "--root", str(source), "--strict"]) == 2


def test_cli_wrong_repository_and_disabled_capability_fail(source):
    init_repo(source, "CultureBotAI/CommunityMech")
    assert main(["--mech", "mediaingredientmech", "--root", str(source), "--strict"]) == 2
    assert main(["--mech", "communitymech", "--root", str(source), "--strict"]) == 2
    assert not (source / "workspace").exists()
