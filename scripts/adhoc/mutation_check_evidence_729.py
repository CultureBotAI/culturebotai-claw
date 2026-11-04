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
