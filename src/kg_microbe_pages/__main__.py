"""`kg-microbe-pages audit` -- enforce one Mech's page budgets."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_fleet.roots import MechRootError, resolve_mech_root
from kg_microbe_pages.budgets import BudgetError, as_json, audit, load_budgets

CLAW_ROOT = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    manifest = load_fleet_manifest()
    parser = argparse.ArgumentParser(
        prog="kg-microbe-pages",
        description=(
            "Measure a built site against the budgets its repository declares: "
            "total bytes, file count, and per-group totals and largest members. "
            "A site with too few files fails before any size limit, because an "
            "empty site is under all of them."
        ),
    )
    parser.add_argument("command", choices=["audit"])
    parser.add_argument("--mech", required=True, choices=sorted(manifest.mechs))
    parser.add_argument(
        "--site",
        type=Path,
        help="the built site, overriding the manifest's site_path (CI builds "
        "into a directory that does not exist in the checkout)",
    )
    args = parser.parse_args(argv)

    mech = manifest.mechs[args.mech]
    capability = mech.capabilities.get("page_budgets")
    if capability is None or not capability.is_enabled:
        reason = getattr(capability, "reason", "") or "not declared in the manifest"
        print(f"{args.mech} declares no page budgets: {reason}")
        return 0

    try:
        root = resolve_mech_root(args.mech, claw_root=CLAW_ROOT)
    except MechRootError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    site = args.site or (root / capability.settings["site_path"])
    try:
        budgets = load_budgets(root / capability.settings["budgets_path"])
    except BudgetError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    metrics, failures = audit(site, budgets)
    print(as_json(metrics, failures), end="")
    for failure in failures:
        print(f"  OVER BUDGET: {failure}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":  # pragma: no cover - console entry point
    sys.exit(main())
