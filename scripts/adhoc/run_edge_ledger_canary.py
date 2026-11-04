#!/usr/bin/env python3
"""Exercise the actual KG producer and CLAW ledger CLIs for one bounded canary.

Purpose: edge-curation implementation, 2026-11-03; CLAW issue #756.
Inputs: explicit KG checkout/Python, source manifest, row bound and new output root.
Outputs: lossless export, local ledger, deferred decision and verified JSON receipt.
No provider calls, scientific approvals, production edits, or overwrite.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path


def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run(command: list[str], cwd: Path, *, succeeds: bool = True) -> dict:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    if succeeds and result.returncode:
        raise RuntimeError(f"canary command failed: {result.stderr}")
    if not succeeds:
        if result.returncode == 0 or "stale ledger revision" not in result.stderr:
            raise RuntimeError("stale update was not refused as expected")
        return {"returncode": result.returncode, "reason": result.stderr.strip()}
    return json.loads(result.stdout)


def main() -> None:
    """Run one end-to-end unit through the same launchers used for later batches."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kg-root", type=Path, required=True)
    parser.add_argument("--kg-python", type=Path, required=True)
    parser.add_argument("--snapshot-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--rows", type=int, default=1000)
    parser.add_argument("--edge-member", default="merged-kg_edges.tsv")
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args()
    if args.rows < 1:
        parser.error("a positive bounded row count is required")
    root = Path(__file__).resolve().parents[2]
    producer = args.kg_root.resolve() / "kg_microbe/edge_snapshot.py"
    for path in (producer, args.kg_python, args.snapshot_manifest):
        if not path.is_file():
            parser.error(f"missing input: {path}")
    output = args.output.absolute()
    if output.exists() or output.is_symlink():
        parser.error("output exists; inspect previous receipts instead of overwriting")
    producer_command = [
        str(args.kg_python),
        str(producer),
        "export",
        str(args.snapshot_manifest.resolve()),
        str(output / "snapshot"),
        "--edge-member",
        args.edge_member,
        "--max-rows",
        str(args.rows),
        "--shard-rows",
        "100",
    ]
    ledger_command = [sys.executable, "-m", "kg_microbe_curation"]
    database = output / "ledger.sqlite"
    commands = {
        "producer": producer_command,
        "ledger_init": [
            *ledger_command,
            "init",
            "--export",
            str(output / "snapshot"),
            "--database",
            str(database),
        ],
        "ledger_status": [*ledger_command, "status", "--database", str(database)],
        "ledger_audit": [*ledger_command, "audit", "--database", str(database)],
    }
    if args.plan:
        print(json.dumps({"mode": "plan", "commands": commands, "output": str(output)}, indent=2))
        return
    output.mkdir(parents=True)
    exported = _run(commands["producer"], args.kg_root)
    initial = _run(commands["ledger_init"], root)
    if initial["accounted_rows"] != exported["selection"]["exported_rows"]:
        raise RuntimeError("persisted occurrence count differs from the producer")
    if initial["accounted_rows"] < 1:
        raise RuntimeError("canary has no persisted edge")
    with (output / "snapshot" / exported["shards"][0]["file"]).open() as handle:
        first = json.loads(handle.readline())
    from kg_microbe_curation.contract import unprocessed_decision

    decision = unprocessed_decision(first["occurrence_id"])
    decision.update(
        review_state="deferred", rationale="Canary routing only; evidence has not been assessed."
    )
    bundle = {
        "contract": "kg-microbe-curation/v1",
        "input_sha256": initial["input_sha256"],
        "occurrence_ids": [first["occurrence_id"]],
        "decisions": [decision],
        "observations": [],
        "claims": [],
        "reviews": [],
    }
    bundle_path = output / "deferred-decision.json"
    bundle_path.write_text(json.dumps(bundle, indent=2) + "\n")
    apply_command = [
        *ledger_command,
        "apply",
        "--database",
        str(database),
        "--bundle",
        str(bundle_path),
        "--expected-revision",
        initial["revision"],
    ]
    updated = _run(apply_command, root)
    stale = _run(apply_command, root, succeeds=False)
    persisted = _run(commands["ledger_status"], root)
    audited = _run(commands["ledger_audit"], root)
    shown = _run(
        [
            *ledger_command,
            "show",
            "--database",
            str(database),
            "--occurrence",
            first["occurrence_id"],
        ],
        root,
    )
    if persisted != updated or shown["source_row"] != first["source_row"]:
        raise RuntimeError("persisted ledger differs from the completed update or source row")
    if persisted["applied_bundles"] != 1 or persisted["disposition"] != {
        "withheld": initial["accounted_rows"]
    }:
        raise RuntimeError("canary incorrectly approved scientific claims or lost decision history")
    if database.stat().st_size == 0:
        raise RuntimeError("ledger was not persisted")
    receipt = {
        "kind": "offline_release_accounting_canary",
        "scientific_approvals": 0,
        "source_manifest_sha256": _hash(args.snapshot_manifest),
        "producer_code_sha256": _hash(producer),
        "consumer_code_sha256": {
            name: _hash(root / "src/kg_microbe_curation" / name)
            for name in ("identity.py", "contract.py", "ledger.py", "__main__.py")
        },
        "commands": commands,
        "apply_command": apply_command,
        "initial": initial,
        "persisted": persisted,
        "membership_and_counters_reconciled": audited["reconciled"],
        "stale_revision_rejected": stale,
        "lookup_exact_source_row": True,
        "ledger_sha256": _hash(database),
        "ledger_bytes": database.stat().st_size,
        "source_members_verified_by_producer": exported["members"],
    }
    receipt_path = output / "receipt.json"
    receipt_path.write_text(json.dumps(receipt, indent=2) + "\n")
    loaded = json.loads(receipt_path.read_text())
    if loaded != receipt:
        raise RuntimeError("receipt persistence verification failed")
    print(
        json.dumps(
            {
                "receipt": str(receipt_path),
                "sha256": _hash(receipt_path),
                "rows": persisted["accounted_rows"],
                "scientific_approvals": 0,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
