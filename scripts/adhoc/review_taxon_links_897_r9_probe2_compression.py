# Historical review evidence: a Claude reviewer's probe for PR 897, round 9 (c8e3fc7a15); findings in culturebotai-claw issues; paths inside name that reviewer's scratch directories, so a re-run at head may need them recreated.
"""Probe 2 for PR 897 round 9 (review scratch, 2026-11-07): _read_merged's chain compression.
Shapes: chain in forward/reverse/shuffled order, two chains sharing a tail, a chain into a cycle, a self-map,
a star onto one node, a chain into a cycle not through its start. Checks the end-only invariant and counts
loop steps to show linearity per row order. Inputs: none. Outputs: one line per case."""
import random, sys, tempfile
from pathlib import Path
sys.path.insert(0, "/Users/marcin/agent-work/culturebotai-claw/review897r9/src")
from kg_microbe_links import taxa as links

def build(pairs):
    root = Path(tempfile.mkdtemp(dir="/Users/marcin/agent-work/culturebotai-claw/review897r9-scratch"))
    p = root / links.MERGED_PATH; p.parent.mkdir(parents=True)
    p.write_text("old_taxon_id\tcurrent_taxon_id\n" + "".join(f"NCBITaxon:{a}\tNCBITaxon:{b}\n" for a, b in pairs), encoding="utf-8")
    idx = links.TaxonIndex.__new__(links.TaxonIndex); idx.root = root
    return idx

def run(name, pairs, expect=None):
    idx = build(pairs)
    try:
        merged = idx._read_merged()
    except links.TaxonLinksError as e:
        print(f"{name:48s} REFUSED {e}"); return
    end_only = all(v not in merged for v in merged.values())
    ok = (expect is None or merged == expect)
    print(f"{name:48s} {'OK ' if ok and end_only else 'BAD'} end_only={end_only} {merged if len(merged) < 12 else str(len(merged)) + ' entries'}")

run("two-hop forward (a->b, b->c)", [(1, 2), (2, 3)], {1: 3, 2: 3})
run("two-hop reverse (b->c, a->b)", [(2, 3), (1, 2)], {1: 3, 2: 3})
run("three-hop middle-first", [(2, 3), (1, 2), (3, 4)], {1: 4, 2: 4, 3: 4})
run("two chains sharing a tail", [(1, 3), (2, 3), (3, 4)], {1: 4, 2: 4, 3: 4})
run("two chains sharing a tail, tail first", [(3, 4), (1, 3), (2, 3)], {1: 4, 2: 4, 3: 4})
run("star onto one merged node", [(i, 100) for i in range(1, 6)] + [(100, 200)], {**{i: 200 for i in range(1, 6)}, 100: 200})
run("self-map", [(5, 5)])
run("self-map after a chain into it", [(1, 2), (2, 5), (5, 5)])
run("2-cycle", [(7, 8), (8, 7)])
run("chain into a cycle not through the start", [(1, 2), (2, 3), (3, 4), (4, 2)])
run("cycle listed after a chain into it", [(9, 1), (1, 2), (2, 3), (3, 1)])
run("duplicate old id (last wins, dict comp)", [(1, 2), (1, 3)], {1: 3})
run("no rows", [], {})

# Linearity: count while-loop iterations for a 200,000 chain under three orders, by instrumenting a copy of the loop.
def steps(pairs):
    merged = dict(pairs); count = 0
    for start in merged:
        path = []; on_path = set(); taxon = start
        while taxon in merged:
            count += 1
            if taxon in on_path: raise RuntimeError("cycle")
            on_path.add(taxon); path.append(taxon); taxon = merged[taxon]
        for w in path: merged[w] = taxon
    assert all(v not in merged for v in merged.values())
    return count
n = 200_000
fwd = [(i, i + 1) for i in range(n)]
rev = list(reversed(fwd))
shuf = fwd[:]; random.Random(7).shuffle(shuf)
for label, pairs in (("forward", fwd), ("reverse", rev), ("shuffled", shuf)):
    print(f"200,000-link chain, {label:8s} order: {steps(pairs):,} loop steps (n={n:,})")
