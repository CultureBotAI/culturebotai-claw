"""Offline native CLI canary for CommunityMech #476; 2026-11-15.

Input: governed mech_shared schema and an explicitly synthetic cached source.
Output: exclusive scratch directory with three inputs, native logs and a JSON
receipt. Actual native traversal, parsing and substring matching are retained;
network acquisition, enrichment and cache saving are refused. No fleet rollout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import socket
import subprocess
from contextlib import ExitStack
from datetime import datetime, timezone
from importlib.metadata import version
from pathlib import Path
from unittest.mock import patch

import yaml
from linkml_reference_validator.cli.validate import validate_app
from linkml_reference_validator.etl.reference_fetcher import ReferenceFetcher
from linkml_reference_validator.plugins.reference_validation_plugin import (
    ReferenceValidationPlugin,
)
from linkml_reference_validator.validation.supporting_text_validator import (
    SupportingTextValidator,
)
from typer.testing import CliRunner

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "src/kg_microbe_governance/artifacts/schema/mech_shared.yaml"
QUOTE = "This synthetic source reports an unchanged cobalt control."
MUTATION = "ZZQQ_UNSUPPORTED_SUPPORTING_REFERENCE_CANARY_XYZ"
REFERENCE = (
    "PMID:1"  # Synthetic fixture identity, not a claim about publication PMID:1.
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_probe(
    output: Path, target_class: str = "Discussion", schema: Path = SCHEMA
) -> dict:
    """Persist controls before judging their measured counts; refuse overwrites."""
    if target_class not in {"Discussion", "Dataset"}:
        raise ValueError(
            "Only the two canonical SupportingReference containers are supported"
        )
    output.mkdir(parents=True, exist_ok=False)
    started = datetime.now(timezone.utc).isoformat()
    schema_hash = digest(schema)
    cache = output / "cache"
    cache.mkdir()
    source = cache / "PMID_1.md"
    source.write_text(
        "---\nreference_id: PMID:1\ntitle: Synthetic canary source\n"
        "content_type: full_text\n---\n# Synthetic canary source\n\n## Content\n\n"
        + QUOTE
        + "\n",
        encoding="utf-8",
    )
    source_hash = digest(source)
    cases = []
    violations = []
    native_excerpt = ReferenceValidationPlugin._validate_excerpt
    native_match = SupportingTextValidator.find_text_in_reference
    native_substring = SupportingTextValidator._substring_match
    events: list[dict] = []

    def refuse(*args, **kwargs):
        violations.append("acquisition, enrichment or cache saving attempted")
        raise RuntimeError(violations[-1])

    def excerpt(plugin, text, reference_id, expected_title, path):
        events.append(
            {
                "path": path,
                "reference": reference_id,
                "text": text,
                "matcher_calls": 0,
                "substring_calls": 0,
            }
        )
        yield from native_excerpt(plugin, text, reference_id, expected_title, path)

    def match(validator, text, reference):
        event = events[-1]
        event["matcher_calls"] += 1
        event["loaded_reference_id"] = reference.reference_id
        result = native_match(validator, text, reference)
        event["matched"] = result.found
        return result

    def substring(validator, *args, **kwargs):
        events[-1]["substring_calls"] += 1
        return native_substring(validator, *args, **kwargs)

    runner = CliRunner()
    for name, text, expected_exit in (
        ("control", QUOTE, 0),
        ("mutation", MUTATION, 1),
        ("restoration", QUOTE, 0),
    ):
        record = output / f"{name}.yaml"
        document = {"evidence": [{"reference": REFERENCE, "snippet": text}]}
        if target_class == "Discussion":
            document.update(
                discussion_id="synthetic-canary", prompt="A structural test only"
            )
        else:
            document.update(
                identifier="synthetic-canary", title="A structural test only"
            )
        record.write_text(yaml.safe_dump(document, sort_keys=False), encoding="utf-8")
        before_record = digest(record)
        events.clear()
        args = [
            "data",
            str(record),
            "--schema",
            str(schema),
            "--target-class",
            target_class,
            "--cache-dir",
            str(cache),
            "--no-full-text",
        ]
        with ExitStack() as stack:
            stack.enter_context(
                patch.object(ReferenceValidationPlugin, "_validate_excerpt", excerpt)
            )
            stack.enter_context(
                patch.object(SupportingTextValidator, "find_text_in_reference", match)
            )
            stack.enter_context(
                patch.object(SupportingTextValidator, "_substring_match", substring)
            )
            for method in (
                "_enrich_with_full_text",
                "_save_by_access",
                "_save_to_disk",
                "_save_pdf",
            ):
                stack.enter_context(patch.object(ReferenceFetcher, method, refuse))
            stack.enter_context(
                patch(
                    "linkml_reference_validator.etl.reference_fetcher.ReferenceSourceRegistry.get_source",
                    side_effect=refuse,
                )
            )
            for method in ("connect", "connect_ex", "sendto"):
                stack.enter_context(patch.object(socket.socket, method, refuse))
            for method in ("create_connection", "getaddrinfo"):
                stack.enter_context(patch.object(socket, method, refuse))
            result = runner.invoke(validate_app, args)
        log = output / f"{name}.log.txt"
        log.write_text(result.output.replace(str(output), "<canary>"), encoding="utf-8")
        (output / f"{name}.exit").write_text(f"{result.exit_code}\n", encoding="utf-8")
        expected_event = {
            "path": "evidence[0].snippet",
            "reference": REFERENCE,
            "text": text,
            "matcher_calls": 1,
            "substring_calls": 1,
            "loaded_reference_id": REFERENCE,
            "matched": expected_exit == 0,
        }
        cases.append(
            {
                "case": name,
                "native_exit_code": result.exit_code,
                "expected_exit_code": expected_exit,
                "events": list(events),
                "record_sha256": before_record,
                "log_sha256": digest(log),
                "log_bytes": log.stat().st_size,
                "passed": result.exit_code == expected_exit
                and events == [expected_event]
                and digest(record) == before_record
                and log.stat().st_size > 0,
            }
        )
    unchanged = digest(source) == source_hash and digest(schema) == schema_hash
    unchanged = unchanged and sorted(p.name for p in cache.iterdir()) == [source.name]
    report = {
        "checkout_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "source_hashes": {
            str(path.relative_to(ROOT)): digest(path)
            for path in (
                Path(__file__).resolve(),
                ROOT / "pyproject.toml",
                ROOT / "uv.lock",
            )
        },
        "started_at": started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "invocation": "Actual native Typer validate data CLI, --no-full-text",
        "target_class": target_class,
        "schema_sha256": schema_hash,
        "synthetic_cache_sha256": source_hash,
        "dependencies": {
            name: version(name) for name in ("linkml", "linkml-reference-validator")
        },
        "cases": cases,
        "refused_operations": violations,
        "inputs_unchanged": unchanged,
        "passed": unchanged
        and not violations
        and all(case["passed"] for case in cases),
        "limit": "Synthetic lexical coverage control; no scientific support or downstream rollout claim.",
    }
    (output / "receipt.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument(
        "--target-class", choices=("Discussion", "Dataset"), default="Discussion"
    )
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args()
    output = args.output_dir.resolve()
    if not output.is_relative_to(ROOT / ".temp") or output.exists():
        parser.error(
            "Output must be a new exclusive directory under this repository .temp/"
        )
    if args.plan:
        print(
            json.dumps(
                {
                    "schema_sha256": digest(SCHEMA),
                    "target_class": args.target_class,
                    "cases": ["control", "mutation", "restoration"],
                    "network": "forbidden",
                }
            )
        )
        return 0
    report = run_probe(output, args.target_class)
    print(json.dumps(report, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
