"""What a KGX node/edge TSV must hold to, checked once for the fleet.

The companion to `kg_microbe_sssom`. Where SSSOM had three producers to
generalise from, KGX has one: CommunityMech exports `output/kgx/{nodes,edges}.tsv`
and validates them with a 184-line `validate_kgx.py`. Building a shared
*exporter* from a single implementation is the trap #180 named, so this is a
shared *validator* -- and unlike an exporter, a validator can be proved against
artifacts nobody wrote for it, which is what makes it worth having.

Two artifacts, and both fail, differently.

CommunityMech's own nodes.tsv is read as 1,007 rows by anything that splits on
newlines and 998 by Python's `csv` module. The file contains quote characters
that `csv` treats as opening a quoted field, so it swallows the following lines.
Nine rows of the fleet's own export mean different things to the two most
obvious readers.

kg-microbe's merged edge file -- vendored into CommunityMech at
`app/kgm/merged-kg_edges.tsv` -- carries a bare carriage return inside its
header, immediately after a duplicated `agent_type` column:

    id\\tsubject\\tpredicate\\tobject\\trelation\\tagent_type\\tagent_type\\r\\tknowledge_level...

`awk` sees eleven columns. Python's text mode treats the `\\r` as a line
terminator and sees **seven**, so every field past `agent_type` silently
misaligns for any Python consumer. Nothing reports this: the file opens, parses,
and yields plausible rows.

That file contains exactly one bare CR, and CommunityMech's own exports contain
none -- they are CRLF throughout, which is a line ending and not a defect. The
first version of this module did not distinguish the two and reported every row
of a healthy file, which is the failure that makes a checker ignorable.

So the rules here are mostly about a file meaning the same thing to whoever
reads it. Column names, required fields and dangling edges matter too, but a
disagreement between readers is the one that corrupts quietly.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

__all__ = [
    "EDGE_REQUIRED",
    "Finding",
    "KgxProfile",
    "NODE_REQUIRED",
    "Table",
    "check_edges",
    "check_graph",
    "check_nodes",
    "read_table",
]

#: KGX requires an identifier and a category on a node, and a triple on an edge.
#: A subset rather than an exact list: CommunityMech writes five node columns and
#: kg-microbe's merged graph writes ten, and both are valid KGX.
NODE_REQUIRED = ("id", "category")
EDGE_REQUIRED = ("subject", "predicate", "object")

_CURIE = re.compile(r"^[A-Za-z][A-Za-z0-9._-]*:\S")


@dataclass(frozen=True)
class Finding:
    code: str
    detail: str
    row: int | None = None

    def __str__(self) -> str:
        where = f" (row {self.row})" if self.row is not None else ""
        return f"{self.code}: {self.detail}{where}"


@dataclass
class Table:
    columns: tuple[str, ...] = ()
    rows: list[list[str]] = field(default_factory=list)
    #: Rows as the `csv` module sees them, which is not always the same number.
    csv_row_count: int = 0
    header_has_cr: bool = False
    rows_with_cr: int = 0


@dataclass(frozen=True)
class KgxProfile:
    """The per-Mech half."""

    #: Categories and predicates are expected to be biolink CURIEs. kg-microbe's
    #: merged graph also carries METPO predicates, so a Mech that contributes
    #: those declares them rather than being told it is wrong.
    extra_prefixes: tuple[str, ...] = ()
    require_biolink: bool = True


def read_table(path: Path) -> Table:
    """Read a KGX TSV twice, deliberately.

    Once by splitting lines on the newline, which is what `awk`, `cut` and most
    pipelines do; and once through Python's `csv` module, which is what most
    Python consumers do. The row counts should agree. Where they do not, the
    file means two different things and one of the readers is silently wrong.
    """
    raw = Path(path).read_bytes()
    # CRLF is a line ending, not a defect. Stripping it before looking for a
    # stray CR is the whole distinction: CommunityMech's exports are CRLF
    # throughout -- 999 CR, 999 CRLF, none bare -- and treating those as
    # corruption reported every row of a healthy file.
    normalised = raw.replace(b"\r\n", b"\n")
    text = normalised.decode("utf-8", errors="replace")
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()

    columns: tuple[str, ...] = ()
    rows: list[list[str]] = []
    header_has_cr = False
    rows_with_cr = 0
    if lines:
        header_has_cr = "\r" in lines[0]
        columns = tuple(lines[0].replace("\r", "").split("\t"))
        for line in lines[1:]:
            if "\r" in line:
                rows_with_cr += 1
            rows.append(line.replace("\r", "").split("\t"))
    # Anything left is a CR that was not a line ending.

    csv_rows = 0
    with Path(path).open(encoding="utf-8", errors="replace", newline="") as handle:
        reader = csv.reader(handle, delimiter="\t")
        for index, _ in enumerate(reader):
            if index:
                csv_rows += 1

    return Table(
        columns=columns,
        rows=rows,
        csv_row_count=csv_rows,
        header_has_cr=header_has_cr,
        rows_with_cr=rows_with_cr,
    )


def _shape_findings(table: Table, required: Sequence[str], what: str) -> list[Finding]:
    findings: list[Finding] = []
    if not table.columns:
        return [Finding("EMPTY_FILE", f"{what} file has no header")]

    missing = [c for c in required if c not in table.columns]
    if missing:
        findings.append(
            Finding("MISSING_REQUIRED_COLUMN", f"{what} lacks {missing}")
        )

    duplicated = sorted({c for c in table.columns if table.columns.count(c) > 1})
    if duplicated:
        findings.append(
            Finding(
                "DUPLICATE_COLUMN",
                f"{duplicated} named more than once, so a reader keying by name "
                f"cannot tell which is meant",
            )
        )

    if table.header_has_cr:
        findings.append(
            Finding(
                "CARRIAGE_RETURN_IN_HEADER",
                "a bare CR inside the header; Python's text mode ends the line "
                "there, so it reads fewer columns than awk and every field past "
                "the break misaligns without error",
            )
        )
    if table.rows_with_cr:
        findings.append(
            Finding(
                "CARRIAGE_RETURN_IN_ROWS",
                f"{table.rows_with_cr} row(s) contain a bare CR",
            )
        )

    if table.csv_row_count != len(table.rows):
        findings.append(
            Finding(
                "READERS_DISAGREE",
                f"{len(table.rows)} rows by line, {table.csv_row_count} by the csv "
                f"module -- a quote character is opening a field and swallowing "
                f"following lines, so the two most obvious readers see different data",
            )
        )

    width = len(table.columns)
    ragged = sum(1 for r in table.rows if len(r) != width)
    if ragged:
        findings.append(
            Finding(
                "NEWLINE_IN_FIELD",
                f"{ragged} physical line(s) do not have {width} field(s), which "
                f"is what a literal newline inside a field looks like to a "
                f"line-based reader -- CommunityMech has nine node descriptions "
                f"like this, some quoted and some not",
            )
        )
    return findings


def _column(table: Table, name: str, row: list[str]) -> str:
    try:
        return row[table.columns.index(name)].strip()
    except (ValueError, IndexError):
        return ""


def _prefix_ok(value: str, profile: KgxProfile) -> bool:
    if not profile.require_biolink:
        return bool(_CURIE.match(value))
    prefix = value.split(":", 1)[0]
    return prefix == "biolink" or prefix in profile.extra_prefixes


def check_nodes(table: Table, profile: KgxProfile | None = None) -> list[Finding]:
    profile = profile or KgxProfile()
    findings = _shape_findings(table, NODE_REQUIRED, "nodes")
    if not table.columns:
        return findings
    width = len(table.columns)
    seen: dict[str, int] = {}
    for number, row in enumerate(table.rows, start=1):
        if len(row) != width:
            # Not a row. It is a fragment of one, and judging its id or category
            # would report the same structural break several more times in
            # language that suggests separate defects.
            continue
        identifier = _column(table, "id", row)
        if not identifier:
            findings.append(Finding("EMPTY_IDENTIFIER", "node id is empty", row=number))
        elif not _CURIE.match(identifier):
            findings.append(
                Finding("NOT_A_CURIE", f"node id {identifier!r}", row=number)
            )
        else:
            first = seen.setdefault(identifier, number)
            if first != number:
                findings.append(
                    Finding(
                        "DUPLICATE_NODE_ID",
                        f"{identifier} already defined at row {first}",
                        row=number,
                    )
                )
        category = _column(table, "category", row)
        if category and not _prefix_ok(category, profile):
            findings.append(
                Finding("UNEXPECTED_CATEGORY", f"category {category!r}", row=number)
            )
    return findings


def check_edges(
    table: Table, node_ids: Iterable[str] = (), profile: KgxProfile | None = None
) -> list[Finding]:
    profile = profile or KgxProfile()
    findings = _shape_findings(table, EDGE_REQUIRED, "edges")
    if not table.columns:
        return findings
    known = set(node_ids)
    width = len(table.columns)
    dangling = 0
    for number, row in enumerate(table.rows, start=1):
        if len(row) != width:
            continue
        subject = _column(table, "subject", row)
        obj = _column(table, "object", row)
        predicate = _column(table, "predicate", row)
        for name, value in (("subject", subject), ("object", obj)):
            if not value:
                findings.append(
                    Finding("EMPTY_IDENTIFIER", f"{name} is empty", row=number)
                )
            elif known and value not in known:
                dangling += 1
        if predicate and not _prefix_ok(predicate, profile):
            findings.append(
                Finding("UNEXPECTED_PREDICATE", f"predicate {predicate!r}", row=number)
            )
    if dangling:
        findings.append(
            Finding(
                "DANGLING_EDGE",
                f"{dangling} endpoint(s) name a node the nodes file does not define",
            )
        )
    return findings


def check_graph(
    nodes_path: Path, edges_path: Path, profile: KgxProfile | None = None
) -> list[Finding]:
    nodes = read_table(nodes_path)
    edges = read_table(edges_path)
    findings = check_nodes(nodes, profile)
    identifiers = {
        _column(nodes, "id", row) for row in nodes.rows if _column(nodes, "id", row)
    }
    findings.extend(check_edges(edges, identifiers, profile))
    return findings


def summarise(findings: Sequence[Finding]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for finding in findings:
        counts[finding.code] = counts.get(finding.code, 0) + 1
    return counts
