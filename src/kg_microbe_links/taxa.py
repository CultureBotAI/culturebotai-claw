"""Judge every taxon a Mech's records cite against what TaxonMech holds.

A Mech names taxa in the slots its manifest `taxon_links` declaration lists.
Each cited `NCBITaxon` CURIE gets one verdict:

- `retired`: an id NCBI has merged into another, judged first, since TaxonMech's
  own scope still lists fourteen such ids; the record should cite the current
  id, whose own verdict is reported beside it;
- `record`: TaxonMech's seed scope holds it, so a link resolves to a record;
- `species_of_strain`: it is below species and its nearest ancestor that is a
  record (usually its species; a strain's forma or an unranked taxon in a few
  cases) holds it, so a link resolves up to that record, and should say so;
- `above_species`: a genus or higher, never a record by TaxonMech's rule;
- `outside_domain`: an animal, plant or virus, which TaxonMech's sources never
  attest, so TaxonMech is not where it resolves;
- `unplaced`: an entry at species rank or below under no cellular domain and
  not a virus: a metagenome, an uncultured or unclassified sequence, a vector;
- `unattested_microbial`: a bacterial, archaeal, fungal or protist species or
  strain that no TaxonMech source attests, the only kind a scope change could
  admit (TaxonMech holds protists: Plasmodium, Paramecium, diatoms);
- `absent`: an id the pinned taxdump does not contain;
- `malformed`: a value that is not an `NCBITaxon:<digits>` CURIE.

Everything is read from TaxonMech's checkout: `curation/seed_scope.tsv` (the
scope), `data/raw/ncbi_merged_ids.tsv` (merges; the only merge source, so a
verdict cannot change within a process), `data/raw/ncbitaxon_taxa.tsv`
(rank and parent for every attested taxon) and, only for taxa outside that
inventory, the NCBI taxdump snapshot `conf/ncbi_taxdump.yaml` pins. Nothing is
fetched, so the verdict is the same on a laptop and in CI. The taxdump's nodes
and names are each read at most once per process, lazily, and cost tens of
seconds each.
"""

from __future__ import annotations

import csv
import re
import tarfile
import zlib
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Iterator, Sequence

import yaml

from kg_microbe_corpus.statistics import iter_records

CURIE = re.compile(r"^NCBITaxon:([1-9][0-9]*)$")
DOMAINS = {2: "Bacteria", 2157: "Archaea", 2759: "Eukaryota", 10239: "Viruses"}
KINGDOMS = {4751: "Fungi", 33090: "Viridiplantae", 33208: "Metazoa"}
MICROBIAL_DOMAINS = {"Bacteria", "Archaea"}
NON_MICROBIAL_KINGDOMS = {"Metazoa", "Viridiplantae"}
ROOT_TAXON = 1
SCOPE_PATH = "curation/seed_scope.tsv"
MERGED_PATH = "data/raw/ncbi_merged_ids.tsv"
INVENTORY_PATH = "data/raw/ncbitaxon_taxa.tsv"
TAXDUMP_CONF = "conf/ncbi_taxdump.yaml"


class TaxonLinksError(RuntimeError):
    """An input that cannot be judged: a missing TaxonMech file, a bad slot path."""


class Verdict(str, Enum):
    RECORD = "record"
    SPECIES_OF_STRAIN = "species_of_strain"
    ABOVE_SPECIES = "above_species"
    OUTSIDE_DOMAIN = "outside_domain"
    UNPLACED = "unplaced"
    UNATTESTED_MICROBIAL = "unattested_microbial"
    RETIRED = "retired"
    ABSENT = "absent"
    MALFORMED = "malformed"


@dataclass(frozen=True)
class Judgement:
    verdict: Verdict
    taxon: int | None = None
    name: str = ""
    rank: str = ""
    domain: str = ""
    kingdom: str = ""
    current: int | None = None  # for RETIRED: the id it merged into
    current_verdict: Verdict | None = None
    ancestor: int | None = None  # for SPECIES_OF_STRAIN: the in-scope ancestor
    ancestor_name: str = ""


