"""Offline triage and execution-policy queries over a Mech research profile.

Every command here is read-only and never contacts a provider. `authorize` is
the command that decides whether a call *would* be permitted; it prints the
decision and exits nonzero when policy refuses, so a caller can gate on it
before spending anything.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from .policy import COST_TIERS, PolicyError, authorize, plan_stage
from .profile import ProfileError, ResearchProfile, load_profile
from .providers import (
    PROVIDERS,
    normalize_allowlist,
    provider_status,
    unknown_providers,
)
from .triage import build_report


def _table(headers: Sequence[str], rows: Sequence[Sequence[object]]) -> str:
    values: list[tuple[str, ...]] = [tuple(headers)]
    values.extend(tuple(str(cell) for cell in row) for row in rows)
    widths = [max(len(row[index]) for row in values) for index in range(len(headers))]
    lines = [
        "  ".join(value.ljust(widths[index]) for index, value in enumerate(values[0])),
        "  ".join("-" * width for width in widths),
    ]
    lines.extend(
        "  ".join(value.ljust(widths[index]) for index, value in enumerate(row))
        for row in values[1:]
    )
    return "\n".join(lines)


RANKED_HEADERS = (
    "Provider",
    "Status",
    "Fit",
    "Cost",
    "Paid",
    "Time",
    "Synthesis",
    "Source scope",
)


def _load(args: argparse.Namespace) -> ResearchProfile:
    return load_profile(Path(args.profile))


def _cmd_providers(args: argparse.Namespace) -> int:
    rows = []
    for name, provider in sorted(PROVIDERS.items()):
        status, reason = provider_status(name)
        rows.append(
            {
                "provider": name,
                "label": provider.label,
                "status": status,
                "status_reason": reason,
                "cost": provider.cost,
                "paid": provider.cost in {"high", "very_high"},
                "time": provider.time,
                "synthesis": provider.synthesis,
                "source_scope": provider.source_scope,
                "capabilities": sorted(provider.capabilities),
                "best_for": provider.best_for,
                "limitation": provider.limitation,
            }
        )
    if args.json:
        print(json.dumps({"providers": rows}, indent=2))
        return 0
    print(
        _table(
            ("Provider", "Status", "Cost", "Paid", "Time", "Synthesis", "Why"),
            [
                (
                    row["provider"],
                    row["status"],
                    row["cost"],
                    "yes" if row["paid"] else "no",
                    row["time"],
                    row["synthesis"],
                    row["status_reason"],
                )
                for row in rows
            ],
        )
    )
    return 0


def _cmd_triage(args: argparse.Namespace) -> int:
    profile = _load(args)
    allow = normalize_allowlist(args.allow or None)
    if allow is not None:
        unknown = unknown_providers(allow)
        if unknown:
            # Same refusal as `authorize`; otherwise a typo'd --allow is
            # indistinguishable from "no provider fits" and still exits 0.
            raise PolicyError(
                f"Unknown provider(s) in allowlist: {unknown}; choose from "
                f"{', '.join(sorted(PROVIDERS))}"
            )
    report = build_report(
        profile,
        args.focus,
        allow=allow,
        no_paid=args.no_paid,
    )
    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    print(f"{report['mech']} — {report['focus_label']} ({report['focus']})")
    if report["target"]:
        print(f"Target: {report['target']}")
    for stage in report["stages"]:
        print(f"\n## {stage['name']}")
        if stage["objective"]:
            print(stage["objective"])
        recommended = stage["recommended_available"]
        print(
            "Recommended: "
            + (recommended["provider"] if recommended else "none under this policy")
        )
        rows = [
            (
                row["provider"],
                row["status"],
                str(row["fit"]),
                row["cost"],
                "yes" if row["paid"] else "no",
                row["time"],
                row["synthesis"],
                row["source_scope"],
            )
            for row in stage["ranking"]
        ]
        print(_table(RANKED_HEADERS, rows))
    return 0


def _cmd_authorize(args: argparse.Namespace) -> int:
    profile = _load(args)
    plan = plan_stage(
        profile,
        args.stage,
        focus=args.focus,
        allow=args.allow or None,
        no_paid=args.no_paid,
    )
    try:
        decision = authorize(
            plan,
            provider=args.provider,
            apply=args.apply,
            acknowledge_paid=args.acknowledge_paid,
            max_cost=args.max_cost,
            override_reason=args.override_reason,
        )
    except PolicyError as exc:
        payload: dict[str, Any] = {"permitted": False, "error": str(exc)}
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"Refused: {exc}", file=sys.stderr)
        return 2
    payload = {"permitted": True, **decision.as_dict()}
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"{decision.provider} — {payload['mode']}")
        for reason in decision.reasons:
            print(f"  - {reason}")
    return 0


def _add_profile_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--profile",
        required=True,
        help="Path to a Mech conf/deep_research_provider.yaml focus profile.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="kg-microbe-research",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    providers = subparsers.add_parser(
        "providers", help="List the shared provider catalogue and local status."
    )
    providers.add_argument("--json", action="store_true")
    providers.set_defaults(func=_cmd_providers)

    triage = subparsers.add_parser(
        "triage", help="Rank providers for every stage of a focus."
    )
    _add_profile_argument(triage)
    triage.add_argument("--focus", help="Focus name; defaults to the profile default.")
    triage.add_argument(
        "--allow", action="append", metavar="PROVIDER", help="Restrict recommendations."
    )
    triage.add_argument(
        "--no-paid", action="store_true", help="Exclude paid-tier providers."
    )
    triage.add_argument("--json", action="store_true")
    triage.set_defaults(func=_cmd_triage)

    authorize_parser = subparsers.add_parser(
        "authorize",
        help="Decide whether a call is permitted. Dry run unless --apply.",
    )
    _add_profile_argument(authorize_parser)
    authorize_parser.add_argument("--stage", required=True)
    authorize_parser.add_argument("--focus")
    authorize_parser.add_argument("--provider", help="Override the triage choice.")
    authorize_parser.add_argument("--allow", action="append", metavar="PROVIDER")
    authorize_parser.add_argument("--no-paid", action="store_true")
    authorize_parser.add_argument(
        "--apply",
        action="store_true",
        help="Authorize a live, possibly billed call. Off by default.",
    )
    authorize_parser.add_argument(
        "--acknowledge-paid",
        action="store_true",
        help="Acknowledge that the chosen provider bills for the call.",
    )
    authorize_parser.add_argument(
        "--max-cost",
        choices=COST_TIERS,
        help="Authorize paid calls up to and including this cost tier.",
    )
    authorize_parser.add_argument(
        "--override-reason",
        help="Record why a provider triage would not offer is being used anyway.",
    )
    authorize_parser.add_argument("--json", action="store_true")
    authorize_parser.set_defaults(func=_cmd_authorize)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (ProfileError, PolicyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
