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
     " if key not in matched and f.record not in unreadable]",
     " if key not in matched]",
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
