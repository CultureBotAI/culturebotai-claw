"""kg_microbe_links.taxa judges each cited taxon by what TaxonMech holds.

Every verdict is driven by an input where it differs from its neighbours: a
species in the scope against the strain below it, a genus against its species,
a fungus no source attests against an animal, a retired id whose current id is
a record against one whose current id is absent. TaxonMech is a fake checkout
under tmp_path with the four files the index reads, including a small taxdump
tarball holding the taxa the attested inventory does not.
"""

from __future__ import annotations

import io
import tarfile
from pathlib import Path

import pytest
import yaml

from kg_microbe_links import taxa as links

# taxon: (name, rank, parent). The inventory holds the scope and its lineage; the
# taxdump holds everything, as NCBI does.
TAXA = {
    1: ("root", "no rank", 1),
    131567: ("cellular organisms", "no rank", 1),
    2: ("Bacteria", "superkingdom", 131567),
    2759: ("Eukaryota", "superkingdom", 131567),
    2157: ("Archaea", "superkingdom", 131567),
    2285: ("Sulfolobus acidocaldarius", "species", 2157),
    33090: ("Viridiplantae", "kingdom", 2759),
    3702: ("Arabidopsis thaliana", "species", 33090),
    10239: ("Viruses", "superkingdom", 1),
    543: ("Enterobacteriaceae", "family", 2),
    561: ("Escherichia", "genus", 543),
    562: ("Escherichia coli", "species", 561),
    83333: ("Escherichia coli K-12", "strain", 562),
    511145: ("Escherichia coli str. K-12 substr. MG1655", "strain", 83333),
    1279: ("Staphylococcus", "genus", 2),
    1280: ("Staphylococcus aureus", "species", 1279),
    1281: ("Staphylococcus aureus subsp. aureus", "subspecies", 1280),  # also a record: two scoped ancestors above 1282
    1282: ("Staphylococcus aureus NCTC 8325", "strain", 1281),
    1386: ("Bacillus", "genus", 2),
    1423: ("Bacillus subtilis", "species", 1386),
    4751: ("Fungi", "kingdom", 2759),
    4930: ("Saccharomyces", "genus", 4751),
    4932: ("Saccharomyces cerevisiae", "species", 4930),
    559292: ("Saccharomyces cerevisiae S288C", "strain", 4932),
    5478: ("Nakaseomyces glabratus", "species", 4751),
    5820: ("Plasmodium", "genus", 2759),
    5833: ("Plasmodium falciparum", "species", 5820),
    33208: ("Metazoa", "kingdom", 2759),
    9605: ("Homo", "genus", 33208),
    9606: ("Homo sapiens", "species", 9605),
    10665: ("Enterobacteria phage T4", "species", 10239),
    777: ("Escherichia coli (old name)", "species", 561),
    999: ("marine metagenome", "species", 1),
    9991: ("marine metagenome isolate 9991", "subspecies", 999),  # the real taxdump's 22 below-species unplaced are subspecies
    998: ("unclassified sequences", "no rank", 1),
}
SCOPE = {562, 1280, 1281, 4932, 777}  # 777 is also retired: TaxonMech's scope keeps some merged ids
INVENTORY = {1, 131567, 2, 2759, 543, 561, 562, 1279, 1280, 4751, 4930, 4932}
MERGED = {46170: 1280, 999001: 999002, 777: 562}


def _dmp(rows: list[list[str]]) -> bytes:
    return "".join("\t|\t".join(row) + "\t|\n" for row in rows).encode()


