"""Private read-only projection of saved supervisor durability observations.

This does not extend the public history/snapshot schema or scan a host. Public
progress remains independently validated; operators opt into one known local
supervisor runtime to inspect its explicit ownership inventory.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from kg_microbe_fleet import FleetManifest
from kg_microbe_workflows.session_durability import public_summary

from . import ProgressError, read_json


def read_durability(runtime: Path, manifest: FleetManifest, now: datetime) -> list[dict[str, Any]]:
    if now.utcoffset() is None:
        raise ProgressError("durability observation time requires a timezone")
    root = runtime.absolute()
    if root.resolve() != root or not root.is_dir():
        raise ProgressError("durability runtime must be an existing directory without symlink aliases")
    config = read_json(root / "config.json")
    if not isinstance(config.get("run_id"), str) or not config["run_id"]:
        raise ProgressError("durability runtime has no run identity")
    targets = config.get("targets")
    if not isinstance(targets, list) or not targets or len(targets) > len(manifest.mechs):
        raise ProgressError("durability runtime has invalid targets")
    rows, seen = [], set()
    for target in targets:
        if not isinstance(target, dict):
            raise ProgressError("durability target is malformed")
        key = target.get("repository_key")
        if not isinstance(key, str) or key not in manifest.mechs or key in seen:
            raise ProgressError("durability target is unknown or duplicated")
        seen.add(key)
        if target.get("github_repository") != manifest.mechs[key].github:
            raise ProgressError("durability target GitHub identity differs from the pinned fleet")
        directory = root / key
        if directory.resolve() != directory:
            raise ProgressError("durability repository directory is a symlink")
        path = directory / "status.json"
        row: dict[str, Any]
        try:
            path.lstat()
        except FileNotFoundError:
            row = {"repository_key": key, "status": "unknown", "alert": True, "reason": "not_observed",
                   "unpushed_commits": None, "at_risk_files": None, "overdue_files": None}
        else:
            status = read_json(path)
            if status.get("run_id") != config["run_id"] or status.get("repository_key") != key:
                raise ProgressError("durability status belongs to another run or repository")
            observation = status.get("session_durability")
            if observation is None:
                row = {"repository_key": key, "status": "unknown", "alert": True, "reason": "not_collected",
                       "unpushed_commits": None, "at_risk_files": None, "overdue_files": None}
            else:
                row = {"repository_key": key, **public_summary(observation)}
                age = (now - datetime.fromisoformat(row["observed_at"])).total_seconds()
                if age > 900 or age < -60:
                    row.update(status="unknown", alert=True, complete=False,
                               reason="stale" if age > 900 else "future_timestamp")
        rows.append(row)
    return rows


def format_durability(row: dict[str, Any]) -> str:
    def count(field: str) -> str:
        return "unknown" if row[field] is None else str(row[field])
    reason = f" ({row['reason']})" if row.get("reason") else ""
    return (f"Local durability {row['repository_key']}: {row['status']}{reason}; "
            f"unpushed commits={count('unpushed_commits')}, "
            f"at-risk files={count('at_risk_files')}, overdue files={count('overdue_files')}")
