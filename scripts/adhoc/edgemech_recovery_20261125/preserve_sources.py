#!/usr/bin/env python3
"""Offline, append-only archival of explicitly selected recovery tool source.

No archived source is imported or executed. Private original bytes and native
result records stay separate from inert, binding-parameterized public source.
Created 2026-11-26 for CultureBotAI/EdgeMech issue 228.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
from pathlib import Path
from typing import Any


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def regular_bytes(path: Path) -> bytes:
    if not stat.S_ISREG(path.lstat().st_mode):
        raise ValueError(f"not a regular, non-symlink file: {path}")
    return path.read_bytes()


def fresh_directory(path: Path) -> None:
    if not path.is_absolute():
        raise ValueError("output directories must be absolute")
    for parent in [path, *path.parents]:
        if parent.is_symlink():
            raise ValueError("symlink output component")
    if path.exists():
        raise FileExistsError(path)
    path.mkdir(parents=True, exist_ok=False)


def save(path: Path, data: bytes) -> dict[str, Any]:
    with path.open("xb") as stream:
        stream.write(data)
    return {"name": path.name, "sha256": sha(data), "bytes": len(data)}


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


class Bindings:
    """Replace explicit sensitive bindings, retaining the map only privately."""

    patterns = (
        ("HOME", r"/Users/[A-Za-z0-9_.-]+"),
        ("UUID", r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"),
        ("SOCKET", r"/(?:private/)?tmp/tmux-\d+/default"),
        ("PANE", r"%\d+\b"),
        ("TTY", r"(?:/dev/)?ttys\d+\b"),
        ("SESSION", r"\bedge-(?:restart|prep)-[A-Za-z0-9-]+"),
        ("CLIENT", r"\bclient-\d+\b"),
        ("CALL", r"\bcall_[A-Za-z0-9]+\b"),
        ("IP", r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
    )

    def __init__(self, explicit: dict[str, str] | None = None):
        self.values: dict[str, str] = {}
        for token, value in (explicit or {}).items():
            if not re.fullmatch(r"PRIVATE_[A-Z0-9_]+", token) or not value:
                raise ValueError("invalid explicit binding")
            if value in self.values:
                raise ValueError("duplicate explicit binding value")
            self.values[value] = token

    def transform(self, text: str) -> str:
        for kind, pattern in self.patterns:
            for match in re.finditer(pattern, text):
                value = match.group()
                if value not in self.values:
                    self.values[value] = f"PRIVATE_{kind}_{len(self.values) + 1:03d}"
        # Longest first protects paths containing shorter identifiers.
        for value, token in sorted(self.values.items(), key=lambda x: (-len(x[0]), x[0])):
            pattern = re.escape(value)
            if value.isdecimal():
                pattern = rf"(?<![A-Za-z0-9]){pattern}(?![A-Za-z0-9])"
            text = re.sub(pattern, lambda _: token, text)
        return text


def python_blocks(shell: str) -> list[str]:
    """Extract exact heredoc contents, without evaluating shell or substitutions."""
    lines = shell.splitlines(keepends=True)
    blocks: list[str] = []
    for i, line in enumerate(lines):
        match = re.search(r"\bpython(?:3)?\s+-\s+<<(['\"]?)([A-Za-z_][A-Za-z_0-9]*)\1", line)
        if match:
            end = next(
                (j for j in range(i + 1, len(lines)) if lines[j].rstrip("\r\n") == match[2]), None
            )
            if end is None:
                raise ValueError("unterminated Python heredoc")
            blocks.append("".join(lines[i + 1 : end]))
    return blocks


def selected_call(
    records: list[tuple[bytes, dict[str, Any]]], line: int, cutoff: str
) -> dict[str, Any]:
    if not isinstance(line, int) or not 1 <= line <= len(records):
        raise ValueError("source line outside rollout")
    raw, record = records[line - 1]
    payload = record.get("payload", {})
    if payload.get("type") != "custom_tool_call" or payload.get("name") != "exec":
        raise ValueError("selection is not an exec source call")
    if record["timestamp"] > cutoff:
        raise ValueError("selection exceeds inventory cutoff")
    call_id = payload["call_id"]
    result = [
        {"line": i + 1, "raw_sha256": sha(r), "record": d}
        for i, (r, d) in enumerate(records)
        if d.get("payload", {}).get("type") == "custom_tool_call_output"
        and d["payload"].get("call_id") == call_id
    ]
    if len(result) != 1:
        raise ValueError("source call needs exactly one matching result record")
    # Native command completions before the next tool request belong to this
    # bounded call window. Record the window rule; never invent exit status.
    commands = []
    for i in range(line, len(records)):
        r, d = records[i]
        q = d.get("payload", {})
        if q.get("type") in {"custom_tool_call", "function_call"}:
            break
        item = q.get("item", {})
        if q.get("type") == "item_completed" and item.get("type") == "CommandExecution":
            commands.append({"line": i + 1, "raw_sha256": sha(r), "record": d})
    return {
        "line": line,
        "raw_sha256": sha(raw),
        "timestamp": record["timestamp"],
        "call_id": call_id,
        "source": payload["input"],
        "results": result,
        "commands": commands,
    }


def preserve(spec: dict[str, Any], private: Path, public: Path) -> dict[str, Any]:
    if private == public or private in public.parents or public in private.parents:
        raise ValueError("private and public roots must be disjoint")
    bindings = Bindings(spec.get("bindings"))
    selections = []
    seen = set()
    for owner in spec["owners"]:
        path = Path(owner["rollout"])
        raw = regular_bytes(path)
        records = [(line, json.loads(line)) for line in raw.splitlines(keepends=True)]
        for item in owner["calls"]:
            key = (str(path), item["line"])
            if key in seen:
                raise ValueError("duplicate source selection")
            seen.add(key)
            selected = selected_call(records, item["line"], spec["cutoff"])
            selected["rollout_read_sha256"] = sha(raw)
            selected["rollout_read_bytes"] = len(raw)
            selections.append((item["id"], item["purpose"], path, selected))
    ids = [x[0] for x in selections]
    if len(set(ids)) != len(ids) or any(not re.fullmatch(r"[a-z][a-z0-9-]+", x) for x in ids):
        raise ValueError("invalid or duplicate public id")
    # Validate all selection inputs before either destination is created.
    fresh_directory(private)
    fresh_directory(public)
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "issue": "https://github.com/CultureBotAI/EdgeMech/issues/228",
        "cutoff_utc": spec["cutoff"],
        "relationship": "Inert sanitized source derived at preservation time; never used for historical execution. Private exact originals remain authoritative.",
        "archive_executions": 0,
        "entries": [],
    }
    for ident, purpose, rollout, selected in selections:
        private_dir = private / ident
        private_dir.mkdir()
        public_dir = public / ident
        public_dir.mkdir()
        sources = [("orchestrator.js.txt", selected["source"])]
        for index, command in enumerate(selected["commands"], 1):
            argv = command["record"]["payload"]["item"].get("command", [])
            if argv:
                shell = argv[-1]
                sources.append((f"command-{index:02d}.sh.txt", shell))
                for sub, code in enumerate(python_blocks(shell), 1):
                    sources.append((f"command-{index:02d}-python-{sub:02d}.py.txt", code))
        files = []
        for name, source in sources:
            original = save(private_dir / name, source.encode())
            derived = save(public_dir / name, bindings.transform(source).encode())
            files.append(
                {
                    "path": f"{ident}/{name}",
                    "private_original_sha256": original["sha256"],
                    "private_original_bytes": original["bytes"],
                    "public": derived,
                }
            )
        linkage = {
            "rollout": str(rollout),
            **{k: v for k, v in selected.items() if k != "source"},
            "command_linkage_rule": "Native CommandExecution completions after source call and before next tool request; explicit result call_id equality. Missing status remains unknown.",
        }
        save(private_dir / "linkage.json", json_bytes(linkage))
        manifest["entries"].append(
            {
                "id": ident,
                "purpose": purpose,
                "timestamp_utc": selected["timestamp"],
                "files": files,
                "result_records": len(selected["results"]),
                "native_commands": [
                    {
                        "status": c["record"]["payload"]["item"].get("status"),
                        "exit_code": c["record"]["payload"]["item"].get("exit_code"),
                    }
                    for c in selected["commands"]
                ],
            }
        )
    save(private / "binding-map.json", json_bytes(bindings.values))
    save(private / "selection.json", json_bytes(spec))
    save(private / "MANIFEST.json", json_bytes(manifest))
    save(public / "MANIFEST.json", json_bytes(manifest))
    return manifest


def selection_from_inventory(inventory: dict[str, Any], bindings: dict[str, str]) -> dict[str, Any]:
    owners = []
    seen = set()
    for pin in inventory["source_pins"]:
        actor = pin["actor"]
        if actor in seen:
            raise ValueError("duplicate inventory actor")
        seen.add(actor)
        calls = [
            {
                "id": f"{actor.replace('_', '-')}-{c['line']}",
                "line": c["line"],
                "purpose": c["scope_reason"],
            }
            for c in inventory["calls"]
            if c["actor"] == actor and c["classification"] == "required_producer_or_runtime_control"
        ]
        owners.append({"rollout": pin["path"], "calls": calls})
    expected = inventory["counts"]["required_producer_or_runtime_control"]
    if sum(len(o["calls"]) for o in owners) != expected:
        raise ValueError("inventory required-source count mismatch")
    return {"cutoff": inventory["fixed_execution_cutoff"], "owners": owners, "bindings": bindings}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--selection", type=Path)
    group.add_argument("--inventory", type=Path)
    parser.add_argument("--bindings", type=Path)
    parser.add_argument("--private-output", type=Path, required=True)
    parser.add_argument("--public-output", type=Path, required=True)
    args = parser.parse_args()
    inventory_bytes = regular_bytes(args.inventory) if args.inventory else None
    if inventory_bytes is not None:
        bindings = json.loads(regular_bytes(args.bindings)) if args.bindings else {}
        spec = selection_from_inventory(json.loads(inventory_bytes), bindings)
    else:
        spec = json.loads(regular_bytes(args.selection))
    result = preserve(spec, args.private_output, args.public_output)
    if inventory_bytes is not None:
        save(args.private_output / "reviewed-inventory.json", inventory_bytes)
    print(json.dumps({"entries": len(result["entries"]), "archive_executions": 0}))


if __name__ == "__main__":
    main()
