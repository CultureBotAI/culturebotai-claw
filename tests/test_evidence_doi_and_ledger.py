"""DOI sources, the known-findings ledger and the quote-bearing share (#729).

Every case is driven by an input where the two behaviours differ: a cache
that holds the quote under one identifier and not the other, a ledger entry
that matches one finding and not its neighbour.
"""
from __future__ import annotations

import json
import os
import subprocess
from types import SimpleNamespace

import pytest

import kg_microbe_evidence.__main__ as cli
from kg_microbe_evidence import (
    EvidenceConfig,
    EvidenceError,
    EvidenceValidator,
    KnownFinding,
    cache_file_name,
    exit_code,
    load_known_findings,
    normalize_doi,
    plan_known_findings,
    validate_corpus,
    write_known_findings,
)

DOI = "10.1000/abc"
ISSUE = "https://github.com/CultureBotAI/HabitatMech/issues/1"
OTHER_ISSUE = "https://github.com/CultureBotAI/HabitatMech/issues/2"
LEDGER = "curation/evidence_known_findings.tsv"


@pytest.fixture
def root(tmp_path):
    cache = tmp_path / "references_cache"
    cache.mkdir()
    (cache / "PMID_1.md").write_text(
        "# PMID:1\n\n**Title:** A title is metadata.\n\n## Abstract\n\nThe PMID abstract says growth increased.\n")
    (cache / cache_file_name("DOI", DOI)).write_text(
        "# DOI:10.1000/ABC\n\n**PMID:** 9\n\n## Abstract\n\nThe DOI abstract says yield doubled.\n")
    return tmp_path


def check(root, item, **settings):
    config = EvidenceConfig.from_settings({"cache_dir": "references_cache",
                                           "reference_fields": ["pmid", "doi", "reference"], **settings})
    return EvidenceValidator(root, config).check_item(item)


@pytest.mark.parametrize("citation", [
    "doi:10.1000/abc", "DOI:10.1000/ABC", "https://doi.org/10.1000/abc",
    "http://dx.doi.org/10.1000/abc", "10.1000/abc",
])
def test_every_spelling_of_one_doi_reads_one_cache(root, citation):
    result = check(root, {"reference": citation, "snippet": "yield doubled"})
    assert (result.verdict, result.reference) == ("OK", f"DOI:{DOI}")
    assert check(root, {"reference": citation, "snippet": "growth increased"}).verdict == "SNIPPET_NOT_IN_SOURCE"


def test_doi_cache_must_name_the_cited_doi(root):
    (root / "references_cache" / cache_file_name("DOI", "10.1000/xyz")).write_text(
        "# DOI:10.1000/abc\n\n## Abstract\n\nyield doubled\n")
    assert check(root, {"reference": "doi:10.1000/xyz", "snippet": "yield doubled"}).verdict == "INVALID_CACHE"


def test_pmid_keeps_precedence_over_a_doi(root):
    # The DOI cache holds this quote and the PMID cache does not: a PMID-first
    # checker reports a mismatch, a DOI-first one would report OK.
    result = check(root, {"pmid": "1", "doi": DOI, "snippet": "yield doubled"})
    assert (result.verdict, result.reference) == ("SNIPPET_NOT_IN_SOURCE", "PMID:1")


def test_two_distinct_dois_conflict(root):
    item = {"doi": DOI, "reference": "doi:10.1000/other", "snippet": "yield doubled"}
    assert check(root, item).verdict == "INVALID_EVIDENCE"
    item["reference"] = "https://doi.org/10.1000/ABC"
    assert check(root, item).verdict == "OK"


def test_doi_without_cache_is_missing_not_unsupported(root):
    result = check(root, {"reference": "doi:10.2000/none", "snippet": "anything"})
    assert result.verdict == "MISSING_CACHE"
    assert result.cache_path == "references_cache/" + cache_file_name("DOI", "10.2000/none")


def test_cache_names_are_reversible_and_case_folded():
    assert cache_file_name("DOI", "10.1000/a:b") == "DOI_10.1000%2Fa%3Ab.md"
    assert cache_file_name("DOI", "10.1000/a/b") != cache_file_name("DOI", "10.1000/a_b")
    assert normalize_doi("DOI:10.1000/ABC") == normalize_doi("10.1000/abc") == "10.1000/abc"
    assert normalize_doi("10.1000/has space") is None
    assert normalize_doi("https://example.org/10.1000/abc") is None


