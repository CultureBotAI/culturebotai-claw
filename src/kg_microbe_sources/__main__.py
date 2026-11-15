"""`kg-microbe-sources` -- validate catalogues and query shared sources."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_fleet.roots import MechRootError, claw_root, resolve_mech_root
from kg_microbe_sources.acs_figshare import (
    AcsFigshareClient,
    AcsFigshareError,
    AcsSupportingInformation,
    stage_acs_supporting_file,
)
from kg_microbe_sources.catalogue import CatalogueError, load_blocks, validate
from kg_microbe_sources.fetch import FetchError
from kg_microbe_sources.fulltext_access import (
    FulltextResolution,
    access_ladder,
    author_request_draft,
    crossref_meta,
    epmc_core,
    fetch_to_staging,
)
from kg_microbe_sources.imodulondb import (
    DEFAULT_BASE_URL,
    ImodulonDBClient,
    ImodulonDBError,
    ImodulonGene,
    ImodulonGeneTable,
    OrganismDatasets,
    SearchResults,
    dataset_key,
    gene_key,
    imodulon_key,
)
from kg_microbe_sources.local_provenance import (
    extract_citations_from_text,
    search_local_provenance,
)

CLAW_ROOT = claw_root()


class ImodulonDB(Protocol):
    def organism_datasets(self) -> tuple[OrganismDatasets, ...]: ...

    def search(self, organism_id: str, dataset: str, query: str) -> SearchResults: ...

    def imodulon_genes(
        self, organism_id: str, dataset: str, k: int
    ) -> ImodulonGeneTable: ...


class AcsFigshare(Protocol):
    def probe_supporting_info(
        self, raw_doi: str, *, index: int = 1
    ) -> AcsSupportingInformation | None: ...


def main(
    argv: list[str] | None = None,
    *,
    imodulondb_client: ImodulonDB | None = None,
    acs_figshare_client: AcsFigshare | None = None,
) -> int:
    args = _parser().parse_args(argv)
    if args.command == "imodulondb":
        client = imodulondb_client or ImodulonDBClient(
            base_url=args.base_url, timeout=args.timeout
        )
        try:
            if args.imodulondb_command == "datasets":
                _print_imodulondb_datasets(client.organism_datasets())
                return 0
            if args.imodulondb_command == "search":
                _print_imodulondb_search(
                    client.search(args.organism, args.dataset, args.query),
                    organism=args.organism,
                    dataset=args.dataset,
                    query=args.query,
                )
                return 0
            if args.imodulondb_command == "summarize":
                _print_imodulon_summary(
                    client.imodulon_genes(args.organism, args.dataset, args.k),
                    organism=args.organism,
                    dataset=args.dataset,
                    k=args.k,
                    limit=args.limit,
                )
                return 0
        except ImodulonDBError as exc:
            print(str(exc), file=sys.stderr)
            return 2

    if args.command == "acs-si":
        acs_client = acs_figshare_client or AcsFigshareClient(timeout=args.timeout)
        try:
            info = acs_client.probe_supporting_info(args.doi, index=args.index)
            if info is None:
                print(f"No ACS Figshare Supporting Information found for {args.doi}")
                return 1
            if args.dest_dir is not None:
                for si_file in info.files:
                    stage_acs_supporting_file(si_file, args.dest_dir)
        except (AcsFigshareError, FetchError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        if args.json:
            print(json.dumps(info.to_dict(), indent=2))
        else:
            _print_acs_si(info)
        return 0

    if args.command == "local-provenance":
        return _run_local_provenance(args)

    if args.command == "fulltext":
        return _run_fulltext(args, acs_figshare_client=acs_figshare_client)

    return _check_catalogue(args)


def _parser() -> argparse.ArgumentParser:
    manifest = load_fleet_manifest()
    parser = argparse.ArgumentParser(
        prog="kg-microbe-sources",
        description=(
            "Validate Mech source catalogues and query shared curation sources."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    check = subparsers.add_parser(
        "check",
        help="validate a Mech download.yaml source catalogue",
        description=(
            "Validate a Mech's download.yaml source catalogue: every source "
            "names itself, its licence and its seeder, and every file of a "
            "multi-file source says which file it is."
        ),
    )
    check.add_argument(
        "--mech",
        required=True,
        choices=sorted(manifest.mechs),
        help="which Mech's catalogue to read",
    )
    check.add_argument(
        "--seeder-glob",
        default="seed_*.py",
        help=(
            "how this repository names its seeder scripts, for the "
            "unreferenced-seeder sweep (default: %(default)s)"
        ),
    )

    imodulondb = subparsers.add_parser(
        "imodulondb",
        help="query iModulonDB for organism/dataset/gene/iModulon evidence",
    )
    imodulondb.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help="iModulonDB base URL (default: %(default)s)",
    )
    imodulondb.add_argument(
        "--timeout",
        type=_positive_int,
        default=30,
        help="HTTP timeout in seconds (default: %(default)s)",
    )
    imodulondb_subparsers = imodulondb.add_subparsers(
        dest="imodulondb_command", required=True
    )

    imodulondb_subparsers.add_parser(
        "datasets",
        help="list covered organism/dataset pairs",
    )

    search = imodulondb_subparsers.add_parser(
        "search",
        help="search genes and iModulons in one organism/dataset",
    )
    _add_imodulondb_dataset_args(search)
    search.add_argument("--query", required=True, help="gene, regulator, or term to find")

    summarize = imodulondb_subparsers.add_parser(
        "summarize",
        help="summarize the in-component genes of one dataset-local iModulon",
    )
    _add_imodulondb_dataset_args(summarize)
    summarize.add_argument(
        "--k",
        type=int,
        required=True,
        help="dataset-local iModulon component number",
    )
    summarize.add_argument(
        "--limit",
        type=_positive_int,
        default=20,
        help="maximum in-iModulon genes to list by absolute weight",
    )

    acs_si = subparsers.add_parser(
        "acs-si",
        help="probe ACS Publications Figshare API v2 for <doi>.s001 Supporting Information",
        description=(
            "Query the public Figshare API v2 for an ACS article's child "
            "Supporting Information DOI (<doi>.s001) and optionally stage its "
            "files with SHA-256 provenance sidecars."
        ),
    )
    acs_si.add_argument(
        "--doi",
        required=True,
        help="ACS article DOI (e.g. 10.1021/acschembio.8b00793)",
    )
    acs_si.add_argument(
        "--index",
        type=_positive_int,
        default=1,
        help="SI suffix index (.s001 -> 1, default: %(default)s)",
    )
    acs_si.add_argument(
        "--timeout",
        type=_positive_int,
        default=30,
        help="HTTP timeout in seconds (default: %(default)s)",
    )
    acs_si.add_argument(
        "--dest-dir",
        type=Path,
        default=None,
        help="optional gitignored directory (e.g. .temp/acs-si/) to download SI files into",
    )
    acs_si.add_argument(
        "--json",
        action="store_true",
        help="emit JSON instead of Markdown",
    )

    local_prov = subparsers.add_parser(
        "local-provenance",
        help="search gitignore-independently across local Mech caches/raw tables for citations",
        description=(
            "Extract DOIs, PMIDs, CAS-RNs, ChEBI IDs, and Standard InChIKeys "
            "from a record file or explicit tokens and search local Mech "
            "research_notes/, references_cache/, data/raw/, and harvest TSVs."
        ),
    )
    local_prov.add_argument(
        "--record",
        type=Path,
        default=None,
        help="path to a Mech YAML/Markdown record to extract citations and chemical IDs from",
    )
    local_prov.add_argument(
        "--token",
        action="append",
        default=[],
        help="explicit DOI, PMID, CAS-RN, CHEBI ID, or InChIKey to search (repeatable)",
    )
    local_prov.add_argument(
        "--root",
        type=Path,
        action="append",
        default=[],
        help="directory or TSV file to search (repeatable; defaults to record repo root if omitted)",
    )
    local_prov.add_argument(
        "--max-hits-per-root",
        type=_positive_int,
        default=200,
        help="maximum hits to collect per root (default: %(default)s)",
    )
    local_prov.add_argument(
        "--json",
        action="store_true",
        help="emit JSON instead of Markdown",
    )

    fulltext = subparsers.add_parser(
        "fulltext",
        help="run the legal full-text discovery ladder for a DOI or PMID",
        description=(
            "Check local Zotero PDFs, Europe PMC OA, OpenAlex OA, bioRxiv/medRxiv, "
            "DOE OSTI.gov, LBNL publisher TDM APIs (Elsevier, Springer Nature, Wiley), "
            "CORE, and ACS Figshare Supporting Information (.s001) without disclosing "
            "personal email addresses."
        ),
    )
    ft_group = fulltext.add_mutually_exclusive_group(required=True)
    ft_group.add_argument("--pmid", help="PubMed ID to resolve")
    ft_group.add_argument("--doi", help="Article DOI to resolve")
    fulltext.add_argument("--title", default=None, help="fallback title for CORE search")
    fulltext.add_argument(
        "--fetch-to",
        type=Path,
        default=None,
        help="stage the resolved payload to this path (outside references_cache/)",
    )
    fulltext.add_argument(
        "--no-acs-si",
        action="store_true",
        help="skip ACS Figshare (.s001) Supporting Information fallback",
    )
    fulltext.add_argument(
        "--json",
        action="store_true",
        help="emit JSON instead of tab-delimited output",
    )

    return parser


def _add_imodulondb_dataset_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--organism", required=True, help="iModulonDB organism ID")
    parser.add_argument("--dataset", required=True, help="iModulonDB dataset folder")


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError("must be at least 1")
    return parsed


def _check_catalogue(args: argparse.Namespace) -> int:
    manifest = load_fleet_manifest()
    # A Mech without a catalogue is a recorded decision, not a missing file.
    # Reporting "No such file or directory" would read as breakage and say
    # nothing about why, where the manifest already carries the reason.
    capability = manifest.mechs[args.mech].capabilities.get("source_catalogue")
    if capability is None or not capability.is_enabled:
        reason = getattr(capability, "reason", "") or "not declared in the manifest"
        print(f"{args.mech} declares no source catalogue: {reason}")
        return 0

    try:
        root = resolve_mech_root(args.mech, claw_root=CLAW_ROOT)
    except MechRootError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    catalogue = root / "download.yaml"
    try:
        blocks = load_blocks(catalogue)
    except CatalogueError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    report = validate(
        blocks, seeder_dir=root / "scripts", seeder_glob=args.seeder_glob
    )

    statuses: dict[str, int] = {}
    for block in blocks:
        status = block.get("status") if isinstance(block, dict) else None
        if isinstance(status, str) and status:
            statuses[status] = statuses.get(status, 0) + 1
    summary = ", ".join(f"{n} {s}" for s, n in sorted(statuses.items()))
    print(f"{args.mech}/download.yaml: {len(blocks)} block(s) ({summary})")

    for finding in report.warnings:
        print(f"  WARN:  {finding}")
    for finding in report.errors:
        print(f"  ERROR: {finding}")

    if report.errors:
        print(f"\n{len(report.errors)} error(s).")
        return 1
    print(f"\nOK ({len(report.warnings)} warning(s)).")
    return 0


def _print_imodulondb_datasets(organisms: Sequence[OrganismDatasets]) -> None:
    print("# iModulonDB datasets")
    print()
    print("| key | organism | dataset | description |")
    print("|---|---|---|---|")
    for organism in organisms:
        for dataset in organism.datasets:
            print(
                "| "
                f"`{_md(dataset_key(organism.organism_id, dataset))}` | "
                f"{_md(organism.name)} | "
                f"{_md(dataset)} | "
                f"{_md(organism.description)} |"
            )


def _print_imodulondb_search(
    results: SearchResults,
    *,
    organism: str,
    dataset: str,
    query: str,
) -> None:
    print(f"# iModulonDB search: `{query}`")
    print()
    print(f"- dataset: `{organism}/{dataset}`")
    print(f"- genes: {len(results.genes)}")
    print(f"- iModulons: {len(results.imodulons)}")

    print()
    print("## iModulons")
    print()
    print("| key | name | regulators | category | function | match |")
    print("|---|---|---|---|---|---|")
    for imodulon_hit in results.imodulons:
        print(
            "| "
            f"`{_md(imodulon_key(organism, dataset, imodulon_hit.k))}` | "
            f"{_md(imodulon_hit.name)} | "
            f"{_md(', '.join(imodulon_hit.regulator))} | "
            f"{_md(imodulon_hit.category)} | "
            f"{_md(imodulon_hit.function)} | "
            f"{_md(_match(imodulon_hit.matched_field, imodulon_hit.matched_value))} |"
        )

    print()
    print("## Genes")
    print()
    print("| key | name | product | match |")
    print("|---|---|---|---|")
    for gene_hit in results.genes:
        print(
            "| "
            f"`{_md(gene_key(organism, dataset, gene_hit.gene_id))}` | "
            f"{_md(gene_hit.gene_name)} | "
            f"{_md(gene_hit.gene_product)} | "
            f"{_md(_match(gene_hit.matched_field, gene_hit.matched_value))} |"
        )


def _print_imodulon_summary(
    table: ImodulonGeneTable,
    *,
    organism: str,
    dataset: str,
    k: int,
    limit: int,
) -> None:
    member_genes = sorted(
        table.in_imodulon,
        key=lambda gene: abs(gene.weight),
        reverse=True,
    )
    shown = member_genes[:limit]
    regulators = _regulators(member_genes)
    uniprots = {gene.uniprot_id for gene in member_genes if gene.uniprot_id}

    print(f"# iModulonDB iModulon `{imodulon_key(organism, dataset, k)}`")
    print()
    print(f"- threshold: {_number(table.threshold)}")
    print(f"- total genes scored: {len(table.genes)}")
    print(f"- genes in iModulon: {len(member_genes)}")
    print(f"- mapped UniProt accessions: {len(uniprots)}")
    print(f"- regulators named by member rows: {_md(', '.join(regulators))}")

    print()
    print(f"## Top {len(shown)} Genes")
    print()
    print("| key | name | weight | UniProt | STRING | COG | regulators |")
    print("|---|---|---:|---|---|---|---|")
    for gene in shown:
        print(_gene_row(gene, organism, dataset))


def _regulators(genes: Sequence[ImodulonGene]) -> tuple[str, ...]:
    found: set[str] = set()
    for gene in genes:
        if gene.all_regulators:
            found.update(
                regulator.strip()
                for regulator in gene.all_regulators.split(",")
                if regulator.strip()
            )
    return tuple(sorted(found, key=str.casefold))


def _gene_row(gene: ImodulonGene, organism: str, dataset: str) -> str:
    return (
        "| "
        f"`{_md(gene_key(organism, dataset, gene.gene_id))}` | "
        f"{_md(gene.gene_name)} | "
        f"{_number(gene.weight)} | "
        f"{_md(gene.uniprot_id)} | "
        f"{_md(gene.string_id)} | "
        f"{_md(gene.cog)} | "
        f"{_md(gene.all_regulators)} |"
    )


def _match(field: str | None, value: str | None) -> str | None:
    if field and value:
        return f"{field}={value}"
    return value or field


def _number(value: float | None) -> str:
    if value is None:
        return ""
    return f"{value:.6g}"


def _md(value: object) -> str:
    if value is None or value == "":
        return ""
    return str(value).replace("\n", " ").replace("|", r"\|")


def _print_acs_si(info: AcsSupportingInformation) -> None:
    print(f"# ACS Supporting Information: `{info.si_doi}`")
    print()
    print(f"- parent DOI: `{info.parent_doi}`")
    print(f"- Figshare article ID: `{info.article_id}`")
    print(f"- title: {_md(info.title)}")
    print(f"- public URL: {info.url_public_html}")
    print(f"- files: {len(info.files)}")
    print()
    print("| file_id | name | size (bytes) | md5 | download_url |")
    print("|---:|---|---:|---|---|")
    for f in info.files:
        print(
            f"| `{f.file_id}` | `{_md(f.name)}` | {f.size} | "
            f"`{_md(f.supplied_md5)}` | {f.download_url} |"
        )


def _run_local_provenance(args: argparse.Namespace) -> int:
    tokens: list[str] = list(args.token or [])
    if args.record is not None:
        if not args.record.is_file():
            print(f"record file does not exist: {args.record}", file=sys.stderr)
            return 2
        text = args.record.read_text(encoding="utf-8", errors="replace")
        tokens.extend(extract_citations_from_text(text))

    if not tokens:
        print("provide at least one --token or a --record with citations", file=sys.stderr)
        return 2

    roots: list[Path] = list(args.root or [])
    if not roots:
        if args.record is not None:
            roots.append(args.record.resolve().parent)
        else:
            roots.append(Path.cwd())

    report = search_local_provenance(
        tokens,
        roots,
        max_hits_per_root=args.max_hits_per_root,
    )
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
        return 0

    print("# Local Provenance Lookup")
    print()
    print(f"- tokens queried: {len(report.tokens)} ({', '.join(f'`{t}`' for t in report.tokens)})")
    print(f"- ACS DOIs eligible for `.s001` Figshare SI probe: {len(report.acs_dois)}")
    for acs_doi in report.acs_dois:
        print(f"  - `{acs_doi}` -> `kg-microbe-sources acs-si --doi {acs_doi}`")
    print(f"- total hits: {len(report.hits)}")
    print()
    if report.hits:
        print("| root | category | path:line | token | snippet |")
        print("|---|---|---|---|---|")
        for hit in report.hits:
            print(
                f"| `{_md(hit.root)}` | `{hit.category}` | "
                f"`{_md(hit.relative_path)}:{hit.line_number}` | "
                f"`{_md(hit.matched_token)}` | {_md(hit.snippet)} |"
            )
    return 0


def _run_fulltext(
    args: argparse.Namespace,
    *,
    acs_figshare_client: AcsFigshare | None = None,
) -> int:
    rec = epmc_core(args.pmid, args.doi)
    doi = args.doi or rec.get("doi")
    if not rec.get("title"):
        rec = {**crossref_meta(doi), **rec}
    title = args.title or re.sub(r"<[^>]+>", "", str(rec.get("title", "") or ""))

    acs_client = (
        acs_figshare_client
        if isinstance(acs_figshare_client, AcsFigshareClient)
        else None
    )
    method, url = access_ladder(
        rec,
        doi,
        title,
        pmid=args.pmid,
        include_acs_si=not args.no_acs_si,
        acs_client=acs_client,
    )
    staged_str: str | None = None
    if url:
        if args.fetch_to is not None:
            try:
                saved = fetch_to_staging(method, url, args.fetch_to)
                staged_str = str(saved)
            except Exception as exc:
                print(str(exc), file=sys.stderr)
                return 2
        if args.json:
            res = FulltextResolution(
                method=method,
                url=url,
                doi=doi,
                pmid=args.pmid or rec.get("pmid"),
                title=title,
                staged_path=staged_str,
            )
            print(json.dumps(res.to_dict(), indent=2))
        else:
            print(f"ACCESS\t{method}\t{url}")
            if staged_str:
                print(f"SAVED\t{method}\t{staged_str}")
        return 0

    if args.json:
        res = FulltextResolution(
            method="none",
            url=None,
            doi=doi,
            pmid=args.pmid or rec.get("pmid"),
            title=title,
            staged_path=None,
        )
        print(json.dumps(res.to_dict(), indent=2))
        return 2

    print(
        "NO_LEGAL_OA\t(paywalled; no full text via Zotero / Europe PMC / OpenAlex / OSTI / TDM / CORE / ACS SI)",
        file=sys.stderr,
    )
    missing_keys = [
        k
        for k in (
            "ZOTERO_DATA_DIR",
            "ELSEVIER_API_KEY",
            "SPRINGER_API_KEY",
            "WILEY_TDM_TOKEN",
            "CORE_API_KEY",
        )
        if not os.environ.get(k)
    ]
    if missing_keys:
        print(
            f"  (optional API keys not set: {', '.join(missing_keys)})",
            file=sys.stderr,
        )
    print("\n--- author-request draft ---")
    print(author_request_draft(rec, doi))
    return 2


if __name__ == "__main__":  # pragma: no cover - console entry point
    sys.exit(main())
