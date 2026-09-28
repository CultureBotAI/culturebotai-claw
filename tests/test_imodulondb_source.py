"""iModulonDB source adapter normalization."""

from __future__ import annotations

from typing import Any

import pytest

from kg_microbe_sources.imodulondb import (
    ImodulonDBClient,
    ImodulonDBError,
    dataset_key,
    gene_key,
    imodulon_key,
    load_gene,
    load_imodulon_gene_table,
    load_organism_datasets,
    load_search_results,
)

DATASETS: list[dict[str, Any]] = [
    {
        "id": "e_coli",
        "name": "Escherichia coli",
        "description": "Escherichia coli dataset: modulome",
        "datasets": ["modulome", "precise1k"],
    },
    {
        "id": "s_aureus",
        "name": "Staphylococcus aureus",
        "description": "Staphylococcus aureus dataset: staph_precise108",
        "datasets": ["staph_precise108", "staph_precise165"],
    },
]


GENE: dict[str, Any] = {
    "gene_id": "b4062",
    "gene_name": "soxS",
    "gene_product": "DNA-binding transcriptional dual regulator SoxS",
    "cog": "Transcription",
    "start_pos": 4277060,
    "stop_pos": 4277383,
    "strand": "-",
    "operon": None,
    "uniprot_id": "P0A9E2",
    "uniprot_protein_name": "Regulatory protein SoxS",
    "uniprot_function": "Transcriptional activator of the superoxide response regulon",
    "string_id": "511145.b4062",
    "external_links": None,
    "is_regulator": True,
}


GENE_TABLE: dict[str, Any] = {
    "genes": [
        {
            "gene_id": "b4062",
            "gene_locus": "b4062",
            "gene_name": "soxS",
            "gene_product": "DNA-binding transcriptional dual regulator SoxS",
            "weight": 0.262296982,
            "in_imodulon": True,
            "cog": "Transcription",
            "all_regulators": "AcrR, Fnr, Fur, Lrp, RpoD, SoxR, SoxS, mgrR",
            "start_pos": 4277060,
            "stop_pos": 4277383,
            "strand": "-",
            "string_id": "511145.b4062",
            "uniprot_id": "P0A9E2",
            "uniprot_protein_name": "Regulatory protein SoxS",
            "uniprot_function": "Transcriptional activator",
            "organism": "e_coli",
            "dataset": "precise1k",
        },
        {
            "gene_id": "b2160",
            "gene_locus": "b2160",
            "gene_name": "yeiI",
            "gene_product": "putative sugar kinase YeiI",
            "weight": 0.01,
            "in_imodulon": False,
            "cog": "Carbohydrate transport and metabolism",
            "all_regulators": None,
            "start_pos": 2251700,
            "stop_pos": 2252788,
            "strand": "+",
            "string_id": None,
            "uniprot_id": None,
            "uniprot_protein_name": None,
            "uniprot_function": None,
            "organism": "e_coli",
            "dataset": "precise1k",
        },
    ],
    "threshold": "0.030026006",
}


SEARCH: dict[str, Any] = {
    "genes": [
        {
            "gene_id": "b0683",
            "gene_name": "fur",
            "gene_product": "DNA-binding%2C transcriptional dual regulator Fur",
            "matched_field": "gene_name",
            "matched_value": "fur",
        }
    ],
    "imodulons": [
        {
            "k": 54,
            "name": "Fur-1",
            "regulator": ["Fur"],
            "function": (
                "Iron sensing and uptake, enterobactin biosynthesis, "
                "iron-sulfur cluster activation, iron sequestration"
            ),
            "category": "Metal Homeostasis",
            "matched_field": "name",
            "matched_value": "Fur-1",
        }
    ],
}


def test_dataset_keys_are_organism_scoped():
    organisms = load_organism_datasets(DATASETS)

    assert organisms[0].organism_id == "e_coli"
    assert organisms[0].dataset_keys == ("e_coli/modulome", "e_coli/precise1k")


def test_gene_payload_keeps_external_accessions():
    gene = load_gene(GENE)

    assert gene.gene_id == "b4062"
    assert gene.gene_name == "soxS"
    assert gene.uniprot_id == "P0A9E2"
    assert gene.string_id == "511145.b4062"
    assert gene.is_regulator is True


def test_imodulon_gene_table_keeps_weights_and_thresholds():
    table = load_imodulon_gene_table(GENE_TABLE)

    assert table.threshold == pytest.approx(0.030026006)
    assert [gene.gene_id for gene in table.in_imodulon] == ["b4062"]
    assert table.genes[0].weight == pytest.approx(0.262296982)
    assert table.genes[1].all_regulators is None