def test_overlong_doi_stays_unverified(root):
    doi = "10.1000/" + "x" * 300
    assert check(root, {"reference": doi, "snippet": "anything"}).verdict == "UNSUPPORTED_REFERENCE"


# --- known-findings ledger -------------------------------------------------

def record(root, *items):
    lines = ["evidence:"]
    for reference, snippet in items:
        lines += [f"- reference: '{reference}'", f"  snippet: '{snippet}'"]
    (root / "item.yaml").write_text("\n".join(lines) + "\n")


def config(**extra):
    return EvidenceConfig.from_settings({"cache_dir": "references_cache", "reference_fields": ["reference"],
                                         "snippet_fields": ["snippet"], **extra})


def ledger_rows(root, report, issue=ISSUE):
    plan = plan_known_findings(report, issue)
    write_known_findings(root, LEDGER, plan["rows"])
    return plan


def test_a_recorded_finding_stops_blocking_and_is_counted_apart(root):
    record(root, ("PMID:1", "a paraphrase"), ("PMID:1", "growth increased"))
    unrecorded = validate_corpus(root, ["item.yaml"], config(known_findings=LEDGER), missing_ledger_ok=True)
    assert exit_code(unrecorded, strict=True) == 2
    ledger_rows(root, unrecorded)
    report = validate_corpus(root, ["item.yaml"], config(known_findings=LEDGER))
    assert exit_code(report, strict=True) == 0
    assert report["known_findings"]["SNIPPET_NOT_IN_SOURCE"] == 1
    assert report["verdicts"]["SNIPPET_NOT_IN_SOURCE"] == 1  # still reported, never validated
    assert report["quote_validated_items"] == 1


def test_a_new_failure_beside_a_recorded_one_still_blocks(root):
    record(root, ("PMID:1", "a paraphrase"))
    ledger_rows(root, validate_corpus(root, ["item.yaml"], config(known_findings=LEDGER), missing_ledger_ok=True))
    record(root, ("PMID:1", "a paraphrase"), ("PMID:1", "another invention"))
    report = validate_corpus(root, ["item.yaml"], config(known_findings=LEDGER))
    assert exit_code(report, strict=True) == 2
    assert report["known_findings"]["SNIPPET_NOT_IN_SOURCE"] == 1


def test_a_repaired_finding_leaves_a_stale_entry_that_blocks(root):
    record(root, ("PMID:1", "a paraphrase"))
    ledger_rows(root, validate_corpus(root, ["item.yaml"], config(known_findings=LEDGER), missing_ledger_ok=True))
    record(root, ("PMID:1", "growth increased"))
    report = validate_corpus(root, ["item.yaml"], config(known_findings=LEDGER))
    assert report["verdicts"]["OK"] == 1
    assert len(report["stale_known_findings"]) == 1
    assert exit_code(report, strict=False) == 2


def test_moving_an_item_keeps_its_entry_but_editing_the_quote_does_not(root):
    record(root, ("PMID:1", "growth increased"), ("PMID:1", "a paraphrase"))
    ledger_rows(root, validate_corpus(root, ["item.yaml"], config(known_findings=LEDGER), missing_ledger_ok=True))
    record(root, ("PMID:1", "a paraphrase"), ("PMID:1", "growth increased"))
    assert exit_code(validate_corpus(root, ["item.yaml"], config(known_findings=LEDGER)), strict=True) == 0
    record(root, ("PMID:1", "a different paraphrase"), ("PMID:1", "growth increased"))
    report = validate_corpus(root, ["item.yaml"], config(known_findings=LEDGER))
    assert len(report["stale_known_findings"]) == 1
    assert report["known_findings"]["SNIPPET_NOT_IN_SOURCE"] == 0


