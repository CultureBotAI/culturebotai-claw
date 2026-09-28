"""Small iModulonDB API adapter for Mech source enrichment.

iModulonDB's useful source-native identifiers are scoped: a dataset belongs to
an organism, an iModulon integer belongs to a dataset, and a gene locus belongs
to that organism/dataset namespace. This module keeps those keys explicit and
normalizes the public JSON shapes used by curation helpers.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

__all__ = [
    "DEFAULT_BASE_URL",
    "Gene",
    "ImodulonDBClient",
    "ImodulonDBError",
    "ImodulonGene",
    "ImodulonGeneTable",
    "OrganismDatasets",
    "SearchGeneHit",
    "SearchImodulonHit",
    "SearchResults",
    "dataset_key",
    "gene_key",
    "imodulon_key",
    "load_gene",
    "load_imodulon_gene_table",
    "load_organism_datasets",
    "load_search_results",
]

DEFAULT_BASE_URL = "https://imodulondb.org"


class ImodulonDBError(RuntimeError):
    """The iModulonDB API returned a shape this adapter cannot normalize."""


JsonTransport = Callable[[str], Any]


@dataclass(frozen=True)
class OrganismDatasets:
    """The `/api/datasets` entry for one organism."""

    organism_id: str
    name: str
    datasets: tuple[str, ...]
    description: str | None = None

    @property
    def dataset_keys(self) -> tuple[str, ...]:
        return tuple(dataset_key(self.organism_id, dataset) for dataset in self.datasets)


@dataclass(frozen=True)
class Gene:
    """The `/api/genes/{organism}/{dataset}/{gene}` payload."""

    gene_id: str
    gene_name: str | None = None
    gene_product: str | None = None
    cog: str | None = None
    start_pos: int | None = None
    stop_pos: int | None = None
    strand: str | None = None
    operon: str | None = None
    uniprot_id: str | None = None
    uniprot_protein_name: str | None = None
    uniprot_function: str | None = None
    string_id: str | None = None
    external_links: Any = None
    is_regulator: bool = False


@dataclass(frozen=True)
class ImodulonGene:
    """One row from `/api/imodulons/{organism}/{dataset}/{k}/genes`."""

    gene_id: str
    gene_locus: str | None
    gene_name: str | None
    gene_product: str | None
    weight: float
    in_imodulon: bool
    cog: str | None
    all_regulators: str | None
    start_pos: int | None
    stop_pos: int | None
    strand: str | None
    string_id: str | None
    uniprot_id: str | None
    uniprot_protein_name: str | None
    uniprot_function: str | None
    organism: str
    dataset: str


@dataclass(frozen=True)
class ImodulonGeneTable:
    """Genes and threshold for one source iModulon."""

    genes: tuple[ImodulonGene, ...]
    threshold: float | None

    @property
    def in_imodulon(self) -> tuple[ImodulonGene, ...]:
        return tuple(gene for gene in self.genes if gene.in_imodulon)


@dataclass(frozen=True)
class SearchGeneHit:
    gene_id: str
    gene_name: str | None
    gene_product: str | None
    matched_field: str | None
    matched_value: str | None


@dataclass(frozen=True)
class SearchImodulonHit:
    k: int
    name: str | None
    regulator: tuple[str, ...]
    function: str | None
    category: str | None
    matched_field: str | None
    matched_value: str | None

    def stable_key(self, organism_id: str, dataset: str) -> str:
        return imodulon_key(organism_id, dataset, self.k)


@dataclass(frozen=True)
class SearchResults:
    genes: tuple[SearchGeneHit, ...]
    imodulons: tuple[SearchImodulonHit, ...]


def dataset_key(organism_id: str, dataset: str) -> str:
    """Return iModulonDB's stable dataset key."""

    return f"{organism_id}/{dataset}"


def imodulon_key(organism_id: str, dataset: str, k: int) -> str:
    """Return iModulonDB's stable iModulon key.

    The integer component is only stable inside one organism/dataset pair.
    """

    return f"{dataset_key(organism_id, dataset)}/{k}"


def gene_key(organism_id: str, dataset: str, gene_id: str) -> str:
    """Return iModulonDB's stable gene key."""

    return f"{dataset_key(organism_id, dataset)}/{gene_id}"


def load_organism_datasets(payload: Any) -> tuple[OrganismDatasets, ...]:
    """Normalize `/api/datasets`."""

    entries = _sequence(payload, "/api/datasets")
    return tuple(_load_organism(entry, index) for index, entry in enumerate(entries))


