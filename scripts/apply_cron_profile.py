#!/usr/bin/env python3
"""Apply a named cadence profile from .github/cron-profiles.yaml to the workflows.

Rewrites ONLY the `on.schedule:` block of each managed workflow. Inputs, jobs and
every comment outside that block are left byte-for-byte alone, which is why this
edits lines rather than round-tripping through a YAML dumper — a dumper would
discard the comments that carry the reasoning.

    python scripts/apply_cron_profile.py <profile> [--dry-run] [--config PATH]
    python scripts/apply_cron_profile.py --list

Exit codes: 0 ok, 1 nothing to do or a workflow was malformed, 2 bad usage.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = REPO_ROOT / ".github" / "cron-profiles.yaml"
WORKFLOW_DIR = REPO_ROOT / ".github" / "workflows"


def load_config(path: Path) -> dict:
    if not path.is_file():
        sys.exit(f"error: config not found at {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if "profiles" not in data:
        sys.exit(f"error: {path} has no `profiles:` key")
    return data


def managed_workflows(config: dict) -> set[str]:
    """Every workflow named by any profile.

    Union rather than intersection so a workflow added to one profile but
    forgotten in another is caught by the completeness check below instead of
    being silently unmanaged.
    """
    names: set[str] = set()
    for profile in config["profiles"].values():
        names.update((profile.get("workflows") or {}).keys())
    return names


def check_profiles_complete(config: dict) -> list[str]:
    """A profile that omits a managed workflow would leave it on its old cadence.

    That is the exact failure this file exists to prevent, so it is an error
    rather than a warning.
    """
    problems = []
    everything = managed_workflows(config)
    for name, profile in config["profiles"].items():
        missing = everything - set((profile.get("workflows") or {}).keys())
        if missing:
            problems.append(f"profile '{name}' does not mention: {', '.join(sorted(missing))}")
    return problems


def resolve_workflow(stem: str) -> Path | None:
    for ext in (".yml", ".yaml"):
        candidate = WORKFLOW_DIR / f"{stem}{ext}"
        if candidate.is_file():
            return candidate
    return None


def render_schedule(entries: list[dict]) -> list[str]:
    lines = ["  schedule:"]
    for entry in entries:
        cron = entry["cron"]
        comment = entry.get("comment")
        suffix = f"   # {comment}" if comment else ""
        lines.append(f'    - cron: "{cron}"{suffix}')
    return lines


def rewrite(text: str, entries: list[dict]) -> tuple[str, str]:
    """Return (new_text, what_changed). Raises ValueError if the shape is unexpected."""
    lines = text.splitlines()

    on_idx = next((i for i, l in enumerate(lines) if l.rstrip() == "on:"), None)
    if on_idx is None:
        raise ValueError("no top-level `on:` block")

    # The `on:` block runs until the next line that starts in column 0 and is not
    # blank or a comment.
    end = len(lines)
    for i in range(on_idx + 1, len(lines)):
        stripped = lines[i]
        if stripped and not stripped[0].isspace() and not stripped.startswith("#"):
            end = i
            break

    sched_idx = next(
        (i for i in range(on_idx + 1, end) if lines[i].rstrip() == "  schedule:"), None
    )

    if sched_idx is None:
        if not entries:
            return text, "already unscheduled"
        # Insert immediately after `on:` so the schedule reads first.
        new_lines = lines[: on_idx + 1] + render_schedule(entries) + lines[on_idx + 1 :]
        return "\n".join(new_lines) + "\n", f"added {len(entries)} cron entr(y/ies)"

    # Extent of the existing schedule block: subsequent lines indented deeper.
    sched_end = sched_idx + 1
    while sched_end < end:
        line = lines[sched_end]
        if line.strip() == "" or line.startswith("    ") or line.lstrip().startswith("#"):
            sched_end += 1
            continue
        break

    if not entries:
        new_lines = lines[:sched_idx] + lines[sched_end:]
        return "\n".join(new_lines) + "\n", "removed the schedule block"

    new_lines = lines[:sched_idx] + render_schedule(entries) + lines[sched_end:]
    return "\n".join(new_lines) + "\n", f"set {len(entries)} cron entr(y/ies)"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("profile", nargs="?", help="profile name from cron-profiles.yaml")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--list", action="store_true", dest="do_list")
    args = ap.parse_args(argv)

    config = load_config(Path(args.config))

    problems = check_profiles_complete(config)
    if problems:
        for p in problems:
            print(f"error: {p}", file=sys.stderr)
        print(
            "Every profile must name every managed workflow — an omission would "
            "silently leave it on its previous cadence.",
            file=sys.stderr,
        )
        return 1

    if args.do_list or not args.profile:
        active = config.get("active")
        print(f"active: {active}")
        for name, profile in config["profiles"].items():
            marker = "*" if name == active else " "
            desc = " ".join((profile.get("description") or "").split())
            print(f" {marker} {name}: {desc}")
        if not args.profile:
            return 0
        return 0

    if args.profile not in config["profiles"]:
        print(
            f"error: unknown profile '{args.profile}'. Known: "
            f"{', '.join(config['profiles'])}",
            file=sys.stderr,
        )
        return 2

    wanted = config["profiles"][args.profile].get("workflows") or {}
    changed = missing = failed = 0

    for stem, entries in sorted(wanted.items()):
        path = resolve_workflow(stem)
        if path is None:
            # Expected while the agent workflows are still unwritten. Report it
            # rather than passing silently — a typo'd stem looks identical.
            print(f"  skip  {stem}: no workflow file (not created yet?)")
            missing += 1
            continue
        original = path.read_text(encoding="utf-8")
        try:
            updated, what = rewrite(original, entries or [])
        except ValueError as exc:
            print(f"  FAIL  {stem}: {exc}", file=sys.stderr)
            failed += 1
            continue
        if updated == original:
            print(f"  ok    {stem}: unchanged")
            continue
        if args.dry_run:
            print(f"  would {stem}: {what}")
        else:
            path.write_text(updated, encoding="utf-8")
            print(f"  wrote {stem}: {what}")
        changed += 1

    print(
        f"\nprofile '{args.profile}': {changed} changed, {missing} absent, {failed} failed"
    )
    if not args.dry_run and changed:
        print("Remember to update `active:` in cron-profiles.yaml to match.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
