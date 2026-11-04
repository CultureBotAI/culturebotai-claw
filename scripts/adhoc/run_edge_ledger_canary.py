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
import importlib
import json
import os
import subprocess
import sys
from importlib.resources import files
from pathlib import Path

RUNTIME_MODULES = {
    "kg_microbe_curation": "__init__.py",
    **{
        f"kg_microbe_curation.{name}": f"{name}.py"
        for name in ("identity", "contract", "ledger", "__main__")
    },
}


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _consumer_environment(root: Path) -> dict[str, str]:
    """Ignore ambient package paths for every consumer probe and command (#763)."""
    return {
        **os.environ,
        "PYTHONPATH": os.pathsep.join((str(root / "src"), str(root))),
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def _runtime_probe() -> dict:
    """Report actual imported module and packaged-schema origins in a child process."""
    modules = {}
    for name in RUNTIME_MODULES:
        module = importlib.import_module(name)
        path = Path(module.__file__).resolve(strict=True)
        modules[name] = {"path": str(path), "sha256": _hash(path)}
    schema = Path(str(files("kg_microbe_curation").joinpath("schema/bundle.json"))).resolve(
        strict=True
    )
    return {
        "interpreter": {"executable": str(Path(sys.executable).absolute()), "version": sys.version},
        "modules": modules,
        "schema": {"path": str(schema), "sha256": _hash(schema)},
    }


def _verify_runtime(probe: dict, root: Path) -> None:
    """Reject a different interpreter, checkout, packaged resource, or source digest."""
    try:
        if probe["interpreter"]["executable"] != str(Path(sys.executable).absolute()):
            raise ValueError("interpreter differs")
        if probe["interpreter"]["version"] != sys.version or set(probe["modules"]) != set(
            RUNTIME_MODULES
        ):
            raise ValueError("interpreter version or module set differs")
        expected = {
            **{
                name: root / "src/kg_microbe_curation" / relative
                for name, relative in RUNTIME_MODULES.items()
            },
            "schema": root / "src/kg_microbe_curation/schema/bundle.json",
        }
        for name, path in expected.items():
            observed = probe["schema"] if name == "schema" else probe["modules"][name]
            actual = Path(observed["path"]).resolve(strict=True)
            if not actual.is_relative_to(root.resolve()) or actual != path.resolve(strict=True):
                raise ValueError(f"{name} origin is outside the expected checkout")
            if observed["sha256"] != _hash(path):
                raise ValueError(f"{name} digest differs from the expected checkout")
    except (KeyError, TypeError, ValueError, OSError) as exc:
        raise RuntimeError(f"consumer runtime verification failed: {exc}") from exc


def _probe(root: Path, environment: dict[str, str]) -> dict:
    probe = _run(
        [sys.executable, str(Path(__file__).resolve()), "--probe-runtime"],
        root,
        env=environment,
    )
    _verify_runtime(probe, root)
    return probe


def _verify_file_hashes(expected: dict[Path, str]) -> None:
    """Refuse receipts when a directly executed source or input changed during the run."""
    for path, digest in expected.items():
        if _hash(path) != digest:
            raise RuntimeError(f"canary input or executed source changed: {path}")


def _run(command: list[str], cwd: Path, *, succeeds: bool = True, env: dict | None = None) -> dict:
    result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True, check=False)
    if succeeds and result.returncode:
        raise RuntimeError(f"canary command failed: {result.stderr}")
    if not succeeds:
        if result.returncode == 0 or "stale ledger revision" not in result.stderr:
            raise RuntimeError("stale update was not refused as expected")
        return {"returncode": result.returncode, "reason": result.stderr.strip()}
    return json.loads(result.stdout)


def main() -> None:
    """Run one end-to-end unit through the same launchers used for later batches."""
    if sys.argv[1:] == ["--probe-runtime"]:
        print(json.dumps(_runtime_probe(), sort_keys=True))
        return
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
    environment = _consumer_environment(root)
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
        print(
            json.dumps(
                {
                    "mode": "plan",
                    "commands": commands,
                    "output": str(output),
                    "consumer_pythonpath": environment["PYTHONPATH"],
                },
                indent=2,
            )
        )
        return
    consumer_runtime = _probe(root, environment)
    bound_files = {
        path: _hash(path) for path in (producer, args.snapshot_manifest, Path(__file__).resolve())
    }
    output.mkdir(parents=True)
    exported = _run(commands["producer"], args.kg_root)
    initial = _run(commands["ledger_init"], root, env=environment)
    if initial["accounted_rows"] != exported["selection"]["exported_rows"]:
        raise RuntimeError("persisted occurrence count differs from the producer")
    if initial["accounted_rows"] < 1:
        raise RuntimeError("canary has no persisted edge")
    with (output / "snapshot" / exported["shards"][0]["file"]).open() as handle:
        first = json.loads(handle.readline())
    # Construct the explicit routing packet without importing an ambient parent package.
    decision = {
        "occurrence_id": first["occurrence_id"],
        "lifecycle": "active",
        "review_state": "deferred",
        "conflict_state": "not_assessed",
        "disposition": "withheld",
        "claim_ids": [],
        "observation_id": None,
        "review_ids": [],
        "rationale": "Canary routing only; evidence has not been assessed.",
    }
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
    updated = _run(apply_command, root, env=environment)
    stale = _run(apply_command, root, succeeds=False, env=environment)
    persisted = _run(commands["ledger_status"], root, env=environment)
    audited = _run(commands["ledger_audit"], root, env=environment)
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
        env=environment,
    )
    if persisted != updated or shown["source_row"] != first["source_row"]:
        raise RuntimeError("persisted ledger differs from the completed update or source row")
    if persisted["applied_bundles"] != 1 or persisted["disposition"] != {
        "withheld": initial["accounted_rows"]
    }:
        raise RuntimeError("canary incorrectly approved scientific claims or lost decision history")
    if database.stat().st_size == 0:
        raise RuntimeError("ledger was not persisted")
    if _probe(root, environment) != consumer_runtime:
        raise RuntimeError("consumer runtime changed during canary execution")
    _verify_file_hashes(bound_files)
    if exported["source_manifest_sha256"] != bound_files[args.snapshot_manifest]:
        raise RuntimeError("producer consumed a different source manifest")
    receipt = {
        "kind": "offline_release_accounting_canary",
        "scientific_approvals": 0,
        "source_manifest_sha256": bound_files[args.snapshot_manifest],
        "producer_code_sha256": bound_files[producer],
        "canary_script_sha256": bound_files[Path(__file__).resolve()],
        "consumer_runtime": consumer_runtime,
        "consumer_code_sha256": {
            RUNTIME_MODULES[name]: observed["sha256"]
            for name, observed in consumer_runtime["modules"].items()
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
