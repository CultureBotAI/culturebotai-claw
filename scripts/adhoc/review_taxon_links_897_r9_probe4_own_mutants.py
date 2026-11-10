# Historical review evidence: a Claude reviewer's probe for PR 897, round 9 (c8e3fc7a15); findings in culturebotai-claw issues; paths inside name that reviewer's scratch directories, so a re-run at head may need them recreated.
"""Probe 4 for PR 897 round 9 (review scratch, 2026-11-07): reviewer's own mutants against the round-9 code.
Each entry edits src/kg_microbe_links/taxa.py in the review worktree, runs the named test(s) in a fresh pytest
process with a timeout, and restores the file. Inputs: the worktree. Outputs: one line per mutant.
Run only when nothing else uses the worktree (the runner also mutates this file in place)."""
import subprocess, sys, time
from pathlib import Path
ROOT = Path("/Users/marcin/agent-work/culturebotai-claw/review897r9")
TAXA = ROOT / "src/kg_microbe_links/taxa.py"
UNIT = "tests/test_taxon_links.py"
TIMEOUT = 60
SHORT = f"{UNIT}::test_a_malformed_taxonmech_tsv_is_refused_not_a_traceback[data/raw/ncbitaxon_taxa.tsv-taxon_id\\tlabel\\trank\\tparent_id\\nNCBITaxon:1423\\tBacillus subtilis\\n-row 2 has a different number of cells than the header]"
LONG = f"{UNIT}::test_a_malformed_taxonmech_tsv_is_refused_not_a_traceback[data/raw/ncbitaxon_taxa.tsv-taxon_id\\tlabel\\trank\\tparent_id\\nNCBITaxon:1423\\tBacillus subtilis\\tSPECIES\\tNCBITaxon:1386\\textra\\n-row 2 has a different number of cells than the header]"
MUTANTS = [
    ("M3b cycle detected only when the walk returns to its start", "                if taxon in on_path:\n", "                if path and taxon == start:\n", UNIT),
    ("M9 point walked ids at the last merged id, not the end", "                merged[walked] = taxon  # the end", "                merged[walked] = path[-1]  # the end", UNIT),
]
original = TAXA.read_text(encoding="utf-8")
try:
    for name, before, after, test in MUTANTS:
        assert original.count(before) == 1, (name, original.count(before))
        TAXA.write_text(original.replace(before, after), encoding="utf-8")
        started = time.perf_counter()
        try:
            r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-x", "-rfE", test], cwd=ROOT, capture_output=True, text=True, timeout=TIMEOUT)
            rc, tail = r.returncode, ' | '.join(l for l in r.stdout.splitlines() if l.startswith(('FAILED', 'ERROR')) or 'passed' in l or 'failed' in l)
        except subprocess.TimeoutExpired:
            rc, tail = "TIMEOUT", f"no result within {TIMEOUT} s"
        finally:
            TAXA.write_text(original, encoding="utf-8")
        verdict = "SURVIVED" if rc == 0 else "KILLED  "
        print(f"{verdict} {name:52s} rc={rc} {time.perf_counter() - started:5.1f}s  {tail[:110]}")
finally:
    TAXA.write_text(original, encoding="utf-8")