@pytest.fixture
def taxonmech(tmp_path: Path) -> Path:
    root = tmp_path / "TaxonMech"
    (root / "curation").mkdir(parents=True)
    (root / "data" / "raw").mkdir(parents=True)
    (root / "conf").mkdir()
    (root / "data" / "source_snapshots").mkdir()
    (root / "curation" / "seed_scope.tsv").write_text(
        "identifier\tadded\treason\n" + "".join(f"NCBITaxon:{t}\t2026-09-10\tcore rule\n" for t in sorted(SCOPE)),
        encoding="utf-8")
    (root / "data" / "raw" / "ncbi_merged_ids.tsv").write_text(
        "old_taxon_id\tcurrent_taxon_id\n" + "".join(f"NCBITaxon:{o}\tNCBITaxon:{n}\n" for o, n in MERGED.items()),
        encoding="utf-8")
    (root / "data" / "raw" / "ncbitaxon_taxa.tsv").write_text(
        "taxon_id\tlabel\trank\tparent_id\tattested_by\n"
        + "".join(f"NCBITaxon:{t}\t{TAXA[t][0]}\t{TAXA[t][1].upper().replace(' ', '_')}\t"
                  f"{'' if t == 1 else 'NCBITaxon:' + str(TAXA[t][2])}\tncbitaxon\n" for t in sorted(INVENTORY)),
        encoding="utf-8")
    tar_path = root / "data" / "source_snapshots" / "taxdump.tar.gz"
    with tarfile.open(tar_path, "w:gz") as tar:
        for member, payload in (
            ("nodes.dmp", _dmp([[str(t), str(p), r] for t, (_, r, p) in sorted(TAXA.items())])),
            ("names.dmp", _dmp([[str(t), n, "", "scientific name"] for t, (n, _, _) in sorted(TAXA.items())]
                               + [["1423", "Bacillus globigii", "", "synonym"]])),  # a synonym the names must skip
            ("merged.dmp", _dmp([[str(o), str(n)] for o, n in MERGED.items()])),
        ):
            info = tarfile.TarInfo(member)
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
    (root / "conf" / "ncbi_taxdump.yaml").write_text(
        "snapshot: '2026-09-13'\npath: data/source_snapshots/taxdump.tar.gz\n", encoding="utf-8")
    return root


@pytest.fixture
def index(taxonmech: Path) -> links.TaxonIndex:
    return links.TaxonIndex(taxonmech)


def judge(index: links.TaxonIndex, value: object) -> links.Judgement:
    return index.judge(value)


def test_a_scoped_species_is_a_record(index):
    assert judge(index, "NCBITaxon:562").verdict is links.Verdict.RECORD


@pytest.mark.parametrize("strain,species", [(511145, 562), (83333, 562), (559292, 4932)])
def test_a_strain_resolves_to_its_scoped_species(index, strain, species):
    judgement = judge(index, f"NCBITaxon:{strain}")
    assert judgement.verdict is links.Verdict.SPECIES_OF_STRAIN
    assert judgement.ancestor == species


@pytest.mark.parametrize("taxon", [561, 1386, 543])
def test_a_genus_or_family_is_above_species(index, taxon):
    assert judge(index, f"NCBITaxon:{taxon}").verdict is links.Verdict.ABOVE_SPECIES


def test_a_strain_resolves_to_its_nearest_scoped_ancestor_not_the_farthest(index):
    """1282 sits under the subspecies 1281 and the species 1280, both records: the link goes to 1281."""
    judgement = judge(index, "NCBITaxon:1282")
    assert judgement.verdict is links.Verdict.SPECIES_OF_STRAIN
    assert judgement.ancestor == 1281
    assert judge(index, "NCBITaxon:1281").verdict is links.Verdict.RECORD


def test_an_unscoped_archaeon_is_unattested_and_a_plant_is_outside_the_domain(index):
    archaeon = judge(index, "NCBITaxon:2285")
    assert (archaeon.verdict, archaeon.domain) == (links.Verdict.UNATTESTED_MICROBIAL, "Archaea")
    plant = judge(index, "NCBITaxon:3702")
    assert (plant.verdict, plant.kingdom) == (links.Verdict.OUTSIDE_DOMAIN, "Viridiplantae")


def test_an_unscoped_bacterial_species_is_unattested_not_above_species(index):
    judgement = judge(index, "NCBITaxon:1423")
    assert judgement.verdict is links.Verdict.UNATTESTED_MICROBIAL
    assert judgement.domain == "Bacteria"


