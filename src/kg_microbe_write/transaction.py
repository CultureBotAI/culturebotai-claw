"""A validated, atomic, recoverable write transaction.

Phase 3 of the standardization plan: the mutation boundary was the one part of
the control plane each writer implemented for itself, so "validate before you
replace" and "never leave a half-written corpus" were conventions rather than
guarantees. Both had already failed in practice -- a per-record writer that
resolved its vocabulary lazily wrote every record classified before the first
one that needed it, then aborted, leaving an unknown subset of another
repository's corpus modified with no recovery path (#156).

The transaction is deliberately small and offline. It does not resolve
repositories, take locks, or decide authorization policy: `RepositorySettings`
and `LockManager` already own those, and a transaction that re-implemented them
would be a second definition of a rule this repository has one of. It accepts
the resolved root and refuses to write outside it.

Nothing is written until `commit()`. `commit()` without `apply=True` is a dry
run that reports the diff it would have applied.
"""

from __future__ import annotations

import difflib
import json
import os
import tempfile
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

JOURNAL_VERSION = 1


class WriteError(RuntimeError):
    """A write was refused, or could not be completed safely."""


class ValidationFailed(WriteError):
    """Proposed content did not validate, so it never reached the target."""


@dataclass(frozen=True)
class Change:
    """One proposed file replacement."""

    path: Path
    new_text: str
    old_text: str | None

    @property
    def exists(self) -> bool:
        return self.old_text is not None

    @property
    def changed(self) -> bool:
        return self.old_text != self.new_text

    def diff(self, *, context: int = 3) -> str:
        """A unified diff of what this change would do."""
        return "".join(
            difflib.unified_diff(
                (self.old_text or "").splitlines(keepends=True),
                self.new_text.splitlines(keepends=True),
                fromfile=f"a/{self.path.name}" if self.exists else "/dev/null",
                tofile=f"b/{self.path.name}",
                n=context,
            )
        )


@dataclass
class WriteResult:
    """What a `commit()` did, or would have done."""

    applied: bool
    changed: tuple[Path, ...]
    unchanged: tuple[Path, ...]
    created: tuple[Path, ...]
    journal_path: Path | None = None

    @property
    def touched(self) -> int:
        return len(self.changed) + len(self.created)

    def as_dict(self) -> dict[str, Any]:
        return {
            "applied": self.applied,
            "changed": [str(p) for p in self.changed],
            "created": [str(p) for p in self.created],
            "unchanged": [str(p) for p in self.unchanged],
            "journal": str(self.journal_path) if self.journal_path else None,
        }


Validator = Callable[[Path, str], None]
"""Raise to reject proposed content. Receives the target path and the new text."""


