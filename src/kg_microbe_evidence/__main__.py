"""Run the declared offline quote gate against one exact active Mech checkout."""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import sys
import tempfile
from pathlib import Path

from kg_microbe_evidence import (
    CAPABILITY,
    EvidenceConfig,
    EvidenceError,
    exit_code,
    plan_known_findings,
    render_known_findings,
    validate_corpus,
    write_known_findings,
)
from kg_microbe_fleet import FleetManifestError, load_fleet_manifest
from kg_microbe_fleet.roots import claw_root
from plugins.repository_settings import (
    RepositoryConfigurationError,
    RepositorySettings,
    RepositoryTarget,
    merged_repository_environment,
)


def quote_share(report: dict) -> str:
    """Say how much of the gate's scope it can check at all (#729)."""
    total, quoted = report["evidence_items"], report["quote_bearing_items"]
    share = f"{quoted / total:.1%}" if total else "n/a"
    return (f"Quote-bearing items: {quoted} of {total} in-scope evidence items ({share}); "
            "items without a quote cannot be checked, so a pass covers only these.")


def write_reports(report: dict, output: Path) -> None:
    """Reports contain quote hashes, not redistributed source passages."""
    output.mkdir(parents=True, exist_ok=True)
    buffer = io.StringIO()
    fields = ["record", "location", "verdict", "reference", "detail", "quote_sha256", "cache_path",
              "cache_sha256", "known_issue"]
    writer = csv.DictWriter(buffer, fieldnames=fields, delimiter="\t")
    writer.writeheader()
    writer.writerows(report["results"])
    lines = ["# Evidence reference validation", "", report["limits"], "",
             f"Records read: {report['records']}; evidence items: {report['evidence_items']}; quote-validated items: {report['quote_validated_items']}.",
             quote_share(report),
             f"Unmeasured items outside declared selectors: {report['unmeasured_items']}.",
             "Selected evidence paths: " + (", ".join(report["evidence_paths"]) or "all declared evidence fields"),
             "", "| Verdict | Items | Recorded as known |", "|---|---:|---:|"]
    lines.extend(f"| {key} | {value} | {report['known_findings'].get(key, '')} |"
                 for key, value in report["verdicts"].items())
    if report["known_findings_ledger"]:
        recorded = sum(report["known_findings"].values())
        lines.extend(["", f"Known findings ledger `{report['known_findings_ledger']}`: {recorded} current "
                      "findings are recorded there and do not block. They are not validated; each "
                      "names the issue that owns its repair.",
                      f"Stale ledger entries (finding no longer occurs; remove them): {len(report['stale_known_findings'])}."])
    if report["errors"]:
        lines.extend(["", "## Input errors", ""])
        lines.extend(f"- {row['record']}: {row['error']}" for row in report["errors"])
    payloads = {"json": json.dumps(report, indent=2, sort_keys=True) + "\n",
                "tsv": buffer.getvalue(), "md": "\n".join(lines) + "\n"}
    for suffix, text in payloads.items():
        target = output / f"evidence_reference_validation.{suffix}"
        if target.is_symlink():
            raise EvidenceError("report output must not be a symlink")
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=output, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
        try:
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)


def record_known_findings(report: dict, root: Path, config: EvidenceConfig,
                          issue: str | None, *, apply: bool) -> int:
    """Rewrite the declared ledger from the current findings, dry-run by default.

    Input errors stop it: an unreadable record's findings are unknown, so a
    ledger written then would silently forget them.
    """
    if config.known_findings is None:
        raise EvidenceError("declare known_findings in this Mech's evidence profile first")
    if report["errors"]:
        raise EvidenceError(f"{len(report['errors'])} records could not be read; fix them before recording findings")
    plan = plan_known_findings(report, issue)
    render_known_findings(plan["rows"])  # a row the writer would refuse fails the dry run too
    print(f"{config.known_findings}: keep {plan['kept']}, add {plan['added']}, drop {plan['dropped']} stale; "
          f"{len(plan['rows'])} entries after the update")
    if plan["unowned"]:
        print(f"  {len(plan['unowned'])} current findings have no owner; pass --issue to record them")
    if not apply:
        print("  Dry run: nothing written. Pass --apply to write the ledger.")
        return 1 if plan["unowned"] else 0
    if plan["unowned"]:
        raise EvidenceError("refusing to write a ledger that leaves current findings unrecorded")
    write_known_findings(root, config.known_findings, plan["rows"])
    print(f"  Wrote {root / config.known_findings}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mech", required=True)
    parser.add_argument("--root", type=Path, help="exact active Mech checkout, with origin identity verified")
    parser.add_argument("--strict", action="store_true", help="also fail on missing caches and unsupported sources")
    parser.add_argument("--output-dir", type=Path, help="report directory inside the active Mech checkout")
    parser.add_argument("--record-known-findings", action="store_true",
                        help="plan the declared ledger from the current findings: keep entries "
                             "that still occur, drop stale ones, and add new ones owned by --issue")
    parser.add_argument("--issue", help="GitHub issue URL that owns newly recorded findings")
    parser.add_argument("--apply", action="store_true",
                        help="with --record-known-findings, write the ledger; omitted means dry-run")
    args = parser.parse_args(argv)
    if (args.issue or args.apply) and not args.record_known_findings:
        parser.error("--issue and --apply apply only to --record-known-findings")
    try:
        manifest = load_fleet_manifest()
        mech = manifest.mechs.get(args.mech)
        if mech is None:
            raise EvidenceError(f"unknown Mech: {args.mech}")
        capability = mech.capability(CAPABILITY)
        if capability is None or not capability.is_enabled:
            reason = capability.reason if capability else "undeclared"
            raise EvidenceError(f"{args.mech}: evidence validation is not enabled: {reason}")
        config = EvidenceConfig.from_settings(capability.settings)
        if args.root is not None:
            target = RepositoryTarget(mech.key, args.root.expanduser().resolve(), mech.github)
        else:
            dotenv = claw_root() / ".env"
            env = merged_repository_environment(dotenv if dotenv.exists() else None)
            target = RepositorySettings.from_environment(environ=env, manifest=manifest).get_target(mech.key)
        repo = target.open()
        root = target.path
        output = args.output_dir or root / "workspace/reports"
        if not output.is_absolute():
            output = root / output
        output = output.resolve()
        if not output.is_relative_to(root):
            raise EvidenceError("report output must remain inside the active checkout")
        report = validate_corpus(root, mech.record_globs, config,
                                 missing_ledger_ok=args.record_known_findings)
        report.update(repository=mech.github, revision=repo.head.commit.hexsha,
                      strict=args.strict, input_state="active checkout, including uncommitted files")
        if args.record_known_findings:
            return record_known_findings(report, root, config, args.issue, apply=args.apply)
        write_reports(report, output)
        print(f"{mech.key}: {report['evidence_items']} evidence items; "
              f"{report['quote_validated_items']} quote-validated; {len(report['errors'])} input errors")
        print(f"  {quote_share(report)}")
        print(f"  Outside declared selectors (unmeasured): {report['unmeasured_items']}")
        for verdict, count in report["verdicts"].items():
            recorded = report["known_findings"].get(verdict)
            print(f"  {verdict}: {count}" + (f" ({recorded} recorded as known)" if recorded else ""))
        if report["stale_known_findings"]:
            print(f"  Stale known-findings entries: {len(report['stale_known_findings'])}")
        return exit_code(report, strict=args.strict)
    except (EvidenceError, FleetManifestError, RepositoryConfigurationError, OSError, ValueError) as exc:
        print(f"evidence validation: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