def test_an_unscoped_fungus_or_protist_is_unattested_but_an_animal_and_a_virus_are_outside_the_domain(index):
    assert judge(index, "NCBITaxon:5478").verdict is links.Verdict.UNATTESTED_MICROBIAL
    assert judge(index, "NCBITaxon:5478").kingdom == "Fungi"
    # TaxonMech holds protists, so an unattested one is a scope gap, not another domain.
    assert judge(index, "NCBITaxon:5833").verdict is links.Verdict.UNATTESTED_MICROBIAL
    assert judge(index, "NCBITaxon:5833").kingdom == ""
    assert judge(index, "NCBITaxon:9606").verdict is links.Verdict.OUTSIDE_DOMAIN
    assert judge(index, "NCBITaxon:9606").kingdom == "Metazoa"
    assert judge(index, "NCBITaxon:10665").verdict is links.Verdict.OUTSIDE_DOMAIN
    assert judge(index, "NCBITaxon:10665").domain == "Viruses"


def test_a_retired_id_reports_its_current_id_and_that_id_s_own_verdict(index):
    merged_into_record = judge(index, "NCBITaxon:46170")
    assert merged_into_record.verdict is links.Verdict.RETIRED
    assert (merged_into_record.current, merged_into_record.current_verdict) == (1280, links.Verdict.RECORD)
    merged_into_nothing = judge(index, "NCBITaxon:999001")
    assert (merged_into_nothing.current, merged_into_nothing.current_verdict) == (999002, links.Verdict.ABSENT)


def test_a_retired_id_that_the_scope_still_lists_is_retired_not_a_record(index):
    judgement = judge(index, "NCBITaxon:777")
    assert judgement.verdict is links.Verdict.RETIRED
    assert (judgement.current, judgement.current_verdict) == (562, links.Verdict.RECORD)


def test_a_metagenome_under_no_domain_is_unplaced_but_a_rank_above_species_there_is_above_species(index):
    judgement = judge(index, "NCBITaxon:999")
    assert judgement.verdict is links.Verdict.UNPLACED
    assert judgement.domain == "other"
    assert judge(index, "NCBITaxon:998").verdict is links.Verdict.ABOVE_SPECIES


def test_the_merge_table_is_the_only_merge_source(taxonmech):
    """A header-only TSV means no merges: the same verdict on the judgement that reads the taxdump and on the one after.

    46170 is outside the inventory, so the first judgement reads nodes.dmp, which is where a merged.dmp fallback
    would fill the merges; the second judgement would then say retired.
    """
    (taxonmech / "data" / "raw" / "ncbi_merged_ids.tsv").write_text("old_taxon_id\tcurrent_taxon_id\n", encoding="utf-8")
    index = links.TaxonIndex(taxonmech)
    assert index._nodes is None
    assert judge(index, "NCBITaxon:46170").verdict is links.Verdict.ABSENT
    assert index._nodes is not None
    assert judge(index, "NCBITaxon:46170").verdict is links.Verdict.ABSENT


def test_a_strain_under_a_metagenome_is_unplaced_too(index):
    """Below species under no domain: not a strain of any record, not above species, not in a domain."""
    judgement = judge(index, "NCBITaxon:9991")
    assert judgement.verdict is links.Verdict.UNPLACED
    assert judgement.rank == "subspecies"


def test_names_refuse_an_absent_tarball_as_nodes_do(index, taxonmech):
    """One accessor decides: after the nodes were read, a tarball that has gone is refused by names() too, not blank."""
    assert judge(index, "NCBITaxon:511145").verdict is links.Verdict.SPECIES_OF_STRAIN  # reads nodes.dmp
    (taxonmech / "data" / "source_snapshots" / "taxdump.tar.gz").unlink()
    with pytest.raises(links.TaxonLinksError, match="is not present"):
        index.names([511145, 562])


