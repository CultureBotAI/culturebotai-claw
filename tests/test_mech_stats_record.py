"""Local stats archives preserve evidence and never invent chat history."""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_progress import ProgressError, snapshot_from_history

ROOT = Path(__file__).parents[1]
NOW = datetime(2026, 10, 25, 20, tzinfo=timezone.utc)


@pytest.fixture
def recorder(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location("mech_stats_record", ROOT / "scripts/mech_stats_record.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "source" / "bundle.json"
    path.parent.mkdir()
    history = {"schema_version": "1.0.0", "closures": [], "pr_events": [], "associations": [], "cursors": []}
    snapshot = snapshot_from_history(history, generated_at=(NOW - timedelta(hours=1)).isoformat())
    path.write_text(json.dumps({"history": history, "snapshot": snapshot}))
    (path.parent / "fleet.yaml").write_text(load_fleet_manifest().source.read_text())
    return path


def response(**overrides):
    return {"source_id": "conversation:reply-1", "source": "conversation summary",
            "text_kind": "summary", "text": "The response summarized the verified tracker counts.",
            "responded_at": None, "prompt": None, **overrides}


def test_snapshot_and_response_are_distinct_idempotent_and_sources_unchanged(recorder, source, tmp_path):
    archive = tmp_path / "report"
    before = source.read_bytes()
    first = recorder.record_stats(source, archive, now=NOW)
    assert first["snapshots"] == 1 and first["responses"] == 0
    second = recorder.record_stats(source, archive, response=response(), now=NOW)
    assert second["snapshots"] == 1 and second["responses"] == 1
    saved = (archive / "report.json").read_bytes()
    repeated = recorder.record_stats(source, archive, response=response(), now=NOW + timedelta(days=1))
    assert repeated["status"] == "unchanged"
    assert (archive / "report.json").read_bytes() == saved
    assert source.read_bytes() == before
    report = json.loads(saved)
    assert report["responses"][0]["responded_at"] is None
    assert report["responses"][0]["text_kind"] == "summary"
    row = report["snapshots"][0]
    assert row["freshness_at_recording"]["warnings"]
    assert len(row["per_mech"]) == len(load_fleet_manifest().keys)
    assert row["tracking"]["earlier_history"] == "unknown"
    recorder.validate_report(archive, report)


def test_backfill_sorts_by_observation_time_without_fabricating_responses(recorder, source, tmp_path):
    archive = tmp_path / "report"
    recorder.record_stats(source, archive, now=NOW)
    old = json.loads(source.read_text())
    old["snapshot"]["generated_at"] = (NOW - timedelta(days=1)).isoformat()
    source.write_text(json.dumps(old))
    recorder.record_stats(source, archive, now=NOW)
    report = json.loads((archive / "report.json").read_text())
    assert len(report["snapshots"]) == 2 and report["responses"] == []
    assert report["snapshots"][0]["as_of"] == old["snapshot"]["generated_at"]


@pytest.mark.parametrize("tamper", ["input_counts", "archived_counts", "archive_bytes", "response_rewrite"])
def test_invalid_or_rewritten_evidence_cannot_replace_the_report(recorder, source, tmp_path, tamper):
    archive = tmp_path / "report"
    recorder.record_stats(source, archive, response=response(), now=NOW)
    report_path = archive / "report.json"
    report = json.loads(report_path.read_text())
    changed_response = response()
    if tamper == "input_counts":
        value = json.loads(source.read_text())
        value["snapshot"]["totals"]["unique_prs"] = 100
        source.write_text(json.dumps(value))
    elif tamper == "archived_counts":
        report["snapshots"][0]["totals"]["completed_goals"] = 100
        report_path.write_text(json.dumps(report))
    elif tamper == "archive_bytes":
        bundle = archive / report["snapshots"][0]["evidence"]["bundle"]["path"]
        bundle.write_text("{}")
    else:
        changed_response["text"] = "Silently changed historical answer"
    before = report_path.read_bytes()
    with pytest.raises(ProgressError):
        recorder.record_stats(source, archive, response=changed_response, now=NOW)
    assert report_path.read_bytes() == before


def test_supplement_preserved_but_never_used_as_verified_counts(recorder, source, tmp_path):
    archive = tmp_path / "report"
    supplemental = tmp_path / "observations.json"
    supplemental.write_text('[{"unverified_supplement": true, "unique_prs": 999}]\n')
    recorder.record_stats(source, archive, now=NOW)
    recorder.record_stats(source, archive, observations_path=supplemental, now=NOW)
    report = json.loads((archive / "report.json").read_text())
    row = report["snapshots"][0]
    assert row["totals"]["unique_prs"] == 0
    assert (archive / row["evidence"]["supplements"][0]["path"]).read_bytes() == supplemental.read_bytes()


def test_response_time_requires_timezone(recorder, source, tmp_path):
    with pytest.raises(ProgressError, match="timezone"):
        recorder.record_stats(source, tmp_path / "report", response=response(responded_at="2026-10-25T20:00:00"), now=NOW)


def test_redirected_archive_cannot_write_outside_report(recorder, source, tmp_path):
    archive = tmp_path / "report"
    archive.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (archive / "snapshots").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ProgressError, match="symlink"):
        recorder.record_stats(source, archive, now=NOW)
    assert list(outside.iterdir()) == []


def test_broken_adjacent_manifest_never_falls_back(recorder, source, tmp_path):
    pin = source.parent / "fleet.yaml"
    pin.unlink()
    pin.symlink_to(tmp_path / "missing-manifest.yaml")
    with pytest.raises(ProgressError, match="regular"):
        recorder.record_stats(source, tmp_path / "report", now=NOW)


def test_failed_evidence_write_can_be_retried(recorder, source, tmp_path, monkeypatch):
    archive = tmp_path / "report"
    replace = recorder.os.replace
    def interrupted(source_path, destination):
        if Path(destination).name == "bundle.json":
            raise OSError("simulated failed atomic replace")
        return replace(source_path, destination)
    with monkeypatch.context() as patch:
        patch.setattr(recorder.os, "replace", interrupted)
        with pytest.raises(OSError, match="simulated"):
            recorder.record_stats(source, archive, now=NOW)
    assert not (archive / "report.json").exists()
    assert not list(archive.rglob("bundle.json"))
    assert recorder.record_stats(source, archive, now=NOW)["status"] == "recorded"


def test_reported_count_parser_ignores_stale_explanation(recorder):
    text = ("14 Mechs, 181 PRs (181 merged, 0 open), 170 completed goals, 22 completed cycles\n\n"
            "These are last verified counts from 05:19 UTC, about 1h50m old. Both monitors are running.")
    assert recorder.reported_counts(text) == {
        "mech_count": 14, "unique_prs": 181, "merged_prs": 181, "open_prs": 0,
        "closed_prs": 0, "completed_goals": 170, "completed_cycles": 22,
    }
    with pytest.raises(ProgressError):
        recorder.reported_counts("Requested example: " + text)


def test_response_only_history_never_becomes_a_verified_snapshot(recorder, source, tmp_path):
    archive = tmp_path / "report"
    recorder.record_stats(source, archive, response=response(), now=NOW)
    reply = response(source_id="transcript:1", text_kind="verbatim",
        text="14 Mechs, 8 PRs (6 merged, 2 open), 2 completed goals, 0 completed cycles",
        responded_at="2026-10-21T00:34:22.168Z", prompt="current mech work stats",
        prompted_at="2026-10-21T00:34:11.022Z", snapshot_id=None)
    result = recorder.record_response_history(archive, [reply],
        supersedes={"conversation:reply-1": "transcript:1"}, now=NOW)
    assert result["response_only_observations"] == 1
    report = json.loads((archive / "report.json").read_text())
    assert len(report["snapshots"]) == 1
    assert report["snapshots"][0]["totals"]["unique_prs"] == 0
    assert report["response_only_observations"][0]["reported_counts"]["unique_prs"] == 8
    assert report["responses"][0]["superseded_by"] == "transcript:1"
    assert recorder.record_response_history(archive, [reply],
        supersedes={"conversation:reply-1": "transcript:1"}, now=NOW)["status"] == "unchanged"


def test_transcript_cannot_link_a_different_measurement(recorder, source, tmp_path):
    archive = tmp_path / "report"
    result = recorder.record_stats(source, archive, now=NOW)
    reply = response(text="14 Mechs, 8 PRs (6 merged, 2 open), 2 completed goals, 0 completed cycles",
                     snapshot_id=result["snapshot_id"])
    before = (archive / "report.json").read_bytes()
    with pytest.raises(ProgressError, match="linked snapshot"):
        recorder.record_response_history(archive, [reply], now=NOW)
    assert (archive / "report.json").read_bytes() == before


def test_embedded_observation_requires_an_exact_unambiguous_response_excerpt(recorder):
    summary = "14 Mechs, 8 PRs (5 merged, 3 open), 1 completed goal, 0 completed cycles"
    value = response(text=f"Dashboard is live. Currently recorded: **{summary}**. Earlier history is unknown.",
                     reported_summary=summary, reported_counts=recorder.reported_counts(summary))
    assert recorder.response_record(value, None, NOW.isoformat())["reported_counts"]["completed_goals"] == 1
    value["reported_summary"] = summary.replace("1 completed goal", "2 completed goals")
    with pytest.raises(ProgressError, match="exact unique excerpt"):
        recorder.response_record(value, None, NOW.isoformat())


def test_cli_response_without_optional_counts_cannot_link_another_measurement(
        recorder, source, tmp_path, capsys):
    archive = tmp_path / "report"
    recorder.record_stats(source, archive, now=NOW)
    before = (archive / "report.json").read_bytes()
    count = len(load_fleet_manifest().keys)
    answer = response(text_kind="verbatim", text=(
        f"{count} Mechs, 1 PR (0 merged, 1 open), 0 completed goals, 0 completed cycles"))
    assert "reported_counts" not in answer
    response_path = tmp_path / "response.json"
    response_path.write_text(json.dumps(answer))
    result = recorder.main(["--bundle", str(source), "--report-dir", str(archive),
                            "--response-file", str(response_path)])
    assert result == 1
    assert "linked snapshot" in capsys.readouterr().err
    assert (archive / "report.json").read_bytes() == before


@pytest.mark.parametrize("retry", ["stats", "history"])
def test_numeric_response_retry_preserves_legacy_rows_without_derived_counts(
        recorder, source, tmp_path, retry):
    archive = tmp_path / "report"
    summary = recorder.format_summary(json.loads(source.read_text())["snapshot"])
    answer = response(text=summary + "\n\nEarlier stale notes mentioned 999 PRs.")
    result = recorder.record_stats(source, archive, response=answer, now=NOW)
    path = archive / "report.json"
    report = json.loads(path.read_text())
    assert report["responses"][0]["reported_counts"]["unique_prs"] == 0
    # A report created before automatic count derivation must remain retryable.
    del report["responses"][0]["reported_counts"]
    report["response_only_observations"] = []
    path.write_text(json.dumps(report))
    before = path.read_bytes()
    if retry == "stats":
        repeated = recorder.record_stats(source, archive, response=answer, now=NOW + timedelta(days=1))
    else:
        repeated = recorder.record_response_history(archive,
            [{**answer, "snapshot_id": result["snapshot_id"]}], now=NOW + timedelta(days=1))
    assert repeated["status"] == "unchanged"
    assert path.read_bytes() == before


def test_revalidation_checks_legacy_numeric_text_without_optional_counts(recorder, source, tmp_path):
    archive = tmp_path / "report"
    summary = recorder.format_summary(json.loads(source.read_text())["snapshot"])
    recorder.record_stats(source, archive, response=response(text=summary), now=NOW)
    path = archive / "report.json"
    report = json.loads(path.read_text())
    report["responses"][0].pop("reported_counts")
    report["responses"][0]["text"] = summary.replace("0 completed goals", "1 completed goal")
    path.write_text(json.dumps(report))
    before = path.read_bytes()
    with pytest.raises(ProgressError, match="linked snapshot"):
        recorder.record_stats(source, archive, now=NOW)
    assert path.read_bytes() == before


def test_explicit_excerpt_is_parsed_without_optional_counts(recorder, source, tmp_path):
    summary = recorder.format_summary(json.loads(source.read_text())["snapshot"])
    value = response(text=f"Tracker report: **{summary}**. Other notes are not measurements.",
                     reported_summary=summary)
    assert "reported_counts" not in value
    row = recorder.response_record(value, None, NOW.isoformat())
    assert row["reported_counts"] == recorder.reported_counts(summary)
    value["text"] += " " + summary
    with pytest.raises(ProgressError, match="exact unique excerpt"):
        recorder.response_record(value, None, NOW.isoformat())
    value = response(text="Context: not a stats line.", reported_summary="not a stats line.")
    with pytest.raises(ProgressError, match="unambiguous stats line"):
        recorder.response_record(value, None, NOW.isoformat())


def test_later_stats_line_is_not_inferred_for_an_unparsed_summary(recorder, source):
    summary = recorder.format_summary(json.loads(source.read_text())["snapshot"])
    value = response(text="An attributed summary with no current numerical answer.\n" + summary)
    assert "reported_counts" not in recorder.response_record(value, None, NOW.isoformat())


@pytest.mark.parametrize("length", [2, 3])
def test_supersession_cycles_across_collections_preserve_prior_report(
        recorder, source, tmp_path, length):
    archive = tmp_path / "report"
    recorder.record_stats(source, archive, response=response(source_id="a"), now=NOW)
    summary = recorder.format_summary(json.loads(source.read_text())["snapshot"])
    entries = [response(source_id=name, text=summary, snapshot_id=None)
               for name in ("b", "c")[:length - 1]]
    chain = {"a": "b"} if length == 2 else {"a": "b", "b": "c"}
    recorder.record_response_history(archive, entries, supersedes=chain, now=NOW)
    path = archive / "report.json"
    before = path.read_bytes()
    with pytest.raises(ProgressError, match="cycle"):
        recorder.record_response_history(archive, [],
            supersedes={("b" if length == 2 else "c"): "a"}, now=NOW)
    assert path.read_bytes() == before
    recorder.validate_report(archive, json.loads(before))


def test_supersession_allows_shared_successor_and_acyclic_chains(recorder, source, tmp_path):
    archive = tmp_path / "report"
    recorder.record_stats(source, archive, response=response(source_id="a"), now=NOW)
    summary = recorder.format_summary(json.loads(source.read_text())["snapshot"])
    entries = [response(source_id=name, text=summary, snapshot_id=None) for name in ("b", "c", "d")]
    links = {"a": "c", "b": "c", "c": "d"}
    recorder.record_response_history(archive, entries, supersedes=links, now=NOW)
    report = json.loads((archive / "report.json").read_text())
    recorder.validate_report(archive, report)
    rows = report["responses"] + report["response_only_observations"]
    assert [row["source_id"] for row in rows if "superseded_by" not in row] == ["d"]
    assert recorder.record_response_history(archive, [], supersedes=links, now=NOW)["status"] == "unchanged"
