"""Fleet reports preserve explicit uncertainty and append-only issue histories."""

import csv
import io
import subprocess
from copy import deepcopy
from types import SimpleNamespace

import pytest
import yaml
from test_record_review import action, finding
from test_record_review import repository as repository  # noqa: F401
from test_record_review import review as review  # noqa: F401

from kg_microbe_governance.artifacts.scripts import record_review as contract
from kg_microbe_reviews.aggregate import collect_repository, render_summary, triage


def commit(root):
    subprocess.run(["git", "-C", str(root), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(root), "commit", "-m", "Fixture observation"],
                   check=True, capture_output=True)


def observation(review, suffix="one", *, status="open", previous=()):
    value = deepcopy(review)
    value["review_id"] = "20261008T010000Z-" + suffix
    value["findings"] = [finding()]
    value["findings"][0]["status"] = status
    value["verdict"] = "needs_curation"
    if status != "open":
        value["findings"][0]["disposition_reason"] = "Explicitly inspected synthetic evidence."
    if previous:
        value["findings"][0]["previous_occurrences"] = [
            {"repository": p["repository"], "review_id": p["review_id"], "finding_id": "f1"}
            for p in previous
        ]
    if status == "open":
        value["actions"] = [action()]
    contract.validate_review(value)
    return value


def surface(*records):
    return {"repository": records[0]["repository"], "surface": "git_ref", "ref": "origin/main",
            "revision": "a" * 40, "remote_freshness": "not_checked", "status": "observed",
            "error": None, "reports": [
                {"record": r, "path": f"reviews/structured/{r['review_id']}/review.yaml",
                 "sha256": "b" * 64, "source_currentness": "matches_observed_surface",
                 "source_provenance": {"status": "working_tree_attestation", "reason": "Synthetic fixture."},
                 "changed_inputs": [], "unavailable_inputs": []} for r in records]}


def test_git_collection_excludes_uncommitted_reports(repository, review):
    contract.save_review(repository, review)
    assert collect_repository(repository, review["repository"], ref="HEAD")["reports"] == []
    working = collect_repository(repository, review["repository"], ref=None)
    assert working["reports"][0]["source_currentness"] == "matches_observed_surface"
    commit(repository)
    pinned = collect_repository(repository, review["repository"], ref="HEAD")
    assert pinned["reports"][0]["record"] == review
    (repository / "data/item.yaml").write_text("id: EX:changed\n")
    assert collect_repository(repository, review["repository"], ref=None)["reports"][0]["source_currentness"] == "changed"
    assert collect_repository(repository, review["repository"], ref="HEAD")["reports"][0]["source_currentness"] == "matches_observed_surface"
    commit(repository)
    changed = collect_repository(repository, review["repository"], ref="HEAD")["reports"][0]
    assert changed["changed_inputs"] == ["data/item.yaml"]
    assert changed["source_currentness"] == "changed"


@pytest.mark.parametrize("damage", ["edit", "delete", "committed-edit"])
def test_append_only_gate_uses_the_trusted_base(repository, review, damage):
    path = contract.save_review(repository, review)
    commit(repository)
    base = subprocess.check_output(["git", "-C", str(repository), "rev-parse", "HEAD"]).decode().strip()
    contract.assert_append_only(repository, base)
    if damage == "delete":
        path.unlink()
    else:
        review["summary"] = "Rewritten historical observation"
        path.write_text(yaml.safe_dump(review, sort_keys=False))
        path.with_name("review.md").write_text(contract.render_markdown(review))
        if damage == "committed-edit":
            commit(repository)
            contract.assert_append_only(repository, "HEAD")
    with pytest.raises(contract.ReviewError, match="append-only"):
        contract.assert_append_only(repository, base)


def test_append_only_gate_rejects_unknown_base_even_without_reviews(repository):
    with pytest.raises(contract.ReviewError, match="Git provenance"):
        contract.assert_append_only(repository, "absent-revision")


