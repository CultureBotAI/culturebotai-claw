# Historical review evidence: a Claude reviewer's probe for PR 897, rounds 7 and 8 (193cdc9955); findings in culturebotai-claw issues; paths inside name that reviewer's scratch directories, so a re-run at head may need them recreated.
"""Measure the memory the 'merge cycle not refused' mutant reaches before the runner's timeout: apply the mutant in a
disposable worktree, run the self-map test with a 20 s limit, report the child's max RSS, restore the source.
Inputs: worktree path. Outputs: printed RSS. Written 2026-11-07 for the review of PR 897."""
import resource, subprocess, sys, time
from pathlib import Path
WT = Path(sys.argv[1]); TAXA = WT / "src/kg_microbe_links/taxa.py"
original = TAXA.read_text(encoding="utf-8")
before, after = "                if state.get(taxon) == 1:\n", "                if False:\n"
assert original.count(before) == 1
test = "tests/test_taxon_links.py::test_a_self_mapping_or_cyclic_merge_table_is_refused[old_taxon_id\\tcurrent_taxon_id\\nNCBITaxon:562\\tNCBITaxon:562\\n]"
try:
    TAXA.write_text(original.replace(before, after), encoding="utf-8")
    t0 = time.perf_counter()
    try:
        subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", test], cwd=WT, capture_output=True, text=True, timeout=20)
        print("finished within 20 s (unexpected)")
    except subprocess.TimeoutExpired:
        print(f"timed out after {time.perf_counter() - t0:.0f} s, as the runner's rule expects")
    rss = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    print(f"child max RSS after 20 s: {rss / 2**30:.2f} GiB (the runner allows 120 s)")
finally:
    TAXA.write_text(original, encoding="utf-8")
