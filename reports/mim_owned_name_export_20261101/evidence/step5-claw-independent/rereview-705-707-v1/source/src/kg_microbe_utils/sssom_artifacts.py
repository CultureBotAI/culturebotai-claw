"""Publish one diagnostic SSSOM artifact set with the native write transaction.

This is working-copy publication, not approval or canonical MIM promotion.
Replacement is recoverable through a native journal; multiple renames are not
one filesystem-atomic operation. Source discovery and chemistry stay in the
builder, which supplies an exact snapshot checker.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import json
import os
import stat
import unicodedata
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path

from kg_microbe_utils.owned_name_policy import POLICY_VERSION
from kg_microbe_write import ValidatedWriteTransaction
from kg_microbe_write.transaction import JOURNAL_VERSION

POLICY_MARKER = "owned-name-policy-v1; suppression-sidecar-required"


def checked_path(path: Path) -> Path:
    """Reject traversal/symlink spellings before any lexical normalization."""
    path = Path(path)
    if ".." in path.parts:
        raise ValueError(f"Parent traversal in artifact/input path refused: {path}")
    for entry in (path, *path.parents):
        if entry.is_symlink():
            raise ValueError(f"Symlink artifact/input path refused: {entry}")
    return Path(os.path.abspath(path))


def artifact_paths(
    output: Path, sidecar_output: Path | None = None, manifest_output: Path | None = None,
) -> tuple[Path, Path, Path]:
    """Return explicit artifact paths without resolving away an alias."""
    output = checked_path(output)
    return (
        output,
        checked_path(sidecar_output or output.with_name("suppressed_aliases.tsv")),
        checked_path(manifest_output or output.with_suffix(output.suffix + ".manifest.json")),
    )


def _check_path(path: Path) -> bool:
    for entry in (path, *path.parents):
        if entry.is_symlink():
            raise ValueError(f"Symlink artifact/input path refused: {entry}")
    try:
        info = path.lstat()
    except FileNotFoundError:
        return False
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError(f"Expected a regular, unaliased file: {path}")
    return True


def _regular(path: Path) -> bytes | None:
    return path.read_bytes() if _check_path(path) else None


def capture_beforeimages(paths: Iterable[Path]) -> dict[Path, bytes | None]:
    return {checked_path(p): _regular(checked_path(p)) for p in paths}


def _load_lock_manager(claw_root: Path):
    source = claw_root / "plugins/lock_manager.py"
    spec = importlib.util.spec_from_file_location("sssom_artifact_lock", source)
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot load native lock manager: {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.LockManager


def _validate_pair(sssom_bytes: bytes, sidecar_bytes: bytes) -> None:
    from kg_microbe_utils.owned_name_policy import SIDECAR_COLUMNS

    text = sssom_bytes.decode("utf-8")
    header = "\n".join(line for line in text.splitlines() if line.startswith("#"))
    if POLICY_MARKER not in header:
        raise ValueError("SSSOM is missing the suppression-sidecar policy marker")
    rows = csv.DictReader(io.StringIO("".join(
        line for line in text.splitlines(keepends=True) if not line.startswith("#")
    )), delimiter="\t")
    if not rows.fieldnames or not {"subject_id", "other"} <= set(rows.fieldnames):
        raise ValueError("SSSOM lacks subject_id/other columns")
    tokens: dict[str, set[str]] = {}
    for row in rows:
        if None in row or None in row.values():
            raise ValueError("Malformed SSSOM row")
        tokens.setdefault(row["subject_id"], set()).update(
            token.strip().casefold() for token in row["other"].split("|") if token.strip()
        )
    reader = csv.DictReader(io.StringIO(sidecar_bytes.decode("utf-8")), delimiter="\t")
    if reader.fieldnames != list(SIDECAR_COLUMNS):
        raise ValueError("Unexpected suppression sidecar columns")
    seen: set[tuple[str, str]] = set()
    for row in reader:
        if None in row or None in row.values():
            raise ValueError("Malformed suppression sidecar row")
        subject, key = row["subject_id"], row["token_key"]
        pair = (subject, key)
        if (not key or "|" in row["token"] or row["token"].strip().casefold() != key or pair in seen
                or row["disposition"] != "SUPPRESS" or subject not in tokens
                or key in tokens[subject]):
            raise ValueError(f"Invalid or still-published suppression pair: {pair}")
        for field in ("owner_subject_ids", "input_surfaces", "source_refs", "evidence_refs"):
            value = json.loads(row[field])
            if (not isinstance(value, list) or not value
                    or any(not isinstance(x, str) or not x.strip() for x in value)
                    or value != sorted(set(value))):
                raise ValueError(f"Invalid suppression provenance: {field}")
            if field == "owner_subject_ids" and subject in value:
                raise ValueError("A subject cannot suppress its own preferred name")
        seen.add(pair)


def publish_candidate_artifacts(
    output: Path, sssom_bytes: bytes, sidecar_bytes: bytes, manifest_body: dict,
    input_check: Callable[[], None], *, input_paths: Iterable[Path],
    expected_before: Mapping[Path, bytes | None], claw_root: Path,
    working_copy_stamp_input: bool = False, sidecar_output: Path | None = None,
    manifest_output: Path | None = None,
) -> dict:
    """Validate, lock, journal and verify the complete working-copy artifact set.

    The only permitted input/output overlap is the explicitly declared SSSOM
    working-copy stamp beforeimage. The callback must check all other source
    bytes and complete source path sets; it runs before and after publication.
    """
    paths = artifact_paths(output, sidecar_output, manifest_output)
    before = {checked_path(p): b for p, b in expected_before.items()}
    if len(set(paths)) != 3 or set(before) != set(paths):
        raise ValueError("Three distinct destinations and exact beforeimages are required")
    # Be portable even when files do not yet exist (#703). A case-sensitive
    # filesystem may distinguish these spellings, but artifact sets must also
    # be safe on case-insensitive/normalizing filesystems without a write probe.
    def portable_key(path: Path) -> str:
        return unicodedata.normalize("NFC", str(path)).casefold()

    if len({portable_key(p) for p in paths}) != 3:
        raise ValueError("Case/Unicode-equivalent artifact destinations are aliases")
    if len({p.parent for p in paths}) != 1:
        raise ValueError("Candidate artifacts must have the same parent directory")
    inputs = tuple(checked_path(p) for p in input_paths)
    overlap = set(inputs) & set(paths)
    allowed = {paths[0]} if working_copy_stamp_input else set()
    if overlap - allowed or (working_copy_stamp_input and paths[0] not in inputs):
        raise ValueError("Unexpected input/output alias or undeclared working-copy input")
    for path in paths:
        for source in inputs:
            if path == source and path in allowed:
                continue
            if portable_key(path) == portable_key(source):
                raise ValueError(f"Case/Unicode input/output alias: {path} and {source}")
    for path in (*paths, *inputs):
        _check_path(path)
    for index, path in enumerate(paths):
        for other in (*paths[index + 1:], *inputs):
            if path == other and path in allowed:
                continue
            if path.exists() and other.exists() and path.samefile(other):
                raise ValueError(f"Filesystem input/output alias: {path} and {other}")
    for content in before.values():
        if content is not None:
            # Native journals preserve text. Refuse a beforeimage that text
            # decoding/newline conversion would not recover byte-for-byte.
            content.decode("utf-8")
            if b"\r" in content:
                raise ValueError("Artifact beforeimages must use UTF-8/LF")
    if {"schema_version", "policy_version", "artifacts"} & manifest_body.keys():
        raise ValueError("Generation manifest body contains reserved artifact fields")
    _validate_pair(sssom_bytes, sidecar_bytes)
    manifest = {
        **manifest_body, "schema_version": 1, "policy_version": POLICY_VERSION,
        "artifacts": [
            {"role": role, "path": str(path), "sha256": hashlib.sha256(content).hexdigest()}
            for role, path, content in zip(
                ("sssom", "suppressed_aliases"), paths, (sssom_bytes, sidecar_bytes), strict=False
            )
        ],
    }
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode()
    intended = dict(zip(paths, (sssom_bytes, sidecar_bytes, manifest_bytes), strict=True))
    journal_dir = paths[0].parent / ".sssom-artifact-journals"

    def check_journal_path() -> None:
        checked_path(journal_dir)
        if journal_dir.exists() and not journal_dir.is_dir():
            raise ValueError(f"Journal path is not a directory: {journal_dir}")

    def check_before() -> None:
        for path in inputs:
            _check_path(path)
        input_check()
        check_journal_path()
        # Hashing the sources may take time. Recheck destinations afterward,
        # including the no-op and final native precommit boundary (#704).
        for path, content in before.items():
            if _regular(path) != content:
                raise ValueError(f"Artifact beforeimage changed: {path}")

    def validate_staged(path: Path, text: str) -> None:
        if text.encode("utf-8") != intended[path]:
            raise ValueError(f"Staged artifact changed: {path}")
        check_before()

    locker = _load_lock_manager(Path(claw_root))()
    with locker.lock("mediaingredientmech", "build owned-name SSSOM candidate"):
        check_before()
        if all(before[p] == content for p, content in intended.items()):
            return {"status": "unchanged", "artifacts": manifest["artifacts"],
                    "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest(), "journal": None}
        paths[0].parent.mkdir(parents=True, exist_ok=True)
        # Recheck directory identity after creation; resolve() must not silently
        # turn a newly introduced symlink into a different write destination.
        check_before()
        transaction = ValidatedWriteTransaction(
            root=paths[0].parent, validator=validate_staged,
            journal_dir=journal_dir,
        )
        for path, content in intended.items():
            transaction.stage(path, content.decode("utf-8"))
        result = transaction.commit(apply=True)
        changed = sorted(p for p in paths if before[p] is not None and before[p] != intended[p])
        created = sorted(p for p in paths if before[p] is None)
        unchanged = sorted(p for p in paths if before[p] == intended[p])
        if (result.applied is not True or list(result.changed) != changed
                or list(result.created) != created or list(result.unchanged) != unchanged
                or result.journal_path is None
                or checked_path(result.journal_path).parent != journal_dir):
            raise ValueError("Native transaction result is not bound to the intended artifact set")
        journal_before_check = _regular(result.journal_path)
        previous = {}
        for path in changed:
            old_content = before[path]
            if old_content is None:
                raise ValueError(f"Changed artifact is missing its beforeimage: {path}")
            previous[str(path)] = old_content.decode("utf-8")
        expected_journal = {
            "version": JOURNAL_VERSION, "root": str(paths[0].parent), "status": "complete",
            "changed": [str(p) for p in changed], "created": [str(p) for p in created],
            "previous": previous,
        }
        expected_journal_bytes = json.dumps(expected_journal, indent=2, sort_keys=True).encode("utf-8")
        if journal_before_check != expected_journal_bytes:
            raise ValueError(f"Missing or invalid completed recovery journal: {result.journal_path}")
        input_check()
        check_journal_path()
        if _regular(result.journal_path) != journal_before_check:
            raise ValueError(f"Completed recovery journal changed: {result.journal_path}")
        for path, content in intended.items():
            if _regular(path) != content:
                raise ValueError(f"Artifact publication mismatch: {path}; journal={result.journal_path}")
        return {"status": "complete", **result.as_dict(), "artifacts": manifest["artifacts"],
                "manifest_sha256": hashlib.sha256(manifest_bytes).hexdigest()}
