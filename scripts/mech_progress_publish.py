#!/usr/bin/env python3
"""Publish only validated public progress documents to a dedicated Git data branch.

Runtime ledgers are read-only inputs. The data branch contains no executable code.
Git ref updates are fast-forward only; local history survives failed uploads.
"""
from __future__ import annotations

import argparse
import base64
import fcntl
import json
import os
from pathlib import Path
import signal
import stat
import subprocess
import tempfile
import time
from typing import Any

from kg_microbe_progress import collect_progress, validate_extension, validate_history, validate_bundle
from kg_microbe_progress import read_json as read_progress_json
from kg_microbe_progress.prs import gather_associations, fetch_pr_observations

REPOSITORY = "CultureBotAI/culturebotai-claw"
BRANCH = "mech-progress-data"
MAX_DOCUMENT_BYTES = 8_000_000


class PublishError(ValueError):
    """A publication could not be proven safe and complete."""


def gh(path: str, *, method: str = "GET", payload: dict | None = None) -> Any:
    args = ["gh", "api", "--method", method, path]
    body = None
    if payload is not None:
        args += ["--input", "-"]
        body = json.dumps(payload)
    result = subprocess.run(args, input=body, text=True, capture_output=True, timeout=90, check=False)
    if result.returncode:
        if method == "GET" and "(HTTP 404)" in result.stderr:
            return None
        # Do not publish API responses or stderr: they may contain private diagnostics.
        raise PublishError(f"GitHub {method} request failed (exit {result.returncode})")
    return json.loads(result.stdout) if result.stdout.strip() else None


def encode(value: dict) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise PublishError("Refusing a symlink state destination")
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encode(value)); stream.flush(); os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path: Path) -> dict:
    # One bounded nonblocking descriptor read rejects symlinks, FIFOs, devices,
    # duplicate keys and non-finite JSON before any state can be trusted.
    return read_progress_json(path)


def read_remote(api=gh) -> tuple[str | None, dict | None]:
    ref = api(f"repos/{REPOSITORY}/git/ref/heads/{BRANCH}")
    if ref is None:
        return None, None
    head = ref["object"]["sha"]
    commit = api(f"repos/{REPOSITORY}/git/commits/{head}")
    tree = api(f"repos/{REPOSITORY}/git/trees/{commit['tree']['sha']}")
    if tree.get("truncated"):
        raise PublishError("Truncated data branch tree")
    entries = {entry["path"]: entry for entry in tree["tree"]}
    if set(entries) != {"history.json", "progress.json"}:
        raise PublishError("Data branch contains unexpected files")
    documents = {}
    for name, entry in entries.items():
        if entry["type"] != "blob" or entry["mode"] != "100644" or entry.get("size", 0) > MAX_DOCUMENT_BYTES:
            raise PublishError("Invalid data branch entry")
        blob = api(f"repos/{REPOSITORY}/git/blobs/{entry['sha']}")
        if blob.get("encoding") != "base64" or blob.get("size", 0) > MAX_DOCUMENT_BYTES:
            raise PublishError("Invalid public data blob")
        raw = base64.b64decode(blob["content"], validate=False)
        if len(raw) > MAX_DOCUMENT_BYTES:
            raise PublishError("Public data blob is too large")
        documents[name] = json.loads(raw)
    history, snapshot = documents["history.json"], documents["progress.json"]
    validate_bundle(history, snapshot)
    return head, {"history": history, "snapshot": snapshot}


def newest_history(local: dict | None, remote: dict | None) -> dict | None:
    if local is None:
        return remote
    validate_history(local)
    if remote is None:
        return local
    validate_history(remote)
    try:
        validate_extension(remote, local)
        return local
    except ValueError:
        try:
            validate_extension(local, remote)
            return remote
        except ValueError as error:
            raise PublishError("Local and remote histories diverged; reconcile explicitly") from error


