# Historical review evidence: a Claude reviewer's probe for PR 897, rounds 7 and 8 (193cdc9955); findings in culturebotai-claw issues; paths inside name that reviewer's scratch directories, so a re-run at head may need them recreated.
"""Review probes for PR 897 rounds 7-8 (head 193cdc9955). Read-only; builds fixtures under a scratch dir.
Inputs: the test fixture builder. Outputs: printed observations. Written 2026-11-07 for the review of PR 897."""
import sys, time, traceback, tempfile, shutil
from pathlib import Path
ROOT = Path(sys.argv[1]); SCRATCH = Path(sys.argv[2])
sys.path[:0] = [str(ROOT), str(ROOT / "src")]
from tests.test_taxon_links import taxonmech, SCOPE, MERGED
import kg_microbe_links.taxa as links

def fresh(name):
    base = SCRATCH / "fx" / name
    if base.exists(): shutil.rmtree(base)
    base.mkdir(parents=True)
    return taxonmech.__wrapped__(base)

def attempt(label, fn):
    try:
        out = fn()
        print(f"[{label}] OK -> {out!r}"[:300])
    except links.TaxonLinksError as exc:
        print(f"[{label}] TaxonLinksError: {exc}"[:300])
    except Exception as exc:
        print(f"[{label}] *** UNMAPPED {type(exc).__module__}.{type(exc).__name__}: {str(exc)[:160]}")

SCOPE_HDR = "identifier\tadded\treason\n"
def scope_case(label, content=None, encoding="utf-8", raw=None):
    tx = fresh("scope_" + label)
    p = tx / "curation/seed_scope.tsv"
    if raw is not None: p.write_bytes(raw)
    else: p.write_text(content, encoding=encoding)
    attempt("scope:" + label, lambda: sorted(links.TaxonIndex(tx).scope))

print("=== 1. _read_tsv edge cases (scope) ===")
scope_case("zero_byte", "")
scope_case("newline_only", "\n")
scope_case("two_newlines", "\n\n")
scope_case("bom", SCOPE_HDR + "NCBITaxon:562\tx\ty\n", encoding="utf-8-sig")
scope_case("crlf", "identifier\tadded\treason\r\nNCBITaxon:562\tx\ty\r\n")
scope_case("cr_only", raw=b"identifier\tadded\treason\rNCBITaxon:562\tx\ty\r")
scope_case("header_trailing_ws", "identifier \tadded\treason\nNCBITaxon:562\tx\ty\n")
scope_case("header_trailing_tab", "identifier\tadded\treason\t\nNCBITaxon:562\tx\ty\n")
scope_case("dup_columns", "identifier\tidentifier\nNCBITaxon:562\tNCBITaxon:1280\n")
scope_case("empty_identifier_cell", SCOPE_HDR + "\tx\ty\n")
scope_case("short_row_no_cells", SCOPE_HDR + "NCBITaxon:562\tx\ty\n\n")
scope_case("blank_line_between", SCOPE_HDR + "NCBITaxon:562\tx\ty\n\n562\tx\ty\n")
scope_case("quoted_field", SCOPE_HDR + '"NCBITaxon:562"\tx\ty\n')
scope_case("quote_in_reason", SCOPE_HDR + 'NCBITaxon:562\tx\t"unterminated\nNCBITaxon:1280\tx\ty\n')
scope_case("nul_byte", raw=b"identifier\tadded\treason\nNCBITaxon:562\tx\0\ty\n")
scope_case("invalid_utf8", raw=b"identifier\tadded\treason\nNCBITaxon:562\tx\xff\ty\n")
scope_case("huge_field", SCOPE_HDR + "NCBITaxon:562\tx\t" + "y" * 200_000 + "\n")
scope_case("leading_space_curie", SCOPE_HDR + " NCBITaxon:562\tx\ty\n")
scope_case("twelve_digits", SCOPE_HDR + "NCBITaxon:" + "9" * 12 + "\tx\ty\n")
scope_case("thirteen_digits", SCOPE_HDR + "NCBITaxon:" + "9" * 13 + "\tx\ty\n")
scope_case("only_header_plus_blank", SCOPE_HDR + "\n")

