"""Public audit component and strict final receipt union.

Only protected code runs here. Candidate manifests are parsed as data; candidate
Python is never imported. Public reports are incomplete whenever private work is
owed. The required aggregate authenticates their Actions artifact before use.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import GovernanceError
from . import automatic_private_audit as auto
from . import private_audit_coverage as coverage
from . import private_scaleup_audit as manual
from .artifacts.scripts.check_vendored_sync import _git_environment, parse_manifest
from .fleet_audit import _commit_at
from .public_repository_metadata import PublicRepositoryMetadata

LANES = ("protected", "candidate")
ROW_FIELDS = {
    "key",
    "github",
    "head",
    "pin",
    "state",
    "expected_artifacts",
    "checked_artifacts",
    "issues",
}
STATES = {"audited", "tracked", "pending_bootstrap"}

DIAGNOSTIC_STAGES = frozenset({
    "arguments", "configuration", "protected_runtime", "parent_binding",
    "public_component", "manifest_binding", "coverage_obligation", "public_metadata",
    "public_clone", "public_materialization", "source_preparation", "protected_audit",
    "candidate_completeness", "receipt_validation", "parent_recheck", "receipt",
})


def failure_stage(error: Exception, fallback: str) -> str:
    value = getattr(error, "_public_fleet_stage", None)
    return value if isinstance(value, str) and value in DIAGNOSTIC_STAGES else fallback


@contextmanager
def diagnostic_stage(stage: str) -> Iterator[None]:
    """Annotate failures with a closed phase while preserving their original type."""
    if stage not in DIAGNOSTIC_STAGES:
        raise ValueError("unsupported public diagnostic stage")
    try:
        yield
    except Exception as error:
        # An inner phase is more precise than its enclosing audit phase.
        setattr(error, "_public_fleet_stage", failure_stage(error, stage))
        raise


def git(root: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", *arguments],
        cwd=root,
        env=_git_environment(),
        capture_output=True,
        timeout=180,
        check=True,
    )
    return result.stdout.decode().strip()


def manifests(public, binding: dict):
    values = {}
    hashes = {}
    for lane, ref in (
        ("protected", binding["protected_main_sha"]),
        ("candidate", binding["checkout_sha"]),
    ):
        raw = auto.public_blob(public, auto.MANIFEST_PATH, ref)
        values[lane], hashes[lane] = parse_manifest(raw), manual.digest(raw)
    return values, hashes


def prepare_sources(root: Path) -> None:
    from .infrastructure_admission import trusted_source_ref

    refs = set()
    selected = trusted_source_ref(root)
    if selected:
        refs.add(selected)
    # An optional protected extension owns later public consumer declarations.
    # Absence is not interpreted as an admission for a candidate-only consumer.
    if (root / "src/kg_microbe_governance/consumer_admission.py").is_file():
        from .consumer_admission import source_refs  # type: ignore[import-not-found]

        refs.update(source_refs(root))
    for ref in sorted(refs):
        auto.check(manual.is_sha(ref))
        git(
            root,
            "fetch",
            "--no-tags",
            "--no-prune",
            "--no-write-fetch-head",
            "origin",
            ref,
        )


def bootstrap_refs(root: Path) -> dict[str, str]:
    from .infrastructure_admission import ADMITTED, validate_packaged_transition

    result = {}
    path = (
        root
        / "src/kg_microbe_governance/releases/edgemech-infrastructure-admission-v1.json"
    )
    if path.exists():
        result[ADMITTED.key] = validate_packaged_transition(root)["bootstrap_main_ref"]
    if (root / "src/kg_microbe_governance/consumer_admission.py").is_file():
        from .consumer_admission import SPECS, parse_policy  # type: ignore[import-not-found]

        for spec in SPECS:
            path = root / spec.declaration
            if path.is_file():
                result[spec.consumer.key] = parse_policy(path.read_bytes(), spec)[
                    "bootstrap_main_ref"
                ]
    return result


def candidate_bootstrap_refs(trusted: Path, binding: dict, manifest) -> dict[str, str]:
    """Proposed completeness only; these data never activate deployed admission."""
    module = trusted / "src/kg_microbe_governance/consumer_admission.py"
    if not module.is_file():
        raise GovernanceError(
            "Prospective public bootstrap requires protected consumer_admission framework (PR1056)"
        )
    from .consumer_admission import compose  # type: ignore[import-not-found]
    from .fleet_audit import _head_blob

    ref = binding["checkout_sha"]
    auto.check(manual.is_sha(ref))
    git(
        trusted,
        "fetch",
        "--no-tags",
        "--no-prune",
        "--no-write-fetch-head",
        "origin",
        ref,
    )

    def read(path: str) -> bytes:
        auto.check(
            path in {auto.MANIFEST_PATH, "src/kg_microbe_fleet/fleet.yaml"}
            or (
                path.startswith("src/kg_microbe_governance/releases/")
                and path.endswith(".json")
                and ".." not in path
            )
        )
        blob = _head_blob(trusted, ref, path)
        if blob is None:
            raise FileNotFoundError(path)
        auto.check(blob[0] == "100644")
        return blob[1]

    _, composed, additions = compose(
        read, read("src/kg_microbe_fleet/fleet.yaml"), read(auto.MANIFEST_PATH)
    )
    auto.check(composed.consumers == manifest.consumers)
    result = {}
    for key, admission in additions.items():
        if key == "scaleupmech":
            continue
        source_ref = admission.policy["source_ref"]
        git(
            trusted,
            "fetch",
            "--no-tags",
            "--no-prune",
            "--no-write-fetch-head",
            "origin",
            source_ref,
        )
        source_blob = _head_blob(trusted, source_ref, auto.MANIFEST_PATH)
        auto.check(
            source_blob == ("100644", admission.source_content), "source_unverified"
        )
        result[key] = admission.policy["bootstrap_main_ref"]
    return result


def pending_by_lane(trusted: Path, binding: dict, values: dict, rows: dict) -> dict:
    protected = bootstrap_refs(trusted)
    candidate = dict(protected)
    proposed = any(
        row.get("state") == "pending_bootstrap" and row.get("key") not in protected
        for row in rows.get("candidate", [])
    )
    if proposed:
        candidate.update(
            candidate_bootstrap_refs(trusted, binding, values["candidate"])
        )
    return {"protected": protected, "candidate": candidate}


def clone_public(public, workspace: Path, values: dict) -> dict[str, Path]:
    consumers: dict[str, Any] = {}
    for manifest in values.values():
        for key, consumer in manifest.consumers.items():
            if key == "scaleupmech":
                coverage.obligation(manifest)  # exact policy or refusal, never clone
                continue
            auto.check(
                key not in consumers or consumers[key] == consumer, "source_unverified"
            )
            consumers[key] = consumer
    metadata_client = PublicRepositoryMetadata({consumer.github for consumer in consumers.values()})
    roots = {}
    workspace.mkdir(parents=True, exist_ok=False)
    for key, consumer in sorted(consumers.items()):
        with diagnostic_stage("public_metadata"):
            metadata = metadata_client.get(consumer.github)
            auto.check(
                metadata.get("full_name") == consumer.github
                and metadata.get("private") is False
                and metadata.get("default_branch") == "main",
                "source_unverified",
            )
        target = workspace / key
        # Lazy fetching stays disabled for every Git command. Fetch the current
        # tree's blobs up front; depth one avoids history and sparse checkout
        # still limits materialized files. A blobless clone cannot do this checkout.
        with diagnostic_stage("public_clone"):
            git(
                workspace,
                "clone",
                "--no-checkout",
                "--depth",
                "1",
                "--branch",
                "main",
                f"https://github.com/{consumer.github}.git",
                str(target),
            )
        targets = set()
        for manifest in values.values():
            if key in manifest.consumers:
                targets.add(manifest.pin_path)
                targets.update(
                    a.target.replace("{package_path}", consumer.package_path)
                    for a in manifest.artifacts_for(consumer)
                )
        with diagnostic_stage("public_materialization"):
            git(target, "sparse-checkout", "init", "--no-cone")
            git(target, "sparse-checkout", "set", "--no-cone", *sorted(targets))
            git(target, "checkout", "--detach", "origin/main")
        roots[key] = target
    return roots


def public_component(public, trusted: Path, binding: dict, workspace: Path) -> dict:
    with diagnostic_stage("manifest_binding"):
        values, hashes = manifests(public, binding)
        protected = values["protected"]
        auto.check(
            (trusted / auto.MANIFEST_PATH).read_bytes()
            == auto.public_blob(public, auto.MANIFEST_PATH, binding["protected_main_sha"])
        )
    with diagnostic_stage("coverage_obligation"):
        obligation = auto.private_obligation(public, binding, manual.load_policy())
    with diagnostic_stage("public_materialization"):
        roots = clone_public(public, workspace, values)
    with diagnostic_stage("source_preparation"):
        prepare_sources(trusted)
    with diagnostic_stage("protected_audit"):
        item = coverage.obligation(protected)
        deferred = {} if item is None else {item.key: item}
        protected_roots = {
            key: roots[key] for key in protected.consumers if key not in deferred
        }
        if (
            trusted / "src/kg_microbe_governance/releases/mech-cycle-v2-canary.json"
        ).exists():
            from .cycle_release_audit import audit_release

            result = audit_release(trusted, protected_roots, private_obligations=deferred)
            auto.check(result.get("public_component_ok") is True)
            raw_rows = [row for row in result["repositories"] if row["key"] not in deferred]
        else:
            from .fleet_audit import audit_fleet_pins

            pins = {
                git(root, "show", f"HEAD:{protected.pin_path}")
                for root in protected_roots.values()
            }
            auto.check(len(pins) == 1)
            ref = next(iter(pins))
            auto.check(manual.is_sha(ref))
            git(trusted, "merge-base", "--is-ancestor", ref, "HEAD")
            fleet_result = audit_fleet_pins(
                protected_roots, ref, private_obligations=deferred
            )
            auto.check(
                all(
                    issue.code == "private_verification_required"
                    for issue in fleet_result.issues
                )
            )
            raw_rows = [asdict(row) for row in fleet_result.repositories]
        pending = bootstrap_refs(trusted)
    prospective = None
    rows: dict[str, list[dict[str, Any]]] = {"protected": [], "candidate": []}
    for row in raw_rows:
        count = len(protected.artifacts_for(protected.consumers[row["key"]]))
        is_pending = row.get("state") == "pending_infrastructure_bootstrap"
        rows["protected"].append(
            {
                "key": row["key"],
                "github": row["github"],
                "head": row["head"],
                "pin": row["pin"],
                "state": "pending_bootstrap" if is_pending else "audited",
                "expected_artifacts": count,
                "checked_artifacts": 0 if is_pending else row["checked_artifacts"],
                "issues": row["issues"],
            }
        )
    with diagnostic_stage("candidate_completeness"):
        for key, consumer in values["candidate"].consumers.items():
            if key == "scaleupmech":
                continue
            root = roots[key]
            head = _commit_at(root, "origin/main")
            artifacts = values["candidate"].artifacts_for(consumer)
            missing = []
            for artifact in artifacts:
                path = artifact.target.replace("{package_path}", consumer.package_path)
                if (
                    git(
                        root, "ls-tree", "--format=%(objecttype)", "origin/main", "--", path
                    )
                    != "blob"
                ):
                    missing.append(path)
            if missing and key not in pending:
                if prospective is None:
                    prospective = candidate_bootstrap_refs(
                        trusted, binding, values["candidate"]
                    )
                candidate_pending = {**pending, **prospective}
            else:
                candidate_pending = pending
            is_pending = bool(
                missing
                and candidate_pending.get(key) == head
                and len(missing) == len(artifacts)
            )
            if is_pending:
                if key in protected.consumers:
                    auto.check(
                        values["candidate"].artifacts_for(consumer)
                        == protected.artifacts_for(protected.consumers[key])
                    )
            auto.check(not missing or is_pending, "inspection_invalid")
            rows["candidate"].append(
                {
                    "key": key,
                    "github": consumer.github,
                    "head": head,
                    "pin": None,
                    "state": "pending_bootstrap" if is_pending else "tracked",
                    "expected_artifacts": len(artifacts),
                    "checked_artifacts": 0 if is_pending else len(artifacts),
                    "issues": [],
                }
            )
    report = {
        "version": 1,
        "kind": "public_fleet_component",
        "parent": binding,
        "manifest_sha256": hashes,
        "public_component_ok": True,
        "full_fleet_ok": not obligation["required"],
        "private_required": obligation["required"],
        "lanes": rows,
    }
    with diagnostic_stage("receipt_validation"):
        validate_report(
            auto.canonical(report),
            values,
            hashes,
            binding,
            {"protected": pending, "candidate": {**pending, **(prospective or {})}},
        )
    with diagnostic_stage("parent_recheck"):
        auto.check(
            auto.parent_binding(
                public,
                binding["run_id"],
                binding["run_attempt"],
                checkout_sha=binding["checkout_sha"],
            )
            == binding
        )
    return report


def validate_report(
    raw: bytes, values: dict, hashes: dict, binding: dict, pending: dict
) -> dict:
    value = manual.parse_json(raw)
    auto.check(
        isinstance(value, dict)
        and set(value)
        == {
            "version",
            "kind",
            "parent",
            "manifest_sha256",
            "public_component_ok",
            "full_fleet_ok",
            "private_required",
            "lanes",
        }
    )
    private = any("scaleupmech" in manifest.consumers for manifest in values.values())
    auto.check(
        type(value["version"]) is int
        and value["version"] == 1
        and value["kind"] == "public_fleet_component"
        and value["parent"] == binding
        and value["manifest_sha256"] == hashes
        and value["public_component_ok"] is True
        and value["private_required"] is private
        and value["full_fleet_ok"] is (not private)
        and isinstance(value["lanes"], dict)
        and set(value["lanes"]) == set(LANES)
    )
    for lane in LANES:
        manifest = values[lane]
        rows = value["lanes"][lane]
        auto.check(
            isinstance(rows, list)
            and len(rows)
            == len(manifest.consumers) - ("scaleupmech" in manifest.consumers)
        )
        expected = set(manifest.consumers) - {"scaleupmech"}
        keys = []
        for row in rows:
            auto.check(
                isinstance(row, dict)
                and set(row) == ROW_FIELDS
                and row.get("key") in expected
            )
            key = row["key"]
            keys.append(key)
            consumer = manifest.consumers[key]
            count = len(manifest.artifacts_for(consumer))
            auto.check(
                row["github"] == consumer.github
                and manual.is_sha(row["head"])
                and row["issues"] == []
                and row["state"] in STATES
                and type(row["expected_artifacts"]) is int
                and row["expected_artifacts"] == count
                and type(row["checked_artifacts"]) is int
            )
            if row["state"] == "pending_bootstrap":
                auto.check(
                    pending.get(lane, {}).get(key) == row["head"]
                    and row["pin"] is None
                    and row["checked_artifacts"] == 0
                )
            else:
                auto.check(
                    row["checked_artifacts"] == count
                    and row["state"]
                    == ("audited" if lane == "protected" else "tracked")
                )
                auto.check(
                    manual.is_sha(row["pin"])
                    if lane == "protected"
                    else row["pin"] is None
                )
        auto.check(len(keys) == len(set(keys)) and set(keys) == expected)
    return value


def authenticate_report(public, trusted: Path, binding: dict) -> dict:
    values, hashes = manifests(public, binding)
    raw, artifact = auto.artifact_bytes(
        public,
        binding["run_id"],
        f'public-fleet-{binding["run_id"]}-{binding["run_attempt"]}',
    )
    run = public.get(
        f'/repos/{manual.CONTROL}/actions/runs/{binding["run_id"]}/attempts/{binding["run_attempt"]}'
    )
    auto.check(manual.utc(artifact["created_at"]) >= manual.utc(run["run_started_at"]))
    candidate_report = manual.parse_json(raw)
    auto.check(
        isinstance(candidate_report, dict)
        and isinstance(candidate_report.get("lanes"), dict)
    )
    return validate_report(
        raw,
        values,
        hashes,
        binding,
        pending_by_lane(trusted, binding, values, candidate_report["lanes"]),
    )


def finalize(public, trusted: Path, binding: dict, evidence, *, report: dict) -> None:
    # Reparse the closed report against current immutable inputs even for callers
    # that obtained it earlier. Raw private JSON is never accepted here.
    values, hashes = manifests(public, binding)
    validate_report(
        auto.canonical(report),
        values,
        hashes,
        binding,
        pending_by_lane(trusted, binding, values, report["lanes"]),
    )
    for lane in LANES:
        manifest = values[lane]
        required = "scaleupmech" in manifest.consumers
        private = {"scaleupmech": evidence} if required else {}
        auto.check(not required or isinstance(evidence, auto.VerifiedPrivateEvidence))
        coverage.complete_rows(
            manifest.consumers,
            report["lanes"][lane],
            private,
            manifest,
            now=datetime.now(timezone.utc),
        )


def failure_code(error: Exception) -> str:
    """Return only closed public diagnostics, never exception text or subprocess output."""
    if isinstance(error, manual.AuditError):
        return error.code if isinstance(error.code, str) and error.code in manual.CODES else "unexpected_failure"
    if isinstance(error, subprocess.TimeoutExpired):
        return "subprocess_timeout"
    if isinstance(error, subprocess.SubprocessError):
        return "subprocess_failed"
    if isinstance(error, GovernanceError):
        return "governance_invalid"
    if isinstance(error, OSError):
        return "filesystem_error"
    if isinstance(error, ValueError):
        return "invalid_value"
    return "unexpected_failure"


def main(argv=None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trusted-root", type=Path, required=True)
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--checkout-sha", required=True)
    args = parser.parse_args(argv)
    stage = "arguments"
    try:
        from .automatic_private_audit_cli import (
            append_receipt,
            integer,
            protected_runtime,
        )

        auto.check(
            not args.output.exists() and manual.is_sha(args.checkout_sha),
            "invalid_arguments",
        )
        stage = "configuration"
        run_id, run_attempt = integer("GITHUB_RUN_ID"), integer("GITHUB_RUN_ATTEMPT")
        public = manual.GitHubRead(os.environ.get("GH_PUBLIC_READ_TOKEN", ""))
        stage = "protected_runtime"
        trusted_sha = protected_runtime(public, args.trusted_root)
        stage = "parent_binding"
        binding = auto.parent_binding(
            public,
            run_id,
            run_attempt,
            checkout_sha=args.checkout_sha,
        )
        auto.check(binding["protected_main_sha"] == trusted_sha)
        stage = "public_component"
        report = public_component(public, args.trusted_root, binding, args.workspace)
        stage = "receipt"
        append_receipt(args.output, report)
        print("public_fleet_component_complete_private_obligations_explicit")
        return 0
    except Exception as error:
        stage = failure_stage(error, stage)
        print(
            f"public_fleet_component_failed stage={stage} code={failure_code(error)}",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