def test_strict_only_findings_can_be_recorded(root):
    record(root, ("PMID:2", "no cache yet"), ("UniProtKB:P1", "a database line"))
    report = validate_corpus(root, ["item.yaml"], config(known_findings=LEDGER), missing_ledger_ok=True)
    assert exit_code(report, strict=True) == 2
    ledger_rows(root, report)
    report = validate_corpus(root, ["item.yaml"], config(known_findings=LEDGER))
    assert exit_code(report, strict=True) == 0
    assert report["known_findings"]["MISSING_CACHE"] == report["known_findings"]["UNSUPPORTED_REFERENCE"] == 1


def test_unreadable_record_entries_are_not_called_stale(root):
    record(root, ("PMID:1", "a paraphrase"))
    ledger_rows(root, validate_corpus(root, ["item.yaml"], config(known_findings=LEDGER), missing_ledger_ok=True))
    (root / "item.yaml").write_text("evidence: [\n")
    report = validate_corpus(root, ["item.yaml"], config(known_findings=LEDGER))
    assert report["errors"] and report["stale_known_findings"] == []
    assert exit_code(report, strict=True) == 2


HEADER = "record\treference\tverdict\tquote_sha256\tissue\n"
GOOD = f"item.yaml\tPMID:1\tSNIPPET_NOT_IN_SOURCE\t{'a' * 64}\t{ISSUE}\n"


@pytest.mark.parametrize("text", [
    "record\treference\tverdict\tissue\n",
    HEADER + GOOD.replace("SNIPPET_NOT_IN_SOURCE", "INVALID_EVIDENCE"),
    HEADER + GOOD.replace("SNIPPET_NOT_IN_SOURCE", "INVALID_CACHE"),
    HEADER + GOOD.replace(ISSUE, "HabitatMech#1"),
    HEADER + GOOD.replace("a" * 64, "A" * 64),
    HEADER + GOOD.replace("item.yaml", "../item.yaml"),
    HEADER + GOOD.replace("item.yaml", "/item.yaml"),
    HEADER + GOOD.replace("\tPMID:1\t", "\t\t"),
    HEADER + GOOD.replace("SNIPPET_NOT_IN_SOURCE", "MISSING_REFERENCE"),
    HEADER + GOOD.rstrip("\n") + "\textra\n",
])
def test_malformed_ledger_is_an_input_error(root, text):
    (root / "curation").mkdir()
    (root / LEDGER).write_text(text)
    with pytest.raises(EvidenceError):
        load_known_findings(root, LEDGER)
    (root / LEDGER).write_text(HEADER + GOOD + GOOD)
    assert len(load_known_findings(root, LEDGER)) == 2  # two occurrences, not a duplicate


def test_declared_ledger_must_exist_except_when_creating_it(root):
    record(root, ("PMID:1", "growth increased"))
    with pytest.raises(EvidenceError, match="missing"):
        validate_corpus(root, ["item.yaml"], config(known_findings=LEDGER))
    assert validate_corpus(root, ["item.yaml"], config(known_findings=LEDGER), missing_ledger_ok=True)["errors"] == []