def test_missing_and_symlink_inputs_are_unknown(repository, review):
    contract.save_review(repository, review)
    target = repository / "data/item.yaml"
    target.unlink()
    missing = collect_repository(repository, review["repository"], ref=None)["reports"][0]
    assert missing["source_currentness"] == "unknown"
    target.symlink_to("../../outside.yaml")
    commit(repository)
    linked = collect_repository(repository, review["repository"], ref="HEAD")["reports"][0]
    assert linked["source_currentness"] == "unknown"
    assert linked["unavailable_inputs"] == ["data/item.yaml"]


@pytest.mark.parametrize("damage", ["unpaired", "foreign", "symlink", "unexpected"])
def test_git_collection_refuses_invalid_bundles(repository, review, damage):
    path = contract.save_review(repository, review)
    if damage == "unpaired":
        path.with_name("review.md").unlink()
    elif damage == "foreign":
        review["repository"] = "Other/Mech"
        path.write_text(yaml.safe_dump(review))
        path.with_name("review.md").write_text(contract.render_markdown(review))
    elif damage == "symlink":
        path.unlink()
        path.symlink_to("../../../data/item.yaml")
    else:
        path.with_name("unrelated.txt").write_text("not a review artifact")
    commit(repository)
    with pytest.raises(contract.ReviewError):
        collect_repository(repository, "Example/FixtureMech", ref="HEAD")


def test_invalid_ref_and_origin_fail_closed(repository, review):
    with pytest.raises(contract.ReviewError, match="snapshot"):
        collect_repository(repository, review["repository"], ref="not-a-branch")
    with pytest.raises(contract.ReviewError, match="identity"):
        collect_repository(repository, "Other/Mech", ref="HEAD")


def test_clean_later_review_does_not_close_a_finding(review):
    initial = observation(review)
    later = deepcopy(review)
    later["review_id"] = "20261008T010000Z-later-clean"
    result = triage([surface(initial, later)])
    assert result["issues"][0]["status"] == "open"
    assert result["counts"]["reviews"] == 2
    assert result["counts"]["finding_occurrences"] == 1
    assert result["reviews"][0]["record"]["evidence"] == review["evidence"]


def test_explicit_resolution_advances_only_linked_history(review):
    initial = observation(review)
    resolved = observation(review, "resolved", status="resolved", previous=[initial])
    result = triage([surface(initial, resolved)])
    assert result["issues"][0]["status"] == "resolved"
    assert len(result["issues"][0]["occurrences"]) == 2
    assert len(result["issues"][0]["heads"]) == 1
    missing = triage([surface(resolved)])
    assert missing["issues"][0]["status"] == "unverified_lineage"
    assert missing["lineage_diagnostics"]


def test_conflicting_heads_require_explicit_reconciliation(review):
    initial = observation(review)
    resolved = observation(review, "resolved", status="resolved", previous=[initial])
    rechecked = observation(review, "still-open", previous=[initial])
    result = triage([surface(initial, resolved, rechecked)])
    assert result["issues"][0]["status"] == "conflicting_dispositions"
    reconciled = observation(review, "reconciled", status="resolved", previous=[resolved, rechecked])
    result = triage([surface(initial, resolved, rechecked, reconciled)])
    assert result["issues"][0]["status"] == "resolved"
    assert len(result["issues"][0]["occurrences"]) == 4


@pytest.mark.parametrize("damage", ["issue_key", "chronology", "cycle"])
def test_invalid_history_is_not_silently_resolved(review, damage):
    initial = observation(review)
    later = observation(review, "later", status="resolved", previous=[initial])
    if damage == "issue_key":
        initial["findings"][0]["issue_key"] = "a-different-issue"
    elif damage == "chronology":
        later["finished_at"] = "2026-10-08T00:59:59Z"
        later["review_id"] = "20261008T005959Z-later"
        later["evidence"][0]["accessed_at"] = "2026-10-08T00:59:30Z"
    else:
        initial["findings"][0]["previous_occurrences"] = [
            {"repository": later["repository"], "review_id": later["review_id"], "finding_id": "f1"}]
    result = triage([surface(initial, later)])
    assert any(i["status"] == "unverified_lineage" for i in result["issues"])
    assert result["lineage_diagnostics"]