def test_search_results_keep_component_numbers_dataset_local():
    results = load_search_results(SEARCH)

    assert results.genes[0].gene_id == "b0683"
    assert results.genes[0].gene_product == (
        "DNA-binding, transcriptional dual regulator Fur"
    )
    assert results.imodulons[0].k == 54
    assert results.imodulons[0].regulator == ("Fur",)
    assert (
        results.imodulons[0].stable_key("e_coli", "precise1k")
        == "e_coli/precise1k/54"
    )


def test_stable_keys_include_every_source_namespace():
    assert dataset_key("e_coli", "precise1k") == "e_coli/precise1k"
    assert imodulon_key("e_coli", "precise1k", 22) == "e_coli/precise1k/22"
    assert gene_key("e_coli", "precise1k", "b4062") == "e_coli/precise1k/b4062"


def test_unexpected_payloads_name_the_bad_field():
    with pytest.raises(ImodulonDBError, match=r"genes\[0\].weight"):
        load_imodulon_gene_table(
            {"threshold": 1, "genes": [{**GENE_TABLE["genes"][0], "weight": True}]}
        )


def test_client_builds_the_public_api_urls():
    seen: list[str] = []

    def transport(url: str):
        seen.append(url)
        if url.endswith("/api/datasets"):
            return DATASETS
        if url.endswith("/api/genes/e_coli/precise1k/b4062"):
            return GENE
        if url.endswith("/api/imodulons/e_coli/precise1k/22/genes"):
            return GENE_TABLE
        if url.endswith("/api/search?organism=e_coli&dataset=precise1k&query=fur"):
            return SEARCH
        raise AssertionError(url)

    client = ImodulonDBClient(base_url="https://example.org/", transport=transport)

    assert client.organism_datasets()[0].organism_id == "e_coli"
    assert client.gene("e_coli", "precise1k", "b4062").gene_name == "soxS"
    assert client.imodulon_genes("e_coli", "precise1k", 22).in_imodulon
    assert client.search("e_coli", "precise1k", "fur").imodulons[0].name == "Fur-1"
    assert seen == [
        "https://example.org/api/datasets",
        "https://example.org/api/genes/e_coli/precise1k/b4062",
        "https://example.org/api/imodulons/e_coli/precise1k/22/genes",
        "https://example.org/api/search?organism=e_coli&dataset=precise1k&query=fur",
    ]


def test_client_quotes_path_segments_and_query_strings():
    seen: list[str] = []

    def transport(url: str):
        seen.append(url)
        return GENE

    ImodulonDBClient(base_url="https://example.org", transport=transport).gene(
        "e/coli", "precise 1k", "b/4062"
    )

    assert seen == ["https://example.org/api/genes/e%2Fcoli/precise%201k/b%2F4062"]


class FakeImodulonDB:
    def organism_datasets(self):
        return load_organism_datasets(DATASETS)

    def search(self, organism_id: str, dataset: str, query: str):
        assert (organism_id, dataset, query) == ("e_coli", "precise1k", "fur")
        return load_search_results(SEARCH)

    def imodulon_genes(self, organism_id: str, dataset: str, k: int):
        assert (organism_id, dataset, k) == ("e_coli", "precise1k", 22)
        return load_imodulon_gene_table(GENE_TABLE)


def test_cli_datasets_renders_dataset_scoped_keys(capsys):
    from kg_microbe_sources.__main__ import main

    code = main(["imodulondb", "datasets"], imodulondb_client=FakeImodulonDB())

    assert code == 0
    out = capsys.readouterr().out
    assert "# iModulonDB datasets" in out
    assert "`e_coli/modulome`" in out
    assert "`e_coli/precise1k`" in out
    assert "`s_aureus/staph_precise108`" in out


def test_cli_search_renders_dataset_scoped_keys(capsys):
    from kg_microbe_sources.__main__ import main

    code = main(
        [
            "imodulondb",
            "search",
            "--organism",
            "e_coli",
            "--dataset",
            "precise1k",
            "--query",
            "fur",
        ],
        imodulondb_client=FakeImodulonDB(),
    )

    assert code == 0
    out = capsys.readouterr().out
    assert "# iModulonDB search: `fur`" in out
    assert "`e_coli/precise1k/54`" in out
    assert "`e_coli/precise1k/b0683`" in out
    assert "Metal Homeostasis" in out


def test_cli_summarize_renders_member_genes_by_weight(capsys):
    from kg_microbe_sources.__main__ import main

    code = main(
        [
            "imodulondb",
            "summarize",
            "--organism",
            "e_coli",
            "--dataset",
            "precise1k",
            "--k",
            "22",
            "--limit",
            "1",
        ],
        imodulondb_client=FakeImodulonDB(),
    )

    assert code == 0
    out = capsys.readouterr().out
    assert "# iModulonDB iModulon `e_coli/precise1k/22`" in out
    assert "- genes in iModulon: 1" in out
    assert "- mapped UniProt accessions: 1" in out
    assert "`e_coli/precise1k/b4062`" in out
    assert "P0A9E2" in out
    assert "b2160" not in out
