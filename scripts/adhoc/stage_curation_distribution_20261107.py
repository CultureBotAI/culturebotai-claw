#!/usr/bin/env python3
"""Stage a minimal canonical contract distribution for MIM #1144, 2026-11-07.

Inputs: CLAW Git root, complete immutable source commit, new output directory.
Outputs: a buildable source project containing byte-identical canonical files,
small dependency metadata and a hash-bound provenance manifest. No network,
installation, publishing, downstream mutation or source checkout edits occur.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

FILES = (
    "kg_microbe_curation/__init__.py",
    "kg_microbe_curation/__main__.py",
    "kg_microbe_curation/artifact.py",
    "kg_microbe_curation/contract.py",
    "kg_microbe_curation/identity.py",
    "kg_microbe_curation/ledger.py",
    "kg_microbe_curation/native.py",
    "kg_microbe_curation/schema/artifact.json",
    "kg_microbe_curation/schema/bundle.json",
    "kg_microbe_curation/schema/native_assertion.json",
    "kg_microbe_reviews/__init__.py",
    "kg_microbe_governance/__init__.py",
    "kg_microbe_governance/artifacts/__init__.py",
    "kg_microbe_governance/artifacts/scripts/__init__.py",
    "kg_microbe_governance/artifacts/scripts/check_vendored_sync.py",
    "kg_microbe_governance/artifacts/scripts/record_review.py",
    "kg_microbe_governance/artifacts/schema/record_review.yaml",
)
MAX_SOURCE_BYTES = 2 * 1024 * 1024
TEMPLATE_ROOT = Path(__file__).resolve().parents[2] / "packaging/curation-contracts"


def git(root: Path, *args: str) -> bytes:
    return subprocess.run(["git", "-C", str(root), *args], check=True,
                          stdout=subprocess.PIPE, stderr=subprocess.PIPE).stdout


def stage(root: Path, source_commit: str, output: Path) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", source_commit):
        raise ValueError("source_commit must be a complete lowercase Git commit")
    root = root.resolve(strict=True)
    if git(root, "rev-parse", f"{source_commit}^{{commit}}").decode().strip() != source_commit:
        raise ValueError("Source identity is not the requested commit")
    origin = git(root, "remote", "get-url", "origin").decode().strip().removesuffix(".git")
    if origin not in {"https://github.com/CultureBotAI/culturebotai-claw",
                      "git@github.com:CultureBotAI/culturebotai-claw"}:
        raise ValueError("Expected the canonical CLAW repository origin")
    output = output.absolute()
    if ".." in output.parts or any(path.is_symlink() for path in (output, *output.parents)):
        raise ValueError("Output must not traverse a symlink or parent alias")
    if output.exists():
        raise ValueError("Refusing to replace an existing distribution stage")
    # Read all immutable blobs before reserving an output. Git symlinks and
    # non-regular entries are rejected instead of being materialized as code.
    blobs = {}
    for relative in FILES:
        entry = git(root, "ls-tree", source_commit, "--", "src/" + relative).decode().strip()
        if not entry.startswith("100644 blob "):
            raise ValueError(f"Expected canonical regular source file: {relative}")
        data = git(root, "show", f"{source_commit}:src/{relative}")
        if len(data) > MAX_SOURCE_BYTES:
            raise ValueError(f"Canonical source exceeds build bound: {relative}")
        blobs[relative] = data
    template = (TEMPLATE_ROOT / "pyproject.toml").read_bytes()
    readme = (TEMPLATE_ROOT / "README.md").read_bytes()
    version = "0.1.0+g" + source_commit
    project = template.replace(b'version = "0.1.0"', f'version = "{version}"'.encode())
    if project == template:
        raise ValueError("Distribution version template changed")
    manifest = {
        "format": "kg-microbe-curation-distribution/v1",
        "repository": "CultureBotAI/culturebotai-claw", "source_commit": source_commit,
        "distribution": "kg-microbe-curation-contracts", "version": version,
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(blobs.items())},
        "builder_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "template_sha256": hashlib.sha256(template).hexdigest(),
        "readme_sha256": hashlib.sha256(readme).hexdigest(),
        "project_sha256": hashlib.sha256(project).hexdigest(),
        "scientific_approval": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.mkdir(mode=0o700)
    for relative, data in blobs.items():
        target = output / "src" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("xb") as handle:
            handle.write(data)
    (output / "pyproject.toml").write_bytes(project)
    (output / "README.md").write_bytes(readme)
    provenance = json.dumps(manifest, sort_keys=True, indent=2).encode() + b"\n"
    (output / "src/kg_microbe_curation/distribution-provenance.json").write_bytes(provenance)
    # The completion marker is not a release/publication receipt; it only marks
    # an exclusively created, locally staged build input.
    for relative, digest in manifest["files"].items():
        if hashlib.sha256((output / "src" / relative).read_bytes()).hexdigest() != digest:
            raise ValueError("Staged source hash differs from immutable Git input")
    with (output / "staging-manifest.json").open("xb") as handle:
        handle.write(provenance)
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = stage(args.root, args.source_commit, args.output)
    print(json.dumps({"output": str(args.output), "source_commit": result["source_commit"],
                      "files": len(result["files"]), "version": result["version"]}, sort_keys=True))


if __name__ == "__main__":
    main()
