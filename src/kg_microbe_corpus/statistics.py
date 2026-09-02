"""Comparable corpus statistics for every Mech (#132 Phase 6, item 4).

The acceptance criterion is "every Mech can produce comparable corpus and
repository-health reports". Today the Mechs that have statistics scripts do not
compute the same things: CultureMech has three of them, MediaIngredientMech
two, ProteinTraitsMech one. Put side by side they answer different questions, so
there is nothing to compare.

ProteinTraitsMech's is the most developed, and reading it shows what is and is
not general. The shape -- walk the corpus, tabulate fields, emit deterministic
JSON -- is general. The fields are not: `trait_axis`, `mapping_status` and
`causal_graphs` are its own schema, matched by regexes compiled into the
script. So the fields are declared per Mech in the manifest, as a capability
setting, and everything else lives here once.

One deliberate difference from that script: it greps with `ripgrep` and falls
back to regex over raw bytes, which is fast and reads `trait_axis: X` inside a
comment or a quoted string as a value. This parses the YAML. A corpus report
that is quietly wrong is worse than one that takes longer, and `--sample` is
here for when the whole corpus is too slow to walk.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

import yaml

from kg_microbe_corpus.loader import safe_loader, soundness

# The fastest parser that behaves correctly *here*, decided by trying it once at
# import (#233, #263). CSafeLoader is ~16x faster -- 2,129 records a second
# against 134, roughly 77 minutes down to 7 across ProteinTraitsMech's corpus --
# and on some Linux builds it is broken two ways at once: a valid document
# raises ConstructorError, and a parse error is raised with a class named
# YAMLError that `except yaml.YAMLError` does not catch.
#
# #233 declined to ship the speed-up because that difference was unexplained.
# #263 explained it and reproduced it, and `loader.judge` now probes both
# failure modes at import, so the choice is made per platform rather than
# assumed. The `except yaml.YAMLError` below stays correct precisely because
# judge's second probe refuses any loader whose parse errors escape it.

__all__ = [
    "CorpusError",
    "CorpusReport",
    "FieldStats",
    "collect",
    "iter_records",
    "resolve_value",
]

MAX_TOP_VALUES = 10


class CorpusError(RuntimeError):
    """The corpus could not be read as declared."""


@dataclass(frozen=True)
class FieldStats:
    """How one declared field is populated across the corpus."""

    populated: int
    missing: int
    distinct: int
    top_values: tuple[tuple[str, int], ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "populated": self.populated,
            "missing": self.missing,
            "distinct": self.distinct,
            "top_values": [list(pair) for pair in self.top_values],
        }


@dataclass
class CorpusReport:
    mech: str
    records: int = 0
    bytes: int = 0
    unreadable: list[str] = field(default_factory=list)
    by_glob: dict[str, int] = field(default_factory=dict)
    fields: dict[str, FieldStats] = field(default_factory=dict)
    sampled: bool = False

    # Set by `collect` from the loader that actually did the reading. Not a
    # property re-deriving `soundness()` on demand: this must answer "what read
    # this corpus", and a report built without a read -- or rehydrated from
    # as_dict() on another machine -- would otherwise answer for whichever
    # machine happened to ask.
    parser: tuple[str, str] | None = None

    def parser_note(self) -> str:
        """One line naming the parser that read this corpus, and why that one.

        Deliberately absent from `as_dict()`. The parser is a fact about the
        machine, not about the corpus, and putting it in the artifact would make
        two identical corpora diff between a Linux runner and a laptop -- the
        property the docstring below exists to protect. #233 asks that a run
        taking minutes on one machine and an hour on another say why; it says so
        on stderr, where a person reads it, rather than in the diffable body.
        """
        if self.parser is None:
            return "parser not recorded: this report did not read a corpus"
        name, why = self.parser
        return f"parsed with {name}: {why}"

    def as_dict(self) -> dict[str, Any]:
        """Deterministic JSON: sorted keys, no timestamps, no absolute paths.

        A report that changes when nothing changed cannot be diffed between
        releases, which is most of what makes one worth keeping.
        """
        return {
            "mech": self.mech,
            "records": self.records,
            "bytes": self.bytes,
            "sampled": self.sampled,
            "unreadable": sorted(self.unreadable),
            "by_glob": dict(sorted(self.by_glob.items())),
            "fields": {
                name: stats.as_dict() for name, stats in sorted(self.fields.items())
            },
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), indent=2, sort_keys=True) + "\n"


def resolve_value(record: Any, dotted: str) -> Any:
    """Follow a dotted path, treating a list as "any element that has it".

    `ontology_mapping.ontology_id` is one path in one Mech and a list of them
    in another. Returning the first value found either way is what lets one
    declared field name mean the same thing across corpora.
    """
    node: Any = record
    for part in dotted.split("."):
        if isinstance(node, list):
            for element in node:
                if isinstance(element, dict) and part in element:
                    node = element[part]
                    break
            else:
                return None
        elif isinstance(node, dict):
            if part not in node:
                return None
            node = node[part]
        else:
            return None
    return node


def _populated(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, (str, list, dict, tuple, set)):
        return len(value) > 0
    return True


def _paths_by_glob(root: Path, globs: Sequence[str]) -> dict[str, list[Path]]:
    """Each pattern's matches, with each file attributed to the first that
    claims it.

    Globbing once. Re-globbing per record to decide which pattern a file came
    from is O(records x globs) filesystem calls, which on a few thousand
    records is the whole runtime.
    """
    claimed: set[Path] = set()
    by_glob: dict[str, list[Path]] = {}
    for pattern in globs:
        matches = []
        for path in sorted(root.glob(pattern)):
            if path.is_file() and path not in claimed:
                claimed.add(path)
                matches.append(path)
        by_glob[pattern] = matches
    return by_glob


def iter_records(
    root: Path,
    globs: Sequence[str],
    *,
    sample: int | None = None,
    paths_by_glob: dict[str, list[Path]] | None = None,
) -> Iterator[tuple[Path, Any]]:
    """Yield (path, parsed) for each record, in a stable order.

    Sorted, so a sample is the same sample on every machine and the report can
    be diffed. A file that will not parse is yielded as None rather than
    raising: one broken record must not hide the statistics for the rest, and
    the report names it.
    """
    root = Path(root)
    # Accepting the caller's listing matters at scale: globbing and sorting
    # ProteinTraitsMech's 429,271 records takes ~13s, and `collect` needs the
    # same listing to attribute each file to a glob. Doing it twice was most of
    # the runtime on that corpus.
    matched = paths_by_glob if paths_by_glob is not None else _paths_by_glob(root, globs)
    paths = [p for matches in matched.values() for p in matches]
    if sample is not None:
        paths = paths[:sample]
    # Resolved once. `safe_loader()` is cached and costs 76ns, so calling it
    # per record would add ~21ms across 429,271 -- immaterial. It is hoisted
    # because calling it inside the loop reads as though the loader could
    # differ between records, and it cannot.
    loader = safe_loader()
    for path in paths:
        try:
            yield path, yaml.load(  # noqa: S506 - loader is judged, not guessed
                path.read_text(encoding="utf-8"), Loader=loader
            )
        except (OSError, yaml.YAMLError):
            yield path, None


def collect(
    mech: str,
    root: Path,
    globs: Sequence[str],
    fields: Iterable[str] = (),
    *,
    sample: int | None = None,
) -> CorpusReport:
    """Walk one Mech's corpus and report it in the shape every Mech reports."""
    root = Path(root)
    if not root.is_dir():
        raise CorpusError(f"{mech}: {root} is not a directory")
    if not globs:
        raise CorpusError(
            f"{mech}: no record globs declared; the manifest says which files "
            f"are the corpus"
        )

    sound, why = soundness()
    report = CorpusReport(
        mech=mech,
        sampled=sample is not None,
        parser=("CSafeLoader" if sound else "SafeLoader", why),
    )
    counters: dict[str, Counter] = {name: Counter() for name in fields}
    populated: dict[str, int] = {name: 0 for name in counters}

    matched = _paths_by_glob(root, globs)
    owner = {
        path: pattern for pattern, matches in matched.items() for path in matches
    }
    for pattern in globs:
        report.by_glob[pattern] = 0

    for path, record in iter_records(
        root, globs, sample=sample, paths_by_glob=matched
    ):
        relative = path.relative_to(root).as_posix()
        report.bytes += path.stat().st_size
        report.by_glob[owner[path]] += 1
        if record is None:
            report.unreadable.append(relative)
            continue
        report.records += 1
        for name in counters:
            value = resolve_value(record, name)
            if _populated(value):
                populated[name] += 1
                counters[name][_as_key(value)] += 1

    for name, counter in counters.items():
        report.fields[name] = FieldStats(
            populated=populated[name],
            missing=report.records - populated[name],
            distinct=len(counter),
            # Ties broken by value, so the same corpus gives the same report on
            # every machine rather than whichever key Counter happened to hold.
            top_values=tuple(
                sorted(counter.items(), key=lambda item: (-item[1], item[0]))[
                    :MAX_TOP_VALUES
                ]
            ),
        )
    return report


def _as_key(value: Any) -> str:
    """A stable, readable key for a value of any shape."""
    if isinstance(value, str):
        return value
    if isinstance(value, (list, tuple, set)):
        return ", ".join(sorted(_as_key(item) for item in value))
    if isinstance(value, dict):
        return json.dumps(value, sort_keys=True)
    return str(value)
