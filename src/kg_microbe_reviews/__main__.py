"""`kg-microbe-reviews`: shared review persistence and manifest-scoped fleet triage."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_fleet.roots import claw_root, is_claw_checkout
from kg_microbe_governance.artifacts.scripts import record_review as contract
from kg_microbe_reviews.aggregate import SEVERITY_ORDER, collect_repository, render_summary, triage
from plugins.repository_settings import (
    RepositoryConfigurationError,
    RepositorySettings,
    merged_repository_environment,
)


def fleet_main(argv: list[str]) -> int:
    manifest = load_fleet_manifest()
    parser = argparse.ArgumentParser(description="Aggregate structured reviews without modifying repositories.")
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--all", action="store_true", help="every current manifest Mech, including unavailable roots")
    scope.add_argument("--mech", choices=sorted(manifest.mechs), action="append")
    parser.add_argument("--claw-root", type=Path, default=claw_root())
    surface = parser.add_mutually_exclusive_group()
    surface.add_argument("--ref", default="origin/main", help="local cached Git ref; this command never fetches")
    surface.add_argument("--working-tree", action="store_true", help="include local uncommitted and ignored reviews")
    parser.add_argument("--format", choices=["json", "markdown", "tsv"], default="json")
    parser.add_argument("--severity", choices=list(SEVERITY_ORDER), action="append")
    parser.add_argument("--status", choices=["open", "deferred", "resolved", "accepted_risk", "rejected",
                                             "conflicting_dispositions", "unverified_lineage"], action="append")
    parser.add_argument("--require-reviews", action="store_true", help="fail if any requested repository has no structured review")
    parser.add_argument("--output", type=Path, help="create a new report file, never overwrite")
    args = parser.parse_args(argv)
    try:
        if not is_claw_checkout(args.claw_root):
            raise RepositoryConfigurationError("--claw-root must identify an actual CLAW checkout")
        env_path = args.claw_root / ".env"
        environment = merged_repository_environment(env_path if env_path.exists() or env_path.is_symlink() else None)
        settings = RepositorySettings.from_environment(environ=environment, manifest=manifest)
        keys = sorted(manifest.mechs) if args.all else sorted(set(args.mech))
        results = []
        ref = None if args.working_tree else args.ref
        for key in keys:
            mech = manifest.mechs[key]
            try:
                target = settings.get_target(key)
                target.open()
                result = collect_repository(target.path, mech.github, ref=ref)
            except (RepositoryConfigurationError, contract.ReviewError, OSError, UnicodeError) as exc:
                result = {"repository": mech.github, "surface": "working_tree" if ref is None else "git_ref",
                          "ref": ref, "revision": None, "remote_freshness": "not_checked",
                          "status": "unavailable", "reports": [], "error": str(exc)}
            results.append(result)
        report = triage(results)
        report["generated_at"] = contract.utc_now()
        report["requested_mechs"] = keys
        report["issues"] = [issue for issue in report["issues"]
                            if (not args.severity or issue["severity"] in args.severity)
                            and (not args.status or issue["status"] in args.status)]
        report["filters"] = {"severity": args.severity or [], "status": args.status or []}
        visible = {(i["repository"].lower(), i["issue_key"]) for i in report["issues"]}
        report["planning_inputs"] = [p for p in report["planning_inputs"]
                                     if any((p["repository"].lower(), key) in visible
                                            for key in p["for_issues"])]
        report["displayed_issue_count"] = len(report["issues"])
        text = render_summary(report, args.format)
        if args.output:
            with args.output.open("x", encoding="utf-8") as stream:
                stream.write(text)
            print(str(args.output))
        else:
            print(text, end="")
        return int(bool(report["lineage_diagnostics"] or report["provenance_diagnostics"]
                        or any(result["error"] for result in results)
                        or (args.require_reviews and any(not result["reports"] for result in results))))
    except (RepositoryConfigurationError, contract.ReviewError, OSError, UnicodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments and arguments[0] == "fleet":
        return fleet_main(arguments[1:])
    return contract.main(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
