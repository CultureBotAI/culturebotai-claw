"""A ledger for generated patch sets, so an unapplied backlog is visible.

Item 4 of #129. `generate_kgm_xref_patches.py` writes proposed kg-microbe xref
deltas to `workspace/patches/`, and nothing records whether anyone acted. The
evidence that this matters is the artifact itself: 513 rows, last written on
2026-04-20 and untouched for months, with no indication anywhere that it was
old or outstanding.

The generator is already idempotent against reality -- it recomputes from
kg-microbe's current xrefs, so an applied patch simply stops being emitted.
What was missing is memory across runs: whether this set is new, unchanged, or
shrinking, and how long it has been waiting.

This tracks; it does not apply. Applying means changing kg-microbe, which is a
separate repository and a separately approved operation.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

LEDGER_VERSION = 1
LEDGER_FILENAME = "patch_ledger.json"


class LedgerError(ValueError):
    """The ledger is missing, malformed, or of an unsupported version."""


def fingerprint(rows: list[str]) -> str:
    """A stable identity for a patch set, independent of row order.

    Sorted because the generator's output order follows dict iteration, and a
    reordering is not a change to what is being proposed.
    """
    digest = hashlib.sha256()
    for row in sorted(rows):
        digest.update(row.encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


@dataclass(frozen=True)
class Entry:
    """One recorded generation of a patch set."""

    first_seen: str
    last_seen: str
    runs: int
    rows: int
    fingerprint: str

    @property
    def days_outstanding(self) -> int:
        first = date.fromisoformat(self.first_seen[:10])
        last = date.fromisoformat(self.last_seen[:10])
        return (last - first).days

    def as_dict(self) -> dict[str, Any]:
        return {
            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "runs": self.runs,
            "rows": self.rows,
            "fingerprint": self.fingerprint,
        }


def load(path: Path) -> Entry | None:
    """The recorded entry, or None when nothing has been recorded yet."""
    target = Path(path)
    if not target.is_file():
        return None
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise LedgerError(f"cannot read patch ledger {target}: {exc}") from exc
    if payload.get("version") != LEDGER_VERSION:
        raise LedgerError(
            f"unsupported patch ledger version {payload.get('version')!r} in "
            f"{target}; expected {LEDGER_VERSION}"
        )
    entry = payload.get("entry")
    if not isinstance(entry, dict):
        return None
    try:
        return Entry(**entry)
    except TypeError as exc:
        raise LedgerError(f"patch ledger {target} has a malformed entry: {exc}") from exc


def record(
    path: Path, rows: list[str], *, now: datetime | None = None
) -> tuple[Entry, str]:
    """Record this run's patch set; return the entry and what changed.

    The verdict is one of `first-run`, `unchanged`, or `changed`. `unchanged`
    is the one that matters: the same proposals coming back run after run means
    nobody has applied them, which is the state that was invisible.
    """
    moment = (now or datetime.now(tz=timezone.utc)).isoformat()
    digest = fingerprint(rows)
    previous = load(path)

    if previous is None:
        entry, verdict = Entry(moment, moment, 1, len(rows), digest), "first-run"
    elif previous.fingerprint == digest:
        entry = Entry(
            previous.first_seen, moment, previous.runs + 1, len(rows), digest
        )
        verdict = "unchanged"
    else:
        entry, verdict = Entry(moment, moment, 1, len(rows), digest), "changed"

    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        json.dumps(
            {"version": LEDGER_VERSION, "entry": entry.as_dict()},
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return entry, verdict


def describe(entry: Entry, verdict: str) -> str:
    """A line a human can act on."""
    if verdict == "first-run":
        return f"{entry.rows} patch(es) proposed; first recorded run."
    if verdict == "changed":
        return f"{entry.rows} patch(es) proposed; the set changed since the last run."
    return (
        f"{entry.rows} patch(es) proposed, UNCHANGED across {entry.runs} runs "
        f"over {entry.days_outstanding} day(s) since {entry.first_seen[:10]}. "
        f"Nothing has been applied upstream; these are waiting on a decision."
    )


def staleness(artifact: Path, inputs: list[Path]) -> list[Path]:
    """Inputs newer than `artifact`, i.e. reasons its content may be out of date.

    The generated file carries no indication of its own age. The one in the
    repository was four months old with no sign of it.
    """
    target = Path(artifact)
    if not target.is_file():
        return []
    generated = target.stat().st_mtime
    return [
        path for path in inputs
        if Path(path).exists() and Path(path).stat().st_mtime > generated
    ]