def test_a_synonym_row_never_names_a_taxon(index):
    """names.dmp holds synonyms beside scientific names; only the scientific name is a taxon's name."""
    assert index.names([1423]) == {1423: "Bacillus subtilis"}


def test_a_pinned_digest_is_checked_lazily_not_at_construction(taxonmech, monkeypatch):
    """A fresh clone has the conf and no tarball; a Mech whose taxa are all in the inventory must still be judged."""
    import hashlib
    tar_path = taxonmech / "data" / "source_snapshots" / "taxdump.tar.gz"
    conf = taxonmech / "conf" / "ncbi_taxdump.yaml"
    conf.write_text(conf.read_text(encoding="utf-8") + f"sha256: {hashlib.sha256(tar_path.read_bytes()).hexdigest()}\n",
                    encoding="utf-8")
    monkeypatch.setattr(links, "_sha256", lambda path: (_ for _ in ()).throw(AssertionError("hashed before a taxdump read")))
    index = links.TaxonIndex(taxonmech)
    assert judge(index, "NCBITaxon:562").verdict is links.Verdict.RECORD
    assert judge(index, "NCBITaxon:561").verdict is links.Verdict.ABOVE_SPECIES  # inventory node, no taxdump
    assert index.names([562, 561]) == {562: "Escherichia coli", 561: "Escherichia"}
    assert not index._taxdump_verified


def test_a_pinned_sha256_is_checked_once_per_process(taxonmech):
    """With the digest in the conf, the first taxdump read verifies the file; later reads do not hash it again."""
    import hashlib
    tar_path = taxonmech / "data" / "source_snapshots" / "taxdump.tar.gz"
    conf = taxonmech / "conf" / "ncbi_taxdump.yaml"
    conf.write_text(conf.read_text(encoding="utf-8") + f"sha256: {hashlib.sha256(tar_path.read_bytes()).hexdigest()}\n",
                    encoding="utf-8")
    index = links.TaxonIndex(taxonmech)
    assert judge(index, "NCBITaxon:511145").verdict is links.Verdict.SPECIES_OF_STRAIN
    assert index._taxdump_verified
    tar_path.write_bytes(b"replaced after the check")  # a second access must not hash again
    assert index.taxdump_path == tar_path


@pytest.mark.parametrize("table", [
    "old_taxon_id\tcurrent_taxon_id\nNCBITaxon:562\tNCBITaxon:562\n",
    "old_taxon_id\tcurrent_taxon_id\nNCBITaxon:777\tNCBITaxon:778\nNCBITaxon:778\tNCBITaxon:777\n",
])
def test_a_self_mapping_or_cyclic_merge_table_is_refused(taxonmech, table):
    (taxonmech / "data" / "raw" / "ncbi_merged_ids.tsv").write_text(table, encoding="utf-8")
    with pytest.raises(links.TaxonLinksError, match="in a cycle"):
        links.TaxonIndex(taxonmech)


@pytest.mark.parametrize("relative,content,message", [
    ("curation/seed_scope.tsv", "wrong_column\nNCBITaxon:562\n", "has no identifier column"),
    ("curation/seed_scope.tsv", "", "has no identifier column"),
    ("curation/seed_scope.tsv", "identifier\tadded\treason\n", "lists no taxa"),
    ("curation/seed_scope.tsv", "identifier\n562\n", "row 2: '562' is not an NCBITaxon CURIE"),
    ("data/raw/ncbitaxon_taxa.tsv", "taxon_id\tlabel\n", "has no rank, parent_id column"),
    ("data/raw/ncbi_merged_ids.tsv", "old_taxon_id\n", "has no current_taxon_id column"),
])
def test_a_malformed_taxonmech_tsv_is_refused_not_a_traceback(taxonmech, relative, content, message):
    (taxonmech / relative).write_text(content, encoding="utf-8")
    with pytest.raises(links.TaxonLinksError, match=message):
        links.TaxonIndex(taxonmech)


