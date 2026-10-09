"""The shared review contract preserves scientific variation and rejects false passes."""

import json
import subprocess
from copy import deepcopy
from pathlib import Path

import pytest
import yaml

from kg_microbe_governance.artifacts.scripts.record_review import (
    ReviewError,
    inspect_source,
    load_document,
    main,
    read_review,
    render_markdown,
    review_paths,
    save_review,
    validate_review,
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = ROOT / "src/kg_microbe_governance/artifacts/schema/record_review.yaml"


@pytest.fixture
def review():
    return {
        "schema_version": "1.0.0",
        "review_id": "20261008T010000Z-fixture",
        "kind": "record",
        "repository": "Example/FixtureMech",
        "title": "Offline fixture review",
        "started_at": "2026-10-08T00:59:00Z",
        "finished_at": "2026-10-08T01:00:00Z",
        "reviewer": {"identity": "test fixture", "kind": "deterministic",
                     "independence": "not_applicable",
                     "independence_basis": "This is a synthetic contract test, not scientific review."},
        "skill": "review-yaml-record",
        "completion": "completed",
        "verdict": "pass",
        "scientific_review": False,
        "summary": "The bounded fixture check passed; biology was not assessed.",
        "source": {"git_revision": "a" * 40, "state": "working_tree",
                   "inputs": [{"path": "data/item.yaml", "sha256": "a" * 64, "role": "target"}]},
        "scope": {"description": "Inspect one fixture's explicit identifier.",
                  "selection": "The explicitly named fixture file.", "coverage": "full",
                  "population_size": 1, "reviewed_target_ids": ["EX:item"]},
        "targets": [{"target_id": "EX:item", "path": "data/item.yaml", "label": "Fixture",
                     "kind": "maintained", "owner_paths": [owner()]}],
        "checks": [{"check_id": "identity", "name": "Inspect identifier", "required": True,
                    "status": "passed", "summary": "The explicit ID matches the target.",
                    "target_ids": ["EX:item"], "evidence_ids": ["record"]}],
        "evidence": [{"evidence_id": "record", "kind": "record_content", "reference": "data/item.yaml",
                      "accessed_at": "2026-10-08T00:59:30Z", "support": "supports",
                      "summary": "The fixture declares EX:item."}],
        "assessments": [{"assessment_id": "identity", "area": "identity", "topic": "Record identity",
                         "outcome": "supported", "summary": "The requested fixture was inspected.",
                         "target_ids": ["EX:item"], "evidence_ids": ["record"]}],
        "findings": [], "actions": [], "limitations": [],
    }


def owner():
    return {"repository": "Example/FixtureMech", "path": "data/item.yaml", "role": "maintained record"}


def finding():
    return {"finding_id": "f1", "issue_key": "fixture-evidence-gap", "category": "evidence",
            "severity": "major", "status": "open", "certainty": "confirmed",
            "title": "Missing supporting source", "description": "The scoped claim has no source.",
            "target_ids": ["EX:item"], "evidence_ids": ["record"], "owner_paths": [owner()]}


def action():
    return {"action_id": "a1", "description": "Inspect the original evidence.", "finding_ids": ["f1"],
            "target_ids": ["EX:item"], "owner_paths": [owner()],
            "acceptance_checks": ["A source supports the exact claim or the claim is withdrawn."]}


def test_closed_schema_accepts_explicit_empty_findings(review):
    validate_review(review, SCHEMA)
    review["unexpected"] = "must not be silently discarded"
    with pytest.raises(ReviewError, match="Additional properties"):
        validate_review(review, SCHEMA)


@pytest.mark.parametrize("raw", [
    "verdict: pass\nverdict: blocked\n",
    "nested: {verdict: pass, verdict: blocked}\n",
    "a: &shared [1]\nb: *shared\n",
    "value: !!str unchecked\n",
    "value: .nan\n",
    "value: .inf\n",
    "[not, a, mapping]",
])
def test_reader_refuses_lossy_or_nonfinite_documents(raw):
    with pytest.raises(ReviewError):
        load_document(raw)


def test_unquoted_timestamps_stay_strings():
    assert load_document("time: 2026-10-08T01:00:00Z")["time"] == "2026-10-08T01:00:00Z"


@pytest.mark.parametrize("mutation, message", [
    (lambda r: r.update(finished_at="2026-10-08T00:58:00Z"), "precedes"),
    (lambda r: r.update(finished_at="2026-02-30T01:00:00Z"), "invalid UTC"),
    (lambda r: r.update(review_id="undated"), "timestamp"),
    (lambda r: r["source"]["inputs"][0].update(path="../outside"), "unsafe"),
    (lambda r: r["targets"][0].update(path="not-hashed.yaml"), "hashed source"),
    (lambda r: r["targets"][0].update(kind="snapshot_row"), "selector"),
    (lambda r: r["scope"].update(population_size=2), "full coverage"),
    (lambda r: r["checks"][0].update(target_ids=["missing"]), "dangling"),
    (lambda r: r["checks"][0].update(evidence_ids=["missing"]), "dangling"),
    (lambda r: r["evidence"].append(deepcopy(r["evidence"][0])), "duplicates"),
    (lambda r: r["assessments"][0].update(evidence_ids=[]), "inspected evidence"),
    (lambda r: r["scope"].update(reviewed_target_ids=[]), "full coverage"),
    (lambda r: r["evidence"][0].update(accessed_at="2026-10-08T02:00:00Z"), "after"),
    (lambda r: r["evidence"][0].update(kind="search"), "search scope"),
    (lambda r: r["checks"][0].update(command="a recorded command"), "exit code"),
    (lambda r: r["checks"][0].update(exit_code=1), "failing exit"),
    (lambda r: r["checks"][0].update(status="skipped", exit_code=0), "unexecuted"),
    (lambda r: r["checks"][0].update(status="unavailable"), "completed review"),
    (lambda r: r.update(scientific_review=True), "not scientific"),
])
def test_semantic_failures_are_not_passes(review, mutation, message):
    mutation(review)
    with pytest.raises(ReviewError, match=message):
        validate_review(review, SCHEMA)


def test_findings_require_evidence_ownership_and_nonpassing_verdict(review):
    review["findings"] = [finding()]
    review["actions"] = [action()]
    with pytest.raises(ReviewError, match="passing verdict"):
        validate_review(review, SCHEMA)
    review["verdict"] = "needs_curation"
    validate_review(review, SCHEMA)
    review["findings"][0].pop("owner_paths")
    with pytest.raises(ReviewError, match="ownership"):
        validate_review(review, SCHEMA)
    review["findings"][0]["ownership_note"] = "Maintained owner could not be identified."
    validate_review(review, SCHEMA)


def test_resolution_requires_prior_identity_and_explanation(review):
    item = finding()
    item.update(status="resolved", disposition_reason="A later source check resolved the claim.")
    review["findings"] = [item]
    with pytest.raises(ReviewError, match="previous finding"):
        validate_review(review, SCHEMA)
    item["previous_occurrences"] = [{"repository": review["repository"],
                                    "review_id": "20261007T010000Z-earlier", "finding_id": "f1"}]
    validate_review(review, SCHEMA)
    item["previous_occurrences"][0]["review_id"] = review["review_id"]
    with pytest.raises(ReviewError, match="earlier review"):
        validate_review(review, SCHEMA)


@pytest.mark.parametrize("verdict", ["pass", "pass_with_limitations"])
def test_unknown_evidence_free_assessments_cannot_be_scientific_passes(review, verdict):
    review["reviewer"]["kind"] = "agent"
    review.update(scientific_review=True, verdict=verdict, limitations=["Evidence was unavailable."])
    review["evidence"] = []
    review["checks"][0].update(status="not_applicable", evidence_ids=[])
    review["assessments"][0].update(outcome="unknown", evidence_ids=[])
    with pytest.raises(ReviewError, match="positive evidence-linked"):
        validate_review(review)


def test_plain_pass_cannot_hide_an_unknown_assessment(review):
    review["assessments"].append({**deepcopy(review["assessments"][0]),
                                  "assessment_id": "unassessed", "outcome": "unknown"})
    with pytest.raises(ReviewError, match="unknown or concerning"):
        validate_review(review)
    review.update(verdict="pass_with_limitations", limitations=["The second scoped question is unknown."])
    validate_review(review)


@pytest.mark.parametrize("suffix", ["\n", "\r", "\t", "/escape", "\x00"])
def test_unsafe_ids_cannot_be_saved_or_poison_inventory(repository, review, suffix):
    review["review_id"] += suffix
    with pytest.raises(ReviewError):
        save_review(repository, review)
    assert review_paths(repository) == []


def test_action_dependency_cycles_and_dangling_references_are_rejected(review):
    review["verdict"] = "needs_curation"
    review["findings"] = [finding()]
    first, second = action(), action()
    second["action_id"] = "a2"
    first["depends_on"], second["depends_on"] = ["a2"], ["a1"]
    review["actions"] = [first, second]
    with pytest.raises(ReviewError, match="cycle"):
        validate_review(review, SCHEMA)
    second.pop("depends_on")
    validate_review(review, SCHEMA)
    first["depends_on"] = ["missing"]
    with pytest.raises(ReviewError, match="dangling"):
        validate_review(review, SCHEMA)


def test_sample_is_not_full_population_coverage(review):
    review["kind"] = "batch"
    review["scope"].update(coverage="sampled", population_size=500,
                           sampling_method="One fixed-seed record from the named stratum.",
                           sampling_seed="20261008")
    review["limitations"] = ["499 records were not read; no corpus-wide scientific claim is made."]
    validate_review(review, SCHEMA)
    review["scope"]["coverage"] = "full"
    with pytest.raises(ReviewError, match="full coverage"):
        validate_review(review, SCHEMA)


def test_local_rule_and_metric_semantics_survive_normalization(review):
    review["verdict"] = "needs_curation"
    review["findings"] = [finding()]
    review["actions"] = [action()]
    item = review["findings"][0]
    item.update(rule_id="P2.3", native_severity="P2")
    with pytest.raises(ReviewError, match="normalization"):
        validate_review(review, SCHEMA)
    item["normalization_reason"] = "The native high-priority warning is a material evidence gap."
    review["assessments"][0]["metrics"] = [{"name": "local coverage", "value": 40.0,
        "unit": "percent", "definition": "Inspected claims with attached support in this record.",
        "denominator": 5, "minimum": 0.0, "maximum": 100.0}]
    validate_review(review, SCHEMA)
    review["assessments"][0]["metrics"][0]["value"] = 101.0
    with pytest.raises(ReviewError, match="outside"):
        validate_review(review, SCHEMA)


def test_every_claimed_reviewed_member_requires_an_assessment(review):
    review["kind"] = "batch"
    review["scope"].update(population_size=2, reviewed_target_ids=["EX:item", "EX:other"])
    review["targets"].append({**deepcopy(review["targets"][0]), "target_id": "EX:other",
                              "path": "data/other.yaml"})
    review["source"]["inputs"].append({"path": "data/other.yaml", "sha256": "b" * 64,
                                       "role": "target"})
    with pytest.raises(ReviewError, match="scoped assessment"):
        validate_review(review, SCHEMA)
    review["assessments"][0]["target_ids"].append("EX:other")
    validate_review(review, SCHEMA)


@pytest.fixture
def repository(tmp_path, review):
    root = tmp_path / "repo"
    root.mkdir()
    for args in (("init",), ("config", "user.name", "Fixture"),
                 ("config", "user.email", "fixture@example.invalid"),
                 ("remote", "add", "origin", "https://github.com/Example/FixtureMech.git")):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    (root / "data").mkdir()
    (root / "data/item.yaml").write_text("id: EX:item\n")
    subprocess.run(["git", "-C", str(root), "add", "data/item.yaml"], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-m", "Fixture"], check=True, capture_output=True)
    inspection = inspect_source(root, review["targets"])
    assert inspection["status"] == "inspection_only"
    review["source"] = inspection["source"]
    return root


def test_save_shared_containers_round_trip_without_yaml_aliases(repository, review):
    review["checks"][0]["target_ids"] = review["scope"]["reviewed_target_ids"]
    review["assessments"][0]["target_ids"] = review["scope"]["reviewed_target_ids"]
    path = save_review(repository, review, SCHEMA)
    assert read_review(repository, str(path.relative_to(repository)), SCHEMA) == review
    assert load_document(path.read_bytes()) == review


def test_save_binds_bytes_and_derives_markdown(repository, review):
    path = save_review(repository, review, SCHEMA)
    assert path.name == "review.yaml"
    assert path.parent.name == review["review_id"]
    assert read_review(repository, str(path.relative_to(repository)), SCHEMA) == review
    assert review_paths(repository) == [str(path.relative_to(repository))]
    before = path.read_bytes()
    with pytest.raises(ReviewError, match="immutable"):
        save_review(repository, review, SCHEMA)
    assert path.read_bytes() == before
    # A historical artifact is not invalidated by later changes to its target.
    (repository / "data/item.yaml").write_text("id: EX:later\n")
    assert read_review(repository, str(path.relative_to(repository)), SCHEMA) == review
    with pytest.raises(ReviewError, match="input changed"):
        save_review(repository, review, SCHEMA)


def test_mismatched_markdown_is_not_independent_truth(repository, review):
    path = save_review(repository, review, SCHEMA)
    path.with_name("review.md").write_text("# Everything passed\n")
    with pytest.raises(ReviewError, match="Markdown does not match"):
        read_review(repository, str(path.relative_to(repository)), SCHEMA)


def test_save_refuses_ignored_artifacts(repository, review):
    (repository / ".gitignore").write_text("reviews/\n")
    with pytest.raises(ReviewError, match="ignored"):
        save_review(repository, review, SCHEMA)
    assert not (repository / "reviews").exists()


def test_ignored_existing_artifacts_are_still_checked(repository, review):
    path = save_review(repository, review, SCHEMA)
    (repository / ".gitignore").write_text("reviews/\n")
    assert str(path.relative_to(repository)) in review_paths(repository)


def test_source_symlink_and_wrong_repository_are_refused(repository, review):
    outside = repository.parent / "outside.yaml"
    outside.write_text("id: EX:outside\n")
    (repository / "data/item.yaml").unlink()
    (repository / "data/item.yaml").symlink_to(outside)
    with pytest.raises(OSError):
        inspect_source(repository, review["targets"])
    review["repository"] = "Other/NotThisMech"
    with pytest.raises(ReviewError, match="origin"):
        save_review(repository, review, SCHEMA)


def test_output_parent_symlink_cannot_redirect_a_write(repository, review):
    outside = repository.parent / "outside"
    outside.mkdir()
    (repository / "reviews").symlink_to(outside, target_is_directory=True)
    with pytest.raises(OSError):
        save_review(repository, review, SCHEMA)
    assert list(outside.iterdir()) == []


def test_failed_publication_leaves_no_completed_artifact(repository, review, monkeypatch):
    from kg_microbe_governance.artifacts.scripts import record_review

    def fail(*args, **kwargs):
        raise OSError("injected publication failure")

    monkeypatch.setattr(record_review.os, "link", fail)
    with pytest.raises(OSError, match="injected"):
        save_review(repository, review, SCHEMA)
    assert review_paths(repository) == []


def test_markdown_records_limits_without_html_injection(review):
    review["title"] = "<script>alert('x')</script>"
    review["summary"] = "A literal pipe | and a source quotation."
    rendered = render_markdown(review, SCHEMA)
    assert "# &lt;script&gt;" in rendered
    assert "literal pipe &#124;" in rendered
    assert "Scientific review: false" in rendered
    assert "The sibling review.yaml is authoritative." in rendered


def test_semantic_check_failure_can_be_reported_even_when_command_exits_zero(review):
    review["checks"][0].update(command="report-only-validator", exit_code=0, status="failed",
                               summary="The tool completed but its structured output contained errors.")
    review["verdict"] = "needs_curation"
    validate_review(review, SCHEMA)


def test_expected_rejection_is_not_a_failing_check(review):
    review["checks"][0].update(command="reject-invalid-fixture", exit_code=1, expected_exit_code=1)
    validate_review(review, SCHEMA)


def test_cli_saves_checks_and_lists_one_authoritative_record(repository, review, capsys):
    content = repository.parent / "content.yaml"
    content.write_text(yaml.safe_dump(review))
    prefix = ["--repo-root", str(repository), "--schema", str(SCHEMA)]
    assert main([*prefix, "save", "--content", str(content)]) == 0
    output = json.loads(capsys.readouterr().out)
    assert Path(output["review"]).is_file()
    assert Path(output["markdown"]).is_file()
    assert main([*prefix, "check", "--require-reviews"]) == 0
    assert json.loads(capsys.readouterr().out)["valid_reviews"] == 1
    assert main([*prefix, "list"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["scientific_review"] is False


def test_cli_empty_check_is_explicit_and_required_coverage_fails(repository, capsys):
    prefix = ["--repo-root", str(repository), "--schema", str(SCHEMA)]
    assert main([*prefix, "check"]) == 0
    assert json.loads(capsys.readouterr().out)["coverage"] == "no_structured_reviews"
    assert main([*prefix, "check", "--require-reviews"]) == 1
    assert "absence is not reviewed coverage" in capsys.readouterr().err


def test_cli_inspect_never_creates_a_review(repository, review, capsys):
    targets = repository.parent / "targets.yaml"
    targets.write_text(yaml.safe_dump({"targets": review["targets"]}))
    assert main(["--repo-root", str(repository), "--schema", str(SCHEMA),
                 "inspect", "--targets", str(targets)]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "inspection_only"
    assert not (repository / "reviews").exists()


def test_native_duf_snapshot_row_digest_is_preserved(review):
    target = review["targets"][0]
    target.update(kind="snapshot_row", selector="pfam_id=PF04149",
                  semantic_digest={"algorithm": "dufmech-effective-record-v1", "sha256": "b" * 64,
                                   "description": "Domain digest excludes only declared review bookkeeping."})
    review["source"]["snapshot_id"] = "interpro-pfam-duf-fixture"
    review["verdict"] = "seed_only"
    review["limitations"] = ["Frozen seed metadata was checked; no family function was verified."]
    validate_review(review, SCHEMA)
    rendered = render_markdown(review, SCHEMA)
    assert "pfam_id=PF04149" in rendered
    assert "dufmech-effective-record-v1" in rendered
    assert "Scientific review: false" in rendered


def test_cmm_provenance_only_scope_does_not_become_scientific_acceptance(review):
    review["scope"]["description"] = "Review only the linked history event, not criticality or mechanism evidence."
    review["reviewer"].update(kind="agent", independence="self_review",
                              independence_basis="The curator performed this pass; no independent reviewer.")
    review["limitations"] = ["Criticality authority/edition and recovery experiments were not reassessed."]
    validate_review(review, SCHEMA)
    assert review["scientific_review"] is False
    rendered = render_markdown(review, SCHEMA)
    assert "self_review" in rendered
    assert "were not reassessed" in rendered
