"""Prepare the isolated site follow-up for CLAW #1254 (2026-11-15).

Inputs: an explicit preserved site checkout, CLAW root, destination and branch.
Output: a fresh current-main site clone/topic branch; JSON preparation evidence.
Dry-run by default. No source-checkout mutation, merge, deployment or settings edit.
"""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from kg_microbe_fleet.roots import resolve_culturebotai_site_root
from plugins.lock_manager import LockManager
from plugins.repository_settings import RepositorySettings


def checked(command: list[str], *, cwd: Path | None = None) -> str:
    return subprocess.run(
        command, cwd=cwd, check=True, text=True, capture_output=True, timeout=180
    ).stdout.strip()


def validate_site(path: Path) -> None:
    target = RepositorySettings._resolve_target(
        name="culturebotai_site", raw_path=str(path),
        environment_variable="CULTUREBOTAI_SITE_ROOT",
        expected_repository="CultureBotAI/CultureBotAI.github.io", environ={},
    )
    settings = RepositorySettings({"culturebotai_site": target}, {}, ("culturebotai_site",))
    settings.get_target("culturebotai_site").open()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claw-root", type=Path, required=True)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    claw = args.claw_root.resolve(strict=True)
    source = resolve_culturebotai_site_root(
        claw_root=claw, environ={"CULTUREBOTAI_SITE_ROOT": str(args.source)}
    )
    if source is None:
        raise SystemExit("Explicit site checkout did not resolve")
    validate_site(source)
    destination = args.destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise SystemExit("Destination must not already exist")
    if not destination.parent.resolve(strict=True).is_relative_to(claw / ".temp"):
        raise SystemExit("Destination must be inside the existing CLAW .temp task directory")
    checked(["git", "check-ignore", str(destination)], cwd=claw)
    checked(["git", "check-ref-format", "refs/heads/" + args.branch])
    receipt = {
        "source": str(source), "source_head": checked(["git", "rev-parse", "HEAD"], cwd=source),
        "source_status": checked(["git", "status", "--porcelain=v1"], cwd=source),
        "destination": str(destination), "branch": args.branch, "applied": False,
    }
    if args.apply:
        with LockManager().lock("culturebotai_site", "prepare-public-projection-1254", timeout=600):
            validate_site(source)
            if destination.exists() or destination.is_symlink():
                raise SystemExit("Destination appeared after preflight")
            checked([
                "git", "clone", "--filter=blob:none", "--no-checkout", "--depth", "1",
                "--branch", "main", "https://github.com/CultureBotAI/CultureBotAI.github.io.git",
                str(destination),
            ])
            validate_site(destination)
            checked(["git", "checkout", "-b", args.branch, "origin/main"], cwd=destination)
            receipt["base_sha"] = checked(["git", "rev-parse", "HEAD"], cwd=destination)
            receipt["destination_status"] = checked(["git", "status", "--porcelain=v1"], cwd=destination)
            receipt["applied"] = True
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