def test_symlinked_ledger_is_refused(root, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    (outside / "ledger.tsv").write_text(HEADER)
    (root / "curation").mkdir()
    (root / LEDGER).symlink_to(outside / "ledger.tsv")
    with pytest.raises(EvidenceError, match="symlink"):
        load_known_findings(root, LEDGER)


def test_ledger_plan_keeps_owners_adds_new_and_drops_stale(root):
    record(root, ("PMID:1", "first paraphrase"), ("PMID:1", "second paraphrase"))
    report = validate_corpus(root, ["item.yaml"], config(known_findings=LEDGER), missing_ledger_ok=True)
    first = next(r for r in report["results"] if r["verdict"] == "SNIPPET_NOT_IN_SOURCE")
    write_known_findings(root, LEDGER, [KnownFinding(first["record"], first["reference"], first["verdict"],
                                                     first["quote_sha256"], OTHER_ISSUE),
                                        KnownFinding("item.yaml", "PMID:1", "SNIPPET_NOT_IN_SOURCE", "b" * 64, ISSUE)])
    report = validate_corpus(root, ["item.yaml"], config(known_findings=LEDGER))
    assert plan_known_findings(report, None)["unowned"]
    plan = plan_known_findings(report, ISSUE)
    assert (plan["kept"], plan["added"], plan["dropped"]) == (1, 1, 1)
    owners = {f.quote_sha256: f.issue for f in plan["rows"]}
    assert owners[first["quote_sha256"]] == OTHER_ISSUE
    with pytest.raises(EvidenceError):
        plan_known_findings(report, "not a url")


def test_quote_bearing_share_is_reported(root):
    (root / "item.yaml").write_text(
        "evidence:\n- reference: PMID:1\n  snippet: growth increased\n- reference: PMID:1\n- reference: PMID:1\n")
    report = validate_corpus(root, ["item.yaml"], config())
    assert (report["quote_bearing_items"], report["evidence_items"]) == (1, 3)
    assert "Quote-bearing items: 1 of 3 in-scope evidence items (33.3%)" in cli.quote_share(report)


# --- the ledger CLI ----------------------------------------------------------

def _stub_manifest(settings):
    capability = SimpleNamespace(is_enabled=True, settings=settings, reason=None)
    mech = SimpleNamespace(key="habitatmech", github="CultureBotAI/HabitatMech", record_globs=("item.yaml",),
                           capability=lambda name: capability)
    return SimpleNamespace(mechs={"habitatmech": mech})


def _git_repo(root):
    def git(*args):
        subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)
    git("init", "-q")
    git("config", "user.name", "Test")
    git("config", "user.email", "test@example.invalid")
    git("remote", "add", "origin", "https://github.com/CultureBotAI/HabitatMech.git")
    git("-c", "core.hooksPath=/dev/null", "commit", "--allow-empty", "-qm", "fixture")


def test_cli_records_known_findings_only_with_apply(root, monkeypatch, capsys, tmp_path_factory):
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(tmp_path_factory.mktemp("workspace")))
    _git_repo(root)
    record(root, ("PMID:1", "a paraphrase"))
    settings = {"cache_dir": "references_cache", "reference_fields": ["reference"],
                "snippet_fields": ["snippet"], "known_findings": LEDGER}
    monkeypatch.setattr(cli, "load_fleet_manifest", lambda: _stub_manifest(settings))
    base = ["--mech", "habitatmech", "--root", str(root)]
    assert cli.main([*base, "--strict"]) == 2  # declared ledger is missing
    assert cli.main([*base, "--record-known-findings"]) == 1  # dry run, unowned finding
    assert not (root / LEDGER).exists()
    assert cli.main([*base, "--record-known-findings", "--issue", ISSUE]) == 0
    assert not (root / LEDGER).exists()
    assert cli.main([*base, "--record-known-findings", "--issue", ISSUE, "--apply"]) == 0
    assert (root / LEDGER).stat().st_mode & 0o777 == 0o644
    assert cli.main([*base, "--strict"]) == 0
    report = json.loads((root / "workspace/reports/evidence_reference_validation.json").read_text())
    assert report["known_findings"]["SNIPPET_NOT_IN_SOURCE"] == 1
    assert "do not block" in (root / "workspace/reports/evidence_reference_validation.md").read_text()


def test_cli_refuses_to_record_without_a_declared_ledger(root, monkeypatch):
    _git_repo(root)
    record(root, ("PMID:1", "a paraphrase"))
    settings = {"cache_dir": "references_cache", "reference_fields": ["reference"], "snippet_fields": ["snippet"]}
    monkeypatch.setattr(cli, "load_fleet_manifest", lambda: _stub_manifest(settings))
    assert cli.main(["--mech", "habitatmech", "--root", str(root), "--record-known-findings",
                     "--issue", ISSUE, "--apply"]) == 2
    with pytest.raises(SystemExit):
        cli.main(["--mech", "habitatmech", "--root", str(root), "--apply"])


# --- review findings on #730 (#732 to #736, #738) ----------------------------

def test_a_missing_reference_finding_round_trips_through_the_ledger(root):
    """#732: the recorded row has an empty reference, and the loader accepts it."""
    (root / "item.yaml").write_text("evidence:\n- snippet: a quote with no citation\n")
    report = validate_corpus(root, ["item.yaml"], config(known_findings=LEDGER), missing_ledger_ok=True)
    assert report["verdicts"]["MISSING_REFERENCE"] == 1
    ledger_rows(root, report)
    assert "\t\tMISSING_REFERENCE\t" in (root / LEDGER).read_text()
    assert exit_code(validate_corpus(root, ["item.yaml"], config(known_findings=LEDGER)), strict=True) == 0


