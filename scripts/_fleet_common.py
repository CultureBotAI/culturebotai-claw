"""Shared GitHub CLI, manifest identity, cell sanitization, and locked TSV
snapshot helpers for the `fleet_*_status.py` scripts (#416, #417).
"""
from __future__ import annotations

import csv
import fcntl
import json
import os
import subprocess
import tempfile
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path

from kg_microbe_fleet import FleetManifest, load_fleet_manifest

#: The control plane is reported beside the Mechs but is not itself a Mech.
#: Every Mech identity and its order come exclusively from the manifest.
CONTROL_PLANE_REPOSITORY = "CultureBotAI/culturebotai-claw"

DEFAULT_TSV_DIR = Path(__file__).resolve().parents[1] / "workspace" / "reports"


class GhError(RuntimeError):
    """A `gh` subprocess exited nonzero."""


def _gh(args: list[str], timeout: int = 60) -> str:
    proc = subprocess.run(
        ["gh", *args], capture_output=True, text=True, timeout=timeout
    )
    if proc.returncode != 0:
        raise GhError((proc.stderr or proc.stdout).strip() or "gh failed")
    return proc.stdout


def fleet_repository_identities(
    manifest: FleetManifest | None = None,
) -> tuple[str, ...]:
    """Return claw plus the exact manifest-defined Mech fleet, in stable order."""
    manifest = manifest or load_fleet_manifest()
    return (CONTROL_PLANE_REPOSITORY,) + tuple(
        mech.github for mech in manifest.mechs.values()
    )


def _listing(
    kind: str,
    repository: str,
    fields: str,
    limit: int,
    *,
    gh: Callable[..., str] = _gh,
) -> tuple[list[dict], bool]:
    """Open issues or PRs, capped at `limit`, and whether more were left behind.

    Asks for one more than the cap: `gh ... list` returns a plain list with no
    more-pages indicator, so a listing that lands exactly on the limit is
    indistinguishable from one cut short by it unless the probe row is
    requested (#379). It comes back only if something would have been dropped.
    Sorted newest-first before the slice, so the row dropped is the oldest.
    """
    raw = gh([
        kind, "list", "--repo", repository, "--state", "open",
        "--limit", str(limit + 1), "--json", fields,
    ])
    items = json.loads(raw)
    truncated = len(items) > limit
    return sorted(items, key=lambda item: -item["number"])[:limit], truncated


def _cell(value: object) -> object:
    """Flatten strings and keep spreadsheet software from executing them.

    This is what lets the file be written unquoted, and TSV's whole appeal is
    that `cut -f5` and `awk -F'\\t'` work. Under csv's default quoting a title
    containing a double quote gets wrapped and its quotes doubled -- correct to
    a csv reader, visibly mangled to every naive consumer. Guaranteeing no
    delimiters in the data removes the need to quote at all. Spreadsheet apps
    interpret cells beginning with ``=``, ``+``, ``-``, or ``@`` as formulas,
    so prefix those strings with an apostrophe after whitespace is flattened.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        return value
    flattened = " ".join(value.split())
    if flattened.startswith(("=", "+", "-", "@")):
        return "'" + flattened
    return flattened


def tsv_path_for(
    stem_prefix: str, out_dir: Path, snapshot_utc: str, complete: bool
) -> Path:
    """Datestamped, and marked `.partial` when coverage was incomplete.

    The filename carries that fact because the console warning does not
    survive: a month later the file is all anyone has, and a partial snapshot
    that looks whole is worse than no snapshot. Re-running on the same date
    overwrites -- the file means "the state on that date", not an append log.
    """
    stem = f"{stem_prefix}_{snapshot_utc[:10]}"
    if not complete:
        stem += ".partial"
    return out_dir / f"{stem}.tsv"


def snapshot_lock_path_for(
    stem_prefix: str, out_dir: Path, snapshot_utc: str
) -> Path:
    """One persistent lock inode shared by both completeness variants."""
    return out_dir / f".{stem_prefix}_{snapshot_utc[:10]}.lock"


@contextmanager
def snapshot_lock_for(
    stem_prefix: str, out_dir: Path, snapshot_utc: str
) -> Iterator[None]:
    """Lock one date without following or replacing the stable lock inode."""
    lock_path = snapshot_lock_path_for(stem_prefix, out_dir, snapshot_utc)
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(lock_path, flags, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
    finally:
        os.close(descriptor)


def write_snapshot_tsv(
    stem_prefix: str,
    columns: Sequence[str],
    rows: Sequence[dict],
    out_dir: Path,
    snapshot_utc: str,
    complete: bool,
) -> Path:
    """Atomically write a datestamped TSV snapshot and remove its opposite
    completeness counterpart under a persistent per-date lock (#416, #417).
    """
    path = tsv_path_for(stem_prefix, out_dir, snapshot_utc, complete)
    counterpart = tsv_path_for(stem_prefix, out_dir, snapshot_utc, not complete)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            dir=path.parent,
            prefix=f".{path.name}.",
            newline="",
            delete=False,
            encoding="utf-8",
        ) as handle:
            temporary = Path(handle.name)
            writer = csv.DictWriter(
                handle,
                fieldnames=list(columns),
                delimiter="\t",
                lineterminator="\n",
                extrasaction="raise",
                quoting=csv.QUOTE_NONE,
                quotechar=None,
            )
            writer.writeheader()
            writer.writerows(rows)

        # The selected path and deletion of its opposite marker are one state
        # transition. Both complete and partial writers use this same stable
        # lock file, which must never be unlinked: replacing a lock inode while
        # another process waits on the old one would split the critical section.
        with snapshot_lock_for(stem_prefix, out_dir, snapshot_utc):
            os.replace(temporary, path)
            temporary = None
            counterpart.unlink(missing_ok=True)
    except BaseException:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise
    return path
