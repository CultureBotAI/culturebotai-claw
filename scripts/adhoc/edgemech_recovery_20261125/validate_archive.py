#!/usr/bin/env python3
"""Verify inert original/derived source bytes without executing archived code."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

try:
    from .preserve_sources import regular_bytes, sha
except ImportError:  # Direct script invocation.
    from preserve_sources import regular_bytes, sha


def validate(private: Path, public: Path) -> dict:
    manifest_bytes = regular_bytes(private / "MANIFEST.json")
    if regular_bytes(public / "MANIFEST.json") != manifest_bytes:
        raise ValueError("private/public manifest mismatch")
    manifest = json.loads(manifest_bytes)
    bindings = json.loads(regular_bytes(private / "binding-map.json"))
    count = 0
    python_count = 0
    expected = set()
    for entry in manifest["entries"]:
        for item in entry["files"]:
            name = item["path"]
            if Path(name).is_absolute() or ".." in Path(name).parts:
                raise ValueError("invalid manifest path")
            original = regular_bytes(private / name)
            derived = regular_bytes(public / name)
            if (
                sha(original) != item["private_original_sha256"]
                or len(original) != item["private_original_bytes"]
            ):
                raise ValueError("original source pin mismatch")
            if sha(derived) != item["public"]["sha256"] or len(derived) != item["public"]["bytes"]:
                raise ValueError("public source pin mismatch")
            restored = derived.decode()
            for value, token in sorted(bindings.items(), key=lambda pair: -len(pair[1])):
                restored = restored.replace(token, value)
                pattern = re.escape(value)
                if value.isdecimal():
                    pattern = rf"(?<![A-Za-z0-9]){pattern}(?![A-Za-z0-9])"
                if re.search(pattern, derived.decode()):
                    raise ValueError("private binding remains in public source")
            if restored.encode() != original:
                raise ValueError("derived source cannot restore exact original bytes")
            if name.endswith(".py.txt"):
                compile(original, name, "exec")
                compile(derived, name, "exec")
                python_count += 1
            expected.add(name)
            count += 1
    actual = {str(p.relative_to(public)) for p in public.rglob("*.txt")}
    if actual != expected:
        raise ValueError("public source coverage mismatch")
    return {
        "entries": len(manifest["entries"]),
        "source_files": count,
        "python_sources_compiled_without_execution": python_count,
        "exact_rehydration": True,
        "archive_executions": 0,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--private", type=Path, required=True)
    parser.add_argument("--public", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(validate(args.private, args.public), indent=2))


if __name__ == "__main__":
    main()
