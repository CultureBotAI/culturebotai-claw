#!/usr/bin/env python3
"""Run the pinned shared quote validator on this exact Mech worktree.

CLAW_ROOT must name a clean checkout of CultureBotAI/culturebotai-claw at the
full commit recorded in this worktree's scripts/.vendored_canon_ref. No primary
checkout, sibling directory, mutable branch or network fallback is inferred.
The shared validator owns evidence policy; this runner owns the checkout boundary.
"""

from __future__ import annotations

import argparse
import os
import re
import stat
import subprocess
import sys
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path

CANONICAL_REPOSITORY = "CultureBotAI/culturebotai-claw"
PIN_PATH = Path("scripts/.vendored_canon_ref")
SHA = re.compile(rb"[0-9a-f]{40}\n?")
IMPORT_SUFFIXES = {".py", ".pyw", ".pyc", ".pyo", ".so", ".pyd"}
MAX_IMPORT_FILES = 10000
MAX_IMPORT_FILE_BYTES = 16 * 1024 * 1024
MAX_IMPORT_BYTES = 128 * 1024 * 1024


class RunnerError(RuntimeError):
    """The pinned active-checkout boundary could not be established."""


def _git_bytes(root: Path, *arguments: str, input_data: bytes | None = None) -> bytes:
    environment = {key: value for key, value in os.environ.items()
                   if not key.startswith("GIT_")}
    environment.update(GIT_NO_REPLACE_OBJECTS="1", GIT_NO_LAZY_FETCH="1")
    result = subprocess.run(
        ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", "-C", str(root), *arguments],
        capture_output=True, check=False, timeout=30, env=environment, input=input_data,
    )
    if result.returncode:
        # A remote URL or Git diagnostic may contain credentials; do not echo it.
        raise RunnerError("Git could not verify the requested worktree")
    return result.stdout


def _git(root: Path, *arguments: str) -> str:
    return _git_bytes(root, *arguments).decode("utf-8").strip()


def _verify_tracked_imports(claw: Path) -> set[str]:
    """Compare source/resources to HEAD without trusting index status (#694).

    One tree read and one bounded batch read cover the import roots, including
    top-level Python packages and modules. No flags or user files are changed.
    """
    entries: list[tuple[str, str, str, str, str]] = []
    for row in _git_bytes(claw, "ls-tree", "-rzl", "--full-tree", "HEAD").split(b"\0"):
        if not row:
            continue
        tree_metadata, path_bytes = row.split(b"\t", 1)
        mode, kind, oid, raw_size = tree_metadata.decode("ascii").split()
        relative = path_bytes.decode("utf-8")
        entries.append((relative, mode, kind, oid, raw_size))
    import_roots = {"src", "plugins"} | {
        path.split("/")[0] for path, *_ in entries
        if path.count("/") == 1 and path.endswith("/__init__.py")
    }
    selected: list[tuple[str, str, str, int]] = []
    for relative, mode, kind, oid, size_text in entries:
        path = Path(relative)
        if path.parts[0] not in import_roots and not (len(path.parts) == 1 and path.suffix in IMPORT_SUFFIXES):
            continue
        if kind != "blob" or mode not in {"100644", "100755"}:
            raise RunnerError("Pinned Claw import paths must be regular file blobs")
        size = int(size_text)
        if size < 0 or size > MAX_IMPORT_FILE_BYTES:
            raise RunnerError("Pinned Claw import file exceeds the bounded verification limit")
        selected.append((relative, mode, oid, size))
    required = {
        "src/kg_microbe_fleet/__init__.py", "src/kg_microbe_fleet/fleet.yaml",
        "src/kg_microbe_evidence/__init__.py", "src/kg_microbe_evidence/__main__.py",
        "plugins/__init__.py", "plugins/repository_settings.py",
    }
    if not required <= {path for path, *_ in selected}:
        raise RunnerError("Pinned Claw lacks the required tracked validator source/resources")
    if len(selected) > MAX_IMPORT_FILES or sum(size for *_, size in selected) > MAX_IMPORT_BYTES:
        raise RunnerError("Pinned Claw imports exceed the bounded verification limit")

    objects = {oid: size for _, _, oid, size in selected}
    batch = _git_bytes(claw, "cat-file", "--batch", input_data="".join(oid + "\n" for oid in objects).encode("ascii"))
    payloads: dict[str, bytes] = {}
    offset = 0
    for oid, size in objects.items():
        newline = batch.find(b"\n", offset)
        if newline < 0 or batch[offset:newline] != f"{oid} blob {size}".encode("ascii"):
            raise RunnerError("Git did not return the expected pinned blob batch")
        start, end = newline + 1, newline + 1 + size
        if batch[end:end + 1] != b"\n":
            raise RunnerError("Git returned a truncated pinned blob")
        payloads[oid] = batch[start:end]
        offset = end + 1
    if offset != len(batch):
        raise RunnerError("Git returned unexpected data after the pinned blob batch")

    for relative, mode, oid, size in selected:
        path = claw
        parts = Path(relative).parts
        for index, part in enumerate(parts):
            path = path / part
            file_info = path.lstat()
            regular = stat.S_ISREG(file_info.st_mode) if index == len(parts) - 1 else stat.S_ISDIR(file_info.st_mode)
            if not regular:
                raise RunnerError("Pinned Claw import path is a symlink or nonregular file")
        if bool(file_info.st_mode & stat.S_IXUSR) != (mode == "100755"):
            raise RunnerError("Pinned Claw import mode differs from HEAD")
        with path.open("rb") as stream:
            current = stream.read(size + 1)
        if current != payloads[oid]:
            raise RunnerError("Pinned Claw source or resource differs from HEAD")
    return import_roots


