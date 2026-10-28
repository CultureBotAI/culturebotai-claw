#!/usr/bin/env python3
"""Bind explicitly reported PRs to goals and refresh GitHub facts read-only.

The private JSONL registry is informational. Neither registering a PR nor
observing a merge authorizes the supervisor to complete a goal. Public callers
must project observations through kg_microbe_progress, never publish this file.
"""
from __future__ import annotations

import argparse
import copy
import fcntl
import hashlib
import json
import os
import re
import stat
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

from kg_microbe_fleet import FleetManifest, load_fleet_manifest

REGISTRY_NAME = "pr-associations.jsonl"
MAX_BYTES = 16 * 1024 * 1024
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
SHA = re.compile(r"[0-9a-f]{40}\Z")
CONTEXT_FIELDS = ("run_id", "repository_key", "cycle", "stage", "goal_identity", "workflow_sha256")
RECORD_FIELDS = {"schema_version", *CONTEXT_FIELDS, "pr_number", "reported_at"}


class AssociationError(ValueError):
    """An association cannot safely be used as progress evidence."""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _object(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise AssociationError("duplicate JSON key")
        result[key] = value
    return result


def _json(raw: bytes | str) -> Any:
    try:
        return json.loads(raw, object_pairs_hook=_object,
                          parse_constant=lambda _: (_ for _ in ()).throw(AssociationError("non-finite JSON")))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise AssociationError("invalid JSON") from error


def _read(path: Path, *, missing: bool = False) -> bytes:
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
    try:
        with os.fdopen(os.open(path, flags), "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_BYTES:
                raise AssociationError("input must be a bounded regular file")
            raw = stream.read(MAX_BYTES + 1)
            if len(raw) > MAX_BYTES:
                raise AssociationError("input exceeds size limit")
            return raw
    except FileNotFoundError:
        if missing:
            return b""
        raise
    except OSError as error:
        raise AssociationError("input cannot be read safely") from error


def _timestamp(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
    except ValueError:
        return False


def _positive(value: Any) -> bool:
    return type(value) is int and value > 0


def _context(ledger: dict, record: dict | None = None) -> dict:
    source = record if record is not None else ledger
    context = {
        "run_id": ledger.get("run_id"),
        "repository_key": ledger.get("repository_key"),
        "cycle": source.get("cycle"),
        "stage": source.get("stage"),
        "goal_identity": source.get("goal_identity") if record is not None else ledger.get("adopted_goal"),
        "workflow_sha256": source.get("workflow_sha256") if record is not None else ledger.get("workflow", {}).get("sha256"),
    }
    return context


def _validate_context(context: dict) -> None:
    goal = context.get("goal_identity")
    if (not isinstance(context.get("run_id"), str) or not context["run_id"]
            or len(context["run_id"]) > 200 or not isinstance(context.get("repository_key"), str)
            or not _positive(context.get("cycle")) or type(context.get("stage")) is not int
            or context["stage"] not in range(1, 7)
            or not isinstance(context.get("workflow_sha256"), str)
            or not DIGEST.fullmatch(context["workflow_sha256"])):
        raise AssociationError("association workflow identity is incomplete")
    if (not isinstance(goal, dict)
            or set(goal) != {"conversation_id", "started_at", "start_step_index"}
            or not isinstance(goal["conversation_id"], str) or not goal["conversation_id"]
            or len(goal["conversation_id"]) > 200 or not _timestamp(goal["started_at"])
            or type(goal["start_step_index"]) is not int or goal["start_step_index"] < 0):
        raise AssociationError("association native goal identity is incomplete")


def _continuation_contexts(ledger: dict, anchors: list[dict]) -> list[dict]:
    """Retain PR ownership across verified continuations, without completion credit.

    The coordinator records these links only after unique native acceptance.
    A link cannot invent a stage: its successor chain must reach the current
    goal or an actual completed-stage entry in the same workflow context.
    """
    entries = ledger.get("same_stage_continuations", [])
    if not isinstance(entries, list):
        raise AssociationError("same-stage continuations must be a list")
    keys = {"schema_version", "run_id", "repository_key", "cycle", "stage",
            "workflow_sha256", "predecessor", "successor", "evidence"}
    def encode(value):
        return json.dumps(value, sort_keys=True, separators=(",", ":"))
    roots = {encode(context) for context in anchors}
    edges, incoming, retained = {}, set(), []
    for entry in entries:
        if (not isinstance(entry, dict) or set(entry) != keys
                or type(entry["schema_version"]) is not int or entry["schema_version"] != 1
                or entry["run_id"] != ledger["run_id"]
                or entry["repository_key"] != ledger["repository_key"]):
            raise AssociationError("invalid same-stage continuation binding")
        before = {key: entry[key] for key in CONTEXT_FIELDS if key != "goal_identity"}
        before["goal_identity"] = entry["predecessor"]
        after = {**before, "goal_identity": entry["successor"]}
        _validate_context(before)
        _validate_context(after)
        predecessor, successor = encode(before), encode(after)
        if (predecessor == successor or predecessor in edges or successor in incoming
                or predecessor in roots):
            raise AssociationError("ambiguous same-stage continuation lineage")
        evidence = entry["evidence"]
        if (not isinstance(evidence, dict) or set(evidence) != {"path", "sha256"}
                or not isinstance(evidence["path"], str) or not Path(evidence["path"]).is_absolute()
                or not isinstance(evidence["sha256"], str) or not DIGEST.fullmatch(evidence["sha256"])):
            raise AssociationError("invalid continuation evidence pin")
        try:
            raw = _read(Path(evidence["path"]))
        except OSError as error:
            raise AssociationError("continuation evidence is unavailable") from error
        if hashlib.sha256(raw).hexdigest() != evidence["sha256"]:
            raise AssociationError("continuation evidence hash mismatch")
        proof = _json(raw)
        binding = {key: value for key, value in entry.items() if key != "evidence"}
        if (not isinstance(proof, dict) or encode(proof.get("binding")) != encode(binding)
                or not _timestamp(proof.get("verified_at"))
                or not isinstance(proof.get("instruction_sha256"), str)
                or not DIGEST.fullmatch(proof["instruction_sha256"])):
            raise AssociationError("continuation evidence does not bind the exact lineage")
        instruction = proof["instruction_sha256"]
        if (encode(proof.get("native_acceptance")) != encode({
                **entry["successor"], "submitted_text_sha256": instruction,
                "matching_declarations": 1})
                or encode(proof.get("history_acceptance")) != encode({
                    "conversation_id": entry["successor"]["conversation_id"],
                    "submitted_text_sha256": instruction, "matching_entries": 1})):
            raise AssociationError("continuation lacks unique matching native and history acceptance")
        edges[predecessor] = successor
        incoming.add(successor)
        retained.append(before)
    for predecessor in edges:
        seen, cursor = set(), predecessor
        while cursor not in roots:
            if cursor in seen or cursor not in edges:
                raise AssociationError("continuation is cyclic or disconnected from a retained goal")
            seen.add(cursor)
            cursor = edges[cursor]
    return retained


def _validate_record(record: Any, ledger: dict) -> dict:
    if not isinstance(record, dict) or set(record) != RECORD_FIELDS:
        raise AssociationError("association fields differ from schema version 1")
    if type(record["schema_version"]) is not int or record["schema_version"] != 1:
        raise AssociationError("unsupported association schema")
    if not _positive(record["pr_number"]) or not _timestamp(record["reported_at"]):
        raise AssociationError("association PR number or timestamp is invalid")
    context = {key: record[key] for key in CONTEXT_FIELDS}
    _validate_context(context)
    contexts = [_context(ledger)]
    contexts.extend(_context(ledger, item) for item in ledger.get("completed_stages", []))
    contexts.extend(_continuation_contexts(ledger, contexts))
    if context not in contexts:
        raise AssociationError("PR association does not match a retained goal identity")
    return record


def _records(raw: bytes, ledger: dict) -> list[dict]:
    if raw and not raw.endswith(b"\n"):
        raise AssociationError("association registry has an incomplete final record")
    result = []
    for line in raw.splitlines():
        if not line:
            raise AssociationError("association registry contains a blank record")
        result.append(_validate_record(_json(line), ledger))
    return result


def _ledger(session: Path, fleet: FleetManifest) -> dict:
    ledger = _json(_read(session / "ledger.json"))
    if not isinstance(ledger, dict) or ledger.get("schema_version") != 2:
        raise AssociationError("PR tracking requires a version 2 supervisor ledger")
    key = ledger.get("repository_key")
    if key != session.name or key not in fleet.keys:
        raise AssociationError("session repository is not the canonical fleet member")
    config = _json(_read(session.parent / "config.json"))
    if not isinstance(config, dict) or config.get("run_id") != ledger.get("run_id"):
        raise AssociationError("ledger and runtime run identities differ")
    targets = [item for item in config.get("targets", []) if item.get("repository_key") == key]
    if len(targets) != 1 or targets[0].get("github_repository", "").casefold() != fleet.get(key).github.casefold():
        raise AssociationError("runtime target and canonical GitHub repository differ")
    return ledger


def _association_key(record: dict) -> tuple:
    return (record["repository_key"], record["run_id"], record["cycle"], record["stage"], record["pr_number"])


def gather_associations(runtime_dirs: Iterable[Path], *, fleet: FleetManifest | None = None) -> list[dict]:
    """Read explicit registries and exact version-2 receipt candidate bindings.

    A receipt candidate contributes a reported association only. Malformed or
    legacy candidates contribute nothing; accepted completion authority belongs
    solely to the supervisor's completed_stages ledger.
    """
    fleet = fleet or load_fleet_manifest()
    gathered: dict[tuple, dict] = {}
    for directory in runtime_dirs:
        runtime = Path(directory).resolve(strict=True)
        for key in fleet.keys:
            session = runtime / key
            if not session.exists():
                continue
            if session.is_symlink() or not session.is_dir():
                raise AssociationError("session directory is not a real directory")
            ledger = _ledger(session, fleet)
            records = _records(_read(session / REGISTRY_NAME, missing=True), ledger)
            candidate_raw = _read(session / "completion.json", missing=True)
            if candidate_raw:
                try:
                    candidate = _json(candidate_raw)
                    if isinstance(candidate, dict) and candidate.get("schema_version") == 2:
                        record = {key: candidate.get(key) for key in CONTEXT_FIELDS}
                        record.update(schema_version=1, pr_number=candidate.get("pr", {}).get("number"),
                                      reported_at=ledger.get("last_observed_at", ledger.get("created_at")))
                        records.append(_validate_record(record, ledger))
                except (AssociationError, AttributeError):
                    # A working receipt may be incomplete. It is never a
                    # fallback source of weaker, inferred goal associations.
                    pass
            for record in records:
                identity = _association_key(record)
                prior = gathered.get(identity)
                if prior and any(prior[field] != record[field] for field in CONTEXT_FIELDS):
                    raise AssociationError("conflicting PR association identity")
                gathered[identity] = copy.deepcopy(record)
    return sorted(gathered.values(), key=_association_key)


def register_pr(session_dir: Path, number: int, *, fleet: FleetManifest | None = None) -> dict:
    """Atomically add a PR binding for the exact current supervised goal."""
    if not _positive(number):
        raise AssociationError("PR number must be a positive integer")
    fleet = fleet or load_fleet_manifest()
    session = Path(session_dir)
    if session.is_symlink():
        raise AssociationError("session directory must not be a symlink")
    session = session.resolve(strict=True)
    if not session.is_dir():
        raise AssociationError("session directory is not a directory")
    lock_path = session / ".pr-associations.lock"
    flags = os.O_RDWR | os.O_CREAT | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
    with os.fdopen(os.open(lock_path, flags, 0o600), "r+") as lock:
        if not stat.S_ISREG(os.fstat(lock.fileno()).st_mode):
            raise AssociationError("association lock is not a regular file")
        fcntl.flock(lock, fcntl.LOCK_EX)
        ledger = _ledger(session, fleet)
        status = _json(_read(session / "status.json"))
        context = _context(ledger)
        if not isinstance(status, dict) or any(status.get(key) != value for key, value in context.items()):
            raise AssociationError("current status and ledger disagree; retry after the supervisor sweep")
        if ledger.get("awaiting_goal") is True:
            raise AssociationError("next goal has not yet been adopted")
        record = {**context, "schema_version": 1, "pr_number": number, "reported_at": now()}
        _validate_record(record, ledger)
        path = session / REGISTRY_NAME
        raw = _read(path, missing=True)
        records = _records(raw, ledger)
        for existing in records:
            if _association_key(existing) == _association_key(record):
                if any(existing[field] != record[field] for field in CONTEXT_FIELDS):
                    raise AssociationError("PR identity is already bound to another native goal")
                return existing
        # The supervisor writes whole ledgers atomically. A racing stage
        # transition must not turn a registration into the next goal's PR.
        latest = _ledger(session, fleet)
        _validate_record(record, latest)
        payload = raw + json.dumps(record, sort_keys=True, separators=(",", ":")).encode() + b"\n"
        if len(payload) > MAX_BYTES:
            raise AssociationError("association registry exceeds size limit")
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(dir=session, prefix=".pr-associations-", delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            descriptor = os.open(session, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)
        return record


def _gh(args: list[str]) -> Any:
    return subprocess.run(args, capture_output=True, text=True, timeout=60, check=False)


def fetch_pr_observations(
    associations: Iterable[dict], *, gh: Callable[[list[str]], Any] = _gh,
    fleet: FleetManifest | None = None,
) -> list[dict]:
    """Refresh GitHub facts for explicit private or retained public bindings.

    Public bindings may use run_key in place of private run_id. They must come
    from the previously validated published progress snapshot. GitHub failures
    raise so the publisher preserves its prior successful snapshot.
    """
    fleet = fleet or load_fleet_manifest()
    cache: dict[tuple, dict] = {}
    results = []
    observed_at = now()
    for association in associations:
        key = association.get("repository_key")
        number = association.get("pr_number", association.get("number"))
        if key not in fleet.keys or not _positive(number):
            raise AssociationError("PR query is outside the canonical fleet")
        stage = association.get("stage", association.get("stage_number"))
        if (not _positive(association.get("cycle")) or type(stage) is not int
                or stage not in range(1, 7)
                or ("stage" in association and "stage_number" in association
                    and association["stage"] != association["stage_number"])):
            raise AssociationError("PR query has no explicit goal stage")
        run_field = "run_id" if "run_id" in association else "run_key"
        run = association.get(run_field)
        if not isinstance(run, str) or not run or len(run) > 200:
            raise AssociationError("PR query has no run identity")
        github = fleet.get(key).github
        identity = (key, number)
        if identity not in cache:
            response = gh(["gh", "api", f"repos/{github}/pulls/{number}"])
            if response.returncode:
                raise AssociationError(f"GitHub PR query failed for {github}#{number}")
            live = _json(response.stdout)
            if (not isinstance(live, dict) or type(live.get("number")) is not int or live["number"] != number
                    or live.get("base", {}).get("repo", {}).get("full_name", "").casefold() != github.casefold()
                    or live.get("html_url", "").casefold() != f"https://github.com/{github}/pull/{number}".casefold()
                    or not isinstance(live.get("head", {}).get("sha"), str)
                    or not SHA.fullmatch(live["head"]["sha"])
                    or type(live.get("merged")) is not bool or live.get("state") not in {"open", "closed"}):
                raise AssociationError("GitHub PR identity or state does not match the association")
            facts = {"number": number, "state": "merged" if live["merged"] else live["state"],
                     "head_sha": live["head"]["sha"], "observed_at": observed_at}
            if live["merged"]:
                if (live["state"] != "closed" or not _timestamp(live.get("merged_at"))
                        or not isinstance(live.get("merge_commit_sha"), str)
                        or not SHA.fullmatch(live["merge_commit_sha"])):
                    raise AssociationError("GitHub merged PR evidence is incomplete")
                facts.update(merged_at=live["merged_at"], merge_commit_sha=live["merge_commit_sha"])
            elif live.get("merged_at") is not None:
                raise AssociationError("GitHub unmerged PR has a merge timestamp")
            cache[identity] = facts
        results.append({
            "repository_key": key, run_field: run, "cycle": association["cycle"], "stage": stage,
            "association_authority": "agent_reported", **cache[identity],
        })
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    register = commands.add_parser("register", help="Record every PR for the exact active goal")
    register.add_argument("--session-dir", required=True, type=Path)
    register.add_argument("--number", required=True, type=int)
    args = parser.parse_args(argv)
    try:
        record = register_pr(args.session_dir, args.number)
    except (AssociationError, OSError, ValueError) as error:
        parser.exit(1, f"PR association was not registered: {error}\n")
    print(json.dumps({"registered": True, "number": record["pr_number"],
                      "repository_key": record["repository_key"], "cycle": record["cycle"], "stage": record["stage"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