def test_duplicate_reviews_fail_and_issue_keys_are_repository_scoped(review):
    initial = observation(review)
    with pytest.raises(contract.ReviewError, match="duplicate review identity"):
        triage([surface(initial, initial)])
    other = deepcopy(initial)
    other["repository"] = "Other/Mech"
    result = triage([surface(initial), surface(other)])
    assert len(result["issues"]) == 2
    assert result["counts"]["by_status"] == {"open": 2}


def test_summary_formats_preserve_text_without_table_injection(review):
    initial = observation(review)
    initial["findings"][0]["title"] = 'A\t"quoted" title\n<script>bad</script>|cell'
    result = triage([surface(initial)])
    rows = list(csv.reader(io.StringIO(render_summary(result, "tsv")), delimiter="\t"))
    assert rows[1][4] == initial["findings"][0]["title"]
    rendered = render_summary(result, "markdown")
    assert "<script>" not in rendered
    assert "&lt;script&gt;" in rendered
    assert "&#124;cell" in rendered


def test_terminal_disposition_cannot_erase_an_unreviewed_target(review):
    initial = observation(review)
    initial["kind"] = "batch"
    initial["scope"].update(population_size=2, reviewed_target_ids=["EX:item", "EX:other"])
    initial["targets"].append({**deepcopy(initial["targets"][0]), "target_id": "EX:other",
                               "path": "data/other.yaml"})
    initial["source"]["inputs"].append({"path": "data/other.yaml", "sha256": "b" * 64,
                                        "role": "target"})
    initial["assessments"][0]["target_ids"].append("EX:other")
    initial["findings"][0]["target_ids"].append("EX:other")
    resolved = observation(review, "resolved", status="resolved", previous=[initial])
    result = triage([surface(initial, resolved)])
    assert result["issues"][0]["status"] == "unverified_lineage"
    assert "previous affected targets" in result["lineage_diagnostics"][0]["error"]


@pytest.mark.parametrize("status", ["open", "deferred"])
def test_intermediate_update_cannot_drop_targets_before_resolution(review, status):
    initial = observation(review, "initial")
    initial["kind"] = "batch"
    initial["scope"].update(population_size=2, reviewed_target_ids=["EX:item", "EX:other"])
    initial["targets"].append({**deepcopy(initial["targets"][0]), "target_id": "EX:other",
                               "path": "data/other.yaml"})
    initial["source"]["inputs"].append({"path": "data/other.yaml", "sha256": "b" * 64, "role": "target"})
    initial["assessments"][0]["target_ids"].append("EX:other")
    initial["findings"][0]["target_ids"].append("EX:other")
    narrow = observation(review, "narrow", status=status, previous=[initial])
    resolved = observation(review, "resolved", status="resolved", previous=[narrow])
    result = triage([surface(initial, narrow, resolved)])
    assert result["issues"][0]["status"] == "unverified_lineage"
    assert result["issues"][0]["target_ids"] == ["EX:item", "EX:other"]
    assert result["planning_inputs"]


@pytest.mark.parametrize("completion", ["failed", "partial"])
def test_unreviewed_targets_cannot_be_resolved(review, completion):
    prior = observation(review)
    later = observation(review, "later", status="resolved", previous=[prior])
    later.update(completion=completion, verdict="blocked", limitations=["No target assessed."])
    later["scope"].update(coverage="partial", reviewed_target_ids=[])
    later["checks"][0].update(status="unavailable")
    later["assessments"][0].update(outcome="unknown", evidence_ids=[])
    with pytest.raises(contract.ReviewError, match="actually reviewed"):
        contract.validate_review(later)


@pytest.mark.parametrize("reverse", [False, True])
def test_mixed_invalid_lineage_preserves_valid_predecessor_and_plan(review, reverse):
    prior = observation(review, "prior")
    later = observation(review, "later", status="resolved", previous=[prior])
    later["findings"][0]["previous_occurrences"].append({
        "repository": review["repository"], "review_id": "20261008T010000Z-missing", "finding_id": "f1"})
    if reverse:
        later["findings"][0]["previous_occurrences"].reverse()
    result = triage([surface(prior, later)])
    assert result["issues"][0]["status"] == "unverified_lineage"
    assert prior["review_id"] in {head["review_id"] for head in result["issues"][0]["heads"]}
    assert any(plan["review_id"] == prior["review_id"] for plan in result["planning_inputs"])


