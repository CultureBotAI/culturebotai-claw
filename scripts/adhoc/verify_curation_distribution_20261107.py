#!/usr/bin/env python3
"""Verify installed minimal contract bytes and native canary for MIM #1144, 2026-11-07.

Inputs: independently retained provenance digest/source commit, optional pinned
native export. Output: exclusive JSON conformance receipt; no source/data edits.
Run with the target environment's Python, outside the canonical source tree.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
from collections import Counter
from pathlib import Path


def verify_import_origins(distribution, files: dict[str, str], *, reviews: bool) -> int:
    """Refuse a source-tree or other package shadowing any supported import."""
    selected = (sorted(name for name in files if name.endswith(".py")) if reviews else [
        "kg_microbe_curation/__init__.py", "kg_microbe_curation/artifact.py",
        "kg_microbe_curation/identity.py", "kg_microbe_curation/native.py",
    ])
    for relative in selected:
        module_name = (relative.removesuffix("/__init__.py") if relative.endswith("/__init__.py")
                       else relative.removesuffix(".py")).replace("/", ".")
        module = importlib.import_module(module_name)
        if Path(module.__file__).resolve() != Path(distribution.locate_file(relative)).resolve():
            raise ValueError(f"Imported contract is shadowed outside the verified distribution: {module_name}")
    return len(selected)


def verify(source_commit: str, provenance_sha256: str, *, native_only: bool = False,
           reviews: bool = False,
           native_export: Path | None = None, native_manifest_sha256: str | None = None) -> dict:
    if native_only and reviews:
        raise ValueError("Native-only and optional-review proof modes are mutually exclusive")
    try:
        importlib.metadata.distribution("kg-microbe-orchestration")
    except importlib.metadata.PackageNotFoundError:
        pass
    else:
        raise ValueError("Overlapping full orchestration distribution is installed")
    distribution = importlib.metadata.distribution("kg-microbe-curation-contracts")
    provenance_path = Path(distribution.locate_file("kg_microbe_curation/distribution-provenance.json"))
    encoded = provenance_path.read_bytes()
    if hashlib.sha256(encoded).hexdigest() != provenance_sha256:
        raise ValueError("Installed provenance differs from independently pinned build input")
    provenance = json.loads(encoded)
    if (provenance["format"] != "kg-microbe-curation-distribution/v1"
            or provenance["source_commit"] != source_commit
            or provenance["version"] != distribution.version
            or provenance["scientific_approval"] is not False):
        raise ValueError("Installed distribution identity differs")
    for relative, digest in provenance["files"].items():
        path = Path(distribution.locate_file(relative))
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"Installed canonical contract bytes differ: {relative}")
    if native_only and any(importlib.util.find_spec(name) is not None
                           for name in ("linkml", "linkml_runtime", "yaml", "oaklib", "anthropic")):
        raise ValueError("Native-only proof environment contains optional/orchestration dependencies")
    imported = verify_import_origins(distribution, provenance["files"], reviews=reviews)
    from kg_microbe_curation import artifact, identity, native
    for validator in (artifact.validate_artifact_manifest, native.validate_native_assertion):
        try:
            validator({})
        except identity.CurationError:
            pass
        else:
            raise ValueError("Installed contract validator accepted an empty envelope")
    result = {"format": "kg-microbe-curation-installation-check/v1",
              "verifier_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "source_commit": source_commit, "provenance_sha256": provenance_sha256,
              "distribution_version": distribution.version, "canonical_files": len(provenance["files"]),
              "imported_modules_verified": imported, "review_runtime_origin_verified": reviews,
              "native_only_environment": native_only, "schemas_loaded_and_empty_envelopes_rejected": True,
              "scientific_approvals_created": 0}
    if (native_export is None) != (native_manifest_sha256 is None):
        raise ValueError("Native export and manifest digest must be supplied together")
    if native_export is not None:
        manifest_data = (native_export / "manifest.json").read_bytes()
        if hashlib.sha256(manifest_data).hexdigest() != native_manifest_sha256:
            raise ValueError("Native manifest pin mismatch")
        manifest = json.loads(manifest_data)
        digest, size, count, statuses = hashlib.sha256(), 0, 0, Counter()
        with (native_export / "assertions.jsonl").open("rb") as handle:
            while line := handle.readline(native.MAX_NATIVE_BYTES + 2):
                if len(line) > native.MAX_NATIVE_BYTES + 1:
                    raise ValueError("Native row exceeds canonical byte bound")
                item = json.loads(line)
                native.validate_native_assertion(item)
                if item["native_locator"]["commit"] != manifest["source_commit"]:
                    raise ValueError("Native source commit differs from export manifest")
                digest.update(line)
                size += len(line)
                count += 1
                statuses[item["native_review"]["status"]] += 1
        if ((digest.hexdigest(), size, count) != (manifest["assertions_sha256"],
                                               manifest["assertions_bytes"], manifest["rows"])
                or dict(statuses) != manifest["native_status_counts"]
                or manifest["independent_scientific_reviews"] != 0
                or manifest["kg_occurrences_approved"] != 0):
            raise ValueError("Native installed-package conformance counters do not reconcile")
        if (native_export / "manifest.json").read_bytes() != manifest_data:
            raise ValueError("Native manifest changed while verifying")
        result.update(native_manifest_sha256=native_manifest_sha256,
                      native_assertions_sha256=digest.hexdigest(), native_rows=count,
                      native_status_counts=dict(statuses))
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-commit", required=True)
    parser.add_argument("--provenance-sha256", required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--native-only", action="store_true")
    mode.add_argument("--reviews", action="store_true")
    parser.add_argument("--native-export", type=Path)
    parser.add_argument("--native-manifest-sha256")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = verify(args.source_commit, args.provenance_sha256, native_only=args.native_only,
                    reviews=args.reviews,
                    native_export=args.native_export, native_manifest_sha256=args.native_manifest_sha256)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as handle:
        json.dump(result, handle, sort_keys=True, indent=2)
        handle.write("\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
