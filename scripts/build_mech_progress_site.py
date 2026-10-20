#!/usr/bin/env python3
"""Build Pages from reviewed static sources and a pinned, validated data commit."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil

from mech_progress_publish import read_remote


def build(source: Path, destination: Path) -> str:
    head, bundle = read_remote()
    if head is None or bundle is None:
        raise ValueError("No public progress snapshot has been published")
    if destination.exists():
        raise ValueError("Build destination already exists")
    if not source.is_dir():
        raise ValueError("Missing site source directory")
    for item in source.rglob("*"):
        if item.is_symlink():
            raise ValueError("Site source must not contain symlinks")
    shutil.copytree(source, destination)
    data = destination / "data"
    data.mkdir(exist_ok=True)
    for name, value in (("progress.json", bundle["snapshot"]), ("history.json", bundle["history"])):
        (data / name).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")
    (data / "publication.json").write_text(json.dumps({"data_commit": head}, indent=2) + "\n")
    (destination / ".nojekyll").touch()
    return head


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("site/progress"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    print(build(args.source, args.output))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
