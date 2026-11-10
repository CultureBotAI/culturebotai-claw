# Historical review evidence: a Claude reviewer's probe for PR 897, round 9 (c8e3fc7a15); findings in culturebotai-claw issues; paths inside name that reviewer's scratch directories, so a re-run at head may need them recreated.
"""Probe 1 for PR 897 round 9 (review scratch, 2026-11-07): _read_tsv's cell-count check and error mapping.
Inputs: none (fixtures built under a scratch dir). Outputs: one line per case. Read-only against the repo."""
import csv, sys, tempfile, traceback
from pathlib import Path
sys.path.insert(0, "/Users/marcin/agent-work/culturebotai-claw/review897r9/src")
from kg_microbe_links import taxa as links

def case(name, relative, data: bytes, columns, may_be_empty=False):
    root = Path(tempfile.mkdtemp(dir="/Users/marcin/agent-work/culturebotai-claw/review897r9-scratch"))
    p = root / relative; p.parent.mkdir(parents=True, exist_ok=True); p.write_bytes(data)
    idx = links.TaxonIndex.__new__(links.TaxonIndex); idx.root = root
    try:
        rows = idx._read_tsv(relative, columns, may_be_empty=may_be_empty)
        print(f"{name:55s} OK   rows={rows}")
    except links.TaxonLinksError as e:
        print(f"{name:55s} REFUSED {e}")
    except Exception as e:
        print(f"{name:55s} ESCAPED {type(e).__name__}: {e}")

H = b"taxon_id\tlabel\trank\tparent_id\n"
case("root row, empty trailing parent_id", "i.tsv", H + b"NCBITaxon:1\troot\tNO_RANK\t\n", ["taxon_id","label","rank","parent_id"])
case("root row, 3 cells (no trailing tab)", "i.tsv", H + b"NCBITaxon:1\troot\tNO_RANK\n", ["taxon_id","label","rank","parent_id"])
case("extra empty trailing cell", "i.tsv", H + b"NCBITaxon:1\troot\tNO_RANK\t\t\n", ["taxon_id","label","rank","parent_id"])
case("extra non-empty cell", "i.tsv", H + b"NCBITaxon:1\troot\tNO_RANK\t\tx\n", ["taxon_id","label","rank","parent_id"])
case("header with trailing tab, row without", "i.tsv", b"identifier\t\nNCBITaxon:562\n", ["identifier"])
case("blank line between rows (row numbering)", "i.tsv", b"identifier\nNCBITaxon:562\n\nNCBITaxon:563\n", ["identifier"])
case("blank line then short row (number reported)", "i.tsv", H + b"NCBITaxon:1\troot\tNO_RANK\t\n\nNCBITaxon:2\tBacteria\n", ["taxon_id","label","rank","parent_id"])
case("bad UTF-8 in header", "i.tsv", b"identif\xffier\nNCBITaxon:562\n", ["identifier"])
case("bad UTF-8 in row 2", "i.tsv", b"identifier\nNCBITaxon:562\xff\n", ["identifier"])
case("bad UTF-8 in row ~3000 (beyond first 8 KB chunk)", "i.tsv", b"identifier\n" + b"".join(b"NCBITaxon:%d\n" % i for i in range(1, 3000)) + b"NCBITaxon:9\xff\n", ["identifier"])
case("csv field limit in header", "i.tsv", b"identifier\t" + b"x" * 200_000 + b"\nNCBITaxon:562\n", ["identifier"])
case("csv field limit in row", "i.tsv", b"identifier\nNCBITaxon:" + b"1" * 200_000 + b"\n", ["identifier"])
case("quoted cell swallowing a tab", "i.tsv", H + b"NCBITaxon:1\t\"root\tx\"\tNO_RANK\t\n", ["taxon_id","label","rank","parent_id"])
case("unbalanced leading quote swallowing to EOF", "i.tsv", H + b"NCBITaxon:1\t\"root\tNO_RANK\t\nNCBITaxon:2\tBacteria\tSUPERKINGDOM\tNCBITaxon:1\n", ["taxon_id","label","rank","parent_id"])
case("CRLF line endings", "i.tsv", b"identifier\r\nNCBITaxon:562\r\n", ["identifier"])
case("header-only merge table (may_be_empty)", "m.tsv", b"old_taxon_id\tcurrent_taxon_id\n", ["old_taxon_id","current_taxon_id"], True)
case("empty file", "i.tsv", b"", ["identifier"])
case("NUL byte in row", "i.tsv", b"identifier\nNCBITaxon:562\x00\n", ["identifier"])