def test_a_quote_character_in_a_recorded_citation_round_trips(root):
    """#733: QUOTE_NONE with a quote character must neither crash nor alter the field."""
    citation = 'Smith J. "Iron uptake" J Bact 2020'
    (root / "item.yaml").write_text(f"evidence:\n- reference: '{citation}'\n  snippet: a line\n")
    report = validate_corpus(root, ["item.yaml"], config(known_findings=LEDGER), missing_ledger_ok=True)
    ledger_rows(root, report)
    assert [f.reference for f in load_known_findings(root, LEDGER)] == [citation]
    assert exit_code(validate_corpus(root, ["item.yaml"], config(known_findings=LEDGER)), strict=True) == 0


def test_each_row_excuses_one_occurrence(root):
    """#734: a copy of a recorded failing quote blocks until it is recorded too."""
    one = "evidence:\n- reference: PMID:1\n  snippet: invented\n"
    (root / "item.yaml").write_text(one)
    ledger_rows(root, validate_corpus(root, ["item.yaml"], config(known_findings=LEDGER), missing_ledger_ok=True))
    two = one + "other:\n  evidence:\n  - reference: PMID:1\n    snippet: invented\n"
    (root / "item.yaml").write_text(two)
    report = validate_corpus(root, ["item.yaml"], config(known_findings=LEDGER))
    assert report["known_findings"]["SNIPPET_NOT_IN_SOURCE"] == 1
    assert exit_code(report, strict=True) == 2
    ledger_rows(root, report)
    assert len(load_known_findings(root, LEDGER)) == 2
    assert exit_code(validate_corpus(root, ["item.yaml"], config(known_findings=LEDGER)), strict=True) == 0
    (root / "item.yaml").write_text(one)
    report = validate_corpus(root, ["item.yaml"], config(known_findings=LEDGER))
    assert len(report["stale_known_findings"]) == 1 and exit_code(report, strict=True) == 2


@pytest.mark.parametrize("value", [
    "https://www.doi.org/10.1000/abc", "doi.org/10.1000/abc", "DOI 10.1000/abc", "N/A", "PMID:1",
    "doi:10.1000/one", "",
])
def test_a_pmid_is_checked_exactly_as_before_whatever_its_doi_slot_holds(root, value):
    """#736: with MIM's profile, nothing in the doi slot changes a PMID-cited verdict."""
    for quote, verdict in (("growth increased", "OK"), ("yield doubled", "SNIPPET_NOT_IN_SOURCE")):
        result = check(root, {"pmid": "1", "doi": value, "snippet": quote,
                              "reference": "doi:10.1000/two"})
        assert (result.verdict, result.reference) == (verdict, "PMID:1")


@pytest.mark.parametrize(("citation", "doi"), [
    ("https://www.doi.org/10.1000/ABC", "10.1000/abc"),
    ("doi.org/10.1000/abc", "10.1000/abc"),
    ("www.doi.org/10.1000/abc", "10.1000/abc"),
    ("https://doi.org/10.1002/%28SICI%29", "10.1002/(sici)"),
    ("doi:10.1002/%28SICI%29", "10.1002/%28sici%29"),
    ("10.1002/%28SICI%29", "10.1002/%28sici%29"),
])
def test_only_resolver_urls_are_percent_decoded(citation, doi):
    assert normalize_doi(citation) == doi


def test_ledger_writer_refuses_tabs_and_line_breaks(root):
    for bad in ("a\tb", "a\nb", "a\rb"):
        with pytest.raises(EvidenceError, match="tabs or line breaks"):
            write_known_findings(root, LEDGER, [KnownFinding("item.yaml", bad, "UNSUPPORTED_REFERENCE",
                                                             "a" * 64, ISSUE)])
    assert not (root / LEDGER).exists()


def test_a_symlinked_ledger_directory_is_refused(root, tmp_path_factory):
    outside = tmp_path_factory.mktemp("outside")
    (outside / "evidence_known_findings.tsv").write_text(HEADER)
    (root / "curation").symlink_to(outside, target_is_directory=True)
    with pytest.raises(EvidenceError, match="symlink"):
        load_known_findings(root, LEDGER)
    with pytest.raises(EvidenceError, match="symlink"):
        write_known_findings(root, LEDGER, [])


