"""Separately sealed native-consumer admissions; no implicit cohort expansion.

Candidate composition is data validation only. Runtime authority additionally
requires each declaration's immutable introduction on protected first-parent
history. The legacy Edge declaration and its validators remain unchanged.
"""
from __future__ import annotations

import argparse
import json
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import yaml

from kg_microbe_fleet import UniqueKeySafeLoader, parse_fleet_manifest

from .artifacts.scripts.check_vendored_sync import (
    CANONICAL_MANIFEST_PATH,
    Consumer,
    GovernanceError,
    GovernanceManifest,
    _run_git,
    parse_manifest,
)


@dataclass(frozen=True)
class AdmissionSpec:
    consumer: Consumer
    declaration: str
    snapshot: str
    admission_id: str


# Explicit reviewed identities, never discovered from a downstream pin or glob.
SPECS = (AdmissionSpec(
    Consumer("cofactormech", "CultureBotAI/CofactorMech", "src/cofactormech"),
    "src/kg_microbe_governance/releases/cofactormech-infrastructure-admission-v1.json",
    "src/kg_microbe_governance/releases/cofactormech-infrastructure-source-manifest.json",
    "cofactormech-post-cutoff-infrastructure-v1",
), AdmissionSpec(
    Consumer("assaymech", "CultureBotAI/AssayMech", "src/assaymech"),
    "src/kg_microbe_governance/releases/assaymech-infrastructure-admission-v1.json",
    "src/kg_microbe_governance/releases/assaymech-infrastructure-source-manifest.json",
    "assaymech-post-cutoff-infrastructure-v1",
), AdmissionSpec(
    Consumer("scaleupmech", "CultureBotAI/ScaleupMech", "src/scaleupmech"),
    "src/kg_microbe_governance/releases/scaleupmech-infrastructure-admission-v1.json",
    "src/kg_microbe_governance/releases/scaleupmech-infrastructure-source-manifest.json",
    "scaleupmech-post-cutoff-infrastructure-v1",
),)
FIELDS = frozenset({
    "version", "admission_id", "authority", "consumer", "source_ref",
    "source_manifest_sha256", "bootstrap_main_ref", "fleet_entry_sha256",
    "historical_declaration_sha256", "historical_manifest_sha256",
    "edge_declaration_sha256", "required_artifacts",
})


@dataclass(frozen=True)
class Admission:
    spec: AdmissionSpec
    policy: Mapping[str, Any]
    content: bytes
    source_content: bytes
    source: GovernanceManifest


def parse_policy(content: bytes, spec: AdmissionSpec) -> dict[str, Any]:
    from .infrastructure_admission import _json

    policy = _json(content)
    consumer = spec.consumer
    if (set(policy) != FIELDS or type(policy["version"]) is not int or policy["version"] != 1
            or policy["admission_id"] != spec.admission_id
            or policy["authority"] != "infrastructure_only"
            or policy["consumer"] != {"key": consumer.key, "github": consumer.github,
                                      "package_path": consumer.package_path}):
        raise GovernanceError("Additional admission must name its exact reviewed identity and fields")
    for key in FIELDS:
        if key.endswith("_sha256") or key.endswith("_ref"):
            width = 40 if key.endswith("_ref") else 64
            if not isinstance(policy[key], str) or not re.fullmatch(f"[0-9a-f]{{{width}}}", policy[key]):
                raise GovernanceError(f"Additional admission {key} must be an immutable digest")
    required = policy["required_artifacts"]
    if (not isinstance(required, list) or not all(isinstance(x, str) for x in required)
            or required != sorted(set(required))):
        raise GovernanceError("Additional admission requires an exact sorted artifact obligation")
    return policy


