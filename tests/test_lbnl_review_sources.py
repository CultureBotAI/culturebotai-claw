"""Unit tests for ACS Figshare SI (.s001) probe and local provenance lookup (#1119)."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

import kg_microbe_sources.__main__ as sources_cli
from kg_microbe_sources import (
    AcsFigshareClient,
    AcsFigshareError,
    AcsSupportingFile,
    AcsSupportingInformation,
    TransportResult,
    ValidationFailed,
    access_ladder,
    author_request_draft,
    classify_provenance_path,
    clean_doi,
    derive_acs_si_doi,
    extract_citations_from_text,
    fetch_to_staging,
    is_valid_cas_rn,
    md5_of,
    normalize_acs_doi,
    normalize_doi,
    sanitize_supporting_filename,
    search_local_provenance,
    stage_acs_supporting_file,
    try_acs_figshare_si,
    try_acs_figshare_si_url,
    try_europepmc,
)
from kg_microbe_sources.__main__ import main


def test_normalize_acs_doi_and_derive_si_doi() -> None:
    assert (
        normalize_acs_doi("https://doi.org/10.1021/acschembio.8b00793.s001")
        == "10.1021/acschembio.8b00793"
    )
    assert (
        normalize_acs_doi("DOI: 10.1021/NP070366V")
        == "10.1021/np070366v"
    )
    assert (
        derive_acs_si_doi("10.1021/acschembio.8b00793")
        == "10.1021/acschembio.8b00793.s001"
    )
    assert (
        derive_acs_si_doi("10.1021/acschembio.8b00793", index=2)
        == "10.1021/acschembio.8b00793.s002"
    )

    with pytest.raises(AcsFigshareError, match="Expected an ACS DOI"):
        normalize_acs_doi("10.1016/j.bmc.2019.01.001")

    with pytest.raises(AcsFigshareError, match="SI index"):
        derive_acs_si_doi("10.1021/acschembio.8b00793", index=0)


def test_acs_figshare_client_probes_supporting_info() -> None:
    calls: list[tuple[str, Mapping[str, Any] | None]] = []

    def fake_transport(url: str, body: Mapping[str, Any] | None = None) -> Any:
        calls.append((url, body))
        if url.endswith("/articles/search"):
            assert body == {"search_for": ":doi: 10.1021/acschembio.8b00793.s001"}
            return [
                {
                    "id": 7297136,
                    "title": "Supporting Information for Metagenomic Discovery",
                    "doi": "10.1021/acschembio.8b00793.s001",
                    "url_public_html": "https://chemrxiv.org/articles/dataset/7297136",
                }
            ]
        if url.endswith("/articles/7297136"):
            assert body is None
            return {
                "id": 7297136,
                "title": "Supporting Information for Metagenomic Discovery",
                "doi": "10.1021/acschembio.8b00793.s001",
                "url_public_html": "https://chemrxiv.org/articles/dataset/7297136",
                "files": [
                    {
                        "id": 13470296,
                        "name": "cb8b00793_si_001.pdf",
                        "size": 1732419,
                        "download_url": "https://ndownloader.figshare.com/files/13470296",
                        "supplied_md5": "abc123def456",
                    }
                ],
            }
        raise AssertionError(f"unexpected URL: {url}")

    info = try_acs_figshare_si(
        "https://doi.org/10.1021/acschembio.8b00793",
        transport=fake_transport,
    )
    assert isinstance(info, AcsSupportingInformation)
    assert info.parent_doi == "10.1021/acschembio.8b00793"
    assert info.si_doi == "10.1021/acschembio.8b00793.s001"
    assert info.article_id == 7297136
    assert len(info.files) == 1
    assert info.files[0] == AcsSupportingFile(
        file_id=13470296,
        name="cb8b00793_si_001.pdf",
        size=1732419,
        download_url="https://ndownloader.figshare.com/files/13470296",
        supplied_md5="abc123def456",
    )
    assert len(calls) == 2


def test_stage_acs_supporting_file_writes_payload_and_sidecar(tmp_path: Path) -> None:
    payload_bytes = b"%PDF-1.4\n"
    si_file = AcsSupportingFile(
        file_id=13470296,
        name="cb8b00793_si_001.pdf",
        size=len(payload_bytes),
        download_url="https://ndownloader.figshare.com/files/13470296",
        supplied_md5=md5_of(payload_bytes),
    )

    def fake_fetch_transport(plan: Any, target: Path) -> TransportResult:
        target.write_bytes(payload_bytes)
        return TransportResult(resolved_url=plan.url, headers={"content-type": "application/pdf"})

    result = stage_acs_supporting_file(
        si_file,
        tmp_path / "acs-si",
        transport=fake_fetch_transport,
    )
    staged = tmp_path / "acs-si" / "cb8b00793_si_001.pdf"
    sidecar = tmp_path / "acs-si" / "cb8b00793_si_001.pdf.fetch.json"
    assert staged.is_file()
    assert sidecar.is_file()
    assert result.bytes == 9


def test_stage_acs_supporting_file_sanitizes_name_and_verifies_md5(tmp_path: Path) -> None:
    assert sanitize_supporting_filename("../nested/cb8b00793_si_001.pdf") == "cb8b00793_si_001.pdf"
    with pytest.raises(AcsFigshareError, match="Invalid Figshare supporting filename"):
        sanitize_supporting_filename("..")

    bad_si_file = AcsSupportingFile(
        file_id=13470296,
        name="../evil/cb8b00793_si_001.pdf",
        size=9,
        download_url="https://ndownloader.figshare.com/files/13470296",
        supplied_md5="deadbeef",
    )

    def fake_fetch_transport(plan: Any, target: Path) -> TransportResult:
        target.write_bytes(b"%PDF-1.4\n")
        return TransportResult(resolved_url=plan.url, headers={"content-type": "application/pdf"})

    with pytest.raises(ValidationFailed, match="MD5 mismatch"):
        stage_acs_supporting_file(
            bad_si_file,
            tmp_path / "acs-si-bad",
            transport=fake_fetch_transport,
        )
    assert not (tmp_path / "acs-si-bad" / "cb8b00793_si_001.pdf").exists()
    assert not (tmp_path / "acs-si-bad" / "cb8b00793_si_001.pdf.fetch.json").exists()


def test_extract_citations_and_search_local_provenance(tmp_path: Path) -> None:
    mech_root = tmp_path / "NaturalProductMech"
    (mech_root / "references_cache").mkdir(parents=True)
    (mech_root / "data" / "raw").mkdir(parents=True)
    (mech_root / "kb" / "compounds").mkdir(parents=True)

    # Even if references_cache is listed in .gitignore, search_local_provenance must scan it
    (mech_root / ".gitignore").write_text("references_cache/\n.temp/\n", encoding="utf-8")

    (mech_root / "references_cache" / "DOI_10.1021_acschembio.8b00793.md").write_text(
        "# Cached abstract\nDOI: 10.1021/acschembio.8b00793\nIsolated from Streptomyces.\n",
        encoding="utf-8",
    )
    (mech_root / "data" / "raw" / "lotus_occurrences.tsv").write_text(
        "inchikey\tdoi\ttaxon\n"
        "BLRBXZWBHXWECJ-XFFZJAGNSA-N\t10.1021/acschembio.8b00793\tNCBITaxon:1883\n",
        encoding="utf-8",
    )
    record_path = mech_root / "kb" / "compounds" / "NP001.yaml"
    record_path.write_text(
        "id: npmech:NP001\n"
        "standard_inchi_key: BLRBXZWBHXWECJ-XFFZJAGNSA-N\n"
        "references:\n"
        "  - reference: doi:10.1021/acschembio.8b00793\n"
        "  - reference: PMID:30303030\n"
        "xrefs:\n"
        "  - CHEBI:5530\n"
        "  - CAS-RN:113-73-5\n",
        encoding="utf-8",
    )

    tokens = extract_citations_from_text(
        record_path.read_text(encoding="utf-8") + "\n# date-like token: 2026-04-1\n"
    )
    assert "10.1021/acschembio.8b00793" in tokens
    assert "PMID:30303030" in tokens
    assert "CHEBI:5530" in tokens
    assert "BLRBXZWBHXWECJ-XFFZJAGNSA-N" in tokens
    assert "113-73-5" in tokens
    assert "2026-04-1" not in tokens
    assert is_valid_cas_rn("113-73-5") is True
    assert is_valid_cas_rn("68399-81-5") is True
    assert is_valid_cas_rn("2026-04-1") is False
    assert normalize_doi("https://doi.org/10.1021/ACSChemBio.8b00793.") == (
        "10.1021/acschembio.8b00793"
    )

    report = search_local_provenance(tokens, [mech_root])
    assert report.acs_dois == ("10.1021/acschembio.8b00793",)
    categories = {h.category for h in report.hits}
    assert "research_cache" in categories
    assert "raw_table" in categories
    assert "curated_record" in categories
    assert classify_provenance_path("curation/decisions.tsv") == "curation_table"
    assert classify_provenance_path(".temp/cas_common_chemistry_enriched.tsv") == "harvest_tsv"


def test_cli_acs_si_and_local_provenance(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    def fake_transport(url: str, body: Mapping[str, Any] | None = None) -> Any:
        if url.endswith("/articles/search"):
            return [{"id": 101, "doi": "10.1021/np070366v.s001", "title": "SI"}]
        return {
            "id": 101,
            "doi": "10.1021/np070366v.s001",
            "title": "SI for NP070366V",
            "url_public_html": "https://figshare.com/articles/dataset/101",
            "files": [
                {
                    "id": 555,
                    "name": "np070366v_si_001.pdf",
                    "size": 1024,
                    "download_url": "https://ndownloader.figshare.com/files/555",
                    "supplied_md5": "111222",
                }
            ],
        }

    client = AcsFigshareClient(transport=fake_transport)
    rc = main(
        ["acs-si", "--doi", "10.1021/np070366v", "--json"],
        acs_figshare_client=client,
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["si_doi"] == "10.1021/np070366v.s001"
    assert payload["files"][0]["name"] == "np070366v_si_001.pdf"

    rec_file = tmp_path / "rec.yaml"
    rec_file.write_text("ref: DOI:10.1021/np070366v\n", encoding="utf-8")
    rc_prov = main(
        ["local-provenance", "--record", str(rec_file), "--root", str(tmp_path), "--json"]
    )
    assert rc_prov == 0
    prov_payload = json.loads(capsys.readouterr().out)
    assert prov_payload["acs_dois"] == ["10.1021/np070366v"]
    assert prov_payload["hit_count"] == 1

    # Unsafe filename during --dest-dir staging returns exit code 2 and prints to stderr (#1182)
    def bad_name_transport(url: str, body: Mapping[str, Any] | None = None) -> Any:
        if url.endswith("/articles/search"):
            return [{"id": 102, "doi": "10.1021/np070366v.s001", "title": "SI"}]
        return {
            "id": 102,
            "doi": "10.1021/np070366v.s001",
            "title": "SI",
            "url_public_html": "https://figshare.com/articles/dataset/102",
            "files": [
                {
                    "id": 556,
                    "name": "..",
                    "size": 8,
                    "download_url": "https://ndownloader.figshare.com/files/556",
                    "supplied_md5": "",
                }
            ],
        }

    bad_client = AcsFigshareClient(transport=bad_name_transport)
    rc_bad = main(
        ["acs-si", "--doi", "10.1021/np070366v", "--dest-dir", str(tmp_path / "stage")],
        acs_figshare_client=bad_client,
    )
    assert rc_bad == 2
    assert "Invalid Figshare supporting filename" in capsys.readouterr().err


def test_fulltext_access_ladder_and_cli(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert clean_doi("https://doi.org/10.1021/acschembio.8b00793") == "10.1021/acschembio.8b00793"
    assert (
        try_europepmc({"pmcid": "PMC12345", "isOpenAccess": "Y"})
        == "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC12345/fullTextXML"
    )
    assert try_europepmc({"pmcid": "PMC12345", "isOpenAccess": "N"}) is None

    # Refuse staging directly into references_cache/
    with pytest.raises(ValueError, match="Refusing to stage fulltext_access output"):
        fetch_to_staging(
            "zotero_local",
            "file:///tmp/paper.pdf",
            tmp_path / "references_cache" / "paper.pdf",
        )

    # Stage from local file:// URL
    local_pdf = tmp_path / "zotero_paper.pdf"
    local_pdf.write_bytes(b"%PDF-1.4\n")
    staged_pdf = fetch_to_staging(
        "zotero_local",
        f"file://{local_pdf.resolve()}",
        tmp_path / ".temp" / "staged.pdf",
    )
    assert staged_pdf.read_bytes() == b"%PDF-1.4\n"

    # ACS Figshare SI fallback in access_ladder when main article OA channels return None
    def fake_si_transport(url: str, body: Mapping[str, Any] | None = None) -> Any:
        if url.endswith("/articles/search"):
            return [{"id": 303, "doi": "10.1021/cb3002058.s001", "title": "SI"}]
        return {
            "id": 303,
            "doi": "10.1021/cb3002058.s001",
            "title": "SI for DesA",
            "url_public_html": "https://figshare.com/articles/dataset/303",
            "files": [
                {
                    "id": 908,
                    "name": "cb3002058_si_001.xlsx",
                    "size": 1024,
                    "download_url": "https://ndownloader.figshare.com/files/908",
                    "supplied_md5": "",
                },
                {
                    "id": 909,
                    "name": "cb3002058_si_001.pdf",
                    "size": 2048,
                    "download_url": "https://ndownloader.figshare.com/files/909",
                    "supplied_md5": "",
                },
            ],
        }

    si_client = AcsFigshareClient(transport=fake_si_transport)
    assert (
        try_acs_figshare_si_url("10.1021/cb3002058", client=si_client)
        == "https://ndownloader.figshare.com/files/909"
    )
    assert (
        try_acs_figshare_si_url("10.1021/cb3002058.s001", client=si_client)
        == "https://ndownloader.figshare.com/files/909"
    )

    def empty_files_transport(url: str, body: Mapping[str, Any] | None = None) -> Any:
        if url.endswith("/articles/search"):
            return [{"id": 304, "doi": "10.1021/cb3002058.s001", "title": "SI"}]
        return {
            "id": 304,
            "doi": "10.1021/cb3002058.s001",
            "title": "Empty SI",
            "url_public_html": "https://figshare.com/articles/dataset/304",
            "files": [],
        }

    empty_si_client = AcsFigshareClient(transport=empty_files_transport)
    assert try_acs_figshare_si_url("10.1021/cb3002058", client=empty_si_client) is None

    import kg_microbe_sources.fulltext_access as ft_mod

    monkeypatch.setattr(ft_mod, "try_zotero_local", lambda pmid=None, doi=None: None)
    monkeypatch.setattr(ft_mod, "try_europepmc", lambda rec: None)
    monkeypatch.setattr(ft_mod, "try_openalex_oa", lambda doi, pmid=None: None)
    monkeypatch.setattr(ft_mod, "try_biorxiv", lambda doi: None)
    monkeypatch.setattr(ft_mod, "try_osti", lambda doi, title=None: None)
    monkeypatch.setattr(ft_mod, "try_elsevier_tdm", lambda doi: None)
    monkeypatch.setattr(ft_mod, "try_springer_tdm", lambda doi: None)
    monkeypatch.setattr(ft_mod, "try_wiley_tdm", lambda doi: None)
    monkeypatch.setattr(ft_mod, "try_core", lambda doi, title: None)
    monkeypatch.setattr(
        sources_cli,
        "epmc_core",
        lambda pmid, doi: {
            "doi": doi,
            "pmid": "22906379",
            "title": "Desferrioxamine B Biosynthesis",
            "authorString": "Smith J",
        },
    )

    method, url = access_ladder(
        {"doi": "10.1021/cb3002058"},
        "10.1021/cb3002058",
        "Desferrioxamine B Biosynthesis",
        acs_client=si_client,
    )
    assert method == "acs_figshare_si"
    assert url == "https://ndownloader.figshare.com/files/909"

    rc = main(
        ["fulltext", "--doi", "10.1021/cb3002058", "--json"],
        acs_figshare_client=si_client,
    )
    assert rc == 0
    out_json = json.loads(capsys.readouterr().out)
    assert out_json["method"] == "acs_figshare_si"
    assert out_json["url"] == "https://ndownloader.figshare.com/files/909"

    # With --no-acs-si, falls through to none / author_request_draft (exit code 2)
    rc_none = main(
        ["fulltext", "--doi", "10.1021/cb3002058", "--no-acs-si"],
        acs_figshare_client=si_client,
    )
    assert rc_none == 2
    captured = capsys.readouterr()
    assert "NO_LEGAL_OA" in captured.err
    assert "author-request draft" in captured.out
    assert "Desferrioxamine B Biosynthesis" in author_request_draft(
        {"title": "Desferrioxamine B Biosynthesis", "authorString": "Smith J"},
        "10.1021/cb3002058",
    )