def test_cli_reports_the_quote_bearing_share(root, monkeypatch, capsys):
    _git_repo(root)
    (root / "item.yaml").write_text(
        "evidence:\n- reference: PMID:1\n  snippet: growth increased\n- reference: PMID:1\n")
    settings = {"cache_dir": "references_cache", "reference_fields": ["reference"], "snippet_fields": ["snippet"]}
    monkeypatch.setattr(cli, "load_fleet_manifest", lambda: _stub_manifest(settings))
    assert cli.main(["--mech", "habitatmech", "--root", str(root), "--strict"]) == 0
    share = "Quote-bearing items: 1 of 2 in-scope evidence items (50.0%)"
    assert share in capsys.readouterr().out
    assert share in (root / "workspace/reports/evidence_reference_validation.md").read_text()


def test_cli_will_not_record_findings_while_a_record_is_unreadable(root, monkeypatch):
    _git_repo(root)
    record(root, ("PMID:1", "a paraphrase"))
    (root / "broken.yaml").write_text("evidence: [\n")
    settings = {"cache_dir": "references_cache", "reference_fields": ["reference"],
                "snippet_fields": ["snippet"], "known_findings": LEDGER}
    stub = _stub_manifest(settings)
    stub.mechs["habitatmech"].record_globs = ("*.yaml",)
    monkeypatch.setattr(cli, "load_fleet_manifest", lambda: stub)
    assert cli.main(["--mech", "habitatmech", "--root", str(root), "--record-known-findings",
                     "--issue", ISSUE, "--apply"]) == 2
    assert not (root / LEDGER).exists()


# --- second review on #730 (#743, #746, #747) --------------------------------

def _ledger_cli(root, monkeypatch, tmp_path_factory, *items):
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(tmp_path_factory.mktemp("workspace")))
    _git_repo(root)
    record(root, *items)
    settings = {"cache_dir": "references_cache", "reference_fields": ["reference"],
                "snippet_fields": ["snippet"], "known_findings": LEDGER}
    monkeypatch.setattr(cli, "load_fleet_manifest", lambda: _stub_manifest(settings))
    return ["--mech", "habitatmech", "--root", str(root), "--record-known-findings"]


def test_the_ledger_dry_run_fails_where_apply_would(root, monkeypatch, tmp_path_factory):
    """#743: a row the writer refuses fails the dry run too."""
    args = _ledger_cli(root, monkeypatch, tmp_path_factory)
    (root / "item.yaml").write_text('evidence:\n- reference: "Smith J.\\tIron uptake 2020"\n  snippet: a line\n')
    assert cli.main([*args, "--issue", ISSUE]) == 2
    assert cli.main([*args, "--issue", ISSUE, "--apply"]) == 2
    assert not (root / LEDGER).exists()


def test_apply_refuses_to_leave_a_current_finding_without_an_owner(root, monkeypatch, tmp_path_factory, capsys):
    """#743: --apply without --issue writes nothing while any finding is unowned."""
    args = _ledger_cli(root, monkeypatch, tmp_path_factory, ("PMID:1", "a paraphrase"))
    assert cli.main(args) == 1  # the dry run says so with exit 1
    assert cli.main([*args, "--apply"]) == 2
    assert "unrecorded" in capsys.readouterr().err
    assert not (root / LEDGER).exists()


class _Locks:
    """A LockManager stand-in that knows whether the repository lock is held now."""

    held_now = False
    taken: list[tuple[str, str]] = []

    def lock(self, resource, operation):
        import contextlib

        @contextlib.contextmanager
        def hold():
            _Locks.taken.append((resource, operation))
            _Locks.held_now = True
            try:
                yield
            finally:
                _Locks.held_now = False
        return hold()


