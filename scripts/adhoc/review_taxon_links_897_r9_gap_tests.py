# Historical review evidence: a Claude reviewer's probe for PR 897, round 9 (c8e3fc7a15); findings in culturebotai-claw issues; paths inside name that reviewer's scratch directories, so a re-run at head may need them recreated.
"""Review scratch tests for PR 897 round 9 (2026-11-07): the two inputs the surviving mutants need.
Each reuses the repository's `taxonmech` fixture. Expected: both pass at head; the first fails under the
'first data row only' mutant (M12) and the second hangs or fails under the 'returns to start' mutant (M3b)."""
import pytest
from kg_microbe_links import taxa as links
from tests.test_taxon_links import taxonmech  # noqa: F401  (the fixture)


def test_a_torn_last_inventory_line_after_good_rows_is_refused(taxonmech):
    (taxonmech / "data" / "raw" / "ncbitaxon_taxa.tsv").write_text(
        "taxon_id\tlabel\trank\tparent_id\nNCBITaxon:1\troot\tNO_RANK\t\nNCBITaxon:1423\tBacillus subtilis\n", encoding="utf-8")
    with pytest.raises(links.TaxonLinksError, match="row 3 has a different number of cells than the header"):
        links.TaxonIndex(taxonmech)



def test_a_merge_chain_into_a_cycle_its_start_is_not_on_is_refused(taxonmech):
    (taxonmech / "data" / "raw" / "ncbi_merged_ids.tsv").write_text(
        "old_taxon_id\tcurrent_taxon_id\nNCBITaxon:901\tNCBITaxon:902\nNCBITaxon:902\tNCBITaxon:903\n"
        "NCBITaxon:903\tNCBITaxon:904\nNCBITaxon:904\tNCBITaxon:902\n", encoding="utf-8")
    with pytest.raises(links.TaxonLinksError, match="in a cycle"):
        links.TaxonIndex(taxonmech)
