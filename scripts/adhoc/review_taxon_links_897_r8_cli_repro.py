# Historical review evidence: a Claude reviewer's probe for PR 897, rounds 7 and 8 (193cdc9955); findings in culturebotai-claw issues; paths inside name that reviewer's scratch directories, so a re-run at head may need them recreated.
"""CLI reproductions for the review of PR 897 rounds 7-8: exit codes for TaxonMech inputs the readers do not map, and
the verdict a short inventory row produces. Inputs: the test fixture builders. Outputs: printed exit codes and stderr tails.
Written 2026-11-07."""
import os, shutil, subprocess, sys
from pathlib import Path
ROOT = Path(sys.argv[1]); SCRATCH = Path(sys.argv[2])
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from tests.test_taxon_links import taxonmech
from tests.test_taxon_links_cli import _mech
import kg_microbe_links.taxa as links

def fresh(name):
    base = SCRATCH / "cli" / name
    if base.exists(): shutil.rmtree(base)
    base.mkdir(parents=True)
    return base, taxonmech.__wrapped__(base)

def run_cli(base, tx, value="NCBITaxon:562"):
    mech = _mech(base, "dufmech", {"data/families/a.yaml": {"causal_graphs": [{"taxon": value}]}})
    env = dict(os.environ, PYTHONPATH=f"{ROOT / 'src'}{os.pathsep}{ROOT}", OPENCLAW_WORKSPACE=str(base / "workspace"))
    r = subprocess.run([sys.executable, "-m", "kg_microbe_links", "taxa", "--mech", "dufmech", "--root", str(mech),
                        "--taxonmech-root", str(tx), "--strict"], capture_output=True, text=True, env=env, cwd=ROOT)
    tail = r.stderr.strip().splitlines()[-1] if r.stderr.strip() else ""
    return r.returncode, tail[:160]

SCOPE_HDR = "identifier\tadded\treason\n"
base, tx = fresh("huge_field"); (tx / "curation/seed_scope.tsv").write_text(SCOPE_HDR + "NCBITaxon:562\tx\t" + "y" * 200_000 + "\n", encoding="utf-8")
print("scope field > 131072 chars:", run_cli(base, tx))
base, tx = fresh("huge_id"); (tx / "curation/seed_scope.tsv").write_text(SCOPE_HDR + "NCBITaxon:" + "1" * 200_000 + "\tx\ty\n", encoding="utf-8")
print("scope id of 200,000 digits:   ", run_cli(base, tx))
base, tx = fresh("bad_utf8"); (tx / "curation/seed_scope.tsv").write_bytes(b"identifier\tadded\treason\nNCBITaxon:562\tx\t\xff\n")
print("scope with invalid UTF-8:     ", run_cli(base, tx))
base, tx = fresh("bad_date"); (tx / "conf/ncbi_taxdump.yaml").write_text("snapshot: 2026-13-45\npath: data/source_snapshots/taxdump.tar.gz\n", encoding="utf-8")
print("conf with an invalid date:    ", run_cli(base, tx, "NCBITaxon:511145"))
base, tx = fresh("conf_bad_utf8"); (tx / "conf/ncbi_taxdump.yaml").write_bytes(b"path: data/source_snapshots/taxdump.tar.gz\nsnapshot: \xff\n")
print("conf with invalid UTF-8:      ", run_cli(base, tx, "NCBITaxon:511145"))
base, tx = fresh("conf_path_int"); (tx / "conf/ncbi_taxdump.yaml").write_text("path: 5\n", encoding="utf-8")
print("conf path: 5 (control, mapped):", run_cli(base, tx, "NCBITaxon:511145"))

print("--- short inventory row: 1423 (Bacillus subtilis, unscoped bacterium) with its rank and parent cells missing")
base, tx = fresh("short_inventory_row")
inv = tx / "data/raw/ncbitaxon_taxa.tsv"
inv.write_text(inv.read_text(encoding="utf-8") + "NCBITaxon:1423\tBacillus subtilis\n", encoding="utf-8")  # torn last line
ix = links.TaxonIndex(tx)
j = ix.judge("NCBITaxon:1423")
print("inventory entry:", ix.inventory[1423], "-> verdict", j.verdict.value, "domain", repr(j.domain))
base2, tx2 = fresh("full_inventory_row_control")
print("control (row absent, taxdump used):", links.TaxonIndex(tx2).judge("NCBITaxon:1423").verdict.value)
