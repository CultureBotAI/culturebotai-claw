"""The registry of in-place corpus writers, and the guard that keeps it honest.

Phase 3 items 2 and 5. The acceptance criterion is that every registered writer
either uses the shared transaction or carries a reviewed, time-bounded
exception, and that a new unmanaged writer cannot be added silently.

Scope is deliberately narrow and stated rather than inferred: this registry
tracks callers of the shared `write_yaml` record helper. That helper writes a
record dict straight to a path with `open(path, "w")`, so every caller is an
in-place, non-atomic corpus writer, and it is the concrete migration debt left
by keeping `write_yaml` when `classify_ingredient_type` moved to the
transaction.

It is NOT a general "does this script mutate a Mech" detector. Deciding that
needs dataflow analysis -- whether a write target derives from a Mech root --
and a regex approximation of it is wrong in both directions: a first attempt
here flagged `generate_mapping_taxonomy_report` (writes a report),
`fetch_pubmed_abstracts` (writes a cache), and `publish_sssom` (writes a temp
file) as corpus writers purely because each mentions a Mech root elsewhere.
Registering those would have asserted something false. The wider detector is
tracked separately; this covers the surface it can cover honestly.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

REGISTRY_FILENAME = "writers.yaml"
REGISTRY_VERSION = 1

# Detection is AST-based, generalizing the strongest of the five Mech writer
# audits (ProteinTraitsMech's, which resolves imports and inspects call nodes
# rather than matching text). The regex it replaces produced two defects in one
# session: a fixed-width `(?<!def )` lookbehind that read `def  write_yaml(` as
# a call (#171), and matching the NAME so a module defining its own same-named
# helper was registered as a corpus writer (#172). Both are classes a parser
# does not have.
SHARED_WRITER_MODULE = "classify_ingredient_type"
SHARED_WRITER_NAME = "write_yaml"

STATUSES = frozenset({"transaction", "exception"})


class RegistryError(ValueError):
    """The writer registry is malformed, or disagrees with the repository."""


@dataclass(frozen=True)
class WriterEntry:
    """One declared in-place corpus writer."""

    path: str
    status: str
    targets: str
    reason: str = ""
    review_by: date | None = None

    @property
    def uses_transaction(self) -> bool:
        return self.status == "transaction"


def _local_name_for_shared_writer(tree: ast.AST) -> str | None:
    """The local name the shared helper is bound to, or None if not imported.

    Follows `as` renaming, which text matching cannot: `from … import write_yaml
    as _w` then `_w(path, record)` is a call to the shared helper and reads
    nothing like one.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == SHARED_WRITER_MODULE:
            for alias in node.names:
                if alias.name == SHARED_WRITER_NAME:
                    return alias.asname or alias.name
    return None


def calls_shared_record_writer(source: str) -> bool:
    """Whether this module calls the shared `write_yaml` record helper.

    Both halves are required: the module must import the shared helper AND call
    it under whatever name it bound. A same-named local function is not the
    shared helper however identical the call site looks (#172), and a defining
    module is not a calling one (#171).
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return False

    local_name = _local_name_for_shared_writer(tree)
    if local_name is None:
        return False

    # A module-level def of the same name shadows the import from that point
    # on, so the binding no longer refers to the shared helper.
    shadowed = any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == local_name
        for node in tree.body
    )
    if shadowed:
        return False

    return any(
        isinstance(node, ast.Call) and getattr(node.func, "id", None) == local_name
        for node in ast.walk(tree)
    )


def discover_corpus_writers(root: Path) -> set[str]:
    """Every `write_yaml` caller under `root`, as repository-relative paths."""
    found: set[str] = set()
    for path in sorted((root / "scripts").glob("*.py")):
        try:
            source = path.read_text(encoding="utf-8")
        except OSError:  # pragma: no cover - unreadable file in a checkout
            continue
        if calls_shared_record_writer(source):
            found.add(str(path.relative_to(root)))
    return found


def parse_registry(data: Any) -> dict[str, WriterEntry]:
    """Validate a loaded registry document."""
    if not isinstance(data, dict):
        raise RegistryError("writer registry must be a YAML mapping")
    version = data.get("version")
    if version != REGISTRY_VERSION:
        raise RegistryError(
            f"unsupported writer registry version {version!r}; "
            f"expected {REGISTRY_VERSION}"
        )
    raw_writers = data.get("writers")
    if not isinstance(raw_writers, dict) or not raw_writers:
        raise RegistryError("writer registry requires a non-empty 'writers' mapping")

    entries: dict[str, WriterEntry] = {}
    for path, raw in raw_writers.items():
        if not isinstance(raw, dict):
            raise RegistryError(f"writer {path!r} must be a mapping")
        status = raw.get("status")
        if status not in STATUSES:
            raise RegistryError(
                f"writer {path!r} has status {status!r}; expected one of "
                f"{', '.join(sorted(STATUSES))}"
            )
        targets = raw.get("targets")
        if not isinstance(targets, str) or not targets.strip():
            raise RegistryError(f"writer {path!r} must declare what it targets")

        reason = raw.get("reason", "")
        review_by = raw.get("review_by")
        if status == "exception":
            # A time-bounded, reasoned exception -- not an indefinite opt-out.
            if not isinstance(reason, str) or not reason.strip():
                raise RegistryError(
                    f"writer {path!r} claims an exception without a reason"
                )
            if not isinstance(review_by, date):
                raise RegistryError(
                    f"writer {path!r} claims an exception without a review_by "
                    f"date; an untimed exception is a permanent one"
                )
        else:
            if review_by is not None:
                raise RegistryError(
                    f"writer {path!r} uses the transaction and needs no review_by"
                )
        entries[str(path)] = WriterEntry(
            path=str(path),
            status=status,
            targets=targets.strip(),
            reason=reason.strip() if isinstance(reason, str) else "",
            review_by=review_by if isinstance(review_by, date) else None,
        )
    return entries


def default_registry_path() -> Path:
    return Path(__file__).resolve().parent / REGISTRY_FILENAME


def load_registry(path: Path | None = None) -> dict[str, WriterEntry]:
    """Read and validate the packaged writer registry."""
    target = Path(path) if path is not None else default_registry_path()
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as exc:
        raise RegistryError(f"cannot read writer registry {target}: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise RegistryError(f"writer registry {target} is not valid YAML: {exc}") from exc
    return parse_registry(data)


def overdue(entries: dict[str, WriterEntry], today: date) -> list[WriterEntry]:
    """Exceptions whose review date has passed."""
    return sorted(
        (
            entry
            for entry in entries.values()
            if entry.status == "exception"
            and entry.review_by is not None
            and entry.review_by < today
        ),
        key=lambda entry: entry.path,
    )