def test_the_ledger_is_read_planned_and_written_under_one_lock(root, monkeypatch, tmp_path_factory):
    """#746/#748/#749: no concurrent update can land between the read and the write."""
    args = _ledger_cli(root, monkeypatch, tmp_path_factory, ("PMID:1", "a paraphrase"))
    seen: dict[str, list[bool]] = {"read": [], "write": []}
    validate, write = cli.validate_corpus, cli.write_known_findings

    def watched_validate(*a, **k):
        seen["read"].append(_Locks.held_now)
        return validate(*a, **k)

    def watched_write(*a, **k):
        seen["write"].append(_Locks.held_now)
        return write(*a, **k)
    monkeypatch.setattr(cli, "LockManager", _Locks)
    monkeypatch.setattr(cli, "validate_corpus", watched_validate)
    monkeypatch.setattr(cli, "write_known_findings", watched_write)
    _Locks.held_now, _Locks.taken = False, []
    assert cli.main([*args, "--issue", ISSUE]) == 0
    assert _Locks.taken == [] and seen == {"read": [False], "write": []}
    seen = {"read": [], "write": []}
    assert cli.main([*args, "--issue", ISSUE, "--apply"]) == 0
    assert _Locks.taken == [("habitatmech", "evidence-known-findings")]
    assert seen == {"read": [True], "write": [True]}


def test_a_held_ledger_lock_is_reported_and_nothing_is_written(root, monkeypatch, tmp_path_factory, capsys):
    """#748: the ledger CLI reports a busy lock instead of a traceback."""
    args = _ledger_cli(root, monkeypatch, tmp_path_factory, ("PMID:1", "a paraphrase"))

    class Busy:
        def lock(self, resource, operation):
            raise RuntimeError(f"Failed to acquire lock on {resource}")
    monkeypatch.setattr(cli, "LockManager", Busy)
    assert cli.main([*args, "--issue", ISSUE, "--apply"]) == 2
    assert "Failed to acquire lock" in capsys.readouterr().err
    assert not (root / LEDGER).exists()


def test_the_ledger_dry_run_fails_where_the_lock_setup_would(root, monkeypatch, tmp_path_factory):
    """#750: a symlinked lock workspace fails the dry run as it fails --apply."""
    args = _ledger_cli(root, monkeypatch, tmp_path_factory, ("PMID:1", "a paraphrase"))
    real = tmp_path_factory.mktemp("real-workspace")
    link = tmp_path_factory.mktemp("links") / "workspace"
    link.symlink_to(real, target_is_directory=True)
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(link))
    assert cli.main([*args, "--issue", ISSUE]) == 2
    assert cli.main([*args, "--issue", ISSUE, "--apply"]) == 2
    assert not (root / LEDGER).exists()


def test_the_writer_refuses_a_field_the_reader_cannot_read_back(root):
    """#747: csv's field-size limit applies to reading, so the writer enforces it."""
    import csv
    huge = "x" * (csv.field_size_limit() + 1)
    with pytest.raises(EvidenceError, match="longer than the ledger reader accepts"):
        write_known_findings(root, LEDGER, [KnownFinding("item.yaml", huge, "UNSUPPORTED_REFERENCE",
                                                         "a" * 64, ISSUE)])


# --- third review on #730 (#752) ---------------------------------------------

def test_a_lone_surrogate_fails_the_render_and_the_dry_run(root, monkeypatch, tmp_path_factory):
    """#752: the dry run fails where the UTF-8 write would."""
    with pytest.raises(EvidenceError, match="UTF-8"):
        write_known_findings(root, LEDGER, [KnownFinding("item.yaml", "Smith J. \ud800 2020",
                                                         "UNSUPPORTED_REFERENCE", "a" * 64, ISSUE)])
    args = _ledger_cli(root, monkeypatch, tmp_path_factory)
    (root / "item.yaml").write_text('evidence:\n- reference: "Smith J. \\ud800 2020"\n  snippet: a line\n')
    assert cli.main([*args, "--issue", ISSUE]) == 2
    assert cli.main([*args, "--issue", ISSUE, "--apply"]) == 2
    assert not (root / "curation").exists() or list((root / "curation").iterdir()) == []


def test_a_failed_ledger_write_leaves_no_temporary_file(root, monkeypatch):
    """#752: the leak happened when the stream write itself failed, so fail it there."""
    import kg_microbe_evidence as evidence

    monkeypatch.setattr(evidence, "render_known_findings", lambda rows: "header \ud800\n")
    with pytest.raises(UnicodeEncodeError):
        write_known_findings(root, LEDGER, [])
    assert list((root / "curation").iterdir()) == []