@pytest.mark.parametrize("content,message", [
    ("path: [\n", "cannot be parsed"),
    ("", "must be a mapping with a path"),
    ("snapshot: '2026-09-13'\n", "must be a mapping with a path"),
    ("- a list\n", "must be a mapping with a path"),
])
def test_a_malformed_taxdump_conf_is_refused_not_a_traceback(index, taxonmech, content, message):
    (taxonmech / "conf" / "ncbi_taxdump.yaml").write_text(content, encoding="utf-8")
    with pytest.raises(links.TaxonLinksError, match=message):
        judge(index, "NCBITaxon:511145")  # outside the inventory, so the taxdump is needed


def test_an_unknown_id_is_absent(index):
    assert judge(index, "NCBITaxon:424242").verdict is links.Verdict.ABSENT


@pytest.mark.parametrize("value", ["NCBITaxon:0", "NCBITaxon:", "taxon:562", "NCBITaxon:562 ", "NCBITaxon:562\n",
                                   "NCBITaxon:" + "1" * 5000, 562, None, ""])
def test_anything_but_a_curie_is_malformed(index, value):
    assert judge(index, value).verdict is links.Verdict.MALFORMED


def test_the_taxdump_is_read_only_for_taxa_the_inventory_lacks(taxonmech, monkeypatch):
    index = links.TaxonIndex(taxonmech)
    monkeypatch.setattr(links, "_dmp_rows", lambda *a, **k: (_ for _ in ()).throw(AssertionError("taxdump read")))
    assert judge(index, "NCBITaxon:562").verdict is links.Verdict.RECORD
    assert judge(index, "NCBITaxon:561").verdict is links.Verdict.ABOVE_SPECIES
    with pytest.raises(AssertionError, match="taxdump read"):
        judge(index, "NCBITaxon:511145")


def test_a_missing_taxonmech_file_is_a_clear_refusal(taxonmech):
    (taxonmech / "curation" / "seed_scope.tsv").unlink()
    with pytest.raises(links.TaxonLinksError, match="seed_scope.tsv"):
        links.TaxonIndex(taxonmech)


def test_names_come_from_the_inventory_or_the_taxdump_read_once(index, monkeypatch):
    assert index.names([562, 511145, 424242]) == {562: "Escherichia coli",
                                                    511145: "Escherichia coli str. K-12 substr. MG1655", 424242: ""}
    monkeypatch.setattr(links, "_dmp_rows", lambda *a, **k: (_ for _ in ()).throw(AssertionError("taxdump read again")))
    assert index.names([9606, 424242]) == {9606: "Homo sapiens", 424242: ""}


RECORD = {
    "id": "r1",
    "taxon_id": "NCBITaxon:562",
    "organisms": [{"term": {"id": "NCBITaxon:511145"}}, {"term": {"id": "NCBITaxon:46170"}}, {"note": "none"}],
    "graphs": [{"nodes": [{"examples": [{"taxon_id": "NCBITaxon:9606"}, {"taxon_id": "NCBITaxon:9606"}]}]}],
}


def test_resolve_all_visits_every_list_element_and_skips_absent_keys():
    assert links.resolve_all(RECORD, "taxon_id") == ["NCBITaxon:562"]
    assert links.resolve_all(RECORD, "organisms[].term.id") == ["NCBITaxon:511145", "NCBITaxon:46170"]
    assert links.resolve_all(RECORD, "graphs[].nodes[].examples[].taxon_id") == ["NCBITaxon:9606", "NCBITaxon:9606"]
    assert links.resolve_all(RECORD, "organisms.term.id") == []  # a list is not a mapping
    assert links.resolve_all(RECORD, "missing[].x") == []
    assert links.resolve_all("not a record", "taxon_id") == []


@pytest.mark.parametrize("path", ["", "[]", "a[", "a.[].b", "a[][][", "a]].b", "a[]x", "[]a"])
def test_a_bad_slot_path_is_refused_before_any_record_is_read(path):
    with pytest.raises(links.TaxonLinksError):
        links.resolve_all({}, path)