print("=== 1b. inventory edge cases ===")
INV_HDR = "taxon_id\tlabel\trank\tparent_id\tattested_by\n"
def inv_case(label, content):
    tx = fresh("inv_" + label)
    (tx / "data/raw/ncbitaxon_taxa.tsv").write_text(content, encoding="utf-8")
    def run():
        ix = links.TaxonIndex(tx)
        return {k: v for k, v in ix.inventory.items() if k in (562, 999999)}, {k: v for k, v in ix._inventory_names.items() if k in (562, 999999)}
    attempt("inventory:" + label, run)
inv_case("parent_not_curie", INV_HDR + "NCBITaxon:562\tE. coli\tSPECIES\t561\tx\n")
inv_case("short_row_missing_parent_and_rank", INV_HDR + "NCBITaxon:562\tE. coli\n")
inv_case("short_row_missing_parent_only", INV_HDR + "NCBITaxon:562\tE. coli\tSPECIES\n")
inv_case("empty_rank_and_parent", INV_HDR + "NCBITaxon:562\tE. coli\t\t\tx\n")
inv_case("extra_cells", INV_HDR + "NCBITaxon:562\tE. coli\tSPECIES\tNCBITaxon:561\tx\textra\n")
inv_case("header_only", INV_HDR)
inv_case("reordered_columns", "parent_id\trank\tlabel\ttaxon_id\nNCBITaxon:561\tSPECIES\tE. coli\tNCBITaxon:562\n")

print("=== 1c. merged table edge cases ===")
M_HDR = "old_taxon_id\tcurrent_taxon_id\n"
def merged_case(label, content):
    tx = fresh("merged_" + label)
    (tx / "data/raw/ncbi_merged_ids.tsv").write_text(content, encoding="utf-8")
    attempt("merged:" + label, lambda: dict(links.TaxonIndex(tx).merged))
merged_case("self_map", M_HDR + "NCBITaxon:562\tNCBITaxon:562\n")
merged_case("two_cycle_not_containing_start", M_HDR + "NCBITaxon:1\tNCBITaxon:2\nNCBITaxon:2\tNCBITaxon:3\nNCBITaxon:3\tNCBITaxon:2\n")
merged_case("chain_ending_outside", M_HDR + "NCBITaxon:1\tNCBITaxon:2\nNCBITaxon:2\tNCBITaxon:3\n")
merged_case("chain_into_cycle_later_start", M_HDR + "NCBITaxon:5\tNCBITaxon:6\nNCBITaxon:6\tNCBITaxon:5\nNCBITaxon:1\tNCBITaxon:5\n")
merged_case("two_chains_sharing_tail", M_HDR + "NCBITaxon:1\tNCBITaxon:3\nNCBITaxon:2\tNCBITaxon:3\nNCBITaxon:3\tNCBITaxon:4\n")
merged_case("duplicate_old_id", M_HDR + "NCBITaxon:1\tNCBITaxon:2\nNCBITaxon:1\tNCBITaxon:3\n")
merged_case("zero_byte", "")
merged_case("header_only", M_HDR)
merged_case("empty_current_cell", M_HDR + "NCBITaxon:1\t\n")

print("=== 2. _read_merged linearity ===")
def time_table(label, rows):
    tx = fresh("time_" + label)
    (tx / "data/raw/ncbi_merged_ids.tsv").write_text(M_HDR + rows, encoding="utf-8")
    t0 = time.perf_counter(); ix = links.TaxonIndex(tx); dt = time.perf_counter() - t0
    print(f"[time:{label}] {len(ix.merged)} rows in {dt:.2f}s")
    return ix
