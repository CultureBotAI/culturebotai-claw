"""Explicit post-cutoff infrastructure admission; no historical rollout authority.

The reviewed declaration authorizes one data pin, including after a squash
merge. Only protected current code executes; no code from that pin is loaded.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml

from kg_microbe_fleet import UniqueKeySafeLoader, parse_fleet_manifest

from . import _require_clean_worktree, _validate_target_repository
from .artifacts.scripts.check_vendored_sync import (
    CANONICAL_MANIFEST_PATH,
    CANONICAL_REPOSITORY,
    Consumer,
    GovernanceError,
    GovernanceManifest,
    _reject_duplicate_pairs,
    _run_git,
    expand_target,
    parse_manifest,
)
from .fleet_audit import _commit_at, _head_blob

ADMISSION_PATH = "src/kg_microbe_governance/releases/edgemech-infrastructure-admission-v1.json"
HISTORICAL_MANIFEST_PATH = "src/kg_microbe_governance/releases/mech-cycle-v2-governance-manifest.json"
ADMISSION_ID = "edgemech-post-cutoff-infrastructure-v1"
ADMITTED = Consumer("edgemech", "CultureBotAI/EdgeMech", "src/edgemech")
NATIVE_TESTS = frozenset({
    "curation_timestamp_contract", "record_review_contract", "skill_frontmatter_contract",
})
_FIELDS = frozenset({
    "version", "admission_id", "historical_declaration_sha256", "historical_manifest_sha256",
    "source_ref", "source_manifest_sha256", "consumer", "bootstrap_main_ref",
    "fleet_entry_sha256", "excluded_native_tests", "authority",
})


def sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def canonical_sha(value: Any) -> str:
    return sha(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode())


def _json(content: bytes) -> dict[str, Any]:
    try:
        value = json.loads(content, object_pairs_hook=_reject_duplicate_pairs)
    except (ValueError, UnicodeError) as exc:
        raise GovernanceError(f"Invalid infrastructure admission JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise GovernanceError("Infrastructure admission JSON must be an object")
    return value


def parse_admission(content: bytes) -> dict[str, Any]:
    policy = _json(content)
    if set(policy) != _FIELDS or type(policy["version"]) is not int or policy["version"] != 1:
        raise GovernanceError("Infrastructure admission has unknown fields or version")
    if (policy["admission_id"] != ADMISSION_ID or policy["authority"] != "infrastructure_only"
            or policy["consumer"] != {"key": ADMITTED.key, "github": ADMITTED.github,
                                     "package_path": ADMITTED.package_path}):
        raise GovernanceError("Admission must name only the exact EdgeMech infrastructure identity")
    for key in ("historical_declaration_sha256", "historical_manifest_sha256",
                "source_manifest_sha256", "fleet_entry_sha256", "source_ref", "bootstrap_main_ref"):
        width = 40 if key.endswith("_ref") else 64
        if not isinstance(policy[key], str) or not re.fullmatch(f"[0-9a-f]{{{width}}}", policy[key]):
            raise GovernanceError(f"Admission {key} must be an immutable lowercase digest")
    excluded = policy["excluded_native_tests"]
    if not isinstance(excluded, list) or excluded != sorted(NATIVE_TESTS):
        raise GovernanceError("Admission must exclude exactly the three native-record tests")
    return policy


def validate_transition(
    policy: Mapping[str, Any], historical_policy: bytes, historical_manifest: bytes,
    current_manifest: bytes, fleet_content: bytes,
) -> GovernanceManifest:
    """Prove the only manifest delta is the declared infrastructure admission.

    This pure candidate check is not proof of approved protected history or an
    installed downstream consumer. Historical payload hashes/modes/targets and
    every old consumer's applicability remain exact.
    """
    parse_admission(json.dumps(dict(policy)).encode())
    if sha(historical_policy) != policy["historical_declaration_sha256"]:
        raise GovernanceError("Admission historical declaration hash differs")
    historical = _json(historical_policy)
    if policy["source_ref"] in {historical.get("baseline_ref"), historical.get("release_ref")}:
        raise GovernanceError("Infrastructure source pin cannot replace a historical cohort pin")
    if (sha(historical_manifest) != policy["historical_manifest_sha256"]
            or historical.get("manifest_sha256") != policy["historical_manifest_sha256"]):
        raise GovernanceError("Admission historical manifest hash differs")
    if sha(current_manifest) != policy["source_manifest_sha256"]:
        raise GovernanceError("Admission source manifest hash differs")
    old, new = parse_manifest(historical_manifest), parse_manifest(current_manifest)
    old_doc, new_doc = _json(historical_manifest), _json(current_manifest)
    expected_consumers = {**old_doc["consumers"], ADMITTED.key: {
        "github": ADMITTED.github, "package_path": ADMITTED.package_path,
    }}
    if ADMITTED.key in old.consumers or new_doc["consumers"] != expected_consumers:
        raise GovernanceError("Admission may add only EdgeMech and cannot change historical identities")
    for field in ("version", "canonical_repository", "pin_path"):
        if old_doc[field] != new_doc[field]:
            raise GovernanceError("Admission changed historical governance authority")
    expected = {item["id"]: item for item in old_doc["artifacts"]}
    actual = {item["id"]: item for item in new_doc["artifacts"]}
    if set(expected) != set(actual) or not NATIVE_TESTS <= set(expected):
        raise GovernanceError("Admission changed the historical artifact set")
    for identifier, prior in expected.items():
        admitted = actual[identifier]
        if identifier in NATIVE_TESTS:
            if prior["consumers"] != "all":
                raise GovernanceError("Native exclusion must retain the original complete cohort")
            scope = admitted.get("consumers")
            if not isinstance(scope, list) or sorted(scope) != sorted(old.consumers):
                raise GovernanceError("Native exclusion must retain every historical consumer")
            admitted = {**admitted, "consumers": "all"}
        if admitted != prior:
            raise GovernanceError(f"Admission changed historical artifact bytes, mode, target or scope: {identifier}")
    try:
        fleet_doc = yaml.load(fleet_content, Loader=UniqueKeySafeLoader)
        fleet = parse_fleet_manifest(fleet_doc, Path("fleet.yaml"))
    except (ValueError, yaml.YAMLError) as exc:
        raise GovernanceError(f"Invalid admission fleet: {exc}") from exc
    if {key: (m.github, m.package_path) for key, m in fleet.mechs.items()} != {
        key: (c.github, c.package_path) for key, c in new.consumers.items()
    }:
        raise GovernanceError("Admission fleet identities differ from governance")
    entry = fleet_doc["mechs"][ADMITTED.key]
    if canonical_sha(entry) != policy["fleet_entry_sha256"]:
        raise GovernanceError("Admission fleet entry hash differs")
    if (entry.get("vendored_role") != "consumer"
            or entry.get("serialization", {}).get("verified") is not False
            or set(entry.get("capabilities", {})) != set(fleet.capability_names)):
        raise GovernanceError("Infrastructure admission must explicitly withhold native capabilities")
    for key, capability in entry["capabilities"].items():
        if key == "vendored_sync":
            if capability != {"status": "enabled"}:
                raise GovernanceError("Infrastructure admission requires exact vendored_sync capability")
        elif capability.get("status") not in {"disabled", "not_applicable"}:
            raise GovernanceError("Infrastructure admission cannot enable scientific or execution capabilities")
    return new


def validate_packaged_transition(root: Path) -> dict[str, Any]:
    """Validate candidate/package bytes, without asserting protected activation."""
    from .cycle_release_audit import FLEET_PATH, RELEASE_PATH, parse_release

    historical = (root / RELEASE_PATH).read_bytes()
    release = parse_release(historical)
    for path, digest in release["workflow_assets"].items():
        if sha((root / path).read_bytes()) != digest:
            raise GovernanceError("Admission changed a frozen release workflow asset")
    policy = parse_admission((root / ADMISSION_PATH).read_bytes())
    validate_transition(policy, historical, (root / HISTORICAL_MANIFEST_PATH).read_bytes(),
                        (root / CANONICAL_MANIFEST_PATH).read_bytes(), (root / FLEET_PATH).read_bytes())
    return policy


def admission_anchor(root: Path, head: str, content: bytes) -> str:
    """Require an immutable first-parent introduction, including no resurrection."""
    anchor = None
    for revision in _run_git(root, ("rev-list", "--first-parent", head)).splitlines():
        entry = _head_blob(root, revision, ADMISSION_PATH)
        if entry == ("100644", content):
            anchor = revision
            continue
        if entry is not None:
            raise GovernanceError("Infrastructure admission declaration was modified")
        if _run_git(root, ("log", "-1", "--format=%H", revision, "--", ADMISSION_PATH)):
            raise GovernanceError("Infrastructure admission declaration was deleted and reintroduced")
        break
    if anchor is None:
        raise GovernanceError("Trusted HEAD has no infrastructure admission introduction")
    return anchor


def bind_source_snapshot(
    root: Path, source_ref: str, current_manifest: bytes, current_payloads: Mapping[str, bytes],
) -> tuple[GovernanceManifest, dict[str, bytes]]:
    """Authenticate actual immutable source objects before creating any URL binding."""
    from .cycle_release_audit import _snapshot

    if _commit_at(root, source_ref) != source_ref:
        raise GovernanceError("Infrastructure data ref is not the exact declared commit")
    source, payloads, raw = _snapshot(root, source_ref)
    if raw != current_manifest or payloads != dict(current_payloads):
        raise GovernanceError("Actual infrastructure source snapshot differs from the admitted bytes")
    return source, payloads


def trusted_source_ref(root: Path) -> str | None:
    """Select one protected declaration's data ref; perform no network or Git writes."""
    from .cycle_release_audit import (
        FLEET_PATH,
        RELEASE_PATH,
        _ancestor,
        _blob,
        parse_release,
        release_anchor,
    )

    root = _validate_target_repository(root, Consumer("claw", CANONICAL_REPOSITORY, "src/kg_microbe_governance"))
    _require_clean_worktree(root)
    head = _commit_at(root, "HEAD")
    main = _commit_at(root, "refs/remotes/origin/main")
    protected = set(_run_git(root, ("rev-list", "--first-parent", main)).splitlines())
    if head not in protected:
        raise GovernanceError("Data preparation requires a protected trusted HEAD")
    if _head_blob(root, head, ADMISSION_PATH) is None:
        if _run_git(root, ("log", "-1", "--format=%H", head, "--", ADMISSION_PATH)):
            raise GovernanceError("Infrastructure admission declaration was deleted")
        return None
    content = _blob(root, head, ADMISSION_PATH)
    policy = parse_admission(content)
    anchor = admission_anchor(root, head, content)
    historical = _blob(root, head, RELEASE_PATH)
    release = parse_release(historical)
    lane = release_anchor(root, head, historical)
    if (anchor not in protected or lane not in protected or anchor == lane
            or not _ancestor(root, lane, anchor)):
        raise GovernanceError("Data preparation requires protected post-cutoff admission")
    if release["release_ref"] not in protected:
        raise GovernanceError("Data preparation requires the protected historical release")
    baseline = _blob(root, release["release_ref"], CANONICAL_MANIFEST_PATH)
    if _blob(root, head, HISTORICAL_MANIFEST_PATH) != baseline:
        raise GovernanceError("Data preparation historical snapshot differs")
    validate_transition(policy, historical, baseline, _blob(root, head, CANONICAL_MANIFEST_PATH),
                        _blob(root, head, FLEET_PATH))
    _require_clean_worktree(root)
    if _commit_at(root, "HEAD") != head or _commit_at(root, "refs/remotes/origin/main") != main:
        raise GovernanceError("Trusted history changed during data preparation")
    return str(policy["source_ref"])


