"""Prepare one isolated EdgeMech coordinator from pinned PR metadata.

Purpose/date/issue: parameterized successor to the private 2026-11-20 restart
bootstrap, CultureBotAI/EdgeMech#228. Inputs: explicit CLAW root, selected/prior
PR JSON, request, fresh destination/receipt and branch. Output: one isolated
clone plus a private actual checkout receipt. Requires config validation and
explicit --apply; uses RepositorySettings and a short EdgeMech lock. It does not
launch a worker, answer prompts, merge, or change the canonical checkout.
Historical source and receipts remain private; see README.md and PROVENANCE.json.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from plugins.lock_manager import LockManager  # noqa: E402
from plugins.repository_settings import (  # noqa: E402
    RepositorySettings,
    RepositoryTarget,
    merged_repository_environment,
)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def run(args: list[str], cwd: Path | None = None) -> str:
    return subprocess.run(args, cwd=cwd, capture_output=True, text=True,
                          check=True, timeout=180).stdout


def selection(path: Path) -> dict:
    value = json.loads(path.read_bytes())
    require(isinstance(value, dict) and re.fullmatch(r"[0-9a-f]{40}", value.get("headRefOid", "")) is not None,
            "Full selected commit required")
    require(isinstance(value.get("headRefName"), str) and bool(value["headRefName"]), "Selected branch required")
    return value


def validate_delta(selected: dict, fetched: str, changed: list[str]) -> None:
    require(fetched == selected["headRefOid"], "Fetched branch no longer matches selected commit")
    require(all(name.endswith(".md") for name in changed), "Selected delta is not documentation-only")


def prepare(*, claw_root: Path, selection_file: Path, prior_selection_file: Path,
            request: Path, destination: Path, branch: str, receipt: Path,
            apply: bool = False) -> dict:
    require(apply, "Explicit --apply required")
    require(all(path.is_absolute() for path in (claw_root, request, destination, receipt)),
            "Absolute roots/request/receipt required")
    require(request.is_file(), "Campaign request required")
    require(not os.path.lexists(destination) and not os.path.lexists(receipt),
            "Fresh destination and receipt required")
    require(branch not in ("main", "master"), "Feature branch required")
    run(["git", "check-ref-format", "--branch", branch])
    input_paths = {"request": request, "selection": selection_file, "prior_selection": prior_selection_file}
    input_bytes = {name: path.read_bytes() for name, path in input_paths.items()}
    selected, prior = selection(selection_file), selection(prior_selection_file)
    run([sys.executable, "-m", "cli.main", "config", "validate"], cwd=claw_root)
    environment = merged_repository_environment(claw_root / ".env")
    workspace = Path(environment.get("OPENCLAW_WORKSPACE", ""))
    require(workspace.is_absolute(), "Shared absolute OPENCLAW_WORKSPACE required")
    settings = RepositorySettings.from_environment(environ=environment)
    target = settings.get_target("edgemech")
    with LockManager({"locks_dir": str(workspace / "locks")}).lock(
        "edgemech", "create_native_restart_coordinator"
    ):
        repo = target.open()
        require(not repo.is_dirty(untracked_files=True), "Canonical checkout has local changes")
        require(not os.path.lexists(destination) and not os.path.lexists(receipt),
                "Destination or receipt appeared before lease")
        require(all(path.read_bytes() == input_bytes[name] for name, path in input_paths.items()),
                "Selected inputs changed before clone")
        canonical_head = repo.head.commit.hexsha
        run(["git", "clone", "--shared", "--no-checkout", str(target.path), str(destination)])
        origin = "https://github.com/" + target.expected_repository + ".git"
        run(["git", "remote", "set-url", "origin", origin], destination)
        run(["git", "fetch", "origin", "refs/heads/" + selected["headRefName"]], destination)
        fetched = run(["git", "rev-parse", "FETCH_HEAD"], destination).strip()
        require(fetched == selected["headRefOid"], "Fetched branch no longer matches selected commit")
        run(["git", "checkout", "-b", branch, fetched], destination)
        changed = run(["git", "diff", "--name-only", prior["headRefOid"], fetched], destination).splitlines()
        validate_delta(selected, fetched, changed)
        require(not run(["git", "status", "--porcelain=v1"], destination), "Isolated clone is dirty")
        RepositoryTarget("edgemech", destination, target.expected_repository).open()
        require(all(path.read_bytes() == input_bytes[name] for name, path in input_paths.items()),
                "Selected inputs changed during clone")
        record = {
            "at": datetime.now(timezone.utc).isoformat(), "request": str(request),
            "helper_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "inputs": {name: {"path": str(input_paths[name]), "sha256": hashlib.sha256(raw).hexdigest()}
                       for name, raw in input_bytes.items()},
            "checkout": str(destination), "branch": branch, "head": fetched,
            "code_base": prior["headRefOid"], "changed_from_code_base": changed,
            "canonical_root": str(target.path), "canonical_head": canonical_head,
            "origin": origin, "scope": "isolated coordinator clone; no canonical changes; no merge",
        }
        with receipt.open("x") as stream:
            json.dump(record, stream, indent=2)
            stream.write("\n")
    return record


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("claw-root", "selection-file", "prior-selection-file", "request", "destination", "receipt"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--branch", required=True)
    parser.add_argument("--apply", action="store_true")
    print(json.dumps(prepare(**vars(parser.parse_args())), indent=2))


if __name__ == "__main__":
    main()
