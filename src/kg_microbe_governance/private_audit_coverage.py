"""Explicit public/private coverage for a full-fleet verdict.

A deferred obligation is not a successful audit or a filesystem root. Only an
authenticated automatic receipt can replace it in the final trusted verifier.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from . import GovernanceError
from . import private_scaleup_audit as manual
from .automatic_private_audit import VerifiedPrivateEvidence


@dataclass(frozen=True)
class PrivateObligation:
    key: str
    repository: str
    source_ref: str
    source_manifest_sha256: str
    expected_artifacts: tuple[tuple[str, str, str, str], ...]
    bootstrap_main_ref: str


def obligation(manifest, policy: dict | None = None) -> PrivateObligation | None:
    policy = manual.load_policy() if policy is None else policy
    consumer = manifest.consumers.get("scaleupmech")
    if consumer is None:
        return None
    if consumer.github != manual.PRIVATE or consumer.package_path != "src/scaleupmech":
        raise GovernanceError("Private consumer identity differs from protected policy")
    rows = tuple(
        sorted(
            (
                a.artifact_id,
                a.target.replace("{package_path}", consumer.package_path),
                a.sha256,
                f"{a.mode:04o}",
            )
            for a in manifest.artifacts_for(consumer)
        )
    )
    expected = tuple(
        sorted(
            (a["id"], a["target"], a["sha256"], a["mode"]) for a in policy["artifacts"]
        )
    )
    if rows != expected or manifest.pin_path != policy["pin_path"]:
        raise GovernanceError(
            "Private consumer obligations differ from protected policy"
        )
    return PrivateObligation(
        "scaleupmech",
        manual.PRIVATE,
        policy["source_ref"],
        policy["source_manifest_sha256"],
        rows,
        policy["bootstrap_main_ref"],
    )


def exact_coverage(
    consumers: Mapping, roots: Mapping, deferred: Mapping[str, PrivateObligation]
) -> None:
    if set(roots) & set(deferred) or set(roots) | set(deferred) != set(consumers):
        raise GovernanceError(
            "Release audit requires every exact fleet root or one explicit private obligation"
        )
    for key, item in deferred.items():
        if (
            not isinstance(item, PrivateObligation)
            or key != "scaleupmech"
            or item.key != key
            or item.repository != manual.PRIVATE
            or consumers[key].github != manual.PRIVATE
        ):
            raise GovernanceError("Unknown or mismatched private audit obligation")


def deferred_row(item: PrivateObligation) -> dict[str, Any]:
    return {
        "key": item.key,
        "github": item.repository,
        "root": None,
        "head": None,
        "origin_main": None,
        "pin": None,
        "expected_artifacts": len(item.expected_artifacts),
        "checked_artifacts": 0,
        "issues": [],
        "state": "private_verification_required",
        "installation_verified": False,
        "allowed_refs": [item.source_ref],
        "source_manifest_sha256": item.source_manifest_sha256,
    }


def validate_admission(item: PrivateObligation, declaration: Mapping) -> None:
    policy = manual.load_policy()
    expected = tuple(
        sorted(
            (a["id"], a["target"], a["sha256"], a["mode"]) for a in policy["artifacts"]
        )
    )
    if (
        item.key != "scaleupmech"
        or item.repository != manual.PRIVATE
        or item.source_ref != policy["source_ref"]
        or item.source_manifest_sha256 != policy["source_manifest_sha256"]
        or item.bootstrap_main_ref != policy["bootstrap_main_ref"]
        or item.expected_artifacts != expected
    ):
        raise GovernanceError(
            "Private obligation differs from the fixed protected policy"
        )
    if (
        declaration.get("source_ref") != item.source_ref
        or declaration.get("source_manifest_sha256") != item.source_manifest_sha256
        or declaration.get("bootstrap_main_ref") != item.bootstrap_main_ref
    ):
        raise GovernanceError(
            "Private declaration does not match the authenticated receipt policy"
        )


def complete_rows(
    consumers: Mapping,
    public_rows: list[dict],
    private: Mapping[str, VerifiedPrivateEvidence],
    manifest,
    *,
    now: datetime,
    policy: dict | None = None,
) -> list[dict]:
    """Finalize exact rows; neither an absent private root nor unverified JSON is authority."""
    expected = obligation(manifest, policy)
    expected_private = {} if expected is None else {expected.key: expected}
    keys = [row.get("key") for row in public_rows]
    if len(keys) != len(set(keys)) or set(private) != set(expected_private):
        raise GovernanceError(
            "Duplicate public coverage or missing/unknown private receipt"
        )
    if set(keys) & set(private) or set(keys) | set(private) != set(consumers):
        raise GovernanceError(
            "Final fleet coverage is not the exact disjoint consumer union"
        )
    if any(
        row.get("issues") != []
        or row.get("state") not in {"audited", "tracked", "pending_bootstrap"}
        or row.get("github") != consumers[row["key"]].github
        for row in public_rows
    ):
        raise GovernanceError("Public fleet component is incomplete or invalid")
    result = list(public_rows)
    for key, evidence in private.items():
        if not isinstance(evidence, VerifiedPrivateEvidence):
            raise GovernanceError(
                "Private data has not passed protected artifact verification"
            )
        evidence.fresh(now)
        item = expected_private[key]
        receipt = evidence.receipt
        if (
            receipt["repository"] != item.repository
            or receipt["source_ref"] != item.source_ref
            or receipt["source_manifest_sha256"] != item.source_manifest_sha256
        ):
            raise GovernanceError(
                "Private evidence does not match current protected obligations"
            )
        installed = receipt["state"] == "installed"
        if not installed and not (
            receipt["state"] == "pending_bootstrap"
            and receipt["private_main_sha"] == item.bootstrap_main_ref
        ):
            raise GovernanceError(
                "Private receipt is neither installed nor exact pending bootstrap"
            )
        result.append(
            {
                "key": key,
                "github": item.repository,
                "root": None,
                "head": receipt["private_main_sha"],
                "origin_main": receipt["private_main_sha"],
                "pin": item.source_ref if installed else None,
                "expected_artifacts": len(item.expected_artifacts),
                "checked_artifacts": len(item.expected_artifacts) if installed else 0,
                "issues": [],
                "state": (
                    "installed_infrastructure"
                    if installed
                    else "pending_infrastructure_bootstrap"
                ),
                "installation_verified": installed,
                "allowed_refs": [item.source_ref],
                "evidence_kind": "verified_private_workflow_receipt",
                "producer_run_id": evidence.producer_run_id,
                "producer_attempt": evidence.producer_attempt,
                "private_tip_checked_at": evidence.checked_at.isoformat(),
            }
        )
    return result