@dataclass
class ValidatedWriteTransaction:
    """Stage every change, validate all of them, then replace atomically.

    All-or-nothing by construction: validation runs over the complete staged set
    before any target is touched, so one invalid record cannot leave the earlier
    ones written. That is the property #156 lacked.
    """

    root: Path
    validator: Validator | None = None
    journal_dir: Path | None = None
    _changes: dict[Path, Change] = field(default_factory=dict, init=False)

    def __post_init__(self) -> None:
        self.root = Path(self.root).resolve(strict=True)

    # -- staging -----------------------------------------------------------

    def resolve(self, path: Path | str) -> Path:
        """Resolve `path` inside the root, refusing anything that escapes it.

        `..` and symlinks that leave the tree are refused rather than clamped:
        a writer aiming outside the repository it was handed is a bug, and
        silently rewriting the destination would hide it.
        """
        candidate = Path(path)
        candidate = candidate if candidate.is_absolute() else self.root / candidate
        resolved = candidate.resolve()
        try:
            resolved.relative_to(self.root)
        except ValueError as exc:
            raise WriteError(
                f"{resolved} is outside the transaction root {self.root}"
            ) from exc
        return resolved

    def stage(self, path: Path | str, new_text: str) -> Change:
        """Record a proposed replacement. Nothing is written here."""
        if not isinstance(new_text, str):
            raise WriteError(
                f"staged content for {path} must be str, got "
                f"{type(new_text).__name__}"
            )
        target = self.resolve(path)
        old = target.read_text(encoding="utf-8") if target.is_file() else None
        change = Change(target, new_text, old)
        self._changes[target] = change
        return change

    @property
    def staged(self) -> tuple[Change, ...]:
        return tuple(self._changes[path] for path in sorted(self._changes))

    # -- reporting ---------------------------------------------------------

    def diff(self, *, context: int = 3) -> str:
        """The unified diff of every staged change that would alter something."""
        return "".join(
            change.diff(context=context) for change in self.staged if change.changed
        )

    # -- committing --------------------------------------------------------

    def commit(self, *, apply: bool = False) -> WriteResult:
        """Validate everything, then replace atomically when `apply` is set.

        Returns a dry-run result otherwise. Validation runs in both modes, so a
        dry run is a real check and not merely a preview.
        """
        self._validate_all()

        changed = tuple(
            c.path for c in self.staged if c.changed and c.exists
        )
        created = tuple(c.path for c in self.staged if not c.exists)
        unchanged = tuple(c.path for c in self.staged if c.exists and not c.changed)

        if not apply:
            return WriteResult(False, changed, unchanged, created)

        journal_path = self._write_journal(changed, created)
        written: list[Path] = []
        try:
            for change in self.staged:
                if not change.changed:
                    continue
                _atomic_replace(change.path, change.new_text)
                written.append(change.path)
        except Exception as exc:  # pragma: no cover - exercised via injection
            raise WriteError(
                f"write failed after {len(written)} file(s); journal at "
                f"{journal_path} records the intended set and prior contents"
            ) from exc
        self._complete_journal(journal_path)
        return WriteResult(True, changed, unchanged, created, journal_path)

    # -- internals ---------------------------------------------------------

    def _validate_all(self) -> None:
        if self.validator is None:
            return
        failures: list[str] = []
        for change in self.staged:
            try:
                self.validator(change.path, change.new_text)
            except Exception as exc:
                failures.append(f"{change.path}: {exc}")
        if failures:
            raise ValidationFailed(
                f"{len(failures)} staged change(s) failed validation and nothing "
                f"was written:\n  " + "\n  ".join(failures)
            )

    def _write_journal(
        self, changed: Iterable[Path], created: Iterable[Path]
    ) -> Path | None:
        """Record the intended set and prior contents before touching anything.

        Without this an interrupted run leaves no way to tell which files were
        already replaced.
        """
        if self.journal_dir is None:
            return None
        directory = Path(self.journal_dir)
        directory.mkdir(parents=True, exist_ok=True)
        handle, name = tempfile.mkstemp(
            prefix="write-", suffix=".json", dir=directory
        )
        os.close(handle)
        path = Path(name)
        payload = {
            "version": JOURNAL_VERSION,
            "root": str(self.root),
            "status": "in_progress",
            "changed": [str(p) for p in changed],
            "created": [str(p) for p in created],
            "previous": {
                str(c.path): c.old_text
                for c in self.staged
                if c.changed and c.exists
            },
        }
        _atomic_replace(path, json.dumps(payload, indent=2, sort_keys=True))
        return path

    def _complete_journal(self, path: Path | None) -> None:
        if path is None:
            return
        payload = json.loads(path.read_text(encoding="utf-8"))
        payload["status"] = "complete"
        _atomic_replace(path, json.dumps(payload, indent=2, sort_keys=True))


def _atomic_replace(path: Path, text: str) -> None:
    """Replace `path` with `text` atomically.

    The temporary file is created in the target's own directory so `os.replace`
    stays within one filesystem, and is fsynced before the rename so a crash
    cannot leave a renamed-but-empty file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def recover(journal_path: Path) -> Mapping[str, str | None]:
    """The prior contents an interrupted transaction recorded, keyed by path."""
    payload = json.loads(Path(journal_path).read_text(encoding="utf-8"))
    if payload.get("version") != JOURNAL_VERSION:
        raise WriteError(
            f"unsupported journal version {payload.get('version')!r} in "
            f"{journal_path}; expected {JOURNAL_VERSION}"
        )
    return payload.get("previous", {})
