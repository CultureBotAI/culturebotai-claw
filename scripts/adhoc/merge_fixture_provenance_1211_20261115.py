#!/usr/bin/env python3
"""Combine PR #1211's historical fixture provenance without rewriting records.

Purpose/date: resolve the additive fixture conflict during the 2026-11-15
main refresh; issues #1214 and #1255 require exact retained historical bytes
and preservation of both additive provenance cohorts.
Inputs: two immutable local Git revisions in CultureBotAI/culturebotai-claw.
Output: merged admitted-source-provenance JSON on stdout. No network access or
Git/working-tree mutation occurs. A conflicting identity or unequal duplicate holds.
The operator inspects and installs the output only in the owned repair worktree.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from pathlib import Path

PROVENANCE = "tests/fixtures/admitted-source-provenance.json"
REPOSITORY = "CultureBotAI/culturebotai-claw"


def git(root: Path, *args: str) -> bytes:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
               GIT_NO_REPLACE_OBJECTS="1", GIT_NO_LAZY_FETCH="1", GIT_GRAFT_FILE=os.devnull)
    return subprocess.check_output([
        "git", "-c", "advice.graftFileDeprecated=false", "-c", "gc.auto=0",
        "-c", f"core.hooksPath={os.devnull}", "-C", str(root), *args,
    ], env=env, timeout=30)


def load(root: Path, revision: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("a full immutable Git revision is required")
    document = json.loads(git(root, "show", f"{revision}:{PROVENANCE}"))
    if (set(document) != {"version", "authority", "records"}
            or document["version"] != 1
            or document["authority"] != "offline_fixture_provenance_only"):
        raise ValueError("unexpected fixture provenance format")
    for row in document["records"]:
        if row["source_repository"] != REPOSITORY:
            raise ValueError("unexpected source repository")
        content = git(root, "show", f"{revision}:{row['fixture']}")
        if (len(content) != row["bytes"]
                or hashlib.sha256(content).hexdigest() != row["sha256"]
                or hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
                != row["source_blob"]):
            raise ValueError("retained fixture bytes differ from provenance")
        snapshot = git(root, "show", f"{revision}:{row['snapshot']}")
        if hashlib.sha256(snapshot).hexdigest() != row["snapshot_sha256"]:
            raise ValueError("historical source snapshot differs")
        artifact = next(item for item in json.loads(snapshot)["artifacts"]
                        if item["source"] == row["source_path"])
        if artifact["sha256"] != row["sha256"]:
            raise ValueError("fixture differs from sealed source")
    return document


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--ours", required=True)
    parser.add_argument("--incoming", required=True)
    args = parser.parse_args()
    origin = git(args.root, "remote", "get-url", "origin").decode().strip()
    if origin not in {f"https://github.com/{REPOSITORY}.git",
                       f"https://github.com/{REPOSITORY}",
                       f"git@github.com:{REPOSITORY}.git"}:
        raise ValueError("unexpected object-store identity")
    documents = [load(args.root, ref) for ref in (args.ours, args.incoming)]
    records = {}
    for document in documents:
        seen = set()
        for row in document["records"]:
            key = (row["consumer"], row["source_path"])
            if key in seen or (key in records and records[key] != row):
                raise ValueError("duplicate or conflicting historical provenance")
            seen.add(key)
            records.setdefault(key, row)
    print(json.dumps({**documents[0], "records": list(records.values())}, indent=2))


if __name__ == "__main__":
    main()