def _dmp_rows(tar_path: Path, member: str) -> Iterator[list[str]]:
    """Rows of one taxdump member. Every way the archive can be unusable is a TaxonLinksError, so one accessor decides."""
    if not tar_path.is_file():
        raise TaxonLinksError(f"TaxonMech's pinned taxdump {tar_path} is not present")
    try:
        with tarfile.open(tar_path, "r:gz") as tar:
            try:
                handle = tar.extractfile(member)  # KeyError for an absent name; None for a non-file member
            except KeyError:
                handle = None
            if handle is None:
                raise TaxonLinksError(f"{tar_path} has no member {member}")
            for raw in handle:
                yield raw.decode("utf-8", "replace").rstrip("\t|\n").split("\t|\t")
    except (tarfile.TarError, EOFError, OSError, zlib.error) as exc:  # corrupt or truncated, at open or mid-stream
        raise TaxonLinksError(f"{tar_path} cannot be read as a gzipped tar: {exc}") from exc


def _int_id(curie: str) -> int:
    return int(curie.split(":", 1)[1])


class TaxonIndex:
    """What TaxonMech holds, read once from its checkout."""

    def __init__(self, taxonmech_root: Path) -> None:
        self.root = Path(taxonmech_root)
        self._nodes: dict[int, tuple[str, int]] | None = None  # taxdump, lazily
        self._names: dict[int, str] | None = None  # every scientific name in the taxdump, lazily
        self._inventory_names: dict[int, str] = {}
        self.scope = self._read_scope()
        self.merged = self._read_merged()
        self.inventory = self._read_inventory()  # taxon -> (rank, parent)

    def _require(self, relative: str) -> Path:
        path = self.root / relative
        if not path.is_file():
            raise TaxonLinksError(f"TaxonMech checkout {self.root} has no {relative}")
        return path

    def _read_scope(self) -> set[int]:
        with self._require(SCOPE_PATH).open(encoding="utf-8") as handle:
            return {_int_id(row["identifier"]) for row in csv.DictReader(handle, delimiter="\t")}

    def _read_merged(self) -> dict[int, int]:
        with self._require(MERGED_PATH).open(encoding="utf-8") as handle:
            return {_int_id(row["old_taxon_id"]): _int_id(row["current_taxon_id"])
                    for row in csv.DictReader(handle, delimiter="\t")}

    def _read_inventory(self) -> dict[int, tuple[str, int]]:
        inventory: dict[int, tuple[str, int]] = {}
        with self._require(INVENTORY_PATH).open(encoding="utf-8") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                taxon = _int_id(row["taxon_id"])
                parent = _int_id(row["parent_id"]) if row["parent_id"] else ROOT_TAXON
                inventory[taxon] = ((row["rank"] or "NO_RANK").lower().replace("_", " "), parent)
                self._inventory_names[taxon] = row["label"]
        return inventory

    @property
    def taxdump_path(self) -> Path:
        conf = yaml.safe_load(self._require(TAXDUMP_CONF).read_text(encoding="utf-8"))
        return self.root / conf["path"]

    def _taxdump_nodes(self) -> dict[int, tuple[str, int]]:
        if self._nodes is None:
            self._nodes = {int(f[0]): (f[2], int(f[1])) for f in _dmp_rows(self.taxdump_path, "nodes.dmp")}
        return self._nodes

    def node(self, taxon: int) -> tuple[str, int] | None:
        """(rank, parent) from the inventory, else from the taxdump, else None."""
        if taxon in self.inventory:
            return self.inventory[taxon]
        return self._taxdump_nodes().get(taxon)

    def _rank(self, taxon: int) -> str:
        node = self.node(taxon)
        return node[0] if node is not None else ""

    def lineage(self, taxon: int) -> list[int]:
        chain: list[int] = []
        seen: set[int] = set()
        while taxon != ROOT_TAXON and taxon not in seen:
            node = self.node(taxon)
            if node is None:
                break
            seen.add(taxon)
            chain.append(taxon)
            taxon = node[1]
        return chain

    def names(self, taxa: Sequence[int]) -> dict[int, str]:
        """Scientific names, from the inventory where present, else from the taxdump, read once (and refused like nodes)."""
        if self._names is None and any(t not in self._inventory_names for t in taxa):
            self._names = {int(f[0]): f[1] for f in _dmp_rows(self.taxdump_path, "names.dmp")
                           if f[3] == "scientific name"}
        taxdump_names = self._names or {}
        return {t: self._inventory_names.get(t) or taxdump_names.get(t, "") for t in taxa}

    def judge(self, value: Any) -> Judgement:
        if not isinstance(value, str) or not CURIE.match(value):
            return Judgement(Verdict.MALFORMED)
        taxon = _int_id(value)
        if taxon in self.merged:  # before the scope: TaxonMech's scope still lists some retired ids
            current = self.merged[taxon]
            inner = self.judge(f"NCBITaxon:{current}")
            return Judgement(Verdict.RETIRED, taxon, current=current, current_verdict=inner.verdict)
        if taxon in self.scope:
            return Judgement(Verdict.RECORD, taxon)
        node = self.node(taxon)
        if node is None:
            return Judgement(Verdict.ABSENT, taxon)
        rank, _ = node
        chain = self.lineage(taxon)
        domain = next((DOMAINS[a] for a in chain if a in DOMAINS), "other")
        kingdom = next((KINGDOMS[a] for a in chain if a in KINGDOMS), "")
        ancestor = next((a for a in chain[1:] if a in self.scope), None)
        below_species = rank != "species" and any(self._rank(a) == "species" for a in chain[1:])
        if ancestor is not None and below_species:
            return Judgement(Verdict.SPECIES_OF_STRAIN, taxon, rank=rank, domain=domain, kingdom=kingdom,
                             ancestor=ancestor)
        if rank != "species" and not below_species:
            return Judgement(Verdict.ABOVE_SPECIES, taxon, rank=rank, domain=domain, kingdom=kingdom)
        if domain == "other":
            return Judgement(Verdict.UNPLACED, taxon, rank=rank, domain=domain, kingdom=kingdom)
        if domain in MICROBIAL_DOMAINS or (domain == "Eukaryota" and kingdom not in NON_MICROBIAL_KINGDOMS):
            return Judgement(Verdict.UNATTESTED_MICROBIAL, taxon, rank=rank, domain=domain, kingdom=kingdom)
        return Judgement(Verdict.OUTSIDE_DOMAIN, taxon, rank=rank, domain=domain, kingdom=kingdom)