def compose(
    read: Callable[[str], bytes], fleet_content: bytes, current_content: bytes,
) -> tuple[dict[str, Any], GovernanceManifest, dict[str, Admission]]:
    """Validate the complete declared cohort before making any legacy projection."""
    from .cycle_release_audit import RELEASE_PATH, parse_release
    from .infrastructure_admission import (
        ADMISSION_PATH,
        ADMITTED_CAPABILITIES,
        ADMITTED_MANIFEST_PATH,
        HISTORICAL_MANIFEST_PATH,
        NATIVE_TESTS,
        canonical_sha,
        parse_admission,
        sha,
        validate_current_layout,
        validate_transition,
    )

    historical_policy = read(RELEASE_PATH)
    release = parse_release(historical_policy)
    historical_raw = read(HISTORICAL_MANIFEST_PATH)
    historical = parse_manifest(historical_raw)
    edge_content = read(ADMISSION_PATH)
    edge = parse_admission(edge_content)
    edge_raw = read(ADMITTED_MANIFEST_PATH)
    edge_source = parse_manifest(edge_raw)
    try:
        fleet_doc = yaml.load(fleet_content, Loader=UniqueKeySafeLoader)
        fleet = parse_fleet_manifest(fleet_doc, Path("fleet.yaml"))
    except (ValueError, yaml.YAMLError) as exc:
        raise GovernanceError(f"Invalid complete admission fleet: {exc}") from exc
    additions = {}
    for spec in SPECS:
        try:
            content = read(spec.declaration)
        except FileNotFoundError:
            continue
        policy = parse_policy(content, spec)
        source_content = read(spec.snapshot)
        source = parse_manifest(source_content)
        if (policy["historical_declaration_sha256"] != sha(historical_policy)
                or policy["historical_manifest_sha256"] != sha(historical_raw)
                or policy["edge_declaration_sha256"] != sha(edge_content)
                or policy["source_manifest_sha256"] != sha(source_content)):
            raise GovernanceError("Additional admission snapshot or predecessor digest differs")
        if policy["source_ref"] in {release["baseline_ref"], release["release_ref"], edge["source_ref"]}:
            raise GovernanceError("Additional admission cannot reuse another cohort's allowed pin")
        required = set(policy["required_artifacts"])
        universal = {a.artifact_id for a in historical.artifacts if not a.consumers}
        if required != universal or not NATIVE_TESTS <= required:
            raise GovernanceError("Native admission must retain every universal artifact and native test")
        additions[spec.consumer.key] = Admission(spec, policy, content, source_content, source)
    if len({a.policy["source_ref"] for a in additions.values()}) != len(additions):
        raise GovernanceError("Additional admissions require distinct explicit data pins")
    expected_identities = dict(edge_source.consumers)
    for key, admission in additions.items():
        if key in expected_identities:
            raise GovernanceError("Additional admission overlaps an existing consumer")
        expected_identities[key] = admission.spec.consumer
    actual = {key: Consumer(key, m.github, m.package_path) for key, m in fleet.mechs.items()}
    if actual != expected_identities:
        raise GovernanceError("Complete admission fleet differs from explicitly declared cohort")
    # Projection is safe only after exact full-set equality above. Existing
    # Edge validation remains strict and its own entry digest remains binding.
    old_fleet = {**fleet_doc, "mechs": {k: v for k, v in fleet_doc["mechs"].items()
                                       if k in edge_source.consumers}}
    admitted = validate_transition(edge, historical_policy, historical_raw, edge_raw,
                                   yaml.safe_dump(old_fleet).encode())
    for key, admission in additions.items():
        entry = fleet_doc["mechs"][key]
        admitted_entry = entry
        if (canonical_sha(admitted_entry) != admission.policy["fleet_entry_sha256"]
                and isinstance(entry.get("capabilities"), dict)
                and ADMITTED_CAPABILITIES < set(entry["capabilities"])):
            admitted_entry = {
                **entry,
                "capabilities": {
                    cap_key: cap_value for cap_key, cap_value in entry["capabilities"].items()
                    if cap_key in ADMITTED_CAPABILITIES
                },
            }
        if canonical_sha(admitted_entry) != admission.policy["fleet_entry_sha256"]:
            raise GovernanceError("Additional admission fleet entry digest differs")
        if (entry.get("vendored_role") != "consumer"
                or entry.get("serialization", {}).get("verified") is not False
                or entry.get("serialization", {}).get("options")
                or set(entry.get("capabilities", {})) != set(fleet.capability_names)):
            raise GovernanceError("Additional infrastructure admission must withhold native capabilities")
        for name, capability in entry["capabilities"].items():
            if name == "vendored_sync":
                if capability != {"status": "enabled"}:
                    raise GovernanceError("Additional admission requires exact vendored_sync obligation")
            elif (
                capability.get("status") not in {"disabled", "not_applicable"}
                or "settings" in capability
                or "reason_claims" in capability
            ):
                raise GovernanceError("Additional infrastructure admission cannot enable execution capabilities")
        source = admission.source
        minimum = set(historical.consumers) | {key}
        if not minimum <= set(source.consumers) <= set(expected_identities):
            raise GovernanceError("Additional source has an unknown or incomplete historical cohort")
        if any(consumer != expected_identities[k] for k, consumer in source.consumers.items()):
            raise GovernanceError("Additional source changes a consumer identity")
        if (source.canonical_repository, source.pin_path) != (admitted.canonical_repository, admitted.pin_path):
            raise GovernanceError("Additional source changes governance authority")
        prior_artifacts = {a.artifact_id: a for a in admitted.artifacts}
        if {a.artifact_id for a in source.artifacts} != set(prior_artifacts):
            raise GovernanceError("Additional source changes the artifact set")
        for artifact in source.artifacts:
            prior = prior_artifacts[artifact.artifact_id]
            if replace(artifact, sha256="", consumers=()) != replace(prior, sha256="", consumers=()):
                raise GovernanceError("Additional source changes artifact target, source or mode")
            for member in source.consumers:
                applies = (artifact.artifact_id in additions[member].policy["required_artifacts"]
                            if member in additions else prior.applies_to(member))
                if artifact.applies_to(member) != applies:
                    raise GovernanceError("Additional source changes declared artifact applicability")
    expected_doc = json.loads(edge_raw)
    for key, admission in additions.items():
        c = admission.spec.consumer
        expected_doc["consumers"][key] = {"github": c.github, "package_path": c.package_path}
    for artifact in expected_doc["artifacts"]:
        if artifact["consumers"] == "all":
            # Every newly declared native consumer owes each universal artifact.
            if any(artifact["id"] not in a.policy["required_artifacts"] for a in additions.values()):
                raise GovernanceError("Additional admission omits a universal artifact")
        else:
            artifact["consumers"] += [k for k, a in additions.items()
                                      if artifact["id"] in a.policy["required_artifacts"]]
    expected = parse_manifest(json.dumps(expected_doc).encode())
    validate_current_layout(expected, current_content)
    return edge, expected, additions


