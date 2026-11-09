#!/usr/bin/env python3
"""Run one no-op consumer sync/audit canary for CLAW #960, 2026-11-07.

Inputs: reviewed policy and explicit clean Edge feature worktree under root's
existing edit lease. Output: new receipt outside the consumer, never replaced.
Dry-run first, then --apply; refuses any proposed payload change. No merges,
scientific records or protected-admission claims. Public GitHub pin verification
uses the canonical sync API; no provider or credential-bearing call is made.
"""

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from kg_microbe_governance import plan_sync, sync_repository
from kg_microbe_governance.artifacts.scripts.check_vendored_sync import (
    check_repository,
    expand_target,
    raw_url,
)
from kg_microbe_governance.cycle_release_audit import _snapshot
from kg_microbe_governance.fleet_audit import _head_blob
from kg_microbe_governance.infrastructure_admission import (
    ADMISSION_PATH,
    ADMITTED,
    sha,
    validate_packaged_transition,
)
from plugins.repository_settings import RepositorySettings, RepositoryTarget

ROOT = Path(__file__).resolve().parents[2]


def receipt_path(path: Path, consumer_root: Path) -> Path:
    """Require a new literal output outside the consumer, through no symlinks."""
    if ".." in path.parts:
        raise ValueError("Receipt path traversal is not allowed")
    path = path.absolute()
    for component in (*reversed(path.parents), path):
        if component.is_symlink():
            raise ValueError("Receipt path must not contain a symlink")
    if path.is_relative_to(consumer_root) or path.exists():
        raise ValueError("Use a new receipt path outside the Edge checkout")
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--edge-root", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    claw = RepositoryTarget("claw", ROOT, "CultureBotAI/culturebotai-claw").open()
    if claw.active_branch.name != "feat/edgemech-milestones-766-767-20261107":
        raise ValueError("Unexpected CLAW candidate branch")
    policy = validate_packaged_transition(ROOT)
    target = RepositorySettings.from_environment(environ={"EDGEMECH_ROOT": str(args.edge_root)}).get_target("edgemech")
    repo = target.open()
    root = Path(repo.working_tree_dir).resolve()
    if root != args.edge_root.resolve() or repo.active_branch.name != "feat/storage-adapters-766-767-20261107":
        raise ValueError("Unexpected EdgeMech feature worktree")
    if repo.is_dirty(untracked_files=True):
        raise ValueError("Consumer must be clean before the canary")
    receipt = receipt_path(args.receipt, root)
    source_ref = policy["source_ref"]
    plan = plan_sync(ADMITTED.key, root, source_ref)
    if plan:
        raise ValueError("This reviewed canary must be a no-op; proposed payload changes require review")
    if args.apply and sync_repository(ADMITTED.key, root, source_ref, apply=True):
        raise ValueError("The expected no-op sync unexpectedly changed artifacts")
    manifest, payloads, raw = _snapshot(ROOT, source_ref)
    if sha(raw) != policy["source_manifest_sha256"]:
        raise ValueError("Actual source commit differs from the approved data snapshot")
    canonical = {raw_url(source_ref, path): payload for path, payload in payloads.items()}

    def fetch(url):
        if url not in canonical:
            raise ValueError("Checker requested data outside the reviewed source snapshot")
        return canonical[url]

    checked, problems = check_repository(root, ADMITTED.github, fetch=fetch)
    artifacts = manifest.artifacts_for(ADMITTED)
    if problems or checked != len(artifacts):
        raise ValueError(f"Native checker did not verify every applicable payload: {problems}")
    head = repo.head.commit.hexsha
    for artifact in artifacts:
        expected = ("100755" if artifact.mode & 0o100 else "100644", payloads[artifact.source])
        if _head_blob(root, head, expand_target(artifact, ADMITTED)) != expected:
            raise ValueError("Committed consumer bytes or modes differ from the approved source")
    if _head_blob(root, head, manifest.pin_path) != ("100644", (source_ref + "\n").encode()):
        raise ValueError("Committed consumer data pin differs")
    if repo.is_dirty(untracked_files=True) or repo.head.commit.hexsha != head:
        raise ValueError("Consumer changed during verification")
    result = {
        "format": "edgemech-infrastructure-admission-canary/v1",
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "mode": "noop_sync_and_audit" if args.apply else "dry_run_and_audit",
        "claw_candidate_head": claw.head.commit.hexsha, "consumer_feature_head": head,
        "source_ref": source_ref, "source_manifest_sha256": sha(raw),
        "admission_sha256": sha((ROOT / ADMISSION_PATH).read_bytes()),
        "helper_sha256": sha(Path(__file__).read_bytes()),
        "planned_changes": 0, "applied_changes": 0, "checked_artifacts": checked,
        "committed_artifacts": len(artifacts), "committed_pin_verified": True,
        "consumer_clean": True, "trusted_admission_active": False,
        "scientific_capabilities_enabled": False,
    }
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt_path(receipt, root)
    with receipt.open("x") as handle:
        json.dump(result, handle, sort_keys=True, indent=2)
        handle.write("\n")
    if json.loads(receipt.read_bytes()) != result:
        raise ValueError("Persisted receipt differs")
    print(json.dumps({"receipt": str(receipt), "sha256": sha(receipt.read_bytes()), **result}, sort_keys=True))


if __name__ == "__main__":
    main()
