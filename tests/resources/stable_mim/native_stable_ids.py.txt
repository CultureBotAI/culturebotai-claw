"""Permanent MIM record identities and append-only mint/lifecycle ledgers (#1265).

Planning and validation are pure. Callers coordinate writes and persist the
returned TSV bytes with their validated ingredient batch; this module never
writes a registry or record. Mapping rejection is not identifier retirement.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

MIM_PREFIX = "https://culturebotai.github.io/MediaIngredientMech/ingredient/MIM_"
REGISTRY_PATH = Path("data/ids/mim_id_registry.tsv")
LIFECYCLE_PATH = Path("data/ids/mim_id_lifecycle.tsv")
MINT_COLUMNS = ("mim_id", "label_at_minting", "minted_on", "status", "replaced_by")
EVENT_COLUMNS = ("mim_id", "status", "replaced_by", "changed_at", "reason")
_ID = re.compile(r"MIM:[0-9]{7}\Z")


class StableIdError(ValueError):
    """A permanent identifier or its append-only history is invalid."""


def validate_id(value: Any) -> str:
    if not isinstance(value, str) or not _ID.fullmatch(value) or value == "MIM:0000000":
        raise StableIdError(f"Expected a positive seven-digit MIM identifier: {value!r}")
    return value


def resolver_url(mim_id: str) -> str:
    return MIM_PREFIX + validate_id(mim_id).split(":", 1)[1]


@dataclass(frozen=True)
class Mint:
    mim_id: str
    label_at_minting: str
    minted_on: str
    status: str = "active"
    replaced_by: str = ""


@dataclass(frozen=True)
class Lifecycle:
    mim_id: str
    status: str
    replaced_by: str
    changed_at: str
    reason: str


@dataclass(frozen=True)
class Registry:
    entries: tuple[Mint, ...] = ()
    events: tuple[Lifecycle, ...] = ()

    @property
    def states(self) -> dict[str, tuple[str, str]]:
        result = {row.mim_id: ("active", "") for row in self.entries}
        result.update({row.mim_id: (row.status, row.replaced_by) for row in self.events})
        return result


@dataclass(frozen=True)
class MintPlan:
    assignments: dict[str, str]
    registry: Registry


def _text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip() or any(c in value for c in "\t\r\n\x00"):
        raise StableIdError(f"{label} must be nonblank single-line text")
    return value


def _date(value: str) -> date:
    try:
        parsed = date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise StableIdError("Mint date must be YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise StableIdError("Mint date must be YYYY-MM-DD")
    return parsed


def _time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise StableIdError("Lifecycle time must be a timezone-aware UTC timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise StableIdError("Lifecycle time must be a timezone-aware UTC timestamp")
    return parsed


def validate_registry(registry: Registry) -> None:
    minted: dict[str, date] = {}
    previous_date: date | None = None
    for number, row in enumerate(registry.entries, 1):
        validate_id(row.mim_id)
        if row.mim_id != f"MIM:{number:07d}":
            raise StableIdError("Mint IDs must be sequential, unique, and never reused")
        _text(row.label_at_minting, "Mint label")
        stamp = _date(row.minted_on)
        if previous_date and stamp < previous_date:
            raise StableIdError("Mint dates cannot move backwards")
        previous_date = stamp
        if row.status != "active" or row.replaced_by:
            raise StableIdError(
                "Mint rows are immutable active declarations; append lifecycle events"
            )
        minted[row.mim_id] = stamp
    seen: set[str] = set()
    previous_time: datetime | None = None
    for event in registry.events:
        validate_id(event.mim_id)
        validate_id(event.replaced_by)
        if event.mim_id not in minted or event.replaced_by not in minted:
            raise StableIdError("Lifecycle references an unknown registered ID")
        if event.mim_id in seen:
            raise StableIdError("An ID already has a terminal lifecycle event; it cannot be reused")
        seen.add(event.mim_id)
        if event.status not in {"retired", "merged"}:
            raise StableIdError("Lifecycle status must be retired or merged")
        stamp = _time(event.changed_at)
        if previous_time and stamp < previous_time:
            raise StableIdError("Lifecycle event times cannot move backwards")
        previous_time = stamp
        if stamp.date() < max(minted[event.mim_id], minted[event.replaced_by]):
            raise StableIdError("Lifecycle event predates a referenced mint")
        _text(event.reason, "Lifecycle reason")
    states = registry.states
    for identifier in states:
        _resolve(states, identifier)


def _resolve(states: dict[str, tuple[str, str]], identifier: str) -> str:
    validate_id(identifier)
    visited: set[str] = set()
    while True:
        if identifier not in states:
            raise StableIdError(f"Unknown registered MIM ID: {identifier}")
        if identifier in visited:
            raise StableIdError("Lifecycle replacement chain contains a cycle")
        visited.add(identifier)
        status, replacement = states[identifier]
        if status == "active":
            return identifier
        identifier = replacement


def resolve_id(registry: Registry, identifier: str) -> str:
    validate_registry(registry)
    return _resolve(registry.states, identifier)


def _parse(raw: bytes, columns: tuple[str, ...]) -> list[dict[str, str]]:
    try:
        text = raw.decode("utf-8")
    except UnicodeError as exc:
        raise StableIdError("Registry must be UTF-8") from exc
    if not text.endswith("\n") or "\r" in text or "\x00" in text:
        raise StableIdError("Registry must use complete LF-terminated rows")
    lines = text.split("\n")[:-1]
    if not lines or lines[0].split("\t") != list(columns):
        raise StableIdError("Unexpected registry columns")
    rows = []
    for line in lines[1:]:
        values = line.split("\t")
        if len(values) != len(columns):
            raise StableIdError("Malformed registry row")
        rows.append(dict(zip(columns, values, strict=True)))
    return rows


def parse_registry(mint_bytes: bytes, lifecycle_bytes: bytes) -> Registry:
    registry = Registry(
        tuple(Mint(**row) for row in _parse(mint_bytes, MINT_COLUMNS)),
        tuple(Lifecycle(**row) for row in _parse(lifecycle_bytes, EVENT_COLUMNS)),
    )
    validate_registry(registry)
    return registry


def load_registry(root: Path) -> Registry:
    return parse_registry((root / REGISTRY_PATH).read_bytes(), (root / LIFECYCLE_PATH).read_bytes())


def _dump(rows: tuple, columns: tuple[str, ...]) -> bytes:
    lines = ["\t".join(columns)]
    lines.extend("\t".join(getattr(row, field) for field in columns) for row in rows)
    return ("\n".join(lines) + "\n").encode("utf-8")


def dump_registry(registry: Registry) -> bytes:
    validate_registry(registry)
    return _dump(registry.entries, MINT_COLUMNS)


def dump_lifecycle(registry: Registry) -> bytes:
    validate_registry(registry)
    return _dump(registry.events, EVENT_COLUMNS)


def allocate_ids(
    registry: Registry, records: Mapping[str, Mapping[str, Any]], *, minted_on: str
) -> MintPlan:
    """Plan missing IDs in lexicographic record-key order, retaining existing IDs.

    Keys should be exact repository-relative record paths at mint time. They are
    ordering inputs, not permanent identity; later renames retain each mim_id.
    Re-read the registry under the caller's write lock before applying a plan.
    """
    validate_registry(registry)
    _date(minted_on)
    entries = list(registry.entries)
    states = registry.states
    assignments: dict[str, str] = {}
    claimed: set[str] = set()
    for key in sorted(records):
        record = records[key]
        identifier = record.get("mim_id")
        if identifier is not None:
            validate_id(identifier)
            if identifier not in states or states[identifier][0] != "active":
                raise StableIdError("An existing record ID must be active in the registry")
        else:
            number = len(entries) + 1
            if number > 9_999_999:
                raise StableIdError("The seven-digit MIM identifier space is exhausted")
            identifier = f"MIM:{number:07d}"
            label = _text(record.get("preferred_term"), "Mint label")
            entries.append(Mint(identifier, label, minted_on))
        if identifier in claimed:
            raise StableIdError("Duplicate record MIM ID")
        claimed.add(identifier)
        assignments[key] = identifier
    result = Registry(tuple(entries), registry.events)
    validate_registry(result)
    return MintPlan(assignments, result)


def append_lifecycle(
    registry: Registry, *, mim_id: str, status: str, replaced_by: str, changed_at: str, reason: str
) -> Registry:
    """Plan one permanent terminal event; never rewrite a mint or earlier event."""
    result = Registry(
        registry.entries,
        (*registry.events, Lifecycle(mim_id, status, replaced_by, changed_at, reason)),
    )
    validate_registry(result)
    return result


def validate_records(registry: Registry, records: Mapping[str, Mapping[str, Any]]) -> None:
    validate_registry(registry)
    active = {key for key, (status, _) in registry.states.items() if status == "active"}
    found: set[str] = set()
    for path, record in records.items():
        identifier = validate_id(record.get("mim_id"))
        if identifier in found:
            raise StableIdError(f"Duplicate MIM ID {identifier}: {path}")
        if identifier not in active:
            raise StableIdError(f"Record uses an unknown or retired MIM ID: {identifier}")
        aliases = record.get("legacy_identifiers", [])
        if not isinstance(aliases, list) or any(
            not isinstance(value, str) or not value.strip() for value in aliases
        ):
            raise StableIdError(f"Invalid legacy_identifiers: {path}")
        found.add(identifier)
    if found != active:
        raise StableIdError("Active registry IDs must each have exactly one current record")


@dataclass(frozen=True)
class RecordIndex:
    stable_ids: dict[str, str]
    aliases: dict[str, tuple[str, ...]]

    @property
    def ambiguous_aliases(self) -> dict[str, tuple[str, ...]]:
        return {key: paths for key, paths in self.aliases.items() if len(paths) > 1}

    def lookup(self, identifier: str) -> str:
        # Reserve numeric MIM references regardless of prefix case (#1276).
        # Record IDs remain strict uppercase; reference normalization must never
        # let another record's retained alias impersonate their identity.
        prefix, separator, local = identifier.strip().partition(":")
        if separator and prefix.casefold() == "mim" and local.isdecimal():
            canonical = validate_id(f"MIM:{local}")
            if canonical in self.stable_ids:
                return self.stable_ids[canonical]
            raise StableIdError(f"Unknown permanent MIM ID: {canonical}")
        candidates = self.aliases.get(identifier, ())
        if len(candidates) != 1:
            raise StableIdError(f"Unknown or ambiguous record alias: {identifier}")
        return candidates[0]


def build_record_index(records: Mapping[str, Mapping[str, Any]]) -> RecordIndex:
    """Preserve ambiguous legacy aliases without pretending they identify one record.

    Stable IDs identify one record. Legacy/mapping aliases may legitimately be
    shared; lookup refuses ambiguous aliases rather than silently picking one.
    """
    stable: dict[str, str] = {}
    aliases: dict[str, set[str]] = {}
    for path, record in records.items():
        identifier = validate_id(record.get("mim_id"))
        if identifier in stable:
            raise StableIdError(f"Duplicate record MIM ID: {identifier}")
        stable[identifier] = path
        values = record.get("legacy_identifiers", [])
        if not isinstance(values, list):
            raise StableIdError("legacy_identifiers must be a list")
        for value in values:
            _text(value, "Record alias")
            aliases.setdefault(value, set()).add(path)
    return RecordIndex(stable, {key: tuple(sorted(paths)) for key, paths in aliases.items()})


def check_append_only(current: bytes, previous: bytes, *, label: str) -> None:
    if previous and (not previous.endswith(b"\n") or not current.startswith(previous)):
        raise StableIdError(f"{label} rewrites or removes previously committed rows")


def _record_identity(raw: bytes, path: str) -> str | None:
    """Read only the identity field without silently accepting duplicate YAML keys."""
    try:
        document = yaml.compose(raw, Loader=yaml.SafeLoader)
    except yaml.YAMLError as exc:
        raise StableIdError(f"Cannot read historical record identity: {path}") from exc
    if not isinstance(document, yaml.MappingNode):
        raise StableIdError(f"Record must be a YAML mapping: {path}")
    values = [
        value
        for key, value in document.value
        if isinstance(key, yaml.ScalarNode) and key.value == "mim_id"
    ]
    if not values:
        return None
    if len(values) != 1 or not isinstance(values[0], yaml.ScalarNode):
        raise StableIdError(f"Record must contain one scalar mim_id: {path}")
    return validate_id(values[0].value)


def validate_record_continuity(root: Path, base: str) -> None:
    """Reject same-path identity swaps against the trusted prior inventory.

    Initial minting is allowed when a historical record has no mim_id. Deleted
    and newly added paths are reconciled by registry/inventory checks, so a rename
    or category move retains its ID without binding that ID to a permanent path.
    """
    listing = subprocess.check_output(
        [
            "git",
            "ls-tree",
            "-rz",
            "--full-tree",
            base,
            "--",
            "data/ingredients/mapped",
            "data/ingredients/unmapped",
        ],
        cwd=root,
    )
    candidates = []
    for entry in listing.split(b"\0"):
        if not entry:
            continue
        metadata, encoded_path = entry.split(b"\t", 1)
        path = encoded_path.decode("utf-8")
        relative = Path(path)
        if len(relative.parts) != 4 or relative.suffix != ".yaml":
            continue
        current = root / relative
        if current.is_symlink():
            raise StableIdError(f"Record identity cannot be read through a symlink: {path}")
        if not current.exists():
            continue
        mode, kind, oid = metadata.split()
        if kind != b"blob" or mode not in (b"100644", b"100755"):
            raise StableIdError(f"Historical record must be a regular file: {path}")
        candidates.append((path, oid))
    with subprocess.Popen(
        ["git", "cat-file", "--batch"],
        cwd=root,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    ) as process:
        assert process.stdin is not None and process.stdout is not None
        try:
            for path, oid in candidates:
                process.stdin.write(oid + b"\n")
                process.stdin.flush()
                header = process.stdout.readline().split()
                if len(header) != 3 or header[0] != oid or header[1] != b"blob":
                    raise StableIdError("Cannot read trusted historical record blob")
                size = int(header[2])
                raw = process.stdout.read(size)
                if len(raw) != size or process.stdout.read(1) != b"\n":
                    raise StableIdError("Incomplete historical record blob")
                previous_id = _record_identity(raw, path)
                if previous_id is not None:
                    current_id = _record_identity((root / path).read_bytes(), path)
                    if current_id != previous_id:
                        raise StableIdError(f"Existing record changed permanent mim_id: {path}")
        finally:
            process.stdin.close()
        if process.wait() != 0:
            raise StableIdError("Historical record read failed")


def validate_history(root: Path, base: str) -> None:
    """Compare both complete ledgers with an explicit trusted ancestor commit."""
    if not re.fullmatch(r"[0-9a-f]{40}|[0-9a-f]{64}", base):
        raise StableIdError("History base must be an explicit full commit SHA")
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", base, "HEAD"], cwd=root, capture_output=True
    )
    if result.returncode:
        raise StableIdError("History base must be an available ancestor of HEAD")
    previous: dict[Path, bytes] = {}
    for path in (REGISTRY_PATH, LIFECYCLE_PATH):
        listing = subprocess.run(
            ["git", "ls-tree", base, "--", str(path)], cwd=root, capture_output=True, check=True
        )
        if listing.stdout:
            previous[path] = subprocess.check_output(
                ["git", "show", f"{base}:{path.as_posix()}"], cwd=root
            )
        else:
            previous[path] = b""
    if bool(previous[REGISTRY_PATH]) != bool(previous[LIFECYCLE_PATH]):
        raise StableIdError("Historical registry and lifecycle must exist together")
    if previous[REGISTRY_PATH]:
        parse_registry(previous[REGISTRY_PATH], previous[LIFECYCLE_PATH])
    for path, old in previous.items():
        check_append_only((root / path).read_bytes(), old, label=str(path))
    validate_record_continuity(root, base)
