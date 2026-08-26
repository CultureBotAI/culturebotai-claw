"""Offline triage, policy, and research-result tools for the Mech fleet.

No command here contacts a provider. ``scaffold-result`` writes an append-only
dry-run record; the other commands are read-only. ``authorize`` exits zero only
for an explicitly live authorization and exits three for a successful dry run.
That distinction makes ``kg-microbe-research authorize && provider-command``
fail closed instead of treating a dry run as permission.
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
from .records import (
    ResearchRecordError,
    build_dry_run_result,
    load_result,
    new_result_path,
    write_result,
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


def _repository_file(root: Path, value: str, label: str) -> Path:
    """Resolve a CLI path beneath a repository without accepting escape."""

    repository = root.resolve(strict=True)
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = repository / candidate
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(repository)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise ResearchRecordError(
            f"{label} must be an existing file inside repository root {repository}"
        ) from exc
    if not resolved.is_file():
        raise ResearchRecordError(f"{label} is not a file: {resolved}")
    return resolved


def _repository_root(value: str) -> Path:
    try:
        root = Path(value).resolve(strict=True)
    except (FileNotFoundError, RuntimeError, OSError) as exc:
        raise ResearchRecordError(f"repository root does not exist: {value}") from exc
    if not root.is_dir():
        raise ResearchRecordError(f"repository root is not a directory: {root}")
    return root


def _cmd_scaffold_result(args: argparse.Namespace) -> int:
    repository = _repository_root(args.repository_root)
    profile_path = _repository_file(repository, args.profile, "--profile")
    target_path = _repository_file(repository, args.target_path, "--target-path")
    availability = _availability(args)
    result = build_dry_run_result(
        repository_root=repository,
        profile_path=profile_path,
        target_path=target_path,
        target_id=args.target_id,
        target_label=args.target_label,
        target_type=args.target_type,
        question=args.question,
        question_id=args.question_id,
        focus_name=args.focus,
        allow=args.allow or None,
        no_paid=args.no_paid,
        availability=availability,
    )
    if args.output:
        raw_output = Path(args.output)
        output = raw_output if raw_output.is_absolute() else repository / raw_output
        try:
            output.resolve(strict=False).relative_to(repository)
        except (RuntimeError, ValueError) as exc:
            raise ResearchRecordError(
                f"--output must stay inside repository root {repository}"
            ) from exc
    else:
        output = new_result_path(
            repository,
            target_id=args.target_id,
            result_id=result["result_id"],
        )
    written = write_result(output, result, repository_root=repository)
    print(written)
    return 0


def _cmd_validate_result(args: argparse.Namespace) -> int:
    repository = _repository_root(args.repository_root)
    result_path = _repository_file(repository, args.result, "RESULT")
    load_result(
        result_path,
        repository_root=repository,
        verify_artifacts=True,
        verify_snapshots=args.verify_snapshots,
    )
    print(f"OK: {result_path}", file=sys.stderr)
    return 0


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
        help=(
            "Record why an explicitly selected provider replaces the triage "
            "recommendation, including selection of an eligible fallback."
        ),
    )
    authorize_parser.add_argument("--json", action="store_true")
    authorize_parser.set_defaults(func=_cmd_authorize)

    scaffold = subparsers.add_parser(
        "scaffold-result",
        help="Write a schema-valid dry-run result; never call a provider.",
    )
    _add_profile_argument(scaffold)
    _add_availability_argument(scaffold)
    scaffold.add_argument(
        "--repository-root",
        default=".",
        help="Mech repository root used to constrain paths and verify snapshots.",
    )
    scaffold.add_argument("--target-path", required=True, help="Repo-relative target file.")
    scaffold.add_argument("--target-id", required=True)
    scaffold.add_argument("--target-label", required=True)
    scaffold.add_argument("--target-type", required=True)
    scaffold.add_argument("--question", required=True)
    scaffold.add_argument("--question-id")
    scaffold.add_argument("--focus", help="Focus name; defaults to the profile default.")
    scaffold.add_argument(
        "--allow", action="append", metavar="PROVIDER", help="Restrict recommendations."
    )
    scaffold.add_argument(
        "--no-paid",
        action="store_true",
        help="Exclude every provider not explicitly classified free.",
    )
    scaffold.add_argument(
        "--output",
        help="YAML path inside the repository; defaults to research/runs/<target>/<result-id>.yaml.",
    )
    scaffold.set_defaults(func=_cmd_scaffold_result)

    validate = subparsers.add_parser(
        "validate-result",
        help="Validate schema, semantics, references, and artifact bytes offline.",
    )
    validate.add_argument("result", help="Research-result YAML inside the repository.")
    validate.add_argument("--repository-root", default=".")
    validate.add_argument(
        "--verify-snapshots",
        action="store_true",
        help="Also compare the current profile and target files with historical digests.",
    )
    validate.set_defaults(func=_cmd_validate_result)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except (
        AvailabilityError,
        FileExistsError,
        ProfileError,
        PolicyError,
        ResearchRecordError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
