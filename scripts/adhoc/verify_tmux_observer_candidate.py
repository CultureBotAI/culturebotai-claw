#!/usr/bin/env python3
"""Verify isolated observer evidence for claw issues 1238/1249, 2026-11-15.

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


def indexed_targets(document, label):
    require(isinstance(document, dict) and type(document.get("schema_version")) is int
            and document["schema_version"] == 1 and document.get("role") == "observer_only",
            label + " schema or role differs")
    rows = document.get("targets")
    require(isinstance(rows, list) and 1 <= len(rows) <= 64, label + " target count invalid")
    indexed = {}
    for row in rows:
        require(isinstance(row, dict) and isinstance(row.get("key"), str) and row["key"],
                label + " target key invalid")
        key = row["key"]
        require(key not in indexed, label + " duplicate target key")
        indexed[key] = row
    return indexed


def observation_counts(rows):
    """Recompute the candidate observer's five fields without inferring progress."""
    for row in rows:
        require(isinstance(row.get("binding"), str) and row["binding"]
                and isinstance(row.get("native"), dict)
                and isinstance(row["native"].get("state"), str) and row["native"]["state"],
                "Observation count input invalid")
    return {
        "configured": len(rows),
        "live_process_bindings": sum(row["binding"] == "live" for row in rows),
        "stale_or_unverified_bindings": sum(row["binding"] not in ("live", "unbound") for row in rows),
        "unbound_candidates": sum(row["binding"] == "unbound" for row in rows),
        "verified_native_threads": sum(row["native"]["state"] == "verified" for row in rows),
    }


def require_counts(actual, expected, label):
    require(isinstance(actual, dict) and set(actual) == set(expected)
            and all(type(value) is int and value >= 0 for value in actual.values())
            and actual == expected, label + " counts differ from observations")


def validate_cycle(status, heartbeat, once, snapshot, registry_sha256):
    """Validate saved cycle artifacts only; no process, session or file writes."""
    for label, document in (("Status", status), ("One-shot", once), ("Snapshot", snapshot)):
        indexed_targets(document, label)
        require(document.get("no_input") is True and document.get("no_goal_or_registry_writes") is True,
                label + " read-only flags differ")
    require(snapshot == status == once, "One-shot output and persisted snapshot differ")
    require(isinstance(heartbeat, dict) and type(heartbeat.get("schema_version")) is int
            and heartbeat["schema_version"] == 1, "Heartbeat schema differs")
    require(status.get("registry_sha256") == registry_sha256 == heartbeat.get("registry_sha256"),
            "Candidate registry pin differs")
    counts = observation_counts(status["targets"])
    require_counts(status.get("counts"), counts, "Status")
    require_counts(heartbeat.get("counts"), counts, "Heartbeat")
    require(type(status.get("observer_pid")) is int and status["observer_pid"] > 0
            and type(heartbeat.get("pid")) is int and heartbeat["pid"] == status["observer_pid"]
            and heartbeat.get("complete_cycle") is True and heartbeat.get("running") is True
            and isinstance(status.get("completed_at"), str) and status["completed_at"]
            and heartbeat.get("updated_at") == status["completed_at"],
            "Heartbeat does not describe persisted cycle")
    return counts


def validate_scope(before, proposed, status):
    old = indexed_targets(before, "Baseline")
    new = indexed_targets(proposed, "Proposal")
    seen = indexed_targets(status, "Status")
    require(len(before["targets"]) == len(proposed["targets"]) == len(status["targets"])
            and list(old) == list(new) == list(seen), "Observation scope/order changed")
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
    return {"tmux": moved, "legacy": retained, "unbound": unbound}


def validate_saved_artifacts(state, once, baseline, proposal):
    """Check explicitly named private evidence without creating a receipt."""
    before, proposed = load(baseline), load(proposal)
    status, heartbeat, once = load(state / "status.json"), load(state / "heartbeat.json"), load(once)
    snapshots = list((state / "snapshots").glob("*.json"))
    require(len(snapshots) == 1, "Exactly one persisted snapshot required")
    counts = validate_cycle(status, heartbeat, once, load(snapshots[0]), sha(proposal))
    transports = validate_scope(before, proposed, status)
    return {"counts": counts, "registry_transport_counts": transports,
            "snapshot": snapshots[0], "completed_at": status["completed_at"]}


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
    saved = validate_saved_artifacts(args.state, args.once, args.baseline, args.proposal)
    allowed = {"observer.lock", "heartbeat.json", "status.json", str(saved["snapshot"].relative_to(args.state))}
    actual = {str(path.relative_to(args.state)) for path in args.state.rglob("*") if path.is_file()}
    require(actual == allowed, "Candidate state contains unexpected artifacts")
    process = subprocess.run(["/bin/ps", "-p", str(args.live_pid), "-o", "pid=,lstart=,command="],
                             text=True, capture_output=True, check=True, timeout=10).stdout.split(None, 6)
    require(len(process) == 7 and process[0] == str(args.live_pid) and " ".join(process[1:6]) == args.live_started
            and str(args.live_source) in process[6] and " run --registry " in process[6], "Original observer process changed")
    for path, digest in expected:
        require(sha(path) == digest, "Source changed during verification")
    receipt = {"verified": True, "one_shot_cycle_only": True, "no_running_service_claim": True,
               "counts": saved["counts"], "registry_transport_counts": saved["registry_transport_counts"],
               "preserved_all_keys_and_unmigrated_bindings": True, "live_source_and_registry_unchanged": True,
               "original_observer_pid_still_running": args.live_pid, "candidate_state_artifacts": sorted(actual),
               "adapter_sha256": args.adapter_sha256, "candidate_source_sha256": args.candidate_source_sha256,
               "candidate_registry_sha256": sha(args.proposal), "candidate_completed_at": saved["completed_at"],
               "no_input_or_monitor_lifecycle_action": True}
    with args.output.open("x") as stream:
        json.dump(receipt, stream, indent=2)
        stream.write("\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