def resolve_all(record: Any, dotted: str) -> list[Any]:
    """Every value at a slot path. `a.b[].c` visits each element of list `b`; `[]` may repeat."""
    parts = dotted.split(".") if dotted else []
    if not parts:
        raise TaxonLinksError("a slot path must name at least one key")
    for part in parts:
        lists = part.count("[]")
        name = part[:len(part) - 2 * lists]
        if not name or "[" in name or "]" in name or part != name + "[]" * lists:
            raise TaxonLinksError(f"bad slot path {dotted!r}: each part is a key, optionally followed by [] per list")

    def descend(node: Any, lists: int, rest: list[str]) -> Iterator[Any]:
        if lists == 0:
            yield from walk(node, rest)
        elif isinstance(node, list):
            for element in node:
                yield from descend(element, lists - 1, rest)

    def walk(node: Any, remaining: list[str]) -> Iterator[Any]:
        if not remaining:
            yield node
            return
        head, rest = remaining[0], remaining[1:]
        lists = head.count("[]")
        name = head[:len(head) - 2 * lists]
        if not isinstance(node, dict) or name not in node:
            return
        yield from descend(node[name], lists, rest)

    return list(walk(record, parts))


@dataclass
class TaxonLinksReport:
    mech: str
    taxonmech_root: str
    scope_size: int
    sample: int | None = None
    slots: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))
    verdicts: dict[str, Counter] = field(default_factory=lambda: defaultdict(Counter))
    findings: list[dict] = field(default_factory=list)  # retired, absent, malformed: one per record x value
    resolvable: Counter = field(default_factory=Counter)  # taxon -> occurrences
    resolvable_ancestor: dict[int, int] = field(default_factory=dict)
    unattested: Counter = field(default_factory=Counter)
    unreadable: list[str] = field(default_factory=list)
    records: int = 0
    taxa_by_verdict: dict[str, set] = field(default_factory=lambda: defaultdict(set))

    def as_dict(self, index: TaxonIndex) -> dict:
        # Findings carry no name, so their taxa are not looked up: a corpus whose only
        # out-of-inventory taxa are retired ids never needs the taxdump's names.
        named = index.names(sorted(set(self.resolvable) | set(self.resolvable_ancestor.values()) | set(self.unattested)))
        return {
            "mech": self.mech,
            "taxonmech_root": self.taxonmech_root,
            "scope_size": self.scope_size,
            "sample": self.sample,
            "records": self.records,
            "unreadable": sorted(self.unreadable),
            "slots": {slot: dict(sorted(counter.items())) for slot, counter in sorted(self.slots.items())},
            "verdicts": {v.value: {"occurrences": self.verdicts[v.value]["occurrences"],
                                   "records": self.verdicts[v.value]["records"],
                                   "distinct_taxa": len(self.taxa_by_verdict[v.value])} for v in Verdict},
            "findings": sorted(self.findings, key=lambda f: (f["record"], f["slot"], f["value"])),
            "resolvable": [{"taxon": f"NCBITaxon:{t}", "name": named.get(t, ""), "occurrences": n,
                            "ancestor": f"NCBITaxon:{self.resolvable_ancestor[t]}",
                            "ancestor_name": named.get(self.resolvable_ancestor[t], "")}
                           for t, n in sorted(self.resolvable.items(), key=lambda kv: (-kv[1], kv[0]))],
            "unattested_microbial": [{"taxon": f"NCBITaxon:{t}", "name": named.get(t, ""), "occurrences": n}
                                     for t, n in sorted(self.unattested.items(), key=lambda kv: (-kv[1], kv[0]))],
        }