def _corpus(tmp_path: Path, records: dict[str, object]) -> Path:
    root = tmp_path / "mech"
    for name, content in records.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content if isinstance(content, str) else yaml.safe_dump(content), encoding="utf-8")
    return root


SLOTS = ["taxon_id", "organisms[].term.id", "graphs[].nodes[].examples[].taxon_id"]


def test_collect_counts_occurrences_records_and_findings(tmp_path, index):
    root = _corpus(tmp_path, {
        "data/a.yaml": RECORD,
        "data/b.yaml": {"id": "r2", "taxon_id": "NCBITaxon:1386",
                        "organisms": [{"term": {"id": "NCBITaxon:bogus"}}, {"term": {"id": "GTDB:s__Escherichia coli"}}]},
        "data/c.yaml": "taxon_id: [unclosed",
    })

    report = links.collect("m", root, ["data/**/*.yaml"], SLOTS, index).as_dict(index)

    assert report["records"] == 2 and report["unreadable"] == ["data/c.yaml"]
    verdicts = report["verdicts"]
    assert verdicts["record"] == {"occurrences": 1, "records": 1, "distinct_taxa": 1}
    assert verdicts["species_of_strain"] == {"occurrences": 1, "records": 1, "distinct_taxa": 1}
    assert verdicts["retired"] == {"occurrences": 1, "records": 1, "distinct_taxa": 1}
    assert verdicts["outside_domain"] == {"occurrences": 2, "records": 1, "distinct_taxa": 1}
    assert verdicts["above_species"] == {"occurrences": 1, "records": 1, "distinct_taxa": 1}
    assert verdicts["malformed"] == {"occurrences": 1, "records": 1, "distinct_taxa": 0}
    assert report["findings"] == [
        {"record": "data/a.yaml", "slot": "organisms[].term.id", "value": "NCBITaxon:46170", "verdict": "retired",
         "taxon": 46170, "current": "NCBITaxon:1280", "current_verdict": "record"},
        {"record": "data/b.yaml", "slot": "organisms[].term.id", "value": "NCBITaxon:bogus", "verdict": "malformed",
         "taxon": None},
    ]
    assert report["resolvable"] == [{"taxon": "NCBITaxon:511145", "name": "Escherichia coli str. K-12 substr. MG1655",
                                     "occurrences": 1, "ancestor": "NCBITaxon:562", "ancestor_name": "Escherichia coli"}]
    # The GTDB id in a declared slot is neither a link nor a finding; it is counted so a mixed slot shows as one.
    assert report["slots"] == {"graphs[].nodes[].examples[].taxon_id": {"occurrences": 2},
                               "organisms[].term.id": {"occurrences": 3, "other_identifiers": 1},
                               "taxon_id": {"occurrences": 2}}


def test_findings_are_sorted_and_resolvable_is_most_cited_first(tmp_path, index):
    root = _corpus(tmp_path, {"data/a.yaml": {
        "z_slot": "NCBITaxon:999001", "a_slot": "NCBITaxon:46170",
        "strains": [{"id": "NCBITaxon:511145"}, {"id": "NCBITaxon:559292"}, {"id": "NCBITaxon:559292"},
                    {"id": "NCBITaxon:83333"}],  # cited once, like 511145, and after it: the tie breaks on the id
    }})

    report = links.collect("m", root, ["data/**/*.yaml"], ["z_slot", "a_slot", "strains[].id"], index).as_dict(index)

    assert [f["slot"] for f in report["findings"]] == ["a_slot", "z_slot"]
    assert [r["taxon"] for r in report["resolvable"]] == ["NCBITaxon:559292", "NCBITaxon:83333", "NCBITaxon:511145"]


