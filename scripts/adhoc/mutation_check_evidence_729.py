#!/usr/bin/env python3
"""Mutation checks for the #729 evidence tooling tests (read-only on success).

Purpose: prove each new regression test kills the defect it names. Each
mutation replaces one exact source fragment, runs the named tests in a fresh
pytest process, requires them to FAIL, then restores the file byte-for-byte.
Inputs: this checkout's src/ and tests/. Outputs: a pass/fail line per mutation;
exit 1 if any mutation survives or any fragment is not found.
Serves: culturebotai-claw#729. Written 2026-11-03.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = "src/kg_microbe_evidence/__init__.py"
FETCH = "src/kg_microbe_evidence/fetch.py"
MAIN = "src/kg_microbe_evidence/__main__.py"
LEDGER_TESTS = "tests/test_evidence_doi_and_ledger.py"
FETCH_TESTS = "tests/test_evidence_fetch.py"

MUTATIONS = [
    ("DOI takes precedence over PMID", EVIDENCE,
     "        if pmids:\n            kind, identifier = \"PMID\", next(iter(pmids))\n        elif len(dois) > 1:",
     "        if dois and len(dois) == 1:\n            kind, identifier = \"DOI\", next(iter(dois))\n        elif pmids:\n            kind, identifier = \"PMID\", next(iter(pmids))\n        elif len(dois) > 1:",
     f"{LEDGER_TESTS}::test_pmid_keeps_precedence_over_a_doi"),
    ("DOI cache header identity unchecked", EVIDENCE,
     "(named != identifier if kind == \"PMID\" else normalize_doi(named) != identifier)",
     "(named != identifier if kind == \"PMID\" else False)",
     f"{LEDGER_TESTS}::test_doi_cache_must_name_the_cited_doi"),
    ("ledger key ignores the quote hash", EVIDENCE,
     "        return (self.record, self.reference, self.verdict, self.quote_sha256)",
     "        return (self.record, self.reference, self.verdict, \"\")",
     f"{LEDGER_TESTS}::test_moving_an_item_keeps_its_entry_but_editing_the_quote_does_not"),
    ("stale entries do not block", EVIDENCE,
     "    return 2 if (report[\"errors\"] or report.get(\"stale_known_findings\")",
     "    return 2 if (report[\"errors\"]",
     f"{LEDGER_TESTS}::test_a_repaired_finding_leaves_a_stale_entry_that_blocks"),
    ("recorded findings still block", EVIDENCE,
     "    unrecorded = Counter(row[\"verdict\"] for row in report[\"results\"] if not row.get(\"known_issue\"))",
     "    unrecorded = Counter(row[\"verdict\"] for row in report[\"results\"])",
     f"{LEDGER_TESTS}::test_a_recorded_finding_stops_blocking_and_is_counted_apart"),
    ("unreadable records' entries called stale", EVIDENCE,
     " for f in available[key] if f.record not in unreadable]",
     " for f in available[key]]",
     f"{LEDGER_TESTS}::test_unreadable_record_entries_are_not_called_stale"),
    ("broken-input verdicts can be recorded", EVIDENCE,
     "KNOWN_FINDING_VERDICTS = frozenset({\n    \"MISSING_REFERENCE\",",
     "KNOWN_FINDING_VERDICTS = frozenset({\n    \"INVALID_EVIDENCE\", \"INVALID_CACHE\", \"MISSING_REFERENCE\",",
     f"{LEDGER_TESTS}::test_malformed_ledger_is_an_input_error"),
    ("fetched record trusted without its own PMID", FETCH,
     "            found.update({pmid: a for pmid, a in articles.items() if pmid in chunk})",
     "            found.update({c: a for c, a in zip(chunk, articles.values())})",
     f"{FETCH_TESTS}::test_a_record_for_another_pmid_is_never_written_under_the_requested_one"),
    ("DOI accepted without the record listing it", FETCH,
     "            elif doi not in article.dois:",
     "            elif False:",
     f"{FETCH_TESTS}::test_doi_is_accepted_only_from_a_record_that_lists_it"),
    # The early existence check is only a shortcut; os.link is what refuses to
    # replace a file that appears after it, so that is the guard to mutate.
    ("concurrently created cache replaced", FETCH,
     "            os.link(temporary, target)  # fails rather than replacing a concurrent file",
     "            os.replace(temporary, target)",
     f"{FETCH_TESTS}::test_a_cache_created_after_the_check_is_not_replaced"),
    ("no-abstract record written", FETCH,
     "    if not article.paragraphs:\n        return None",
     "    if not article.paragraphs:\n        article = Article(article.pmid, article.title, article.authors, article.journal, article.year, ('(No abstract)',), article.dois)",
     f"{FETCH_TESTS}::test_written_pmid_cache_is_read_back_by_the_gate"),
    ("API key leaks into the failure message", FETCH,
     "                    raise OSError(f\"{url} failed after {ATTEMPTS} attempts: {type(exc).__name__}\") from None",
     "                    raise OSError(f\"{url} failed after {ATTEMPTS} attempts: {params}\") from None",
     f"{FETCH_TESTS}::test_failure_after_retries_reports_partial_work_without_the_key"),
    # Round 2: fixes for the review findings #732-#740.
    ("#732 MISSING_REFERENCE rows rejected again", EVIDENCE,
     'if (finding.verdict == "MISSING_REFERENCE") != (finding.reference == ""):',
     'if not finding.reference:',
     f"{LEDGER_TESTS}::test_a_missing_reference_finding_round_trips_through_the_ledger"),
    ("#733 default quotechar restored", EVIDENCE,
     'quoting=csv.QUOTE_NONE, quotechar=None, lineterminator=',
     'quoting=csv.QUOTE_NONE, lineterminator=',
     f"{LEDGER_TESTS}::test_a_quote_character_in_a_recorded_citation_round_trips"),
    ("#734 one row excuses every copy", EVIDENCE,
     "        finding = queue.pop(0) if queue else None",
     "        finding = queue[0] if queue else None",
     f"{LEDGER_TESTS}::test_each_row_excuses_one_occurrence"),
    ("#736 doi slot beside a PMID is INVALID again", EVIDENCE,
     "            doi = normalize_doi(ref)\n            if doi is not None:",
     "            doi = normalize_doi(ref)\n            if field == \"doi\" and doi is None:\n                return QuoteResult(\"INVALID_EVIDENCE\", detail=\"doi\", quote_sha256=quote_hash)\n            if doi is not None:",
     f"{LEDGER_TESTS}::test_a_pmid_is_checked_exactly_as_before_whatever_its_doi_slot_holds"),
    ("#736 resolver URL not percent-decoded", EVIDENCE,
     "        text = urllib.parse.unquote(text[resolver.end():])",
     "        text = text[resolver.end():]",
     f"{LEDGER_TESTS}::test_only_resolver_urls_are_percent_decoded"),
    ("#737 no pause between requests", FETCH,
     "            if self.requests:\n                self.sleep(self.pause)",
     "            if False:\n                self.sleep(self.pause)",
     f"{FETCH_TESTS}::test_successive_requests_are_spaced_at_ncbis_published_rate"),
    ("#738 plan fetches every cited source", FETCH,
     '        if row["verdict"] == "MISSING_CACHE":',
     '        if row["verdict"] != "NO_QUOTE":',
     f"{FETCH_TESTS}::test_the_plan_is_exactly_the_gates_missing_caches"),
    ("#738 reference-list DOIs accepted", FETCH,
     'node.findall("PubmedData/ArticleIdList/ArticleId")',
     'node.findall(".//ArticleId")',
     f"{FETCH_TESTS}::test_a_doi_in_the_records_reference_list_is_not_its_own"),
    ("#738 fetch CLI exits 0 on FetchError", FETCH,
     "            outcome, code = exc.partial, 1",
     "            outcome, code = exc.partial, 0",
     f"{FETCH_TESTS}::test_cli_exits_one_when_requests_fail"),
    ("#738 fetch CLI accepts unreadable records", FETCH,
     '            raise EvidenceError(f"{len(report[\'errors\'])} records could not be read; the plan would be incomplete")',
     '            pass',
     f"{FETCH_TESTS}::test_cli_refuses_unreadable_records"),
    ("#738 fetcher writes through a symlinked parent", FETCH,
     "    if any(p.is_symlink() for p in (cache, *cache.parents) if p != root and p.is_relative_to(root)):",
     "    if cache.is_symlink():",
     f"{FETCH_TESTS}::test_cli_refuses_to_write_through_a_symlinked_parent"),
    ("#738 PubMed URL dropped from caches", FETCH,
     'lines.append(f"**Source:** PubMed https://pubmed.ncbi.nlm.nih.gov/{article.pmid}/, "',
     'lines.append(f"**Source:** PubMed, "',
     f"{FETCH_TESTS}::test_written_pmid_cache_is_read_back_by_the_gate"),
    ("#738 ledger written despite unreadable records", MAIN,
     '        raise EvidenceError(f"{len(report[\'errors\'])} records could not be read; fix them before recording findings")',
     '        pass',
     f"{LEDGER_TESTS}::test_cli_will_not_record_findings_while_a_record_is_unreadable"),
    ("#738 retmax 1 hides ambiguity", FETCH,
     '"retmode": "json", "retmax": "2"}',
     '"retmode": "json", "retmax": "1"}',
     f"{FETCH_TESTS}::test_doi_is_accepted_only_from_a_record_that_lists_it"),
    ("#738 writer accepts tabs and breaks", EVIDENCE,
     '        if any(re.search(r"[\\t\\r\\n]", value) for value in values):\n            raise EvidenceError("known finding fields must not contain tabs or line breaks")',
     '        if False:\n            raise EvidenceError("known finding fields must not contain tabs or line breaks")',
     f"{LEDGER_TESTS}::test_ledger_writer_refuses_tabs_and_line_breaks"),
    ("#738 ledger symlink check ignores parents", EVIDENCE,
     "    if any(part.is_symlink() for part in (path, *path.parents) if part != root and part.is_relative_to(root)):",
     "    if path.is_symlink():",
     f"{LEDGER_TESTS}::test_a_symlinked_ledger_directory_is_refused"),
    ("#738 quote share missing from the report", MAIN,
     "             quote_share(report),\n",
     "",
     f"{LEDGER_TESTS}::test_cli_reports_the_quote_bearing_share"),
    ("#739 malformed search reply read as no match", FETCH,
     "            ids = _search_ids(payload)",
     '            ids = (json.loads(payload).get("esearchresult") or {}).get("idlist") or [] if isinstance(json.loads(payload), dict) else []',
     f"{FETCH_TESTS}::test_a_malformed_search_reply_stops_with_the_partial_result"),
    ("#740 limit hides what is missing", FETCH,
     "    result = FetchResult(missing_pmids=missing_pmids, missing_dois=missing_dois,",
     "    result = FetchResult(missing_pmids=pmids, missing_dois=dois,",
     f"{FETCH_TESTS}::test_limit_is_a_canary_that_still_reports_everything_missing"),
    # Round 3: fixes for the second review's findings #742-#747.
    ("#742 summary prints only this run's plan", FETCH,
     "{len(outcome['missing_pmids'])} PMIDs and \"\n          f\"{len(outcome['missing_dois'])} DOIs lack a cache",
     "{len(outcome['planned_pmids'])} PMIDs and \"\n          f\"{len(outcome['planned_dois'])} DOIs lack a cache",
     f"{FETCH_TESTS}::test_cli_prints_everything_missing_beside_what_a_limited_run_covers"),
    ("#743 ledger dry run skips the render", MAIN,
     '    render_known_findings(plan["rows"])  # a row the writer would refuse fails the dry run too\n',
     "",
     f"{LEDGER_TESTS}::test_the_ledger_dry_run_fails_where_apply_would"),
    ("#743 --json directory accepted", FETCH,
     "(not args.json.parent.is_dir() or args.json.is_dir())",
     "(not args.json.parent.is_dir())",
     f"{FETCH_TESTS}::test_cli_refuses_a_json_destination_that_is_a_directory"),
    ("#743 --json write unguarded", FETCH,
     "        except OSError as exc:\n            print(f\"evidence fetch: could not write {args.json}: {exc}\", file=sys.stderr)\n            return max(code, 2)",
     "        except KeyError as exc:\n            print(f\"evidence fetch: could not write {args.json}: {exc}\", file=sys.stderr)\n            return max(code, 2)",
     f"{FETCH_TESTS}::test_cli_reports_an_unwritable_json_destination_without_a_traceback"),
    ("#743 ledger written with unowned findings", MAIN,
     '    if plan["unowned"]:\n        raise EvidenceError("refusing to write a ledger that leaves current findings unrecorded")',
     '    if False:\n        raise EvidenceError("refusing to write a ledger that leaves current findings unrecorded")',
     f"{LEDGER_TESTS}::test_apply_refuses_to_leave_a_current_finding_without_an_owner"),
    ("#743 non-string search ids accepted", FETCH,
     "any(not isinstance(i, str) or not i.isdigit() for i in ids)",
     "any(not str(i).isdigit() for i in ids)",
     f"{FETCH_TESTS}::test_a_non_string_search_id_is_malformed"),
    ("#744 limit spent on PMIDs first", FETCH,
     "        reserve = min(len(dois), max(1, limit // 2)) if dois and pmids else 0",
     "        reserve = 0",
     f"{FETCH_TESTS}::test_a_limited_canary_covers_a_doi_whenever_one_is_pending"),
    ("#745 dry run returns before checking the destination", FETCH,
     "    cache = _cache_root(root, config, create=False)\n    if not apply:\n        return result",
     "    if not apply:\n        return result\n    cache = _cache_root(root, config, create=False)",
     f"{FETCH_TESTS}::test_cli_refuses_to_write_through_a_symlinked_parent"),
    ("#746 fetch writes without the repository lock", FETCH,
     '                with LockManager().lock(mech.key, "evidence-fetch"):\n                    result = run()',
     '                if True:\n                    result = run()',
     f"{FETCH_TESTS}::test_cli_holds_the_repository_lock_only_while_applying"),
    ("#746 ledger written without the repository lock", MAIN,
     '            with LockManager().lock(mech.key, "evidence-known-findings"):\n',
     "            if True:\n",
     f"{LEDGER_TESTS}::test_the_ledger_is_read_planned_and_written_under_one_lock"),
    ("#747 oversized field written", EVIDENCE,
     "        if any(len(value) > csv.field_size_limit() for value in values):",
     "        if False:",
     f"{LEDGER_TESTS}::test_the_writer_refuses_a_field_the_reader_cannot_read_back"),
    # Round 4: fixes for the third review's findings #748-#752.
    ("#748/#749 fetch plans and writes outside the lock", FETCH,
     '                with LockManager().lock(mech.key, "evidence-fetch"):\n                    result = run()',
     '                with LockManager().lock(mech.key, "evidence-fetch"):\n                    pass\n                result = run()',
     f"{FETCH_TESTS}::test_cli_holds_the_repository_lock_only_while_applying"),
    ("#749 ledger read outside the lock", MAIN,
     '            with LockManager().lock(mech.key, "evidence-known-findings"):\n                report = validated()\n',
     '            report = validated()\n            with LockManager().lock(mech.key, "evidence-known-findings"):\n',
     f"{LEDGER_TESTS}::test_the_ledger_is_read_planned_and_written_under_one_lock"),
    ("#748 ledger CLI raises a held lock", MAIN,
     "OSError, ValueError,\n            RuntimeError) as exc:  # RuntimeError: the repository lock is held elsewhere\n        print(f\"evidence validation:",
     "OSError, ValueError) as exc:\n        print(f\"evidence validation:",
     f"{LEDGER_TESTS}::test_a_held_ledger_lock_is_reported_and_nothing_is_written"),
    ("#750 fetch dry run skips the lock setup", FETCH,
     "                    resolve_workspace_root()  # the dry run fails where --apply's lock would (#750)\n",
     "",
     f"{FETCH_TESTS}::test_a_dry_run_fails_where_the_lock_setup_would"),
    ("#750 ledger dry run skips the lock setup", MAIN,
     "            resolve_workspace_root()  # the dry run fails where --apply's lock would (#750)\n",
     "",
     f"{LEDGER_TESTS}::test_the_ledger_dry_run_fails_where_the_lock_setup_would"),
    ("#751 zero limit accepted", FETCH,
     "    if limit is not None and limit < 1:\n",
     "    if limit is not None and limit < 0:\n",
     f"{FETCH_TESTS}::test_a_limit_below_one_is_refused"),
    ("#752 render does not encode", EVIDENCE,
     '        text.encode("utf-8")  # e.g. a lone surrogate from a YAML escape (#752)',
     '        pass',
     f"{LEDGER_TESTS}::test_a_lone_surrogate_fails_the_render_and_the_dry_run"),
    ("#752 ledger write leaks its temporary file", EVIDENCE,
     '    try:  # no temporary file survives a failed write (#752)\n        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:\n            stream.write(text)\n        os.chmod(temporary, 0o644)',
     '    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:\n        stream.write(text)\n    try:\n        os.chmod(temporary, 0o644)',
     f"{LEDGER_TESTS}::test_a_failed_ledger_write_leaves_no_temporary_file"),
    ("#752 report write leaks its temporary file", MAIN,
     '        try:  # no temporary file survives a failed write (#752)\n            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:\n                stream.write(text)\n            os.replace(temporary, target)',
     '        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:\n            stream.write(text)\n        try:\n            os.replace(temporary, target)',
     f"{LEDGER_TESTS}::test_a_failed_report_write_leaves_no_temporary_file"),
]


def main() -> int:
    survived = 0
    for name, relative, old, new, test in MUTATIONS:
        path = ROOT / relative
        original = path.read_bytes()
        text = original.decode("utf-8")
        if text.count(old) != 1:
            print(f"MISSING  {name}: fragment found {text.count(old)} times")
            survived += 1
            continue
        try:
            path.write_text(text.replace(old, new), encoding="utf-8")
            result = subprocess.run([sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", test],
                                    cwd=ROOT, capture_output=True, text=True)
        finally:
            path.write_bytes(original)
        killed = result.returncode != 0
        survived += not killed
        print(f"{'killed  ' if killed else 'SURVIVED'} {name}")
    return 1 if survived else 0


if __name__ == "__main__":
    raise SystemExit(main())