def collect(mech: str, root: Path, globs: Sequence[str], slots: Sequence[str], index: TaxonIndex, *,
            sample: int | None = None) -> TaxonLinksReport:
    """Walk one Mech's records and judge every taxon its declared slots hold."""
    root = Path(root)
    if not root.is_dir():
        raise TaxonLinksError(f"{mech}: {root} is not a directory")
    if not globs:
        raise TaxonLinksError(f"{mech}: no record globs declared; the manifest says which files are the corpus")
    if not slots:
        raise TaxonLinksError(f"{mech}: no taxon_links slots declared; the manifest says where the taxa are")
    for slot in slots:
        resolve_all({}, slot)  # a bad path fails before the walk, not on the first record
    report = TaxonLinksReport(mech=mech, taxonmech_root=str(index.root), scope_size=len(index.scope), sample=sample)
    for path, record in iter_records(root, globs, sample=sample):
        relative = path.relative_to(root).as_posix()
        if record is None:
            report.unreadable.append(relative)
            continue
        report.records += 1
        seen_in_record: set[str] = set()
        for slot in slots:
            for value in resolve_all(record, slot):
                if value is None:
                    continue
                if not (isinstance(value, str) and value.startswith("NCBITaxon:")):
                    # A declared slot may also hold other identifiers (a GTDB id, a
                    # CHEBI node); those are not taxon links and are not malformed.
                    report.slots[slot]["other_identifiers"] += 1
                    continue
                judgement = index.judge(value)
                verdict = judgement.verdict.value
                report.slots[slot]["occurrences"] += 1
                report.verdicts[verdict]["occurrences"] += 1
                if verdict not in seen_in_record:
                    report.verdicts[verdict]["records"] += 1
                    seen_in_record.add(verdict)
                if judgement.taxon is not None:
                    report.taxa_by_verdict[verdict].add(judgement.taxon)
                if judgement.verdict in (Verdict.RETIRED, Verdict.ABSENT, Verdict.MALFORMED):
                    finding = {"record": relative, "slot": slot, "value": str(value), "verdict": verdict,
                               "taxon": judgement.taxon}
                    if judgement.verdict is Verdict.RETIRED:
                        finding["current"] = f"NCBITaxon:{judgement.current}"
                        finding["current_verdict"] = (judgement.current_verdict or Verdict.ABSENT).value
                    report.findings.append(finding)
                elif judgement.verdict is Verdict.SPECIES_OF_STRAIN and judgement.taxon is not None:
                    report.resolvable[judgement.taxon] += 1
                    report.resolvable_ancestor[judgement.taxon] = judgement.ancestor or 0
                elif judgement.verdict is Verdict.UNATTESTED_MICROBIAL and judgement.taxon is not None:
                    report.unattested[judgement.taxon] += 1
    return report