def load_gene(payload: Any) -> Gene:
    """Normalize one `/api/genes/{organism}/{dataset}/{gene}` response."""

    raw = _mapping(payload, "gene")
    return Gene(
        gene_id=_required_string(raw, "gene_id", "gene"),
        gene_name=_optional_string(raw, "gene_name", "gene"),
        gene_product=_optional_string(raw, "gene_product", "gene"),
        cog=_optional_string(raw, "cog", "gene"),
        start_pos=_optional_int(raw, "start_pos", "gene"),
        stop_pos=_optional_int(raw, "stop_pos", "gene"),
        strand=_optional_string(raw, "strand", "gene"),
        operon=_optional_string(raw, "operon", "gene"),
        uniprot_id=_optional_string(raw, "uniprot_id", "gene"),
        uniprot_protein_name=_optional_string(raw, "uniprot_protein_name", "gene"),
        uniprot_function=_optional_string(raw, "uniprot_function", "gene"),
        string_id=_optional_string(raw, "string_id", "gene"),
        external_links=raw.get("external_links"),
        is_regulator=_optional_bool(raw, "is_regulator", "gene") or False,
    )


def load_imodulon_gene_table(payload: Any) -> ImodulonGeneTable:
    """Normalize one `/api/imodulons/{organism}/{dataset}/{k}/genes` response."""

    raw = _mapping(payload, "iModulon gene table")
    return ImodulonGeneTable(
        genes=tuple(
            _load_imodulon_gene(gene, index)
            for index, gene in enumerate(_sequence(raw.get("genes"), "genes"))
        ),
        threshold=_optional_float(raw, "threshold", "iModulon gene table"),
    )


def load_search_results(payload: Any) -> SearchResults:
    """Normalize `/api/search`."""

    raw = _mapping(payload, "search results")
    return SearchResults(
        genes=tuple(
            _load_search_gene(gene, index)
            for index, gene in enumerate(_sequence(raw.get("genes", ()), "genes"))
        ),
        imodulons=tuple(
            _load_search_imodulon(imodulon, index)
            for index, imodulon in enumerate(
                _sequence(raw.get("imodulons", ()), "imodulons")
            )
        ),
    )


