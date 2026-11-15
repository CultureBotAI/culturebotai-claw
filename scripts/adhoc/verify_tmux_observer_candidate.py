#!/usr/bin/env python3
"""Verify isolated observer evidence for claw issue 1238, 2026-11-15.

Inputs: candidate once/state/registry artifacts and exact live source pins.
Output: one exclusive private verification receipt. Reads only the explicitly
named artifacts and live observer PID; never changes a monitor or workflow.
"""
import argparse
import hashlib
import json
import os
import stat
import subprocess
from pathlib import Path


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def read(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        item = os.fstat(stream.fileno())
        require(stat.S_ISREG(item.st_mode) and item.st_size <= 8 * 1024 * 1024, "Input must be bounded regular file")
        raw = stream.read(8 * 1024 * 1024 + 1)
    require(len(raw) <= 8 * 1024 * 1024, "Input too large")
    return raw


def load(path):
    return json.loads(read(path))


def sha(path):
    return hashlib.sha256(read(path)).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ("state", "once", "baseline", "proposal", "live-registry", "live-source", "adapter", "candidate-source", "output"):
        parser.add_argument("--" + field, type=Path, required=True)
    for field in ("live-registry-sha256", "live-source-sha256", "adapter-sha256", "candidate-source-sha256", "live-started"):
        parser.add_argument("--" + field, required=True)
    parser.add_argument("--live-pid", type=int, required=True)
    args = parser.parse_args()
    require(args.live_pid > 0, "Invalid live PID")
    require(not args.output.resolve().is_relative_to(args.live_registry.parent.resolve()), "Output must not touch live state")
    expected = ((args.live_registry, args.live_registry_sha256), (args.live_source, args.live_source_sha256),
                (args.adapter, args.adapter_sha256), (args.candidate_source, args.candidate_source_sha256))
    for path, digest in expected:
        require(sha(path) == digest, "Source or registry digest differs: " + str(path))
    before, proposed = load(args.baseline), load(args.proposal)
    status, heartbeat, once = load(args.state / "status.json"), load(args.state / "heartbeat.json"), load(args.once)
    snapshots = list((args.state / "snapshots").glob("*.json"))
    require(len(snapshots) == 1 and load(snapshots[0]) == status == once, "One-shot output and persisted snapshot differ")
    require(status["registry_sha256"] == sha(args.proposal) == heartbeat["registry_sha256"], "Candidate registry pin differs")
    require(heartbeat["complete_cycle"] is True and heartbeat["pid"] == status["observer_pid"]
            and heartbeat["counts"] == status["counts"] and heartbeat["updated_at"] == status["completed_at"],
            "Heartbeat does not describe persisted cycle")
    old = {row["key"]: row for row in before["targets"]}
    new = {row["key"]: row for row in proposed["targets"]}
    seen = {row["key"]: row for row in status["targets"]}
    require(len(old) == len(before["targets"]) and list(old) == list(new) == list(seen), "Observation scope/order changed")
    moved = retained = unbound = 0
    for key, prior in old.items():
        current = new[key]
        if current.get("transport") == "tmux":
            require(current["prior_binding"] == prior and current["tmux_observation"]["key"] == key,
                    "Prior identity or native descriptor changed")
            require(current["viewer"] == {field: prior.get(field) for field in ("window", "tab", "tty")},
                    "Original viewer provenance changed")
            require(seen[key]["transport"] == "tmux" and seen[key]["binding"] == "live", "Migrated pane not observed")
            require(seen[key]["native"]["state"] == ("unknown" if current["tmux_observation"]["native"]["mode"] == "managed" else "verified"),
                    "Native proof mode changed")
            moved += 1
        else:
            require(current == prior, "Unmigrated binding changed")
            if prior["binding_status"] == "unbound":
                require(seen[key]["binding"] == "unbound", "Unbound candidate was admitted")
                unbound += 1
            else:
                retained += 1
    allowed = {"observer.lock", "heartbeat.json", "status.json", str(snapshots[0].relative_to(args.state))}
    actual = {str(path.relative_to(args.state)) for path in args.state.rglob("*") if path.is_file()}
    require(actual == allowed, "Candidate state contains unexpected artifacts")
    process = subprocess.run(["/bin/ps", "-p", str(args.live_pid), "-o", "pid=,lstart=,command="],
                             text=True, capture_output=True, check=True, timeout=10).stdout.split(None, 6)
    require(len(process) == 7 and process[0] == str(args.live_pid) and " ".join(process[1:6]) == args.live_started
            and str(args.live_source) in process[6] and " run --registry " in process[6], "Original observer process changed")
    for path, digest in expected:
        require(sha(path) == digest, "Source changed during verification")
    receipt = {"verified": True, "one_shot_cycle_only": True, "no_running_service_claim": True,
               "counts": status["counts"], "registry_transport_counts": {"tmux": moved, "legacy": retained, "unbound": unbound},
               "preserved_all_keys_and_unmigrated_bindings": True, "live_source_and_registry_unchanged": True,
               "original_observer_pid_still_running": args.live_pid, "candidate_state_artifacts": sorted(actual),
               "adapter_sha256": args.adapter_sha256, "candidate_source_sha256": args.candidate_source_sha256,
               "candidate_registry_sha256": sha(args.proposal), "candidate_completed_at": status["completed_at"],
               "no_input_or_monitor_lifecycle_action": True}
    with args.output.open("x") as stream:
        json.dump(receipt, stream, indent=2)
        stream.write("\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
