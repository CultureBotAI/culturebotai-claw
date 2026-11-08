# Historical review evidence: a Claude reviewer's probe for PR 897, rounds 7 and 8 (193cdc9955); findings in culturebotai-claw issues; paths inside name that reviewer's scratch directories, so a re-run at head may need them recreated.
"""Reviewer's own mutants against PR 897 rounds 7-8 (head 193cdc9955): patch one line in a disposable worktree, run both
taxon-links test files in a fresh pytest process, restore. Inputs: worktree path. Outputs: KILLED/SURVIVED per mutant.
Written 2026-11-07 for the review of PR 897."""
import subprocess, sys
from pathlib import Path
WT = Path(sys.argv[1])
TAXA = WT / "src/kg_microbe_links/taxa.py"
MUTANTS = [
    ("M1 CURIE bound 12->13 digits (boundary)", TAXA, 'r"NCBITaxon:([1-9][0-9]{0,11})"', 'r"NCBITaxon:([1-9][0-9]{0,12})"'),
    ("M2 _curie_id fullmatch->match (TaxonMech files)", TAXA, "    if not isinstance(value, str) or not CURIE.fullmatch(value):\n        raise", "    if not isinstance(value, str) or not CURIE.match(value):\n        raise"),
    ("M3 conf path type unchecked", TAXA, 'if not isinstance(conf, dict) or not isinstance(conf.get("path"), str):', 'if not isinstance(conf, dict) or conf.get("path") is None:'),
    ("M4 only the first required column checked", TAXA, "missing = [c for c in columns if c not in (reader.fieldnames or [])]", "missing = [c for c in columns[:1] if c not in (reader.fieldnames or [])]"),
    ("M5 cycle walk stops at a marked id instead of raising", TAXA, "while taxon in merged and state.get(taxon) != 2:", "while taxon in merged and state.get(taxon) is None:"),
    ("M9 zero-byte file passes the column check", TAXA, "(reader.fieldnames or [])", "(reader.fieldnames or columns)"),
    ("M12 judge follows two hops only", TAXA, "            while current in self.merged:  # to the end of the chain; acyclic since the table was read\n                current = self.merged[current]\n",
     "            for _ in range(2):\n                if current in self.merged:\n                    current = self.merged[current]\n"),
    ("M13 inventory short row (missing parent cell) treated as root", TAXA, '            parent = _curie_id(row["parent_id"], f"{INVENTORY_PATH} row {n}") if row["parent_id"] else ROOT_TAXON',
     '            parent = _curie_id(row["parent_id"], f"{INVENTORY_PATH} row {n}") if row["parent_id"] is not None and row["parent_id"] != "" else ROOT_TAXON'),
]
original = TAXA.read_text(encoding="utf-8")
for label, path, before, after in MUTANTS:
    assert original.count(before) == 1, label
    try:
        path.write_text(original.replace(before, after), encoding="utf-8")
        run = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests/test_taxon_links.py", "tests/test_taxon_links_cli.py"],
                             cwd=WT, capture_output=True, text=True, timeout=120)
        status = "SURVIVED" if run.returncode == 0 else "KILLED"
        print(f"{status:8} {label}: {run.stdout.strip().splitlines()[-1]}")
    finally:
        path.write_text(original, encoding="utf-8")