def bootstrap_pending(
    root: Path, consumer: Consumer, manifest: GovernanceManifest, policy: Mapping[str, Any],
    *, committed_only: bool = False,
) -> bool:
    """Recognize only the exact empty bootstrap; never certify installed payloads.

    Candidate completeness uses origin/main trees in no-checkout clones. The
    trusted runtime additionally requires a clean checkout at that same tip.
    A changed tip returns false and must undergo normal complete verification.
    """
    if consumer != ADMITTED:
        return False
    root = _validate_target_repository(root, consumer)
    main = _commit_at(root, "refs/remotes/origin/main")
    if main != policy["bootstrap_main_ref"]:
        return False
    paths = [manifest.pin_path, *(expand_target(a, consumer) for a in manifest.artifacts_for(consumer))]
    if any(_head_blob(root, main, path) is not None for path in paths):
        raise GovernanceError("Bootstrap main unexpectedly contains governed artifacts")
    if not committed_only:
        _require_clean_worktree(root)
        if _commit_at(root, "HEAD") != main:
            raise GovernanceError("Bootstrap checkout is not the exact main tip")
        for relative in paths:
            path = root / relative
            if path.exists() or path.is_symlink():
                raise GovernanceError("Bootstrap worktree has an unverified governed artifact")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Select the single protected infrastructure DATA ref; never fetch or execute it")
    parser.add_argument("--trusted-root", type=Path, required=True)
    args = parser.parse_args()
    try:
        ref = trusted_source_ref(args.trusted_root)
    except (GovernanceError, OSError, ValueError) as exc:
        parser.exit(2, f"Infrastructure data preparation refused: {exc}\n")
    if ref is not None:
        print(ref)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