def test_cyclic_lineage_with_terminal_descendant_preserves_open_plans(review):
    first = observation(review, "first")
    second = observation(review, "second", previous=[first])
    first["findings"][0]["previous_occurrences"] = [{
        "repository": second["repository"], "review_id": second["review_id"], "finding_id": "f1"}]
    last = observation(review, "last", status="resolved", previous=[second])
    result = triage([surface(first, second, last)])
    assert result["issues"][0]["status"] == "unverified_lineage"
    assert any("cyclic" in error["error"] for error in result["lineage_diagnostics"])
    assert {first["review_id"], second["review_id"]} <= {
        plan["review_id"] for plan in result["planning_inputs"]}


def test_failed_but_otherwise_assessed_review_cannot_resolve(review):
    prior = observation(review, "prior")
    later = observation(review, "later", status="resolved", previous=[prior])
    later.update(completion="failed", verdict="blocked", limitations=["Execution failed after assessment."])
    with pytest.raises(contract.ReviewError, match="terminal findings"):
        contract.validate_review(later)


def test_partial_review_can_resolve_a_target_it_actually_assessed(review):
    prior = observation(review)
    later = observation(review, "later", status="resolved", previous=[prior])
    later.update(completion="partial", verdict="blocked", limitations=["Optional wider source search unavailable."])
    later["scope"].update(coverage="partial")
    contract.validate_review(later)
    assert triage([surface(prior, later)])["issues"][0]["status"] == "resolved"


@pytest.mark.parametrize("damage, status", [("nonexistent", "unverified"), ("hash", "invalid")])
def test_ingestion_exposes_impossible_committed_provenance(repository, review, damage, status):
    path = contract.save_review(repository, review)
    review["source"]["state"] = "git_commit"
    if damage == "nonexistent":
        review["source"]["git_revision"] = "0" * 40
    else:
        review["source"]["inputs"][0]["sha256"] = "0" * 64
    path.write_text(yaml.safe_dump(review, sort_keys=False))
    path.with_name("review.md").write_text(contract.render_markdown(review))
    with pytest.raises(contract.ReviewError, match="source provenance"):
        contract.read_review(repository, str(path.relative_to(repository)))
    assert contract.main(["--repo-root", str(repository), "check"]) == 1
    observed = collect_repository(repository, review["repository"], ref=None)
    assert observed["reports"][0]["source_provenance"]["status"] == status
    assert triage([observed])["provenance_diagnostics"]
    commit(repository)
    pinned = collect_repository(repository, review["repository"], ref="HEAD")
    assert pinned["reports"][0]["source_provenance"]["status"] == status


def test_committed_historical_provenance_survives_later_target_changes(repository, review):
    review["source"]["state"] = "git_commit"
    path = contract.save_review(repository, review)
    commit(repository)
    (repository / "data/item.yaml").write_text("id: EX:changed\n")
    commit(repository)
    assert contract.read_review(repository, str(path.relative_to(repository))) == review
    observation = collect_repository(repository, review["repository"], ref="HEAD")["reports"][0]
    assert observation["source_provenance"]["status"] == "git_commit_verified"
    assert observation["source_currentness"] == "changed"


@pytest.mark.parametrize("state", ["matches_observed_surface", "changed", "unknown"])
def test_terminal_summary_exposes_head_source_currentness(review, state):
    prior = observation(review)
    resolved = observation(review, "resolved", status="resolved", previous=[prior])
    observed = surface(prior, resolved)
    observed["reports"][1]["source_currentness"] = state
    result = triage([observed])
    assert result["issues"][0]["status"] == "resolved"
    assert state in render_summary(result, "markdown")
    assert state in render_summary(result, "tsv")


def test_mixed_terminal_heads_remain_distinguishable(review):
    prior = observation(review)
    first = observation(review, "resolved-a", status="resolved", previous=[prior])
    second = observation(review, "resolved-b", status="resolved", previous=[prior])
    observed = surface(prior, first, second)
    observed["reports"][2]["source_currentness"] = "unknown"
    result = triage([observed])
    assert "mixed: matches_observed_surface, unknown" in render_summary(result, "tsv")