def _identity(url: str) -> str:
    prefixes = ("https://github.com/", "git@github.com:", "ssh://git@github.com/")
    for prefix in prefixes:
        if url.lower().startswith(prefix):
            identity = url[len(prefix):].rstrip("/")
            if identity.endswith(".git"):
                identity = identity[:-4]
            if re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", identity):
                return identity.lower()
    raise RunnerError("Origin is not an unambiguous GitHub repository identity")


def _worktree_identity(root: Path) -> str:
    if Path(_git(root, "rev-parse", "--show-toplevel")).resolve() != root:
        raise RunnerError("Expected the exact Git worktree root")
    identities: set[str] = set()
    for purpose in ((), ("--push",)):
        urls = _git(root, "remote", "get-url", *purpose, "--all", "origin").splitlines()
        if not urls:
            raise RunnerError("Origin must have fetch and push identities")
        identities.update(_identity(url) for url in urls)
    if len(identities) != 1:
        raise RunnerError("Origin fetch and push identities do not agree")
    return identities.pop()


def pinned_claw(root: Path, environment: Mapping[str, str]) -> Path:
    pin_path = root / PIN_PATH
    if pin_path.is_symlink() or not pin_path.is_file():
        raise RunnerError("The canonical pin must be a regular, non-symlink file")
    with pin_path.open("rb") as stream:
        pin = stream.read(64)
    if SHA.fullmatch(pin) is None:
        raise RunnerError("The canonical pin must be one lowercase full 40-character SHA")
    raw_claw = environment.get("CLAW_ROOT", "").strip()
    if not raw_claw:
        raise RunnerError("Set CLAW_ROOT to the checkout at scripts/.vendored_canon_ref")
    claw = Path(raw_claw).expanduser().resolve()
    if _worktree_identity(claw) != CANONICAL_REPOSITORY.lower():
        raise RunnerError("CLAW_ROOT must identify the canonical Claw repository")
    if _git(claw, "rev-parse", "HEAD") != pin.decode("ascii").strip():
        raise RunnerError("CLAW_ROOT HEAD does not match scripts/.vendored_canon_ref")
    if _git(claw, "status", "--porcelain", "--untracked-files=no"):
        raise RunnerError("CLAW_ROOT has tracked changes; use clean pinned validator code")
    tracked_roots = _verify_tracked_imports(claw)
    # Omit --exclude-standard deliberately: ignored Python modules can shadow
    # pinned imports just as untracked ones can. Ordinary __pycache__ files are
    # harmless only because run() redirects every bytecode read to a fresh,
    # private empty directory and disables writes before importing Claw.
    import_roots = (*sorted(tracked_roots), ":(top,glob)*", ":(top,glob)*/__init__.*")
    for relative in _git(claw, "ls-files", "--others", "-z", "--", *import_roots).split("\0"):
        if not relative:
            continue
        path = claw / relative
        cached = path.parent.name == "__pycache__" and path.suffix == ".pyc"
        if path.is_symlink() or (path.suffix in IMPORT_SUFFIXES and not cached):
            raise RunnerError("CLAW_ROOT has untracked or ignored importable code")
    return claw


