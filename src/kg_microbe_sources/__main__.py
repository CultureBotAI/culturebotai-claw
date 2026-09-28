"""`kg-microbe-sources` -- validate catalogues and query shared sources."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from typing import Protocol

from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_fleet.roots import MechRootError, claw_root, resolve_mech_root
from kg_microbe_sources.catalogue import CatalogueError, load_blocks, validate
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

CLAW_ROOT = claw_root()


class ImodulonDB(Protocol):
    def organism_datasets(self) -> tuple[OrganismDatasets, ...]: ...

    def search(self, organism_id: str, dataset: str, query: str) -> SearchResults: ...

    def imodulon_genes(
        self, organism_id: str, dataset: str, k: int
    ) -> ImodulonGeneTable: ...


def main(
    argv: list[str] | None = None,
    *,
    imodulondb_client: ImodulonDB | None = None,
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


if __name__ == "__main__":  # pragma: no cover - console entry point
    sys.exit(main())