@pytest.mark.parametrize("status", ["unverified", "invalid", "unexpected"])
def test_unverified_resolution_cannot_replace_open_head_or_planning(review, status):
    prior = observation(review)
    resolved = observation(review, "resolved", status="resolved", previous=[prior])
    observed = surface(prior, resolved)
    observed["reports"][1]["source_provenance"] = {"status": status, "reason": "Unusable provenance."}
    result = triage([observed])
    assert result["issues"][0]["status"] == "unverified_lineage"
    assert result["planning_inputs"]


def test_planning_preserves_unlinked_prerequisites_without_claiming_execution(review):
    initial = observation(review)
    initial["actions"][0]["depends_on"] = ["prepare"]
    initial["actions"].append({**action(), "action_id": "prepare", "finding_ids": [],
                               "description": "Prepare bounded evidence context."})
    result = triage([surface(initial)])
    assert len(result["planning_inputs"]) == 2
    assert {p["execution_status"] for p in result["planning_inputs"]} == {"not_established"}
    assert result["counts"]["by_category"] == {"evidence": 1}
    assert result["counts"]["by_repository"] == {"Example/FixtureMech": 1}
    assert "Prepare bounded evidence context" in render_summary(result, "markdown")
    resolved = observation(review, "resolved", status="resolved", previous=[initial])
    assert triage([surface(initial, resolved)])["planning_inputs"] == []


@pytest.fixture
def fleet_cli(monkeypatch, tmp_path):
    from kg_microbe_reviews import __main__ as cli
    from plugins.repository_settings import RepositoryConfigurationError

    monkeypatch.setattr(cli, "load_fleet_manifest", lambda: SimpleNamespace(mechs={
        "fixture": SimpleNamespace(github="Example/FixtureMech"),
        "missing": SimpleNamespace(github="Other/Mech")}))
    monkeypatch.setattr(cli, "claw_root", lambda: tmp_path)
    monkeypatch.setattr(cli, "is_claw_checkout", lambda root: root == tmp_path)
    monkeypatch.setattr(cli, "merged_repository_environment", lambda path: {})

    def target(key):
        if key == "missing":
            raise RepositoryConfigurationError("not configured")
        return SimpleNamespace(path=tmp_path, open=lambda: None)

    monkeypatch.setattr(cli, "RepositorySettings", SimpleNamespace(
        from_environment=lambda **kw: SimpleNamespace(get_target=target)))
    return cli


def test_fleet_cli_keeps_missing_repositories_and_requires_coverage(fleet_cli, monkeypatch, capsys):
    import json

    def empty(*args, **kwargs):
        return {"repository": "Example/FixtureMech", "surface": "git_ref", "ref": "origin/main",
                "revision": "a" * 40, "remote_freshness": "not_checked", "status": "no_structured_reviews",
                "error": None, "reports": []}

    monkeypatch.setattr(fleet_cli, "collect_repository", empty)
    assert fleet_cli.fleet_main(["--all"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert [r["status"] for r in report["repositories"]] == ["no_structured_reviews", "unavailable"]
    assert report["counts"]["repositories"] == 2
    assert fleet_cli.fleet_main(["--mech", "fixture"]) == 0
    capsys.readouterr()
    assert fleet_cli.fleet_main(["--mech", "fixture", "--require-reviews"]) == 1


def test_cli_filters_never_hide_lineage_errors_or_overwrite(fleet_cli, monkeypatch, review, tmp_path, capsys):
    import json

    prior = observation(review)
    resolved = observation(review, "resolved", status="resolved", previous=[prior])
    monkeypatch.setattr(fleet_cli, "collect_repository", lambda *a, **kw: surface(resolved))
    assert fleet_cli.fleet_main(["--mech", "fixture", "--status", "open"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["issues"] == []
    assert report["lineage_diagnostics"]
    assert report["counts"]["distinct_issues"] == 1
    output = tmp_path / "triage.json"
    output.write_text("retained output")
    assert fleet_cli.fleet_main(["--mech", "fixture", "--output", str(output)]) == 1
    assert output.read_text() == "retained output"