def test_a_failed_report_write_leaves_no_temporary_file(root):
    """#752: the existing report writer leaked the same way when the TSV write failed."""
    record(root, ("PMID:1", "growth increased"))
    report = validate_corpus(root, ["item.yaml"], config())
    report["results"][0]["reference"] = "PMID:1 \ud800"  # JSON escapes it; the TSV cannot
    output = root / "reports"
    with pytest.raises(UnicodeEncodeError):
        cli.write_reports(report, output)
    assert sorted(p.name for p in output.iterdir()) == ["evidence_reference_validation.json"]


# --- fourth review on #730 (#754, #755) --------------------------------------

def test_the_ledger_dry_run_fails_where_the_write_or_lock_would(root, monkeypatch, tmp_path_factory):
    """#754: an unwritable ledger directory or a refused lock setup fails both modes."""
    if os.geteuid() == 0:
        pytest.skip("root ignores directory permissions")
    args = _ledger_cli(root, monkeypatch, tmp_path_factory, ("PMID:1", "a paraphrase"))
    (root / "curation").mkdir()
    (root / "curation").chmod(0o555)
    try:
        assert cli.main([*args, "--issue", ISSUE]) == 2
        assert cli.main([*args, "--issue", ISSUE, "--apply"]) == 2
    finally:
        (root / "curation").chmod(0o755)
    filed = tmp_path_factory.mktemp("filed")
    (filed / "locks").write_text("not a directory")
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(filed))
    assert cli.main([*args, "--issue", ISSUE]) == 2
    assert cli.main([*args, "--issue", ISSUE, "--apply"]) == 2
    assert not (root / LEDGER).exists()


def test_plain_validation_never_needs_the_lock(root, monkeypatch, tmp_path_factory):
    """#755: the gate MIM's CI runs must not depend on the lock workspace."""
    _git_repo(root)
    record(root, ("PMID:1", "growth increased"))
    settings = {"cache_dir": "references_cache", "reference_fields": ["reference"], "snippet_fields": ["snippet"]}
    monkeypatch.setattr(cli, "load_fleet_manifest", lambda: _stub_manifest(settings))
    link = tmp_path_factory.mktemp("links") / "workspace"
    link.symlink_to(tmp_path_factory.mktemp("real"), target_is_directory=True)
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(link))

    def refuse(*args, **kwargs):
        raise RuntimeError("plain validation must not touch the lock")
    monkeypatch.setattr(cli, "LockManager", refuse)
    monkeypatch.setattr(cli, "check_lock_setup", refuse)
    assert cli.main(["--mech", "habitatmech", "--root", str(root), "--strict"]) == 0


# --- fifth review on #730 (#765) ---------------------------------------------

def test_a_ledger_dry_run_passes_once_a_ledger_exists(root, monkeypatch, tmp_path_factory):
    """#765: the dry run checks the ledger's directory, which an existing ledger file is not."""
    args = _ledger_cli(root, monkeypatch, tmp_path_factory, ("PMID:1", "a paraphrase"))
    assert cli.main([*args, "--issue", ISSUE, "--apply"]) == 0
    assert (root / LEDGER).is_file()
    assert cli.main(args) == 0


def test_a_missing_ledger_directory_under_an_unwritable_root_fails_both_modes(root, monkeypatch, tmp_path_factory):
    """#765: with no curation directory yet, the nearest existing ancestor decides."""
    if os.geteuid() == 0:
        pytest.skip("root ignores directory permissions")
    args = _ledger_cli(root, monkeypatch, tmp_path_factory, ("PMID:1", "a paraphrase"))
    assert cli.main([*args, "--issue", ISSUE]) == 0  # writable control; the dry run creates nothing
    assert not (root / "curation").exists()
    root.chmod(0o555)
    try:
        assert cli.main([*args, "--issue", ISSUE]) == 2
        assert cli.main([*args, "--issue", ISSUE, "--apply"]) == 2
    finally:
        root.chmod(0o755)
    assert not (root / "curation").exists()
