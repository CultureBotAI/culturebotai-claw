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
    validate_corpus,
)
from kg_microbe_fleet import FleetManifestError, load_fleet_manifest
from kg_microbe_fleet.roots import claw_root
from plugins.repository_settings import (
    RepositoryConfigurationError,
    RepositorySettings,
    RepositoryTarget,
    merged_repository_environment,
)


def write_reports(report: dict, output: Path) -> None:
    """Reports contain quote hashes, not redistributed source passages."""
    output.mkdir(parents=True, exist_ok=True)
    buffer = io.StringIO()
    fields = ["record", "location", "verdict", "reference", "detail", "quote_sha256", "cache_path", "cache_sha256"]
    writer = csv.DictWriter(buffer, fieldnames=fields, delimiter="\t")
    writer.writeheader()
    writer.writerows(report["results"])
    lines = ["# Evidence reference validation", "", report["limits"], "",
             f"Records read: {report['records']}; evidence items: {report['evidence_items']}; quote-validated items: {report['quote_validated_items']}.",
             f"Unmeasured items outside declared selectors: {report['unmeasured_items']}.",
             "Selected evidence paths: " + (", ".join(report["evidence_paths"]) or "all declared evidence fields"),
             "", "| Verdict | Items |", "|---|---:|"]
    lines.extend(f"| {key} | {value} |" for key, value in report["verdicts"].items())
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mech", required=True)
    parser.add_argument("--root", type=Path, help="exact active Mech checkout, with origin identity verified")
    parser.add_argument("--strict", action="store_true", help="also fail on missing caches and unsupported sources")
    parser.add_argument("--output-dir", type=Path, help="report directory inside the active Mech checkout")
    args = parser.parse_args(argv)
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
        report = validate_corpus(root, mech.record_globs, config)
        report.update(repository=mech.github, revision=repo.head.commit.hexsha,
                      strict=args.strict, input_state="active checkout, including uncommitted files")
        write_reports(report, output)
        print(f"{mech.key}: {report['evidence_items']} evidence items; "
              f"{report['quote_validated_items']} quote-validated; {len(report['errors'])} input errors")
        print(f"  Outside declared selectors (unmeasured): {report['unmeasured_items']}")
        for verdict, count in report["verdicts"].items():
            print(f"  {verdict}: {count}")
        return exit_code(report, strict=args.strict)
    except (EvidenceError, FleetManifestError, RepositoryConfigurationError, OSError, ValueError) as exc:
        print(f"evidence validation: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
