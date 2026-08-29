"""`kg-microbe-skills check` -- validate every reference in every skill."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_fleet.roots import MechRootError, resolve_mech_root
from kg_microbe_skills.catalogue import (
    CatalogueError,
    applicable_mechs,
    canonical_text,
    load_canonical,
    load_catalogue,
    render_adapter,
)
from kg_microbe_skills.references import check, format_report

# kg-microbe is not a Mech, so the manifest does not describe it; the
# env-then-sibling shape matches `sync_kgm_dependencies.py`.
_KGM_VARIABLE = "KGMICROBE_ROOT"


def find_claw_root(start: Path | None = None) -> Path:
    """The checkout being checked, found from the working directory.

    Deriving it from `__file__` works only while the package is run from its
    source tree; installed into site-packages, `parents[2]` is somewhere in
    the virtualenv and every skill goes missing at once. The CI step that
    prompted this installs the package and runs from the checkout, which is
    the ordinary shape for a console script.
    """
    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        if (candidate / ".claude" / "skills").is_dir():
            return candidate
    raise SystemExit(
        f"no .claude/skills directory at or above {here}; run this from a "
        f"checkout that has skills to check"
    )


def _downstream(
    claw_root: Path,
) -> tuple[dict[str, Path], list[str], set[str], set[str]]:
    """Every checkout that could be resolved, and the ones that could not.

    An unresolvable checkout is not an error here: the checker reports what it
    could not verify instead of failing outright, and `--require-sources`
    turns that into a failure for callers that need the full answer.
    """
    # Claw answers for its own paths. Without it, a claw skill citing a claw
    # file that no longer exists came back `unverifiable` rather than
    # `missing` -- the checker's whole purpose, defeated in the one
    # configuration the gate actually runs in (#216).
    resolved: dict[str, Path] = {"culturebotai-claw": claw_root}
    absent: list[str] = []
    manifest = load_fleet_manifest()
    known = {"kg-microbe"}
    mech_labels = {m.display_name for m in manifest.mechs.values()}
    for key in sorted(manifest.mechs):
        display = manifest.mechs[key].display_name
        known.add(display)
        try:
            resolved[display] = resolve_mech_root(key, claw_root=claw_root)
        except MechRootError:
            absent.append(display)

    configured = (os.environ.get(_KGM_VARIABLE) or "").strip()
    kgm = Path(configured) if configured else claw_root.parent / "kg-microbe"
    if kgm.is_dir():
        resolved["kg-microbe"] = kgm
    else:
        absent.append("kg-microbe")
    return resolved, absent, known, mech_labels


def _print_catalogue() -> int:
    """What is here, what it is for, and what gets rendered per Mech."""
    entries = load_catalogue()
    width = max(len(name) for name in entries)
    for scope in ("claw", "fleet", "domain"):
        named = sorted(n for n, e in entries.items() if e.scope == scope)
        print(f"{scope} ({len(named)})")
        for name in named:
            print(f"  {name:<{width}}  {entries[name].reason.splitlines()[0]}")
    canonical = load_canonical()
    print(f"\ncanonical templates ({len(canonical)})")
    for name, skill in sorted(canonical.items()):
        mechs = applicable_mechs(skill)
        print(f"  {name}  [{skill.capability}] -> {', '.join(mechs)}")
    return 0


def _render(skill: str | None, mech: str | None) -> int:
    """Print one adapter. Printing, not installing: writing it into a Mech is a
    downstream mutation and goes through the cross-repository checklist."""
    if not skill or not mech:
        print("render needs --skill and --mech", file=sys.stderr)
        return 2
    try:
        print(render_adapter(canonical_text(skill), mech), end="")
    except CatalogueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="kg-microbe-skills",
        description=(
            "Check that every path and sibling-skill reference in this "
            "repository's skills points at something that exists."
        ),
    )
    parser.add_argument(
        "command",
        choices=["check", "catalogue", "render"],
        help=(
            "check: validate every reference; catalogue: list every skill and "
            "its scope; render: print one Mech's adapter for a canonical skill"
        ),
    )
    parser.add_argument(
        "--skill", help="render: which canonical skill (see `catalogue`)"
    )
    parser.add_argument("--mech", help="render: which Mech, by manifest key")
    parser.add_argument(
        "--require-sources",
        action="store_true",
        help=(
            "fail if any downstream checkout could not be resolved, instead of "
            "reporting the references that could not be verified"
        ),
    )
    args = parser.parse_args(argv)

    # `catalogue` and `render` read packaged data, so they work from anywhere.
    # Only `check` needs a checkout, and it finds one after parsing so --help
    # still works without (#179).
    if args.command == "catalogue":
        return _print_catalogue()
    if args.command == "render":
        return _render(args.skill, args.mech)

    claw_root = find_claw_root()
    downstream, absent, known, mech_labels = _downstream(claw_root)
    findings = check(
        claw_root, downstream, repositories=known, mech_labels=mech_labels
    )

    print(format_report(findings))
    if absent:
        print(
            f"\n{len(absent)} checkout(s) not resolvable, so references absent "
            f"from claw could not be ruled in or out against them: "
            f"{', '.join(absent)}"
        )

    if args.require_sources and absent:
        print("\n--require-sources: refusing to report a partial answer.")
        return 2

    broken = [f for f in findings if f.verdict in ("missing", "ambiguous")]
    return 1 if broken else 0


if __name__ == "__main__":  # pragma: no cover - console entry point
    sys.exit(main())
