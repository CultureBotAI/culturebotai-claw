"""Audit the single-DUFMech cycle-v2 release without relaxing coordinated fleet audit.

Only the executing trusted package supplies code. Historical manifests and
artifacts are read as data from the verified Claw Git object database. This
command never fetches, switches checkouts, or executes a downstream pin.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

import yaml

from kg_microbe_fleet import FleetManifest, UniqueKeySafeLoader, parse_fleet_manifest

from . import _require_clean_worktree, _validate_target_repository
from .artifacts.scripts.check_vendored_sync import (
    CANONICAL_MANIFEST_PATH,
    CANONICAL_REPOSITORY,
    Consumer,
    GovernanceError,
    GovernanceManifest,
    _reject_duplicate_pairs,
    _run_git,
    check_repository,
    expand_target,
    parse_manifest,
    raw_url,
)
from .fleet_audit import (
    RepositoryAuditResult,
    _commit_at,
    _head_blob,
    _preflight_repository,
    _run_git_bytes,
)
from .infrastructure_admission import (
    ADMISSION_PATH,
    ADMITTED,
    HISTORICAL_MANIFEST_PATH,
    admission_anchor,
    bind_source_snapshot,
    bootstrap_pending,
    parse_admission,
    validate_transition,
)

RELEASE_ID = "mech-cycle-v2-dufmech"
RELEASE_PATH = "src/kg_microbe_governance/releases/mech-cycle-v2-canary.json"
FLEET_PATH = "src/kg_microbe_fleet/fleet.yaml"
CANARY = "dufmech"
WORKFLOW_ASSETS = frozenset({
    "src/kg_microbe_workflows/templates/mech-cycle.yaml",
    "src/kg_microbe_workflows/schema/workflow.yaml",
    "src/kg_microbe_skills/canonical/triage-and-resolve-issues.md",
    "src/kg_microbe_skills/canonical/evolve-mech-workflow.md",
})
PARENT_PATH = "src/kg_microbe_workflows/templates/mech-cycle.yaml"
_FIELDS = frozenset({
    "version", "release_id", "baseline_ref", "release_ref", "canary",
    "manifest_sha256", "workflow_assets", "parent_version",
})


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _json(content: bytes) -> dict[str, Any]:
    try:
        document = json.loads(content, object_pairs_hook=_reject_duplicate_pairs)
    except (UnicodeError, ValueError) as exc:
        raise GovernanceError(f"Invalid release JSON: {exc}") from exc
    if not isinstance(document, dict):
        raise GovernanceError("Release JSON must be an object")
    return document


def parse_release(content: bytes) -> dict[str, Any]:
    document = _json(content)
    if set(document) != _FIELDS:
        raise GovernanceError("Release declaration has missing or unknown fields")
    if type(document["version"]) is not int or document["version"] != 1:
        raise GovernanceError("Release version must be integer 1")
    if (document["release_id"] != RELEASE_ID or document["canary"] != CANARY
            or document["parent_version"] != "2.0.0"):
        raise GovernanceError("Declaration is not the approved single-DUFMech cycle-v2 release")
    for key, width in (("baseline_ref", 40), ("release_ref", 40), ("manifest_sha256", 64)):
        if not isinstance(document[key], str) or not re.fullmatch(f"[0-9a-f]{{{width}}}", document[key]):
            raise GovernanceError(f"{key} must be a full lowercase immutable digest")
    assets = document["workflow_assets"]
    if not isinstance(assets, dict) or set(assets) != WORKFLOW_ASSETS:
        raise GovernanceError("Release must bind exactly the parent, schema and both canonical skills")
    if any(not isinstance(value, str) or not re.fullmatch("[0-9a-f]{64}", value) for value in assets.values()):
        raise GovernanceError("Every workflow asset needs a full SHA-256 digest")
    return document


def _blob(root: Path, ref: str, path: str, *, mode: str = "100644") -> bytes:
    entry = _head_blob(root, ref, path)
    if entry is None:
        raise GovernanceError(f"Trusted history is missing {path} at {ref}")
    actual_mode, content = entry
    if actual_mode != mode:
        raise GovernanceError(f"Trusted history has unsafe or unexpected mode for {path}: {actual_mode}")
    return content


def _ancestor(root: Path, older: str, newer: str) -> bool:
    result = _run_git_bytes(root, ("merge-base", "--is-ancestor", older, newer), check=False)
    if result.returncode not in {0, 1}:
        raise GovernanceError("Unable to establish trusted Claw ancestry")
    return result.returncode == 0


def release_anchor(root: Path, head: str, content: bytes) -> str:
    """First-parent introduction; an existing release file cannot be edited."""
    revisions = _run_git(root, ("rev-list", "--first-parent", head)).splitlines()
    anchor: str | None = None
    for revision in revisions:
        entry = _head_blob(root, revision, RELEASE_PATH)
        if entry == ("100644", content):
            anchor = revision
            continue
        if entry is not None:
            raise GovernanceError("The release declaration was modified; its current blob is not an immutable introduction")
        # No older copy (including a deleted declaration) may precede this
        # introduction. It would silently turn a previous release into a new C.
        if _run_git(root, ("log", "-1", "--format=%H", revision, "--", RELEASE_PATH)):
            raise GovernanceError("The release declaration was deleted and reintroduced")
        break
    if anchor is None:
        raise GovernanceError("Trusted HEAD does not carry the release declaration")
    return anchor


def _fleet(root: Path, ref: str) -> FleetManifest:
    try:
        document = yaml.load(_blob(root, ref, FLEET_PATH), Loader=UniqueKeySafeLoader)
        return parse_fleet_manifest(document, root / FLEET_PATH)
    except (ValueError, yaml.YAMLError) as exc:
        raise GovernanceError(f"Invalid trusted fleet manifest at {ref}: {exc}") from exc


def _snapshot(root: Path, ref: str) -> tuple[GovernanceManifest, dict[str, bytes], bytes]:
    raw = _blob(root, ref, CANONICAL_MANIFEST_PATH)
    manifest = parse_manifest(raw)
    fleet = _fleet(root, ref)
    identities = {key: (m.github, m.package_path) for key, m in fleet.mechs.items()}
    if {key: (c.github, c.package_path) for key, c in manifest.consumers.items()} != identities:
        raise GovernanceError("Historical governance and fleet consumer identities differ")
    governance = fleet.vendored_governance
    if (manifest.canonical_repository != governance.canonical_repository
            or manifest.pin_path != governance.pin_path
            or governance.manifest_path != CANONICAL_MANIFEST_PATH):
        raise GovernanceError("Historical fleet governance authority differs")
    payloads = {CANONICAL_MANIFEST_PATH: raw}
    for artifact in manifest.artifacts:
        expected_mode = "100755" if artifact.mode & 0o100 else "100644"
        payload = _blob(root, ref, artifact.source, mode=expected_mode)
        if _sha(payload) != artifact.sha256:
            raise GovernanceError(f"Historical artifact checksum drift: {artifact.source}")
        payloads[artifact.source] = payload
    return manifest, payloads, raw


def _validate_release_assets(root: Path, ref: str, policy: Mapping[str, Any]) -> None:
    for path, digest in policy["workflow_assets"].items():
        if _sha(_blob(root, ref, path)) != digest:
            raise GovernanceError(f"Release workflow asset digest differs: {path}")
    try:
        parent = yaml.load(_blob(root, ref, PARENT_PATH), Loader=UniqueKeySafeLoader)
        if (not isinstance(parent, dict) or parent.get("version") != "2.0.0"
                or parent.get("schema_version") != "2.0.0"
                or len(parent.get("stages", [])) != 7
                or parent["stages"][0].get("key") != "open_issue_triage"):
            raise GovernanceError("Release does not carry the seven-goal parent v2.0.0")
    except (ValueError, TypeError, AttributeError, yaml.YAMLError) as exc:
        raise GovernanceError(f"Invalid release parent: {exc}") from exc


def audit_release(trusted_root: Path, roots: Mapping[str, Path]) -> dict[str, Any]:
    """Inspect all roots, returning detailed failures; policy errors raise."""
    trusted = _validate_target_repository(
        trusted_root, Consumer("claw", CANONICAL_REPOSITORY, "src/kg_microbe_governance")
    )
    _require_clean_worktree(trusted)
    head = _commit_at(trusted, "HEAD")
    origin_main = _commit_at(trusted, "refs/remotes/origin/main")
    protected_history = set(_run_git(trusted, ("rev-list", "--first-parent", origin_main)).splitlines())
    if head not in protected_history:
        raise GovernanceError("Trusted audit HEAD is not protected origin/main first-parent history")
    content = _blob(trusted, head, RELEASE_PATH)
    policy = parse_release(content)
    lane_ref = release_anchor(trusted, head, content)
    candidate_ref = policy["release_ref"]
    baseline_ref = policy["baseline_ref"]
    if any(ref not in protected_history for ref in (baseline_ref, candidate_ref, lane_ref)):
        raise GovernanceError("Baseline, release and lane must belong to protected origin/main first-parent history")
    if (baseline_ref == candidate_ref or candidate_ref == lane_ref
            or not _ancestor(trusted, baseline_ref, candidate_ref)
            or not _ancestor(trusted, candidate_ref, lane_ref)):
        raise GovernanceError("The exact baseline must precede the release, which must precede the lane")
    baseline, base_payloads, base_raw = _snapshot(trusted, baseline_ref)
    candidate, candidate_payloads, candidate_raw = _snapshot(trusted, candidate_ref)
    if CANARY not in baseline.consumers:
        raise GovernanceError("Declared canary is not a manifest-defined consumer")
    if (base_raw != candidate_raw or base_payloads != candidate_payloads
            or _sha(candidate_raw) != policy["manifest_sha256"]):
        raise GovernanceError("Cycle release must preserve exact baseline governance bytes and authority")
    current, current_payloads, current_raw = _snapshot(trusted, head)
    admission: dict[str, Any] | None = None
    admission_report = None
    admission_entry = _head_blob(trusted, head, ADMISSION_PATH)
    if admission_entry is None:
        if _run_git(trusted, ("log", "-1", "--format=%H", head, "--", ADMISSION_PATH)):
            raise GovernanceError("Infrastructure admission declaration was deleted")
        if current_raw != candidate_raw or current_payloads != candidate_payloads:
            raise GovernanceError("Current trusted governance differs from the active cycle release")
    else:
        admission_content = _blob(trusted, head, ADMISSION_PATH)
        admission = parse_admission(admission_content)
        admitted_at = admission_anchor(trusted, head, admission_content)
        if (admitted_at not in protected_history or admitted_at == lane_ref
                or not _ancestor(trusted, lane_ref, admitted_at)):
            raise GovernanceError("Infrastructure admission is outside protected post-cutoff history")
        if _blob(trusted, head, HISTORICAL_MANIFEST_PATH) != candidate_raw:
            raise GovernanceError("Packaged historical governance snapshot differs from its frozen release")
        validate_transition(admission, content, candidate_raw, current_raw, _blob(trusted, head, FLEET_PATH))
        if {k: v for k, v in current_payloads.items() if k != CANONICAL_MANIFEST_PATH} != {
            k: v for k, v in candidate_payloads.items() if k != CANONICAL_MANIFEST_PATH
        }:
            raise GovernanceError("Infrastructure admission changed historical payload bytes")
        _validate_release_assets(trusted, head, policy)
        admission_report = {
            "admission_id": admission["admission_id"], "authority": admission["authority"],
            "activation": "protected_first_parent_introduction", "anchor": admitted_at,
            "declaration_sha256": _sha(admission_content), "source_ref": admission["source_ref"],
            "source_manifest_sha256": admission["source_manifest_sha256"],
            "bootstrap_main_ref": admission["bootstrap_main_ref"],
            "historical_cohort_policy_retained": True, "scientific_capabilities_enabled": False,
        }
    _validate_release_assets(trusted, candidate_ref, policy)
    cohort = current.consumers if admission else candidate.consumers
    if set(roots) != set(cohort):
        raise GovernanceError(
            "Release audit requires every exact fleet root "
            f"(missing={sorted(set(cohort) - set(roots))}, "
            f"unknown={sorted(set(roots) - set(cohort))})"
        )

    preflight = []
    for key, consumer in baseline.consumers.items():
        result = _preflight_repository(
            consumer, roots[key], baseline_ref, baseline.pin_path,
            len(baseline.artifacts_for(consumer)),
        )
        if key == CANARY and result.pin == candidate_ref:
            result = replace(
                result,
                expected_artifacts=len(candidate.artifacts_for(consumer)),
                issues=tuple(issue for issue in result.issues if issue.code != "unexpected_pin"),
            )
        preflight.append(result)
    pending_infrastructure = False
    if admission:
        pending_infrastructure = bootstrap_pending(roots[ADMITTED.key], ADMITTED, current, admission)
        if pending_infrastructure:
            root = roots[ADMITTED.key].resolve()
            preflight.append(RepositoryAuditResult(
                ADMITTED.key, ADMITTED.github, root, admission["bootstrap_main_ref"],
                admission["bootstrap_main_ref"], None, 0, 0, (),
            ))
        else:
            preflight.append(_preflight_repository(
                ADMITTED, roots[ADMITTED.key], admission["source_ref"], current.pin_path,
                len(current.artifacts_for(ADMITTED)),
            ))
    resolved = [result.root for result in preflight]
    if len(set(resolved)) != len(resolved) or trusted in resolved:
        raise GovernanceError("Every consumer and trusted Claw root must be distinct")

    historical = {baseline_ref: (baseline, base_payloads), candidate_ref: (candidate, candidate_payloads)}
    if admission:
        # This one reviewed data pin is declared by protected policy, so squash
        # merging its source branch cannot select arbitrary executable code.
        historical[admission["source_ref"]] = bind_source_snapshot(
            trusted, admission["source_ref"], current_raw, current_payloads,
        )
    canonical = {
        raw_url(ref, path): payload
        for ref, (_, payloads) in historical.items() for path, payload in payloads.items()
    }

    def fetch(url: str) -> bytes:
        if url not in canonical:
            raise GovernanceError("Requested canonical data is outside the approved release snapshots")
        return canonical[url]

    rows = []
    # As in fleet-audit, a failed local preflight prevents any claimed payload
    # check. All identities and main tips are known before content comparisons.
    clean = not any(result.issues for result in preflight)
    for result in preflight:
        row = asdict(result)
        row["root"] = str(result.root)
        row["issues"] = list(row["issues"])
        row["allowed_refs"] = [baseline_ref, candidate_ref] if result.key == CANARY else [baseline_ref]
        row["state"] = (
            "adopted" if result.key == CANARY and result.pin == candidate_ref
            else "pending" if result.key == CANARY else "retained"
        )
        is_infrastructure = bool(admission and result.key == ADMITTED.key)
        if is_infrastructure:
            assert admission is not None
            row["allowed_refs"] = [admission["source_ref"]]
            row["state"] = "pending_infrastructure_bootstrap" if pending_infrastructure else "installed_infrastructure"
            row["installation_verified"] = False
        if clean and not (is_infrastructure and pending_infrastructure):
            assert result.pin is not None and result.head is not None
            manifest, payloads = historical[result.pin]
            consumer = manifest.consumers[result.key]
            expected = [
                (expand_target(artifact, consumer), payloads[artifact.source],
                 "100755" if artifact.mode & 0o100 else "100644")
                for artifact in manifest.artifacts_for(consumer)
            ]
            expected.append((manifest.pin_path, (result.pin + "\n").encode(), "100644"))
            for path, payload, mode in expected:
                try:
                    if _head_blob(result.root, result.head, path) != (mode, payload):
                        row["issues"].append({"code": "committed_drift", "message": f"Committed blob or mode differs: {path}"})
                except GovernanceError as exc:
                    row["issues"].append({"code": "committed_read", "message": str(exc)})
            try:
                checked, problems = check_repository(result.root, consumer.github, fetch=fetch)
                row["checked_artifacts"] = checked
                row["issues"].extend({"code": "working_artifact", "message": problem} for problem in problems)
                if checked != result.expected_artifacts:
                    row["issues"].append({"code": "applicability", "message": "Checked artifact count differs from historical manifest"})
            except GovernanceError as exc:
                row["issues"].append({"code": "working_artifact", "message": str(exc)})
            if is_infrastructure:
                row["installation_verified"] = not row["issues"]
        if row["issues"] or not clean:
            row["state"] = "invalid"
        rows.append(row)
    # Re-read metadata after the audit to catch concurrent changes observed
    # during inspection; there is no claim of locking out external writers.
    stable: list[tuple[Path, str, str | None]] = [(trusted, head, origin_main)]
    stable.extend((r.root, r.head, r.origin_main) for r in preflight if r.head and not r.issues)
    for root, observed, remote in stable:
        _require_clean_worktree(root)
        if (_commit_at(root, "HEAD") != observed
                or _commit_at(root, "refs/remotes/origin/main") != remote):
            raise GovernanceError("A worktree HEAD or origin/main changed during the release audit")
    result_document = {
        "version": 1, "ok": clean and not any(row["issues"] for row in rows),
        "release_id": RELEASE_ID,
        "trusted_head": head, "trusted_origin_main": origin_main,
        "declaration_sha256": _sha(content), "declaration_path": RELEASE_PATH,
        "baseline_ref": baseline_ref, "candidate_ref": candidate_ref, "lane_ref": lane_ref,
        "workflow_assets": policy["workflow_assets"], "parent_version": policy["parent_version"],
        "baseline_manifest_sha256": _sha(base_raw),
        "candidate_manifest_sha256": _sha(candidate_raw),
        "counts": {state: sum(row["state"] == state for row in rows)
                   for state in (("pending", "adopted", "retained", "invalid")
                                 + (("pending_infrastructure_bootstrap", "installed_infrastructure") if admission else ()))},
        "repositories": rows,
    }
    if admission_report is not None:
        result_document["infrastructure_admission"] = admission_report
    return result_document


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trusted-root", type=Path, required=True)
    parser.add_argument("--target-root", action="append", required=True, metavar="KEY=PATH")
    parser.add_argument("--json-output", type=Path)
    args = parser.parse_args(argv)
    roots: dict[str, Path] = {}
    output_allowed = False
    try:
        for argument in args.target_root:
            key, separator, path = argument.partition("=")
            if not separator or not key or not path or key in roots:
                raise GovernanceError("Each target root must be a unique KEY=PATH")
            roots[key] = Path(path)
        if args.json_output is not None:
            output = args.json_output.resolve()
            if any(output.is_relative_to(root.resolve()) for root in [args.trusted_root, *roots.values()]):
                raise GovernanceError("The report must be outside the audited checkouts")
            output_allowed = True
        result = audit_release(args.trusted_root, roots)
        code = 0 if result["ok"] else 1
    except (GovernanceError, OSError, ValueError) as exc:
        result = {"version": 1, "ok": False, "error": str(exc)}
        code = 2
    text = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.json_output is not None and output_allowed:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=args.json_output.parent, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(text)
        try:
            os.replace(temporary, args.json_output)
        finally:
            temporary.unlink(missing_ok=True)
    print(text, end="")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