def run(
    args: argparse.Namespace,
    *,
    root: Path,
    environment: Mapping[str, str],
) -> int:
    root = root.resolve()
    consumer_identity = _worktree_identity(root)
    claw = pinned_claw(root, environment)
    if any(name == "plugins" or name.startswith(("plugins.", "kg_microbe_")) for name in sys.modules):
        raise RunnerError("Preloaded Claw modules cannot be verified; run in a fresh interpreter")
    manifest_path = claw / "src/kg_microbe_fleet/fleet.yaml"
    # The CLI must see the same pinned manifest, never a caller's unrelated
    # KG_MICROBE_FLEET_MANIFEST override, including import-time consumers of
    # the manifest. Restore process settings for programmatic callers.
    previous = os.environ.get("KG_MICROBE_FLEET_MANIFEST")
    previous_path = list(sys.path)
    previous_prefix = sys.pycache_prefix
    previous_write = sys.dont_write_bytecode
    bytecode = tempfile.TemporaryDirectory(prefix="claw-evidence-bytecode-")
    os.environ["KG_MICROBE_FLEET_MANIFEST"] = str(manifest_path)
    sys.path[:0] = [str(claw / "src"), str(claw)]
    # -I and -B do not prevent stale .pyc reads (#689). A private, empty cache
    # prefix plus disabled writes forces source compilation, including imports
    # from dependencies, without deleting or trusting a user's cache files.
    sys.pycache_prefix = bytecode.name
    sys.dont_write_bytecode = True
    try:
        from kg_microbe_fleet import load_fleet_manifest
        from plugins.repository_settings import RepositoryTarget

        manifest = load_fleet_manifest(manifest_path)
        matches = [mech for mech in manifest.mechs.values()
                   if mech.github.lower() == consumer_identity]
        if len(matches) != 1:
            raise RunnerError("Active worktree origin is not a unique declared Mech")
        mech = matches[0]
        RepositoryTarget(mech.key, root, mech.github).open()
        from kg_microbe_evidence.__main__ import main as validate

        argv = ["--mech", mech.key, "--root", str(root)]
        if args.strict:
            argv.append("--strict")
        if args.output_dir is not None:
            argv.extend(["--output-dir", str(args.output_dir)])
        return int(validate(argv))
    finally:
        sys.path[:] = previous_path
        sys.pycache_prefix = previous_prefix
        sys.dont_write_bytecode = previous_write
        bytecode.cleanup()
        if previous is None:
            os.environ.pop("KG_MICROBE_FLEET_MANIFEST", None)
        else:
            os.environ["KG_MICROBE_FLEET_MANIFEST"] = previous


def main(
    argv: Sequence[str] | None = None,
    *,
    root: Path | None = None,
    environment: Mapping[str, str] | None = None,
) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        return run(args, root=root or Path(__file__).resolve().parents[1],
                   environment=os.environ if environment is None else environment)
    except (OSError, ValueError, ImportError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f"qc-evidence: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