def test_unattested_taxa_are_listed_most_cited_first(tmp_path, index):
    # 5833 and 1423 are cited once each, 5833 first in the record: the tie breaks on the id, not on arrival.
    root = _corpus(tmp_path, {"data/a.yaml": {"t": [{"id": "NCBITaxon:5833"}, {"id": "NCBITaxon:1423"},
                                                    {"id": "NCBITaxon:5478"}, {"id": "NCBITaxon:5478"}]}})

    report = links.collect("m", root, ["data/**/*.yaml"], ["t[].id"], index).as_dict(index)

    assert [r["taxon"] for r in report["unattested_microbial"]] == ["NCBITaxon:5478", "NCBITaxon:1423", "NCBITaxon:5833"]


def test_findings_need_no_taxdump_names(tmp_path, taxonmech, monkeypatch):
    """A corpus whose only out-of-inventory taxon is a retired id never opens the taxdump."""
    index = links.TaxonIndex(taxonmech)
    (taxonmech / "conf" / "ncbi_taxdump.yaml").unlink()
    root = _corpus(tmp_path, {"data/a.yaml": {"taxon_id": "NCBITaxon:46170"}})

    report = links.collect("m", root, ["data/**/*.yaml"], ["taxon_id"], index).as_dict(index)

    assert report["findings"][0]["verdict"] == "retired"


def test_a_null_value_is_neither_a_link_nor_a_finding(tmp_path, index):
    root = _corpus(tmp_path, {"data/a.yaml": {"taxon_id": None, "organisms": [{"term": {"id": None}}]}})

    report = links.collect("m", root, ["data/**/*.yaml"], ["taxon_id", "organisms[].term.id"], index).as_dict(index)

    assert report["slots"] == {} and report["findings"] == []
    assert all(v["occurrences"] == 0 for v in report["verdicts"].values())


def test_a_sample_reads_the_first_records_and_says_so(tmp_path, index):
    records = {f"data/{n}.yaml": {"taxon_id": "NCBITaxon:562"} for n in "abc"}
    root = _corpus(tmp_path, records)

    sampled = links.collect("m", root, ["data/**/*.yaml"], ["taxon_id"], index, sample=2).as_dict(index)
    whole = links.collect("m", root, ["data/**/*.yaml"], ["taxon_id"], index).as_dict(index)

    assert (sampled["records"], sampled["sample"]) == (2, 2)
    assert (whole["records"], whole["sample"]) == (3, None)


def test_collect_refuses_an_unusable_corpus_before_walking(tmp_path, index):
    root = _corpus(tmp_path, {"data/a.yaml": RECORD})
    with pytest.raises(links.TaxonLinksError, match="no taxon_links slots"):
        links.collect("m", root, ["data/**/*.yaml"], [], index)
    with pytest.raises(links.TaxonLinksError, match="no record globs"):
        links.collect("m", root, [], SLOTS, index)
    with pytest.raises(links.TaxonLinksError, match="bad slot path"):
        links.collect("m", root, ["data/**/*.yaml"], ["a["], index)
    empty = tmp_path / "empty"  # no record to trip over: only the check before the walk can refuse
    (empty / "data").mkdir(parents=True)
    with pytest.raises(links.TaxonLinksError, match="bad slot path"):
        links.collect("m", empty, ["data/**/*.yaml"], ["a["], index)
    with pytest.raises(links.TaxonLinksError, match="not a directory"):
        links.collect("m", root / "nowhere", ["data/**/*.yaml"], SLOTS, index)


def test_the_report_is_the_same_whatever_order_the_files_arrive_in(tmp_path, index):
    records = {f"data/{n}.yaml": {"taxon_id": f"NCBITaxon:{t}"} for n, t in
               (("z", 562), ("a", 511145), ("m", 46170), ("k", 9606))}
    first = links.collect("m", _corpus(tmp_path / "1", records), ["data/**/*.yaml"], ["taxon_id"], index).as_dict(index)
    reversed_records = dict(reversed(list(records.items())))
    second = links.collect("m", _corpus(tmp_path / "2", reversed_records), ["data/**/*.yaml"], ["taxon_id"],
                           index).as_dict(index)
    assert first == second
