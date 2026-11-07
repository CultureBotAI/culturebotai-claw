"""Validate and lock native-adapter worktrees for CLAW #767 (2026-11-07).

Inputs: explicit repository root, intended worktree/branch and expected base.
Outputs: validated isolated worktree, or a locked command's artifacts.
No environment secrets are loaded, written, or printed.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

from kg_microbe_fleet import load_fleet_manifest
from plugins.lock_manager import LockManager
from plugins.repository_settings import RepositorySettings


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default="mediaingredientmech")
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--worktree", type=Path)
    parser.add_argument("--branch")
    parser.add_argument("--expected-head")
    parser.add_argument("--base", help="Explicit new-worktree base; defaults to the validated root HEAD")
    parser.add_argument("--fetch", action="store_true", help="Fetch origin/main under the repository lock before creating the worktree")
    parser.add_argument("--create", action="store_true")
    parser.add_argument("--locks-dir", type=Path, required=True)
    parser.add_argument("--run", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    manifest = load_fleet_manifest()
    definition = manifest.mechs[args.repository]
    environment = dict(os.environ)
    environment[definition.environment_variable] = str(args.root.resolve())
    subprocess.run(
        [sys.executable, "-m", "cli.main", "config", "validate"],
        env=environment, check=True,
    )
    settings = RepositorySettings.from_environment(environ=environment, manifest=manifest)
    target = settings.get_target(args.repository)
    repository = target.open()
    print(f"Validated {args.repository}: {target.path}")
    print(f"Branch {repository.active_branch.name}; HEAD {repository.head.commit.hexsha}")
    status = repository.git.status("--short")
    print(status or "Working tree clean")
    if args.expected_head and repository.head.commit.hexsha != args.expected_head:
        raise ValueError("Repository HEAD differs from the explicitly reviewed base")
    manager = LockManager({"locks_dir": args.locks_dir, "my_id": "edgemech-native-adapters"})
    if args.create:
        if not args.worktree or not args.branch or not args.expected_head:
            parser.error("--create requires --worktree, --branch and --expected-head")
        if args.worktree.exists():
            raise ValueError("Refusing to reuse an existing worktree destination")
        with manager.lock(args.repository, "prepare_native_adapter_worktree"):
            repository = target.open()
            if args.fetch:
                repository.git.fetch("origin", "main")
            base = args.base or args.expected_head
            if repository.commit(base).hexsha != base:
                raise ValueError("Worktree base must be a complete immutable commit")
            if args.fetch and repository.commit("origin/main").hexsha != base:
                raise ValueError("Fetched main differs from the explicitly reviewed base")
            target.open().git.worktree(
                "add", "-b", args.branch, str(args.worktree), base
            )
            environment[definition.environment_variable] = str(args.worktree.resolve())
            created = RepositorySettings.from_environment(
                environ=environment, manifest=manifest
            ).get_target(args.repository).open()
            if created.active_branch.name != args.branch or created.head.commit.hexsha != base:
                raise ValueError("Created worktree failed branch/base verification")
            print(f"Created {created.working_tree_dir} on {created.active_branch.name}")
    if args.run:
        if repository.active_branch.name in {"main", "master"}:
            raise ValueError("Adapter commands require a feature branch")
        with manager.lock(args.repository, "native_adapter_command"):
            target.open()
            subprocess.run(args.run, cwd=target.path, env=environment, check=True)


if __name__ == "__main__":
    main()