def immutable_anchor(root: Path, head: str, path: str, content: bytes) -> str:
    from .fleet_audit import _head_blob

    anchor = None
    for revision in _run_git(root, ("rev-list", "--first-parent", head)).splitlines():
        entry = _head_blob(root, revision, path)
        if entry == ("100644", content):
            anchor = revision
            continue
        if entry is not None:
            raise GovernanceError("Additional admission declaration was modified")
        if _run_git(root, ("log", "-1", "--format=%H", revision, "--", path)):
            raise GovernanceError("Additional admission declaration was deleted and reintroduced")
        break
    if anchor is None:
        raise GovernanceError("Additional admission has no immutable introduction")
    return anchor


def protected_additions(
    root: Path, head: str, protected: set[str], lane: str, additions: Mapping[str, Admission],
) -> dict[str, str]:
    from .cycle_release_audit import _ancestor

    anchors = {}
    for spec in SPECS:
        if spec.consumer.key not in additions:
            if _run_git(root, ("log", "-1", "--format=%H", head, "--", spec.declaration)):
                raise GovernanceError("Additional admission declaration was deleted")
            continue
        admission = additions[spec.consumer.key]
        anchor = immutable_anchor(root, head, spec.declaration, admission.content)
        if (anchor not in protected or anchor == lane or not _ancestor(root, lane, anchor)):
            raise GovernanceError("Additional admission is outside protected post-cutoff history")
        anchors[spec.consumer.key] = anchor
    return anchors


def bind_source(root: Path, admission: Admission) -> tuple[GovernanceManifest, dict[str, bytes]]:
    from .cycle_release_audit import _snapshot
    from .fleet_audit import _commit_at

    ref = admission.policy["source_ref"]
    if _commit_at(root, ref) != ref:
        raise GovernanceError("Additional source ref is not its exact declared commit")
    source, payloads, raw = _snapshot(root, ref)
    if raw != admission.source_content or source != admission.source:
        raise GovernanceError("Actual additional source differs from its sealed snapshot")
    return source, payloads


def bootstrap_pending(root: Path, admission: Admission, *, committed_only: bool = False) -> bool:
    from . import _require_clean_worktree, _validate_target_repository
    from .artifacts.scripts.check_vendored_sync import expand_target
    from .fleet_audit import _commit_at, _head_blob

    consumer, source = admission.spec.consumer, admission.source
    root = _validate_target_repository(root, consumer)
    main = _commit_at(root, "refs/remotes/origin/main")
    if main != admission.policy["bootstrap_main_ref"]:
        return False
    paths = [source.pin_path, *(expand_target(a, consumer) for a in source.artifacts_for(consumer))]
    if any(_head_blob(root, main, path) is not None for path in paths):
        raise GovernanceError("Additional bootstrap unexpectedly contains governed artifacts")
    if not committed_only:
        _require_clean_worktree(root)
        if _commit_at(root, "HEAD") != main:
            raise GovernanceError("Additional bootstrap checkout is not exact main")
        if any((root / p).exists() or (root / p).is_symlink() for p in paths):
            raise GovernanceError("Additional bootstrap worktree contains unverified governed artifacts")
    return True


def source_refs(root: Path) -> tuple[str, ...]:
    """Select only protected declarations; never fetch data or execute source code."""
    from . import _require_clean_worktree
    from .cycle_release_audit import FLEET_PATH
    from .fleet_audit import _commit_at
    from .infrastructure_admission import trusted_source_ref

    head, main_ref = _commit_at(root, "HEAD"), _commit_at(root, "refs/remotes/origin/main")
    edge_ref = trusted_source_ref(root)  # Also verifies all additional protected anchors.
    if edge_ref is None:
        return ()
    from .cycle_release_audit import _blob
    from .fleet_audit import _head_blob

    def committed(path: str) -> bytes:
        if _head_blob(root, head, path) is None:
            raise FileNotFoundError(path)
        return _blob(root, head, path)

    _, _, additions = compose(committed, committed(FLEET_PATH), committed(CANONICAL_MANIFEST_PATH))
    _require_clean_worktree(root)
    if (_commit_at(root, "HEAD"), _commit_at(root, "refs/remotes/origin/main")) != (head, main_ref):
        raise GovernanceError("Trusted history changed during additional data selection")
    return (edge_ref, *(str(a.policy["source_ref"]) for a in additions.values()))


def main() -> int:
    parser = argparse.ArgumentParser(description="Select protected immutable admission DATA refs")
    parser.add_argument("--trusted-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        for ref in source_refs(args.trusted_root):
            print(ref)
    except (GovernanceError, OSError, ValueError) as exc:
        parser.exit(2, f"Additional admission data preparation refused: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