n = 200_000
ix_chain = time_table("chain_200k", "".join(f"NCBITaxon:{i}\tNCBITaxon:{i+1}\n" for i in range(10_000_000, 10_000_000 + n)))
time_table("pairs_200k", "".join(f"NCBITaxon:{i}\tNCBITaxon:{i+1}\n" for i in range(10_000_000, 10_000_000 + 2*n, 2)))
time_table("chain_200k_reversed_order", "".join(f"NCBITaxon:{i}\tNCBITaxon:{i+1}\n" for i in reversed(range(10_000_000, 10_000_000 + n))))
time_table("star_200k_into_one", "".join(f"NCBITaxon:{i}\tNCBITaxon:5\n" for i in range(10_000_000, 10_000_000 + n)))
t0 = time.perf_counter(); j = ix_chain.judge("NCBITaxon:10000000"); print(f"[judge chain start] {j.verdict.value} current={j.current} current_verdict={j.current_verdict} in {time.perf_counter()-t0:.2f}s")
# judging every id of the chain is quadratic in judge (walk per cite); measure 2,000 cites from the start
t0 = time.perf_counter()
for i in range(10_000_000, 10_000_000 + 2000): ix_chain.judge(f"NCBITaxon:{i}")
print(f"[judge 2000 chain ids] {time.perf_counter()-t0:.2f}s (each walks to the end: per-citation cost is chain length)")

print("=== 3. judge chain + 4. CURIE bound ===")
tx = fresh("base"); ix = links.TaxonIndex(tx)
for v in ["NCBITaxon:776", "NCBITaxon:777", "NCBITaxon:46170", "NCBITaxon:999001"]:
    j = ix.judge(v); print(f"[judge {v}] {j.verdict.value} taxon={j.taxon} current={j.current} current_verdict={j.current_verdict}")
for v in ["NCBITaxon:0", "NCBITaxon:" + "1" * 12, "NCBITaxon:" + "1" * 13, "NCBITaxon:" + "9" * 12, "NCBITaxon:562\n", "NCBITaxon:562\r", "\nNCBITaxon:562", "NCBITaxon:0562", "NCBITaxon:562\x00", "NCBITaxon:٥٦٢", "NCBITaxon:562a"]:
    print(f"[curie {v!r}] {ix.judge(v).verdict.value}")

print("=== 5. taxdump_path conf shapes ===")
def conf_case(label, content=None, raw=None):
    tx = fresh("conf_" + label); ix = links.TaxonIndex(tx)
    p = tx / "conf/ncbi_taxdump.yaml"
    if raw is not None: p.write_bytes(raw)
    else: p.write_text(content, encoding="utf-8")
    attempt("conf:" + label, lambda: (ix.taxdump_path, ix.judge("NCBITaxon:511145").verdict.value))
conf_case("list", "- a\n- b\n")
conf_case("path_int", "path: 5\n")
conf_case("path_list", "path: [a, b]\n")
conf_case("path_null", "path:\n")
conf_case("path_empty_str", "path: ''\n")
conf_case("tab_indent", "snapshot:\n\tpath: x\n")
conf_case("tab_after_colon", "path:\tdata/source_snapshots/taxdump.tar.gz\n")
conf_case("invalid_date_value", "snapshot: 2026-13-45\npath: data/source_snapshots/taxdump.tar.gz\n")
conf_case("invalid_utf8", raw=b"path: data/source_snapshots/taxdump.tar.gz\nsnapshot: \xff\n")
conf_case("scalar_string", "just a string\n")
conf_case("sha256_list", "path: data/source_snapshots/taxdump.tar.gz\nsha256: [a]\n")
conf_case("sha256_dict", "path: data/source_snapshots/taxdump.tar.gz\nsha256: {a: b}\n")
conf_case("sha256_bool", "path: data/source_snapshots/taxdump.tar.gz\nsha256: yes\n")
conf_case("duplicate_keys", "path: a\npath: data/source_snapshots/taxdump.tar.gz\n")
# path outside the root
tx = fresh("conf_outside"); ix = links.TaxonIndex(tx)
outside = SCRATCH / "outside_taxdump.tar.gz"; shutil.copy(tx / "data/source_snapshots/taxdump.tar.gz", outside)
(tx / "conf/ncbi_taxdump.yaml").write_text(f"path: {outside}\n", encoding="utf-8")
attempt("conf:absolute_path_outside_root", lambda: (ix.taxdump_path, ix.judge("NCBITaxon:511145").verdict.value))
(tx / "conf/ncbi_taxdump.yaml").write_text("path: ../../outside_taxdump.tar.gz\n", encoding="utf-8")
attempt("conf:dotdot_path_outside_root", lambda: (ix.taxdump_path, ix.judge("NCBITaxon:511145").verdict.value))
