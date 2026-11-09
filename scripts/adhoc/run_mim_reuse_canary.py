#!/usr/bin/env python3
"""Verify offline reuse of a pinned MIM review; edge-curation canary, 2026-11-03.

Inputs: KG checkout/interpreter, its MIM pin, retained export/source archive,
and a KG manifest. Output: a new JSON receipt; no corpus changes or providers.
This proves review import and scope refusal, not a fresh scientific review,
KG edge membership, native RecordReview conversion, or a full KG rebuild.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path, PurePosixPath

POSITIONS = (1, 21, 25)
MIM_COMMIT = "1848b0fe521bc2462f165912fcf92d09ad9a8cec"
VALIDATORS = {
    "kg_microbe.utils.review_claims": "kg_microbe/utils/review_claims.py",
    "scripts.mim_reviewed_release": "scripts/mim_reviewed_release.py",
    "scripts.refresh_reviewed_mim": "scripts/refresh_reviewed_mim.py",
}


def digest(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def payload_digest(value: dict) -> str:
    return digest(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode()
    )


def unique_object(pairs: list) -> dict:
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"Duplicate JSON key: {key}")
        value[key] = item
    return value


def read_json(content: bytes) -> dict:
    value = json.loads(content, object_pairs_hook=unique_object)
    if not isinstance(value, dict):
        raise ValueError("Expected a JSON object")
    return value


def classify_reuse(row: dict, decision: dict, request: dict, dependency: str) -> dict:
    """Require the whole mapping payload and dependencies, never endpoint overlap."""
    result = {
        "eligible_for_reuse": False,
        "biological_claim_approved": False,
        "independent_scientific_review": False,
    }
    if request.get("dependency_sha256") != dependency:
        return dict(result, outcome="stale_dependencies")
    if request.get("kind") != "mim_mapping_payload":
        same_endpoint = request.get("object") == row["object_id"]
        return dict(result, outcome="endpoint_only" if same_endpoint else "scope_mismatch")
    if request.get("payload") != row or payload_digest(row) != decision["row_sha256"]:
        return dict(result, outcome="scope_mismatch")
    if decision["disposition"] == "WITHHOLD":
        return dict(result, outcome="native_withheld_mapping")
    if decision["disposition"] != "SUPPORTED":
        raise ValueError("Unsupported native disposition")
    return dict(result, outcome="eligible_native_mapping_reuse", eligible_for_reuse=True)


def archive_members(path: Path, names: set[str], root: str) -> dict[str, bytes]:
    """Read selected members without extracting or executing archived source."""
    result = {}
    with tarfile.open(path, "r|gz") as archive:
        for member in archive:
            name = member.name.removeprefix(root + "/")
            if name not in names:
                continue
            if name in result or not member.isfile() or member.size > 32 * 1024 * 1024:
                raise ValueError(f"Unsafe/oversized selected archive member: {name}")
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError(f"Unreadable archive member: {name}")
            with stream:
                result[name] = stream.read()
    if set(result) != names:
        raise ValueError(f"Missing archive members: {sorted(names - set(result))}")
    return result


def verify_review_inputs(path: Path, expected: dict, retain: set[str], root: str) -> dict:
    """Hash every declared native review input; retain only the selected evidence."""
    for name, value in expected.items():
        parsed = PurePosixPath(name)
        if (
            parsed.is_absolute()
            or ".." in parsed.parts
            or str(parsed) != name
            or not isinstance(value, str)
            or not re.fullmatch(r"[a-f0-9]{64}", value)
        ):
            raise ValueError(f"Invalid archived review input binding: {name}")
    verified, kept = set(), {}
    with tarfile.open(path, "r|gz") as archive:
        for member in archive:
            name = member.name.removeprefix(root + "/")
            if name not in expected:
                continue
            if name in verified or not member.isfile():
                raise ValueError(f"Duplicate or unsafe review input: {name}")
            stream = archive.extractfile(member)
            if stream is None:
                raise ValueError(f"Unreadable review input: {name}")
            hashed, chunks = hashlib.sha256(), []
            with stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    hashed.update(chunk)
                    if name in retain:
                        chunks.append(chunk)
            if hashed.hexdigest() != expected[name]:
                raise ValueError(f"Archived review input changed: {name}")
            verified.add(name)
            if name in retain:
                kept[name] = b"".join(chunks)
    if verified != set(expected) or not retain <= set(kept):
        raise ValueError("Native review input closure is incomplete")
    return kept


def source_snapshot(root: Path) -> dict:
    """Bind the launcher and selected validator sources before starting Python."""
    root = root.resolve(strict=True)
    sources = {}
    for name, relative in VALIDATORS.items():
        path = (root / relative).resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError(f"Validator source is outside the selected checkout: {path}")
        sources[name] = {"path": str(path), "sha256": digest(path.read_bytes())}
    launcher = Path(__file__).resolve(strict=True)
    return {
        "validators": sources,
        "launcher": {"path": str(launcher), "sha256": digest(launcher.read_bytes())},
    }


def verify_sources(root: Path, expected: dict) -> None:
    if source_snapshot(root) != expected:
        raise ValueError("Canary launcher or validator source changed during execution")


def runtime_metadata(modules: dict) -> dict:
    """Observe imported modules, rather than infer their origins from PYTHONPATH."""
    return {
        "interpreter": {
            "executable": str(Path(sys.executable).absolute()),
            "version": sys.version,
            "prefix": sys.prefix,
            "base_prefix": sys.base_prefix,
        },
        "validators": {
            name: {
                "path": str(Path(module.__file__).resolve(strict=True)),
                "spec_origin": str(Path(module.__spec__.origin).resolve(strict=True)),
                "sha256": digest(Path(module.__file__).read_bytes()),
            }
            for name, module in modules.items()
        },
    }


def verify_runtime(runtime: dict, args: argparse.Namespace, expected: dict) -> None:
    interpreter = runtime["interpreter"]
    if interpreter["executable"] != str(args.kg_python.absolute()) or not all(
        isinstance(interpreter.get(field), str) and interpreter[field]
        for field in ("version", "prefix", "base_prefix")
    ):
        raise ValueError("Canary ran under an unexpected Python interpreter")
    wanted = {
        name: dict(binding, spec_origin=binding["path"])
        for name, binding in expected["validators"].items()
    }
    if runtime["validators"] != wanted:
        raise ValueError("Imported validator origin or source hash differs from selected checkout")


def validate(args: argparse.Namespace, expected: dict) -> dict:
    """Run in the selected Python, binding imported code before and after validation."""
    verify_sources(args.kg_root, expected)
    modules = {name: importlib.import_module(name) for name in VALIDATORS}
    before = runtime_metadata(modules)
    verify_runtime(before, args, expected)
    report = {} if args.runtime_probe else validate_review(args, modules)
    after = runtime_metadata(modules)
    verify_runtime(after, args, expected)
    verify_sources(args.kg_root, expected)
    if before != after:
        raise ValueError("Canary runtime changed during validation")
    report["runtime_provenance"] = {"before": before, "after": after, "sources": expected}
    return report


def validate_review(args: argparse.Namespace, modules: dict) -> dict:
    """Verify the pinned scientific inputs using the already origin-checked modules."""
    validate_review_decision = modules["kg_microbe.utils.review_claims"].validate_review_decision
    release = modules["scripts.mim_reviewed_release"]
    refresh = modules["scripts.refresh_reviewed_mim"]

    pin_path = args.kg_root / refresh.PIN_FILE
    pin_bytes = pin_path.read_bytes()
    pin = refresh.load_release_pin(args.kg_root)
    if pin["schema_version"] != 2 or pin["source_commit"] != MIM_COMMIT:
        raise ValueError("This bounded canary requires the reviewed 1848b0fe export")
    bundle = release.validate_reviewed_bundle(
        args.bundle, expected_manifest_sha256=pin["manifest_sha256"]
    )
    archive_binding = refresh.validate_immutable_export(pin, args.archive, args.bundle)
    root = "MediaIngredientMech-" + pin["source_commit"]
    native = archive_members(args.archive, {refresh.SOURCE_SSSOM, refresh.SOURCE_REVIEW}, root)
    review = read_json(native[refresh.SOURCE_REVIEW])
    if (
        digest(native[refresh.SOURCE_REVIEW]) != bundle.review_sha256
        or digest(native[refresh.SOURCE_SSSOM]) != bundle.source_sha256
        or review["source_sha256"] != bundle.source_sha256
    ):
        raise ValueError("Native source/review does not match the export")
    _, _, source_rows = release._sssom(native[refresh.SOURCE_SSSOM], "archived source")
    if len(source_rows) != bundle.manifest["counts"]["source"]:
        raise ValueError("Archived source denominator differs from export")
    by_position = {int(item["source_position"]): item for item in bundle.disposition_rows}
    native_decisions = {item["source_position"]: item for item in review["decisions"]}
    if len(native_decisions) != len(review["decisions"]) or set(native_decisions) != set(
        by_position
    ):
        raise ValueError("Native decision coverage differs from export")
    expected = {}
    for group in ("inputs", "record_inputs"):
        for name, value in review[group].items():
            if name in expected and expected[name] != value:
                raise ValueError("Conflicting native input hashes")
            expected[name] = value
    selected = [by_position[position] for position in POSITIONS]
    retain = {item[field] for item in selected for field in ("owner_record", "review_evidence")}
    kept = verify_review_inputs(args.archive, expected, retain, root)
    proofs, results = {}, []
    for decision in selected:
        position = int(decision["source_position"])
        row, native_decision = source_rows[position - 1], native_decisions[position]
        for field in (
            "row_sha256",
            "owner_record",
            "disposition",
            "review_reason",
            "review_evidence",
            "evidence_key",
        ):
            if native_decision.get(field) != decision[field]:
                raise ValueError(f"Native/export decision differs: {position}/{field}")
        if any(
            row[field] != decision[field] for field in ("subject_id", "predicate_id", "object_id")
        ):
            raise ValueError("Native/export mapping triple differs")
        owner = decision["owner_record"]
        if expected[owner] != decision["owner_record_sha256"]:
            raise ValueError("Owner-record binding differs")
        validate_review_decision(
            decision, row, owner, expected[owner], kept, proofs, require_owner_path=True
        )
        dependency = payload_digest(
            {
                "manifest": bundle.manifest_sha256,
                "owner": expected[owner],
                "evidence": expected[decision["review_evidence"]],
            }
        )
        request = {"kind": "mim_mapping_payload", "payload": row, "dependency_sha256": dependency}
        altered = dict(row, other=row.get("other", "") + " changed scope")
        scenarios = {
            "exact_payload": classify_reuse(row, decision, request, dependency),
            "changed_payload": classify_reuse(
                row, decision, dict(request, payload=altered), dependency
            ),
            "changed_dependency": classify_reuse(
                row, decision, dict(request, dependency_sha256="0" * 64), dependency
            ),
            "endpoint_only_biological_control": classify_reuse(
                row,
                decision,
                {
                    "kind": "synthetic_biological_assertion",
                    "subject": "example:organism",
                    "predicate": "example:grows_on",
                    "object": row["object_id"],
                    "dependency_sha256": dependency,
                },
                dependency,
            ),
        }
        expected_outcome = (
            "eligible_native_mapping_reuse" if position == 1 else "native_withheld_mapping"
        )
        if (
            scenarios["exact_payload"]["outcome"] != expected_outcome
            or scenarios["changed_payload"]["outcome"] != "scope_mismatch"
            or scenarios["changed_dependency"]["outcome"] != "stale_dependencies"
            or scenarios["endpoint_only_biological_control"]["eligible_for_reuse"]
        ):
            raise ValueError("Canary scope or invalidation control failed")
        proof = proofs[decision["review_evidence"]]["entries"][decision["evidence_key"]]
        if (
            position == 1
            and proof.get("basis", {}).get("previous_decision", {}).get("resolution_status")
            != "APPROVED"
        ):
            raise ValueError("Selected supported claim no longer has inherited approval")
        results.append(
            {
                "native_decision": decision,
                "mapping_payload": row,
                "evidence_entry": proof,
                "dependency_sha256": dependency,
                "assurance": "inherited_native_approval"
                if position == 1
                else "native_withheld_decision",
                "scenarios": scenarios,
            }
        )
    kg_manifest_bytes = args.kg_manifest.read_bytes()
    kg_manifest = read_json(kg_manifest_bytes)
    if (
        refresh._file_hash(args.archive) != pin["source_archive"]["sha256"]
        or pin_path.read_bytes() != pin_bytes
    ):
        raise ValueError("Canary input changed during validation")
    release.validate_reviewed_bundle(args.bundle, expected_manifest_sha256=pin["manifest_sha256"])
    return {
        "schema_version": 1,
        "status": "PASS_OFFLINE_REVIEW_REUSE_CANARY",
        "independent_scientific_review": False,
        "actual_kg_edges_approved": 0,
        "scope": "Pinned MIM review import and synthetic scope/invalidation controls only",
        "mim_source_commit": pin["source_commit"],
        "pin_sha256": digest(pin_bytes),
        "bundle_manifest_sha256": bundle.manifest_sha256,
        "archive_sha256": pin["source_archive"]["sha256"],
        "archive_binding": archive_binding,
        "source_counts": bundle.manifest["counts"],
        "native_review_input_hashes_verified": len(expected),
        "kg_manifest": {
            "sha256": digest(kg_manifest_bytes),
            "declared_members": kg_manifest.get("members", {}),
            "verification": "manifest_only; graph membership not tested",
        },
        "selected_claims": results,
    }


def run_child(args: argparse.Namespace, *, probe_only: bool = False) -> dict:
    """Isolate imports and reject provenance drift before any receipt is published."""
    expected = source_snapshot(args.kg_root)
    command = [str(args.kg_python.absolute()), expected["launcher"]["path"], "--validation-child"]
    if probe_only:
        command.append("--runtime-probe")
    for key, value in vars(args).items():
        if isinstance(value, Path):
            command.extend(["--" + key.replace("_", "-"), str(value.absolute())])
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(args.kg_root.resolve(strict=True))
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    # -B still reads timestamp-valid bytecode. A fresh prefix forces source reads.
    with tempfile.TemporaryDirectory(prefix="mim-canary-pycache-") as pycache:
        environment["PYTHONPYCACHEPREFIX"] = pycache
        completed = subprocess.run(
            command,
            input=json.dumps(expected, allow_nan=False),
            check=True,
            text=True,
            capture_output=True,
            env=environment,
            cwd=args.kg_root,
            timeout=180,
        )
    verify_sources(args.kg_root, expected)
    report = read_json(completed.stdout.encode())
    provenance = report["runtime_provenance"]
    if provenance["sources"] != expected or provenance["before"] != provenance["after"]:
        raise ValueError("Child runtime provenance differs from the launch snapshot")
    for phase in ("before", "after"):
        verify_runtime(provenance[phase], args, expected)
    report["validator_code_sha256"] = {
        VALIDATORS[name]: value["sha256"] for name, value in expected["validators"].items()
    }
    report["canary_script_sha256"] = expected["launcher"]["sha256"]
    return report


def publish_new(path: Path, report: dict) -> None:
    """Publish a complete receipt atomically, never replacing an existing path."""
    data = (json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".mim-canary-", delete=False) as temp:
        temporary = Path(temp.name)
        try:
            temp.write(data)
            temp.flush()
            os.fsync(temp.fileno())
            os.link(temporary, path)
            if path.read_bytes() != data:
                raise ValueError("Persisted canary receipt differs from verified report")
        finally:
            temporary.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("kg-root", "kg-python", "bundle", "archive", "kg-manifest", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument(
        "--plan", action="store_true", help="Print the local execution plan; write nothing"
    )
    parser.add_argument("--validation-child", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--runtime-probe", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.validation_child:
        print(
            json.dumps(
                validate(args, read_json(sys.stdin.buffer.read())),
                ensure_ascii=False,
                allow_nan=False,
            )
        )
        return
    plan = {
        "mode": "offline_review_reuse",
        "selected_native_positions": POSITIONS,
        "paths": {
            key: str(value.absolute())
            for key, value in vars(args).items()
            if isinstance(value, Path)
        },
        "provider_calls": 0,
    }
    if args.plan:
        print(json.dumps(plan, indent=2))
        return
    if args.output.exists() or args.output.is_symlink():
        raise FileExistsError(f"Refusing to overwrite output: {args.output}")
    report = run_child(args)
    report["execution"] = plan
    publish_new(args.output, report)
    print(
        json.dumps(
            {
                "status": report["status"],
                "output": str(args.output.absolute()),
                "sha256": digest(args.output.read_bytes()),
                "actual_kg_edges_approved": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