class ImodulonDBClient:
    """Tiny public-API client with injectable JSON transport."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        transport: JsonTransport | None = None,
        timeout: int = 30,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.transport = transport or _UrlopenJsonTransport(timeout=timeout)

    def organism_datasets(self) -> tuple[OrganismDatasets, ...]:
        return load_organism_datasets(self.transport(self._url("api", "datasets")))

    def gene(self, organism_id: str, dataset: str, gene_id: str) -> Gene:
        return load_gene(
            self.transport(self._url("api", "genes", organism_id, dataset, gene_id))
        )

    def imodulon_genes(
        self, organism_id: str, dataset: str, k: int
    ) -> ImodulonGeneTable:
        return load_imodulon_gene_table(
            self.transport(
                self._url("api", "imodulons", organism_id, dataset, str(k), "genes")
            )
        )

    def search(self, organism_id: str, dataset: str, query: str) -> SearchResults:
        params = urllib.parse.urlencode(
            {"organism": organism_id, "dataset": dataset, "query": query}
        )
        return load_search_results(
            self.transport(f"{self._url('api', 'search')}?{params}")
        )

    def _url(self, *parts: str) -> str:
        encoded = [urllib.parse.quote(part.strip("/"), safe="") for part in parts]
        return f"{self.base_url}/{'/'.join(encoded)}"


class _UrlopenJsonTransport:
    def __init__(self, *, timeout: int) -> None:
        self.timeout = timeout

    def __call__(self, url: str) -> Any:
        request = urllib.request.Request(
            url,
            headers={
                "Accept": "application/json",
                "User-Agent": "kg-microbe-sources/1",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise ImodulonDBError(f"could not fetch {url}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise ImodulonDBError(f"iModulonDB returned non-JSON for {url}") from exc


def _load_organism(payload: Any, index: int) -> OrganismDatasets:
    context = f"organism[{index}]"
    raw = _mapping(payload, context)
    return OrganismDatasets(
        organism_id=_required_string(raw, "id", context),
        name=_required_string(raw, "name", context),
        description=_optional_string(raw, "description", context),
        datasets=tuple(
            _string_value(dataset, f"{context}.datasets[{dataset_index}]")
            for dataset_index, dataset in enumerate(
                _sequence(raw.get("datasets"), f"{context}.datasets")
            )
        ),
    )


def _load_imodulon_gene(payload: Any, index: int) -> ImodulonGene:
    context = f"genes[{index}]"
    raw = _mapping(payload, context)
    return ImodulonGene(
        gene_id=_required_string(raw, "gene_id", context),
        gene_locus=_optional_string(raw, "gene_locus", context),
        gene_name=_optional_string(raw, "gene_name", context),
        gene_product=_optional_string(raw, "gene_product", context),
        weight=_required_float(raw, "weight", context),
        in_imodulon=_required_bool(raw, "in_imodulon", context),
        cog=_optional_string(raw, "cog", context),
        all_regulators=_optional_string(raw, "all_regulators", context),
        start_pos=_optional_int(raw, "start_pos", context),
        stop_pos=_optional_int(raw, "stop_pos", context),
        strand=_optional_string(raw, "strand", context),
        string_id=_optional_string(raw, "string_id", context),
        uniprot_id=_optional_string(raw, "uniprot_id", context),
        uniprot_protein_name=_optional_string(raw, "uniprot_protein_name", context),
        uniprot_function=_optional_string(raw, "uniprot_function", context),
        organism=_required_string(raw, "organism", context),
        dataset=_required_string(raw, "dataset", context),
    )


def _load_search_gene(payload: Any, index: int) -> SearchGeneHit:
    context = f"genes[{index}]"
    raw = _mapping(payload, context)
    return SearchGeneHit(
        gene_id=_required_string(raw, "gene_id", context),
        gene_name=_optional_string(raw, "gene_name", context),
        gene_product=_optional_string(raw, "gene_product", context),
        matched_field=_optional_string(raw, "matched_field", context),
        matched_value=_optional_string(raw, "matched_value", context),
    )


def _load_search_imodulon(payload: Any, index: int) -> SearchImodulonHit:
    context = f"imodulons[{index}]"
    raw = _mapping(payload, context)
    return SearchImodulonHit(
        k=_required_int(raw, "k", context),
        name=_optional_string(raw, "name", context),
        regulator=tuple(
            _string_value(regulator, f"{context}.regulator[{regulator_index}]")
            for regulator_index, regulator in enumerate(
                _sequence(raw.get("regulator", ()), f"{context}.regulator")
            )
        ),
        function=_optional_string(raw, "function", context),
        category=_optional_string(raw, "category", context),
        matched_field=_optional_string(raw, "matched_field", context),
        matched_value=_optional_string(raw, "matched_value", context),
    )


def _mapping(payload: Any, context: str) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise ImodulonDBError(
            f"{context} must be a JSON object, got {type(payload).__name__}"
        )
    return payload


def _sequence(payload: Any, context: str) -> Sequence[Any]:
    if not isinstance(payload, list):
        raise ImodulonDBError(
            f"{context} must be a JSON list, got {type(payload).__name__}"
        )
    return payload


def _string_value(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise ImodulonDBError(f"{context} must be a non-empty string")
    return value


def _required_string(raw: Mapping[str, Any], key: str, context: str) -> str:
    return _string_value(raw.get(key), f"{context}.{key}")


def _optional_string(raw: Mapping[str, Any], key: str, context: str) -> str | None:
    value = raw.get(key)
    if value is None:
        return None
    return _string_value(value, f"{context}.{key}")


def _required_bool(raw: Mapping[str, Any], key: str, context: str) -> bool:
    value = raw.get(key)
    if not isinstance(value, bool):
        raise ImodulonDBError(f"{context}.{key} must be a boolean")
    return value


def _optional_bool(raw: Mapping[str, Any], key: str, context: str) -> bool | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise ImodulonDBError(f"{context}.{key} must be a boolean")
    return value


def _required_int(raw: Mapping[str, Any], key: str, context: str) -> int:
    value = raw.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ImodulonDBError(f"{context}.{key} must be an integer")
    return value


def _optional_int(raw: Mapping[str, Any], key: str, context: str) -> int | None:
    value = raw.get(key)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise ImodulonDBError(f"{context}.{key} must be an integer")
    return value


def _required_float(raw: Mapping[str, Any], key: str, context: str) -> float:
    value = raw.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ImodulonDBError(f"{context}.{key} must be a number")
    return float(value)


def _optional_float(raw: Mapping[str, Any], key: str, context: str) -> float | None:
    value = raw.get(key)
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError as exc:
            raise ImodulonDBError(f"{context}.{key} must be a number") from exc
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ImodulonDBError(f"{context}.{key} must be a number")
    return float(value)
