"""Apply one reviewed three-file supervisor metadata plan; never control agents.

Private paths, identities and replacement bytes are supplied in a hash-bound plan.
The default is read-only. See the adjacent provenance document before live use.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path

from plugins.lock_manager import LockManager
from plugins.repository_settings import RepositoryTarget, merged_repository_environment

NAMES = {"ACK.md", "progress.json", "edgemech_restart_20261120.yaml"}
LIMIT = 2 * 1024 * 1024


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def regular(path: Path) -> bytes:
    """Refuse aliases, symlinks, FIFOs and unexpectedly large metadata inputs."""
    if not path.is_absolute() or path.resolve(strict=True) != path:
        raise ValueError(f"path must be absolute and contain no symlinks: {path}")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
            raise ValueError(f"not a regular file: {path}")
        value = stream.read(LIMIT + 1)
    if len(value) > LIMIT:
        raise ValueError(f"metadata exceeds size limit: {path}")
    return value


def exclusive(path: Path, data: bytes, mode: int = 0o600) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    if regular(path) != data:
        raise ValueError(f"write readback differs: {path}")


def sync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def receipt(path: Path, value: dict) -> None:
    exclusive(path, (json.dumps(value, indent=2) + "\n").encode())
    sync_dir(path.parent)


def prepare(claw: Path, campaign: Path, plan_path: Path, expected_plan: str):
    for root in (claw, campaign):
        if not root.is_absolute() or root.resolve(strict=True) != root or not root.is_dir():
            raise ValueError("roots must be real absolute directories")
    plan_bytes = regular(plan_path)
    if digest(plan_bytes) != expected_plan:
        raise ValueError("reviewed plan hash differs")
    plan = json.loads(plan_bytes)
    if plan.get("version") != 1 or set(plan.get("files", {})) != NAMES:
        raise ValueError("plan must name exactly the three supervisor files")
    run = plan.get("run_id", "")
    if not re.fullmatch(r"\d{8}T\d{6}Z", run):
        raise ValueError("invalid checkpoint run id")
    targets = {
        "ACK.md": campaign / "ACK.md",
        "progress.json": campaign / "progress.json",
        "edgemech_restart_20261120.yaml": claw / "workspace/tasks/edgemech_restart_20261120.yaml",
    }
    prepared = {}
    for name, target in targets.items():
        row = plan["files"][name]
        if row.get("target") != str(target):
            raise ValueError("target differs from the fixed supervisor allowlist")
        before = regular(target)
        candidate = regular(Path(row["candidate"]))
        if digest(before) != row["before_sha256"]:
            raise ValueError(f"beforeimage changed: {name}")
        if digest(candidate) != row["candidate_sha256"]:
            raise ValueError(f"candidate changed: {name}")
        if name != "ACK.md":
            value = json.loads(candidate)
            if not isinstance(value, dict):
                raise ValueError("metadata must be a JSON object")
            if name.endswith(".yaml") and value.get("task_id") != "edgemech_restart_20261120":
                raise ValueError("wrong task registry identity")
        elif not candidate.strip():
            raise ValueError("empty acknowledgement")
        prepared[name] = (target, before, candidate, stat.S_IMODE(target.stat().st_mode))
    return plan, plan_bytes, prepared


def apply_plan(claw: Path, campaign: Path, plan_path: Path, expected_plan: str,
               *, apply: bool = False) -> dict:
    RepositoryTarget("claw", claw, "CultureBotAI/culturebotai-claw").open()
    plan, plan_bytes, prepared = prepare(claw, campaign, plan_path, expected_plan)
    snapshot = campaign / "supervisor-checkpoints" / plan["run_id"]
    if snapshot.exists() or snapshot.is_symlink():
        raise FileExistsError(f"checkpoint already exists: {snapshot}")
    result = {"mode": "dry_run", "plan_sha256": expected_plan,
              "checkpoint": str(snapshot), "files": sorted(prepared)}
    if not apply:
        return result
    env = merged_repository_environment(claw / ".env")
    workspace = Path(env["OPENCLAW_WORKSPACE"])
    if not workspace.is_absolute() or workspace.resolve(strict=True) != workspace:
        raise ValueError("explicit real OPENCLAW_WORKSPACE required")
    with LockManager({"locks_dir": str(workspace / "locks")}).lock(
        "claw", "edgemech-supervisor-metadata", timeout=60
    ):
        RepositoryTarget("claw", claw, "CultureBotAI/culturebotai-claw").open()
        plan, plan_bytes, prepared = prepare(claw, campaign, plan_path, expected_plan)
        snapshot.parent.mkdir(mode=0o700, exist_ok=True)
        if snapshot.parent.resolve(strict=True) != snapshot.parent:
            raise ValueError("checkpoint parent must not be a symlink")
        snapshot.mkdir(mode=0o700)
        (snapshot / "before").mkdir(mode=0o700)
        (snapshot / "candidate").mkdir(mode=0o700)
        exclusive(snapshot / "plan.json", plan_bytes)
        for name, (_, before, candidate, _) in prepared.items():
            exclusive(snapshot / "before" / name, before)
            exclusive(snapshot / "candidate" / name, candidate)
        sync_dir(snapshot / "before")
        sync_dir(snapshot / "candidate")
        receipt(snapshot / "INTENT.json", result)
        staged = {}
        changed = []
        try:
            for name, (target, _, candidate, mode) in prepared.items():
                stage = target.with_name(f".{target.name}.{plan['run_id']}.pending")
                exclusive(stage, candidate, mode)
                staged[name] = stage
            for name, (target, before, candidate, _) in prepared.items():
                if regular(target) != before:
                    raise ValueError(f"target changed before replacement: {name}")
                if regular(staged[name]) != candidate:
                    raise ValueError(f"staged bytes changed: {name}")
                os.replace(staged[name], target)
                changed.append(name)
                sync_dir(target.parent)
                if regular(target) != candidate:
                    raise ValueError(f"target readback differs: {name}")
            result.update(mode="applied", replaced=changed,
                          completed_at=datetime.now(timezone.utc).isoformat())
            receipt(snapshot / "APPLIED.json", result)
        except BaseException as error:
            receipt(snapshot / "FAILED.json", {
                **result, "mode": "failed", "replaced": changed,
                "error": str(error), "pending_stages": {k: str(v) for k, v in staged.items()},
                "recovery": "Retained before/candidate bytes; no automatic rollback or action retry.",
            })
            raise
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claw-root", type=Path, required=True)
    parser.add_argument("--campaign-root", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--plan-sha256", required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(apply_plan(args.claw_root, args.campaign_root, args.plan,
                               args.plan_sha256, apply=args.apply)))


if __name__ == "__main__":
    main()
