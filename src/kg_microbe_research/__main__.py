"""Offline triage and execution-policy queries over a Mech research profile.

Every command here is read-only and never contacts a provider. `authorize`
exits zero only for an explicitly live authorization; a successful dry-run
report exits three. That distinction makes `kg-microbe-research authorize &&
provider-command` fail closed instead of treating a dry run as permission.
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
    AvailabilityError,
    AvailabilityEvidence,
    load_availability,
    normalize_allowlist,
    provider_status,
    requires_usage_authorization,
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
    "Billing",
    "Usage auth",
    "Time",
    "Synthesis",
    "Source scope",
)


def _load(args: argparse.Namespace) -> ResearchProfile:
    return load_profile(Path(args.profile))


def _availability(args: argparse.Namespace) -> AvailabilityEvidence | None:
    path = getattr(args, "availability_evidence", None)
    return load_availability(Path(path)) if path else None


def _cmd_providers(args: argparse.Namespace) -> int:
    availability = _availability(args)
    rows = []
    for name, provider in sorted(PROVIDERS.items()):
        status, reason = provider_status(name, availability=availability)
        rows.append(
            {
                "provider": name,
                "label": provider.label,
                "status": status,
                "status_reason": reason,
                "cost": provider.cost,
                "billing": provider.billing,
                "usage_authorization_required": requires_usage_authorization(name),
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
            (
                "Provider",
                "Status",
                "Cost",
                "Billing",
                "Usage auth",
                "Time",
                "Synthesis",
                "Why",
            ),
            [
                (
                    row["provider"],
                    row["status"],
                    row["cost"],
                    row["billing"],
                    "yes" if row["usage_authorization_required"] else "no",
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
    availability = _availability(args)
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
        availability=availability,
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
            "Recommended: " + (recommended["provider"] if recommended else "none under this policy")
        )
        rows = [
            (
                row["provider"],
                row["status"],
                str(row["fit"]),
                row["cost"],
                row["billing"],
                "yes" if row["usage_authorization_required"] else "no",
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
    availability = _availability(args)
    try:
        plan = plan_stage(
            profile,
            args.stage,
            focus=args.focus,
            allow=args.allow or None,
            no_paid=args.no_paid,
            availability=availability,
        )
        decision = authorize(
            plan,
            provider=args.provider,
            apply=args.apply,
            acknowledge_usage=args.acknowledge_usage,
            max_cost=args.max_cost,
            override_reason=args.override_reason,
        )
    except PolicyError as exc:
        payload: dict[str, Any] = {
            "execution_authorized": False,
            "error": str(exc),
        }
        if args.json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"Refused: {exc}", file=sys.stderr)
        return 2
    payload = {"execution_authorized": decision.live, **decision.as_dict()}
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"{decision.provider} — {payload['mode']}")
        for reason in decision.reasons:
            print(f"  - {reason}")
    return 0 if decision.live else 3


def _add_profile_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--profile",
        required=True,
        help="Path to a Mech conf/deep_research_provider.yaml focus profile.",
    )


def _add_availability_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--availability-evidence",
        metavar="JSON",
        help=(
            "Trusted, versioned provider-status JSON with source/context and a "
            "maximum 24-hour lifetime. This command never creates evidence or "
            "performs a provider health probe."
        ),
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
    _add_availability_argument(providers)
    providers.add_argument("--json", action="store_true")
    providers.set_defaults(func=_cmd_providers)

    triage = subparsers.add_parser("triage", help="Rank providers for every stage of a focus.")
    _add_profile_argument(triage)
    _add_availability_argument(triage)
    triage.add_argument("--focus", help="Focus name; defaults to the profile default.")
    triage.add_argument(
        "--allow", action="append", metavar="PROVIDER", help="Restrict recommendations."
    )
    triage.add_argument(
        "--no-paid",
        action="store_true",
        help="Exclude providers not explicitly free (including quota-metered use).",
    )
    triage.add_argument("--json", action="store_true")
    triage.set_defaults(func=_cmd_triage)

    authorize_parser = subparsers.add_parser(
        "authorize",
        help="Evaluate execution policy; exit zero only for live authorization.",
    )
    _add_profile_argument(authorize_parser)
    _add_availability_argument(authorize_parser)
    authorize_parser.add_argument("--stage", required=True)
    authorize_parser.add_argument("--focus")
    authorize_parser.add_argument("--provider", help="Override the triage choice.")
    authorize_parser.add_argument("--allow", action="append", metavar="PROVIDER")
    authorize_parser.add_argument(
        "--no-paid",
        action="store_true",
        help="Exclude providers not explicitly free (including quota-metered use).",
    )
    authorize_parser.add_argument(
        "--apply",
        action="store_true",
        help="Authorize live execution. Off by default; this command never calls it.",
    )
    authorize_parser.add_argument(
        "--acknowledge-usage",
        "--acknowledge-paid",
        dest="acknowledge_usage",
        action="store_true",
        help="Acknowledge possible provider quota, credit, or billing consumption.",
    )
    authorize_parser.add_argument(
        "--max-cost",
        choices=COST_TIERS,
        help="Authorize non-free use up to and including this relative cost tier.",
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
    except (AvailabilityError, ProfileError, PolicyError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
