#!/usr/bin/env python3
"""Replace the hand-kept list of claw-governed files in two Mechs' AGENTS.md (#2291, #3066).

Purpose: HabitatMech#2291 and CellStructureMech#3066 report that AGENTS.md lists
the claw-governed files by hand and the list has fallen behind the 24 files
claw's manifest governs for each. This replaces each list with a pointer to the
authoritative source (claw's vendored_artifacts.json at the commit pinned in
scripts/.vendored_canon_ref) and a read-only command that prints the current
set, so the guide cannot drift again.
Inputs: Mech roots exported from claw's .env (set -a; . ./.env); --worktrees DIR
for the new worktrees; --apply to write. Without --apply it prints the planned
replacement only.
Outputs: with --apply, one branch per Mech, created as a git worktree from
origin/main under DIR, committed and pushed to origin. It never touches the
Mechs' own checkouts or working trees. Each Mech's write holds its LockManager
lease, and origin is verified against the fleet manifest before the push.
Serves: CultureBotAI/HabitatMech#2291, CultureBotAI/CellStructureMech#3066
(raised in the culturebotai-claw#729 re-pin reviews). Written 2026-11-05.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from kg_microbe_fleet import load_fleet_manifest  # noqa: E402
from plugins.lock_manager import LockManager  # noqa: E402
from plugins.repository_settings import RepositorySettings, RepositoryTarget  # noqa: E402

LISTER = (
    'gh api "repos/CultureBotAI/culturebotai-claw/contents/src/kg_microbe_governance/'
    'vendored_artifacts.json?ref=$(cat scripts/.vendored_canon_ref)" \\\n'
    '{indent}  -H "Accept: application/vnd.github.raw+json" \\\n'
    "{indent}  --jq '.artifacts[] | select(.consumers == \"all\" or any(.consumers[]?; . == \"{key}\"))"
    " | .target'"
)

PLANS = {
    "habitatmech": {
        "issue": "#2291",
        "start": "**Do not edit any claw-governed vendored file here** --",
        "end": "Fix upstream in claw, then re-sync and bump the pin.",
        "new": (
            "**Do not edit any claw-governed vendored file here.** The governed files are\n"
            "every artifact that claw's `src/kg_microbe_governance/vendored_artifacts.json`,\n"
            "at the commit pinned in `scripts/.vendored_canon_ref`, lists for `habitatmech`.\n"
            "That set grows as claw governs more files, so it is not copied here; print it\n"
            "with:\n\n"
            "```bash\n" + LISTER.format(indent="", key="habitatmech") + "\n```\n\n"
            "`{package_path}` in a target is `src/habitatmech`. The files are vendored\n"
            "byte-identically, and `just check-vendored-sync` (and CI) fails on any local\n"
            "edit and names the file. Fix upstream in claw, then re-sync and bump the pin."
        ),
    },
    "cellstructuremech": {
        "issue": "#3066",
        "start": "- **Do not edit claw-governed vendored files here** —",
        "end": "Change them in claw and re-sync.",
        "new": (
            "- **Do not edit claw-governed vendored files here.** They are every artifact\n"
            "  that claw's `src/kg_microbe_governance/vendored_artifacts.json`, at the commit\n"
            "  in `scripts/.vendored_canon_ref`, lists for `cellstructuremech`. That set\n"
            "  grows as claw governs more files, so it is not copied here; print it with:\n\n"
            "  ```bash\n  " + LISTER.format(indent="  ", key="cellstructuremech") + "\n  ```\n\n"
            "  `{package_path}` in a target is `src/cellstructuremech`. They are checked\n"
            "  byte-for-byte in CI (`just vendored-check`). Change them in claw and re-sync."
        ),
    },
}
BRANCH = "docs/{number}-governed-files-pointer"


def run(*args: str) -> str:
    completed = subprocess.run(list(args), text=True, capture_output=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} failed: {completed.stderr.strip() or completed.stdout.strip()}")
    return completed.stdout


def replaced(text: str, plan: dict) -> str:
    for anchor in (plan["start"], plan["end"]):
        if text.count(anchor) != 1:
            raise RuntimeError(f"anchor {anchor!r} occurs {text.count(anchor)} times")
    start = text.index(plan["start"])
    end = text.index(plan["end"], start) + len(plan["end"])
    return text[:start] + plan["new"] + text[end:]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worktrees", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    settings = RepositorySettings.from_environment()
    mechs = load_fleet_manifest().mechs
    for key, plan in PLANS.items():
        root = settings.paths.get(key)
        if root is None:
            raise RuntimeError(f"{key}: {settings.errors.get(key, 'not configured')}")
        slug = mechs[key].github
        RepositoryTarget(name=key, path=root, expected_repository=slug).open()  # origin is the manifest's
        run("git", "-C", str(root), "fetch", "-q", "origin")
        before = run("git", "-C", str(root), "show", "origin/main:AGENTS.md")
        after = replaced(before, plan)
        branch = BRANCH.format(number=plan["issue"].lstrip("#"))
        print(f"=== {key} {slug} {plan['issue']} -> {branch}")
        print(after[after.index(plan["new"][:40]) - 200: after.index(plan["new"][:40]) + len(plan["new"]) + 200])
        if not args.apply:
            continue
        worktree = args.worktrees / f"{key}-governed-pointer"
        with LockManager().lock(key, "agents-governed-files-pointer"):
            run("git", "-C", str(root), "worktree", "add", "-q", "-b", branch, str(worktree), "origin/main")
            (worktree / "AGENTS.md").write_text(after, encoding="utf-8")
            if run("git", "-C", str(worktree), "status", "--porcelain").strip() != "M AGENTS.md":
                raise RuntimeError(f"{key}: unexpected worktree state")
            run("git", "-C", str(worktree), "add", "AGENTS.md")
            run("git", "-C", str(worktree), "commit", "-q", "-m",
                f"Point AGENTS.md at claw's manifest for the governed files\n\n"
                f"AGENTS.md listed the claw-governed files by hand. The list had fallen\n"
                f"behind the 24 files claw's manifest governs here: it omitted the\n"
                f"record-review, merge-queue, PR-shepherd and evidence-gate files. It now\n"
                f"names the manifest at the pinned commit as the source, and gives a\n"
                f"read-only command that prints the current set.\n\n"
                f"Fixes {plan['issue']}.\n\n"
                f"Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>")
            RepositoryTarget(name=key, path=worktree.resolve(), expected_repository=slug).open()
            run("git", "-C", str(worktree), "push", "-q", "-u", "origin", branch)
        print(f"pushed {key} {branch} {run('git', '-C', str(worktree), 'rev-parse', 'HEAD').strip()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
