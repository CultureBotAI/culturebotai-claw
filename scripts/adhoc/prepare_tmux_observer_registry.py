#!/usr/bin/env python3
"""Prepare private tmux observer bindings, claw issue 1238, 2026-11-15.

Inputs: verified migration map, legacy observer registry, reviewed adapter and
two persisted real canaries. Outputs: new candidate registry, exact observations,
and an integration proposal in an operator-selected directory. Never updates the
live registry, sends input, or starts/stops a monitor or agent. Every observation
uses the same adapter CLI and interpreter as the real canaries.
"""
import argparse
import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, data):
    with path.open("x") as stream:
        json.dump(data, stream, indent=2)
        stream.write("\n")


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    for key in ("adapter", "migration", "legacy", "sessions", "embedded-canary", "managed-canary", "output"):
        parser.add_argument("--" + key, type=Path, required=True)
    parser.add_argument("--adapter-sha256", required=True)
    parser.add_argument("--legacy-sha256", required=True)
    parser.add_argument("--tmux", required=True)
    parser.add_argument("--managed-key", action="append", default=[])
    args = parser.parse_args()
    require(digest(args.adapter) == args.adapter_sha256, "Adapter source changed")
    require(digest(args.legacy) == args.legacy_sha256, "Legacy registry changed")
    migration = json.loads(args.migration.read_text())
    legacy = json.loads(args.legacy.read_text())
    for path, mode, native_state in ((args.embedded_canary, "embedded", "verified"),
                                     (args.managed_canary, "managed", "unknown")):
        canary = json.loads(path.read_text())
        require(canary["candidate_only"] is True and canary["binding"]["native"]["mode"] == mode
                and canary["observation"]["binding"] == "live"
                and canary["observation"]["native"]["state"] == native_state, "Canary did not prove expected path")
        require(any(row["pid"] == canary["binding"]["native_process"]["pid"]
                    and row["thread"] == canary["binding"]["native"]["thread_id"] for row in migration),
                "Canary is outside the supplied migration")
    require(isinstance(migration, list) and 1 <= len(migration) <= 64, "Invalid migration count")
    require(legacy["schema_version"] == 1 and legacy["role"] == "observer_only", "Invalid legacy registry")
    args.output.mkdir(parents=True, exist_ok=False)
    save(args.output / "legacy-registry.original.json", legacy)
    selected, seen = {}, set()
    for row in migration:
        require(row["status"] == "verified" and row["head_unchanged"] and row["status_unchanged"],
                "Unverified migration row")
        key = row["repository"].casefold()
        require(key not in seen, "Duplicate migration key")
        seen.add(key)
        require(any(old["key"] == key and old.get("root") == row["cwd"] for old in legacy["targets"]),
                "Migration repository not in legacy observation scope")
        mode = "managed" if key in args.managed_key else "embedded"
        command = [sys.executable, str(args.adapter), "inspect", "--key", key, "--tmux", args.tmux,
                   "--socket", row["socket"], "--session", row["session"], "--pane", row["pane"],
                   "--pid", str(row["pid"]), "--root", row["cwd"], "--native-mode", mode, "--thread", row["thread"]]
        if mode == "embedded":
            paths = list(args.sessions.rglob("*" + row["thread"] + ".jsonl"))
            require(len(paths) == 1, "Exact saved primary thread path is missing or ambiguous")
            command += ["--rollout", str(paths[0])]
        require(digest(args.adapter) == args.adapter_sha256, "Adapter source changed")
        result = subprocess.run(command, text=True, capture_output=True, timeout=120)
        receipt = json.loads(result.stdout)
        save(args.output / (key + ".json"), receipt)
        require(result.returncode == 0 and receipt["observation"]["binding"] == "live", "Target transport not verified: " + key)
        require(receipt["observation"]["native"]["state"] == ("unknown" if mode == "managed" else "verified"),
                "Unexpected native proof state: " + key)
        selected[key] = receipt["binding"]
        print(key + ": verified transport; native " + receipt["observation"]["native"]["state"], flush=True)
    registry = {"schema_version": 1, "role": "observer_only", "targets": list(selected.values())}
    save(args.output / "tmux-registry.proposed.json", registry)
    proposal = copy.deepcopy(legacy)
    for index, old in enumerate(legacy["targets"]):
        binding = selected.get(old["key"])
        if binding is None:
            continue
        new = copy.deepcopy(old)
        new.update(transport="tmux", tmux_observation=binding, prior_binding=copy.deepcopy(old),
                   pid=binding["native_process"]["pid"], tty=binding["native_process"]["tty"],
                   started=binding["native_process"]["started"], comm=binding["native_process"]["comm"],
                   native=copy.deepcopy(binding.get("native")))
        new["viewer"] = {key: old.get(key) for key in ("window", "tab", "tty")}
        new.pop("window", None)
        new.pop("tab", None)
        proposal["targets"][index] = new
    save(args.output / "legacy-registry.proposed.json", proposal)
    require(digest(args.adapter) == args.adapter_sha256 and digest(args.legacy) == args.legacy_sha256,
            "Source or live registry changed during read-only batch")
    result = subprocess.run([sys.executable, str(args.adapter), "observe", "--registry",
                             str(args.output / "tmux-registry.proposed.json")], text=True,
                            capture_output=True, timeout=300)
    final = json.loads(result.stdout)
    save(args.output / "full-observation.json", final)
    require(result.returncode == 0 and final["counts"]["live_transport_bindings"] == len(migration),
            "Final bounded observation failed")
    print(json.dumps({"counts": final["counts"], "live_registry_unchanged": True,
                      "candidate_only": True, "adapter_sha256": args.adapter_sha256}))


if __name__ == "__main__":
    main()
