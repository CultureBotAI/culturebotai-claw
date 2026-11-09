# Historical review evidence: a Claude reviewer's probe for PR 897, round 9 (c8e3fc7a15); findings in culturebotai-claw issues; paths inside name that reviewer's scratch directories, so a re-run at head may need them recreated.
"""Probe 3 for PR 897 round 9 (review scratch, 2026-11-07): judge() as one lookup on a compressed 200,000-link chain.
Measures the chain read, the first judgement, and 2,000 / 200,000 consecutive citations, in this fresh process,
against the unit-test fixture shape (a scratch TaxonMech with a small real tarball). Inputs: none. Outputs: timings."""
import io, sys, tarfile, time, tempfile
from pathlib import Path
sys.path.insert(0, "/Users/marcin/agent-work/culturebotai-claw/review897r9/src")
from kg_microbe_links import taxa as links

root = Path(tempfile.mkdtemp(dir="/Users/marcin/agent-work/culturebotai-claw/review897r9-scratch")) / "TaxonMech"
for d in ("curation", "data/raw", "conf", "data/source_snapshots"): (root / d).mkdir(parents=True)
(root / "curation/seed_scope.tsv").write_text("identifier\nNCBITaxon:562\n")
(root / "data/raw/ncbitaxon_taxa.tsv").write_text("taxon_id\tlabel\trank\tparent_id\nNCBITaxon:1\troot\tNO_RANK\t\nNCBITaxon:562\tEscherichia coli\tSPECIES\tNCBITaxon:1\n")
def dmp(rows): return "".join("\t|\t".join(r) + "\t|\n" for r in rows).encode()
with tarfile.open(root / "data/source_snapshots/taxdump.tar.gz", "w:gz") as tar:
    for member, payload in (("nodes.dmp", dmp([["1", "1", "no rank"], ["562", "1", "species"]])), ("names.dmp", dmp([["1", "root", "", "scientific name"]]))):
        info = tarfile.TarInfo(member); info.size = len(payload); tar.addfile(info, io.BytesIO(payload))
(root / "conf/ncbi_taxdump.yaml").write_text("path: data/source_snapshots/taxdump.tar.gz\n")
n = 200_000
(root / "data/raw/ncbi_merged_ids.tsv").write_text("old_taxon_id\tcurrent_taxon_id\n" + "".join(f"NCBITaxon:{i}\tNCBITaxon:{i + 1}\n" for i in range(10_000_000, 10_000_000 + n)))

t = time.perf_counter(); index = links.TaxonIndex(root); t_read = time.perf_counter() - t
assert all(v == 10_000_000 + n for v in index.merged.values())
t = time.perf_counter(); j = index.judge("NCBITaxon:10000000"); t_first = time.perf_counter() - t  # includes the lazy taxdump read
assert (j.verdict, j.current, j.current_verdict) == (links.Verdict.RETIRED, 10_000_000 + n, links.Verdict.ABSENT)
t = time.perf_counter()
for i in range(10_000_000, 10_002_000): assert index.judge(f"NCBITaxon:{i}").current == 10_000_000 + n
t_2000 = time.perf_counter() - t
t = time.perf_counter()
for i in range(10_000_000, 10_000_000 + n): index.judge(f"NCBITaxon:{i}")
t_all = time.perf_counter() - t
print(f"read 200,000-link chain: {t_read:.3f} s; first judgement (lazy taxdump): {t_first:.4f} s; 2,000 citations: {t_2000:.4f} s (bound 5 s); 200,000 citations: {t_all:.3f} s")