def publish(bundle: dict, previous_head: str | None, previous: dict | None, *, initialize=False, api=gh) -> str:
    history, snapshot = bundle["history"], bundle["snapshot"]
    validate_bundle(history, snapshot)
    if previous:
        validate_extension(previous["history"], history)
    if previous_head is None and not initialize:
        raise PublishError("Data branch is absent; initial publication requires --initialize")
    if previous == bundle and previous_head:
        return previous_head
    entries = []
    for name, document in (("history.json", history), ("progress.json", snapshot)):
        content = encode(document)
        if len(content) > MAX_DOCUMENT_BYTES:
            raise PublishError("Public document exceeds publication limit")
        blob = api(f"repos/{REPOSITORY}/git/blobs", method="POST", payload={
            "content": content.decode(), "encoding": "utf-8"})
        entries.append({"path": name, "mode": "100644", "type": "blob", "sha": blob["sha"]})
    tree = api(f"repos/{REPOSITORY}/git/trees", method="POST", payload={"tree": entries})
    commit = api(f"repos/{REPOSITORY}/git/commits", method="POST", payload={
        "message": "Update verified Mech progress snapshot", "tree": tree["sha"],
        "parents": [previous_head] if previous_head else []})
    head = commit["sha"]
    if previous_head:
        api(f"repos/{REPOSITORY}/git/refs/heads/{BRANCH}", method="PATCH", payload={"sha": head, "force": False})
    else:
        api(f"repos/{REPOSITORY}/git/refs", method="POST", payload={"ref": f"refs/heads/{BRANCH}", "sha": head})
    # If dispatch fails the committed data remains intact and scheduled Pages runs recover it.
    api(f"repos/{REPOSITORY}/dispatches", method="POST", payload={"event_type": "mech_progress_updated"})
    return head


def collect_once(runtime_dirs: list[Path], state_dir: Path, *, apply=False, initialize=False, api=gh) -> dict:
    state_dir.mkdir(parents=True, exist_ok=True)
    lock_path = state_dir / "publisher.lock"
    fd = os.open(lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    with os.fdopen(fd, "w") as lock:
        if not stat.S_ISREG(os.fstat(lock.fileno()).st_mode):
            raise PublishError("Publisher lock must be a regular file")
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        local_path = state_dir / "bundle.json"
        local = read_json(local_path) if local_path.exists() else None
        head, remote = read_remote(api) if apply else (None, None)
        prior = newest_history(local["history"] if local else None, remote["history"] if remote else None)
        associations = gather_associations(runtime_dirs)
        if prior:
            latest = {event["pr_id"]: event for event in prior["pr_events"]}
            for association in prior["associations"]:
                event = latest[association["pr_id"]]
                associations.append({"repository_key": association["repository_key"],
                    "run_key": association["run_key"], "cycle": association["cycle"],
                    "stage_number": association["stage_number"], "pr_number": event["number"]})
        observations = fetch_pr_observations(associations)
        history, snapshot = collect_progress(runtime_dirs, prior, verified_pr_observations=observations)
        bundle = {"history": history, "snapshot": snapshot}
        # A failed remote write never discards newly observed durable history.
        atomic_json(local_path, bundle)
        result = {"status": "collected", "generated_at": snapshot["generated_at"]}
        if apply:
            result.update(status="published", data_commit=publish(bundle, head, remote, initialize=initialize, api=api))
        atomic_json(state_dir / "status.json", result)
        return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", action="append", type=Path, required=True)
    parser.add_argument("--state-dir", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--initialize", action="store_true")
    parser.add_argument("--loop", action="store_true")
    parser.add_argument("--interval", type=int, default=300)
    args = parser.parse_args(argv)
    if args.interval < 60:
        parser.error("--interval must be at least 60 seconds")
    stopping = False
    def stop(_signum, _frame):
        nonlocal stopping
        stopping = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    while not stopping:
        try:
            result = collect_once(args.runtime, args.state_dir, apply=args.apply, initialize=args.initialize)
            print(json.dumps(result), flush=True)
        except (ValueError, OSError, KeyError, TypeError, subprocess.SubprocessError) as error:
            # Safe error class only; raw runtime data and subprocess output stay private.
            failure = {"status": "error", "error_type": type(error).__name__, "observed_at_epoch": time.time()}
            atomic_json(args.state_dir / "status.json", failure)
            print(json.dumps(failure), flush=True)
            if not args.loop:
                return 1
        if not args.loop:
            return 0
        until = time.monotonic() + args.interval
        while not stopping and time.monotonic() < until:
            time.sleep(min(1, max(0, until - time.monotonic())))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
