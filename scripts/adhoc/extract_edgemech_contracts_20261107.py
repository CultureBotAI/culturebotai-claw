#!/usr/bin/env python3
"""Extract the reviewed contracts-only commit under a repository lease, 2026-11-07.

Inputs: explicit clean feature worktree and immutable contract commit 1b5391d.
Output: one cherry-picked commit; fleet/governance/rollout paths stay unchanged.
Provenance for CLAW #766/#767 and the admission split from PR #953.
"""

import argparse
import json
from pathlib import Path

from plugins.lock_manager import LockManager
from plugins.repository_settings import RepositoryTarget

SOURCE = "1b5391d083ba85ac94e5279c3cba25ac4fde243c"
BRANCH = "feat/edgemech-shared-contracts-20261107"
FORBIDDEN = ("src/kg_microbe_fleet/", "src/kg_microbe_governance/",
             "src/kg_microbe_embeddings/", ".github/", "src/kg_microbe_workflows/")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--publish", action="store_true", help="Push the verified extraction branch")
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    target = RepositoryTarget("claw", root, "CultureBotAI/culturebotai-claw")
    with LockManager().lock("claw", "extract-edgemech-shared-contracts"):
        repo = target.open()
        if repo.active_branch.name != BRANCH or repo.is_dirty(untracked_files=True):
            raise ValueError("Expected a clean isolated contracts feature branch")
        if args.publish:
            changed = repo.git.diff_tree("--no-commit-id", "--name-only", "-r", SOURCE).splitlines()
            actual = repo.git.diff("--name-only", "origin/main...HEAD").splitlines()
            if actual != sorted(changed):
                raise ValueError("Published extraction must contain exactly the source contract paths")
            for path in changed:
                if repo.git.hash_object(path) != repo.git.rev_parse(f"{SOURCE}:{path}"):
                    raise ValueError(f"Extracted contract bytes changed: {path}")
            repo.git.push("--set-upstream", "origin", BRANCH)
            print(json.dumps({"status": "pushed", "head": repo.head.commit.hexsha,
                              "branch": BRANCH}, sort_keys=True))
            return
        base = repo.head.commit.hexsha
        if base != repo.git.rev_parse("origin/main"):
            raise ValueError("Contracts branch must begin at freshly fetched origin/main")
        changed = repo.git.diff_tree("--no-commit-id", "--name-only", "-r", SOURCE).splitlines()
        if any(path.startswith(FORBIDDEN) for path in changed):
            raise ValueError("The source commit unexpectedly changes admission or release policy")
        repo.git.cherry_pick(SOURCE)
        for path in changed:
            if repo.git.hash_object(path) != repo.git.rev_parse(f"{SOURCE}:{path}"):
                raise ValueError(f"Cherry-picked contract bytes changed: {path}")
        print(json.dumps({"base": base, "head": repo.head.commit.hexsha,
                          "source_commit": SOURCE, "files": changed}, sort_keys=True))


if __name__ == "__main__":
    main()
