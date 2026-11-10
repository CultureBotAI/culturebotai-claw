# Historical review evidence: a Claude reviewer's probe for PR 897, rounds 7 and 8 (193cdc9955); findings in culturebotai-claw issues; paths inside name that reviewer's scratch directories, so a re-run at head may need them recreated.
"""Compare csv.DictReader (as taxa.py reads TaxonMech's TSVs) against a raw tab split on the real files; scope rank mix.
Inputs: TAXONMECH_ROOT. Outputs: printed observations. Written 2026-11-07 for the review of PR 897."""
import csv, os, sys
from pathlib import Path
root = Path(os.environ["TAXONMECH_ROOT"])
inv = root / "data/raw/ncbitaxon_taxa.tsv"; scope = root / "curation/seed_scope.tsv"
# raw rows with a double quote
n = 0
with inv.open(encoding="utf-8") as h:
    header = h.readline().rstrip("\n").split("\t")
    raw = {}
    for line in h:
        cells = line.rstrip("\n").split("\t")
        raw[cells[0]] = cells
        if '"' in line and n < 6:
            n += 1; print("RAW quote row:", repr(line.rstrip("\n"))[:200])
print("header:", header)
# how csv parses them
diff = 0; examples = []
with inv.open(encoding="utf-8") as h:
    reader = csv.DictReader(h, delimiter="\t")
    csv_rows = 0
    for row in reader:
        csv_rows += 1
        r = raw.get(row["taxon_id"])
        if r is None or [row[c] for c in header] != r:
            diff += 1
            if len(examples) < 5: examples.append((row["taxon_id"], row["label"], r[1] if r else None))
print(f"inventory raw rows {len(raw)}, csv rows {csv_rows}, rows where csv differs from a raw split: {diff}")
for e in examples: print("  csv vs raw:", e)
# scope quotes
with scope.open(encoding="utf-8") as h:
    sh = h.readline().rstrip("\n").split("\t"); print("scope header:", sh)
    for line in h:
        if '"' in line: print("SCOPE quote row:", repr(line.rstrip("\n"))[:200])
with scope.open(encoding="utf-8") as h:
    srows = list(csv.DictReader(h, delimiter="\t"))
print("scope csv rows:", len(srows))
ids = {r["identifier"] for r in srows}
from collections import Counter
ranks = Counter(raw[i][2].lower() if i in raw else "NOT_IN_INVENTORY" for i in ids)
print("scope rank mix:", ranks.most_common(12))
# scope members whose parent chain holds another scope member (nested records), by rank
parent = {c[0]: c[3] for c in raw.values()}
nested = Counter()
for i in ids:
    p = parent.get(i)
    while p and p in raw:
        if p in ids: nested[raw[i][2].lower()] += 1; break
        p = parent.get(p)
print("scope members with a scope ancestor, by rank:", nested.most_common(8))
