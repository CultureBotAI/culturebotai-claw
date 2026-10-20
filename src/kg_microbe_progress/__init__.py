"""Public, durable accounting of verified Mech goal closures and associated PRs.

The supervisor is the closure authority. This reader checks its archived receipt
hash and identity; it does not repeat the supervisor's GitHub/review verification.
Supplementary PR observations are a trusted-caller interface: the caller must
validate an explicit goal association and obtain the state from GitHub. A GitHub
merge alone never completes a goal. Nothing here writes to supervisor runtime.
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import stat
import tempfile
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from jsonschema.validators import validator_for
from linkml.generators.jsonschemagen import JsonSchemaGenerator
from linkml_runtime.linkml_model.meta import SchemaDefinition

from kg_microbe_fleet import FleetManifest, load_fleet_manifest
from kg_microbe_workflows import STAGE_KEYS, load_document

VERSION = "1.0.0"
SCHEMA_PATH = Path(__file__).parent / "schema/progress.yaml"
PHASES = {
    "assessment", "unavailable", "requires_migration", "blocked", "waiting",
    "awaiting_native_acceptance", "ready_to_dispatch", "requires_intervention",
    "closure_blocked", "awaiting_closure_receipt", "unknown",
}
COUNTERS = (
    "completed_cycles", "completed_goals", "unique_prs", "merged_prs",
    "open_prs", "closed_prs", "no_change_goals",
)
MAX_INPUT_BYTES = 64 * 1024 * 1024


class ProgressError(ValueError):
    """An incomplete, inconsistent or unsafe source must not replace progress."""


def digest(value: Any) -> str:
    """Use the supervisor's canonical JSON digest (including its separators)."""
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def run_key(run_id: str) -> str:
    if not isinstance(run_id, str) or not run_id:
        raise ProgressError("missing run identity")
    return digest(["run", run_id])[:24]


def _date(value: Any) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.utcoffset() is None:
            raise ValueError("timezone required")
        return result
    except (AttributeError, TypeError, ValueError) as exc:
        raise ProgressError("invalid timezone-aware timestamp") from exc


def _positive(value: Any, label: str, maximum: int | None = None) -> int:
    if type(value) is not int or value < 1 or (maximum is not None and value > maximum):
        raise ProgressError(f"invalid {label}")
    return value


def _sha(value: Any, length: int = 64) -> str:
    if not isinstance(value, str) or re.fullmatch(f"[0-9a-f]{{{length}}}", value) is None:
        raise ProgressError("invalid evidence digest")
    return value


def _unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ProgressError("duplicate JSON key")
        result[key] = value
    return result


def read_json(path: Path) -> dict[str, Any]:
    """Reject symlinks, special files, duplicate keys and partial JSON writes."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "r") as stream:
            metadata = os.fstat(stream.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise ProgressError("source is not a regular file")
            if metadata.st_size > MAX_INPUT_BYTES:
                raise ProgressError("progress input exceeds size limit")
            value = json.load(stream, object_pairs_hook=_unique_pairs)
        if not isinstance(value, dict):
            raise ProgressError("source must be a JSON object")
        json.dumps(value, allow_nan=False)
        return value
    except (OSError, ValueError) as exc:
        raise ProgressError(f"cannot read valid progress input ({path.name})") from exc


def atomic_write_json(path: Path, value: dict[str, Any]) -> None:
    """Atomically replace one public artifact; caller owns the transaction lock."""
    raw = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ProgressError("refuse to replace a symlink")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@lru_cache(maxsize=8)
def json_schema(class_name: str = "ProgressSnapshot") -> dict[str, Any]:
    schema = load_document(SCHEMA_PATH.read_text())
    if schema.get("imports") or class_name not in schema["classes"]:
        raise ProgressError("invalid progress schema")
    return json.loads(JsonSchemaGenerator(
        SchemaDefinition(**schema), top_class=class_name,
        not_closed=False, include_null=False,
    ).serialize())


def _shape(value: dict[str, Any], class_name: str) -> None:
    schema = json_schema(class_name)
    validator = validator_for(schema)
    errors = sorted(validator(schema).iter_errors(value), key=lambda item: str(item.path))
    if errors:
        raise ProgressError(f"invalid {class_name} at {list(errors[0].path)}: {errors[0].message}")
    if value.get("schema_version") != VERSION:
        raise ProgressError("unsupported progress version")


def _goal_ref(key: str, run: str, cycle: int, stage: int) -> dict[str, Any]:
    return {
        "id": digest(["goal", key, run, cycle, stage]),
        "repository_key": key, "run_key": run, "cycle": cycle, "stage_number": stage,
    }


def _blocker(reason: Any, phase: str) -> str:
    # Deliberately exclude free-form terminal/agent text even on unknown errors.
    if not isinstance(reason, str):
        return "none"
    if "three bounded closure repairs exhausted" in reason:
        return "closure_repairs_exhausted"
    for needle, code in (
        ("busy/background/queued", "agent_busy"),
        ("native execution busy", "agent_busy"),
        ("no-empty-composer", "composer_unavailable"),
        ("unrecognized-composer-tail", "composer_unavailable"),
        ("not clean", "working_tree_changes"),
        ("cancelled", "goal_cancelled"),
        ("goal identity", "goal_identity_changed"),
    ):
        if needle in reason:
            return code
    return "review_required" if phase in {"blocked", "requires_intervention", "closure_blocked"} else "none"


def _receipt(directory: Path, record: dict[str, Any], ledger: dict[str, Any]) -> dict[str, Any]:
    receipt_sha = _sha(record["receipt_sha256"])
    stage = _positive(record["stage"], "closure stage", 6)
    cycle = _positive(record.get("cycle", 1), "closure cycle")
    basename = f"stage-{stage}-{receipt_sha[:12]}.json"
    candidates = [
        directory / "receipts" / f"cycle-{cycle:06d}" / basename,
        directory / "receipts" / basename,
    ]
    present = [path for path in candidates if path.exists() or path.is_symlink()]
    if not present:
        raise ProgressError("verified closure has no archived receipt")
    receipts = [read_json(path) for path in present]
    if any(digest(receipt) != receipt_sha for receipt in receipts):
        raise ProgressError("archived receipt hash changed")
    receipt = receipts[0]
    if any(receipt.get(field) != ledger[field] for field in ("run_id", "repository_key")):
        raise ProgressError("archived receipt belongs to a different run/repository")
    if (receipt.get("stage") != stage or receipt.get("cycle", 1) != cycle
            or receipt.get("goal_identity") != record.get("goal_identity")
            or receipt.get("goal_complete") is not True):
        raise ProgressError("archived receipt goal identity differs from verified closure")
    return receipt


def _closure(directory: Path, record: dict[str, Any], ledger: dict[str, Any],
             github: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    receipt = _receipt(directory, record, ledger)
    verification = record.get("verification", {})
    outcome = verification.get("status")
    if outcome not in {"merged", "no_changes"}:
        raise ProgressError("closure lacks successful supervisor verification")
    _date(verification.get("verified_at"))
    key = ledger["repository_key"]
    ref = _goal_ref(key, run_key(ledger["run_id"]), record.get("cycle", 1), record["stage"])
    event = {
        **ref, "stage_id": STAGE_KEYS[record["stage"] - 1], "outcome": outcome,
        "verified_at": verification["verified_at"], "receipt_sha256": record["receipt_sha256"],
    }
    observation = None
    if outcome == "merged":
        number = _positive(verification.get("pr_number"), "PR number")
        if (receipt.get("status") != "completed"
                or receipt.get("pr", {}).get("number") != number
                or receipt["pr"].get("head_sha") != verification.get("head_sha")):
            raise ProgressError("receipt PR differs from verified PR")
        head = _sha(verification.get("head_sha"), 40)
        merge = _sha(verification.get("merge_commit_sha"), 40)
        _date(verification.get("merged_at"))
        event.update(pr_number=number, pr_url=f"https://github.com/{github}/pull/{number}",
                     merge_commit_sha=merge)
        observation = {
            "repository_key": key, "run_key": ref["run_key"], "cycle": ref["cycle"],
            "stage_number": ref["stage_number"], "number": number, "state": "merged",
            "head_sha": head, "merge_commit_sha": merge, "merged_at": verification["merged_at"],
            "observed_at": verification["verified_at"], "source": "supervisor_closure",
        }
    elif receipt.get("status") != "no_changes" or receipt.get("pr") is not None:
        raise ProgressError("no-change closure contains a PR")
    return event, observation


def _pr_id(key: str, number: int) -> str:
    return digest(["pr", key, number])


def _ingest_pr(history: dict[str, Any], observation: dict[str, Any], github: str) -> None:
    key, number = observation["repository_key"], _positive(observation["number"], "PR number")
    identifier = _pr_id(key, number)
    state = observation["state"]
    if state not in {"open", "closed", "merged"}:
        raise ProgressError("invalid PR state")
    _sha(observation["head_sha"], 40)
    observed = _date(observation["observed_at"])
    ref = _goal_ref(key, observation["run_key"], observation["cycle"], observation["stage_number"])
    association = {
        "id": digest(["association", identifier, ref["id"]]), "pr_id": identifier,
        **{field: ref[field] for field in ("repository_key", "run_key", "cycle", "stage_number")},
    }
    if association not in history["associations"]:
        history["associations"].append(association)
    events = [event for event in history["pr_events"] if event["pr_id"] == identifier]
    latest = events[-1] if events else None
    event = {
        "pr_id": identifier, "repository_key": key, "number": number,
        "url": f"https://github.com/{github}/pull/{number}",
        "state": state, "head_sha": observation["head_sha"],
        "observed_at": observation["observed_at"], "source": observation["source"],
    }
    if state == "merged":
        event["merge_commit_sha"] = _sha(observation.get("merge_commit_sha"), 40)
        _date(observation.get("merged_at"))
        event["merged_at"] = observation["merged_at"]
    if latest:
        if latest["state"] == "merged" and (
            state != "merged" or event["merge_commit_sha"] != latest["merge_commit_sha"]
            or event["head_sha"] != latest["head_sha"]
        ):
            raise ProgressError("verified merged PR changed or regressed")
        # A prior closure can be older than a new GitHub observation. It still
        # creates its association, but cannot roll back current remote state.
        if observed < _date(latest["observed_at"]):
            if state == "merged" and latest["state"] != "merged":
                raise ProgressError("newer PR state contradicts verified merge")
            return
        state_fields = ("state", "head_sha", "merge_commit_sha", "merged_at")
        if all(event.get(field) == latest.get(field) for field in state_fields):
            return
    event["sequence"] = len(events) + 1
    event["id"] = digest([identifier, event["sequence"], event])
    history["pr_events"].append(event)


def validate_history(history: dict[str, Any], manifest: FleetManifest | None = None) -> None:
    """Validate shape, public-field allowlists, event identity and monotonicity."""
    _shape(history, "ProgressHistory")
    fleet = manifest or load_fleet_manifest()
    seen: dict[str, dict[str, Any]] = {}
    for event in history["closures"]:
        ref = _goal_ref(event["repository_key"], event["run_key"], event["cycle"], event["stage_number"])
        if event["id"] != ref["id"] or event["id"] in seen:
            raise ProgressError("duplicate or altered goal closure identity")
        if event["repository_key"] not in fleet.mechs:
            raise ProgressError("unknown repository in history")
        if event["stage_id"] != STAGE_KEYS[event["stage_number"] - 1]:
            raise ProgressError("stage identity mismatch")
        _date(event["verified_at"])
        if event["outcome"] == "merged":
            expected = f"https://github.com/{fleet.mechs[event['repository_key']].github}/pull/{event.get('pr_number')}"
            if event.get("pr_url") != expected or not event.get("merge_commit_sha"):
                raise ProgressError("closure PR provenance mismatch")
        elif any(field in event for field in ("pr_url", "pr_number", "merge_commit_sha")):
            raise ProgressError("no-change closure has PR provenance")
        seen[event["id"]] = event
    latest: dict[str, dict[str, Any]] = {}
    for event in history["pr_events"]:
        key = event["repository_key"]
        if key not in fleet.mechs:
            raise ProgressError("unknown repository in PR history")
        identifier = _pr_id(key, event["number"])
        if (event["pr_id"] != identifier
                or event["url"] != f"https://github.com/{fleet.mechs[key].github}/pull/{event['number']}"):
            raise ProgressError("PR identity mismatch")
        prior = latest.get(identifier)
        if event["sequence"] != (prior["sequence"] + 1 if prior else 1):
            raise ProgressError("PR event sequence is not contiguous")
        without_id = {k: v for k, v in event.items() if k != "id"}
        if event["id"] != digest([identifier, event["sequence"], without_id]):
            raise ProgressError("PR event digest changed")
        if prior and _date(event["observed_at"]) < _date(prior["observed_at"]):
            raise ProgressError("PR observation timestamp regressed")
        _date(event["observed_at"])
        if event["state"] == "merged":
            _sha(event.get("merge_commit_sha"), 40)
            _date(event.get("merged_at"))
        elif "merge_commit_sha" in event or "merged_at" in event:
            raise ProgressError("unmerged PR has merge provenance")
        if prior and prior["state"] == "merged":
            raise ProgressError("merged PR cannot acquire another state transition")
        latest[identifier] = event
    association_ids = set()
    for item in history["associations"]:
        ref = _goal_ref(item["repository_key"], item["run_key"], item["cycle"], item["stage_number"])
        if (item["pr_id"] not in latest
                or latest[item["pr_id"]]["repository_key"] != item["repository_key"]
                or item["id"] != digest(["association", item["pr_id"], ref["id"]])
                or item["id"] in association_ids):
            raise ProgressError("invalid or duplicate PR goal association")
        association_ids.add(item["id"])
    cursor_ids = set()
    for item in history["cursors"]:
        identity = (item["repository_key"], item["run_key"])
        if identity in cursor_ids or item["repository_key"] not in fleet.mechs:
            raise ProgressError("duplicate or unknown run cursor")
        cursor_ids.add(identity)
        if item["stage_id"] != STAGE_KEYS[item["stage_number"] - 1]:
            raise ProgressError("cursor stage identity mismatch")
        _date(item["observed_at"])
        _date(item["started_at"])
    for closure in history["closures"]:
        if (closure["repository_key"], closure["run_key"]) not in cursor_ids:
            raise ProgressError("closure lacks run cursor")
    for item in history["associations"]:
        if (item["repository_key"], item["run_key"]) not in cursor_ids:
            raise ProgressError("PR association lacks run cursor")
    if set(latest) != {item["pr_id"] for item in history["associations"]}:
        raise ProgressError("PR history lacks an explicit goal association")
    for closure in history["closures"]:
        if closure["outcome"] != "merged":
            continue
        identifier = _pr_id(closure["repository_key"], closure["pr_number"])
        pr = latest.get(identifier)
        association_id = digest(["association", identifier, closure["id"]])
        if (pr is None or pr["state"] != "merged"
                or pr["merge_commit_sha"] != closure["merge_commit_sha"]
                or association_id not in association_ids):
            raise ProgressError("merged closure lacks matching PR evidence and association")


def _counts(closures: list[dict[str, Any]], prs: list[dict[str, Any]]) -> dict[str, int]:
    cycles: dict[tuple[str, str, int], set[int]] = {}
    for event in closures:
        cycles.setdefault((event["repository_key"], event["run_key"], event["cycle"]), set()).add(event["stage_number"])
    return {
        "completed_cycles": sum(stages == set(range(1, 7)) for stages in cycles.values()),
        "completed_goals": len(closures), "unique_prs": len(prs),
        "merged_prs": sum(pr["state"] == "merged" for pr in prs),
        "open_prs": sum(pr["state"] == "open" for pr in prs),
        "closed_prs": sum(pr["state"] == "closed" for pr in prs),
        "no_change_goals": sum(event["outcome"] == "no_changes" for event in closures),
    }


def snapshot_from_history(history: dict[str, Any], *, generated_at: str,
                          manifest: FleetManifest | None = None) -> dict[str, Any]:
    fleet = manifest or load_fleet_manifest()
    validate_history(history, fleet)
    _date(generated_at)
    repositories: list[dict[str, Any]] = []
    for key, mech in fleet.mechs.items():
        cursors = [cursor for cursor in history["cursors"] if cursor["repository_key"] == key]
        current = max(cursors, key=lambda c: (_date(c["started_at"]), _date(c["observed_at"]))) if cursors else None
        closures = [event for event in history["closures"] if event["repository_key"] == key]
        latest: dict[str, dict[str, Any]] = {}
        for event in history["pr_events"]:
            if event["repository_key"] == key:
                latest[event["pr_id"]] = event
        prs = []
        for identifier, event in latest.items():
            pr = {k: v for k, v in event.items() if k not in {"sequence", "pr_id"}}
            pr["id"] = identifier
            pr["associations"] = [
                {k: v for k, v in item.items() if k in {"run_key", "cycle", "stage_number"}}
                for item in history["associations"] if item["pr_id"] == identifier
            ]
            prs.append(pr)
        stages = []
        for number, stage_key in enumerate(STAGE_KEYS, 1):
            completed = current is not None and any(
                event["run_key"] == current["run_key"] and event["cycle"] == current["cycle"]
                and event["stage_number"] == number for event in closures
            )
            state = "unverified"
            if completed:
                state = "completed"
            elif current:
                state = "current" if number == current["stage_number"] else (
                    "pending" if number > current["stage_number"] else "unverified"
                )
            stages.append({"number": number, "key": stage_key, "state": state})
        row: dict[str, Any] = {
            "key": key, "name": mech.display_name, "github_url": f"https://github.com/{mech.github}",
            "counters": _counts(closures, prs), "stages": stages, "closures": closures,
            "pull_requests": sorted(prs, key=lambda pr: pr["number"], reverse=True),
            "history_coverage": "partial" if cursors else "unobserved",
        }
        if current:
            row["current"] = {k: v for k, v in current.items() if k not in {"repository_key", "started_at"}}
            row["last_observed_at"] = current["observed_at"]
        repositories.append(row)
    result = {
        "schema_version": VERSION, "generated_at": generated_at,
        "tracking": {"history_scope": "verified_goal_associations", "earlier_history": "unknown",
                     "counts_are_lower_bounds": True},
        "totals": {key: sum(row["counters"][key] for row in repositories) for key in COUNTERS},
        "repositories": repositories,
    }
    validate_snapshot(result, fleet)
    return result


def validate_snapshot(snapshot: dict[str, Any], manifest: FleetManifest | None = None) -> None:
    _shape(snapshot, "ProgressSnapshot")
    fleet = manifest or load_fleet_manifest()
    _date(snapshot["generated_at"])
    if snapshot["tracking"]["counts_are_lower_bounds"] is not True:
        raise ProgressError("historical counts must remain explicitly partial")
    if [row["key"] for row in snapshot["repositories"]] != list(fleet.keys):
        raise ProgressError("snapshot must contain the complete manifest fleet in order")
    for row in snapshot["repositories"]:
        mech = fleet.mechs[row["key"]]
        if row["github_url"] != f"https://github.com/{mech.github}" or row["name"] != mech.display_name:
            raise ProgressError("snapshot repository identity differs from manifest")
        if row["counters"] != _counts(row["closures"], row["pull_requests"]):
            raise ProgressError("snapshot counts differ from evidence")
        if [(stage["number"], stage["key"]) for stage in row["stages"]] != list(enumerate(STAGE_KEYS, 1)):
            raise ProgressError("snapshot stages differ from canonical workflow")
        pr_ids = set()
        for pr in row["pull_requests"]:
            if (pr["repository_key"] != row["key"] or pr["id"] in pr_ids
                    or pr["id"] != _pr_id(row["key"], pr["number"])
                    or pr["url"] != f"https://github.com/{mech.github}/pull/{pr['number']}"):
                raise ProgressError("snapshot PR identity differs from manifest or is duplicated")
            pr_ids.add(pr["id"])
            _date(pr["observed_at"])
        if any(event["repository_key"] != row["key"] for event in row["closures"]):
            raise ProgressError("snapshot contains another repository's closure")
    if snapshot["totals"] != {
        key: sum(row["counters"][key] for row in snapshot["repositories"]) for key in COUNTERS
    }:
        raise ProgressError("snapshot totals differ from repository counts")


def validate_bundle(history: dict[str, Any], snapshot: dict[str, Any],
                    manifest: FleetManifest | None = None) -> None:
    """Require the public snapshot to be exactly the projection of its history."""
    validate_snapshot(snapshot, manifest)
    expected = snapshot_from_history(history, generated_at=snapshot["generated_at"], manifest=manifest)
    if snapshot != expected:
        raise ProgressError("snapshot differs from its history")


def validate_extension(previous: dict[str, Any], new: dict[str, Any],
                       manifest: FleetManifest | None = None) -> None:
    """Reject history replacement, deletion, rewriting and cursor rollback."""
    validate_history(previous, manifest)
    validate_history(new, manifest)
    for field in ("closures", "pr_events", "associations"):
        if new[field][:len(previous[field])] != previous[field]:
            raise ProgressError(f"append-only history changed: {field}")
    cursors = {(item["repository_key"], item["run_key"]): item for item in new["cursors"]}
    for old in previous["cursors"]:
        current = cursors.get((old["repository_key"], old["run_key"]))
        if current is None:
            raise ProgressError("historical run cursor disappeared")
        if (current["started_at"] != old["started_at"]
                or (current["cycle"], current["stage_number"]) < (old["cycle"], old["stage_number"])
                or _date(current["observed_at"]) < _date(old["observed_at"])):
            raise ProgressError("historical run cursor regressed")


def collect_progress(
    runtime_dirs: list[Path], previous_history: dict[str, Any] | None = None, *,
    generated_at: str | None = None, manifest: FleetManifest | None = None,
    verified_pr_observations: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Read explicit supervisor runs and return history plus a public snapshot.

    Omitted old runs retain their history. Supplied runs must retain every
    previously observed closure and must not regress cycle, stage or timestamp.
    Repeated collection is idempotent apart from fresher observation cursors.
    The caller must serialize this read/modify/write operation with an exclusive
    lock, and preserve the previous history on failure.
    """
    fleet = manifest or load_fleet_manifest()
    generated = _date(generated_at) if generated_at is not None else None
    history = copy.deepcopy(previous_history) if previous_history is not None else {
        "schema_version": VERSION, "closures": [], "pr_events": [], "associations": [], "cursors": [],
    }
    validate_history(history, fleet)
    old_closures = {event["id"]: event for event in history["closures"]}
    observations: list[dict[str, Any]] = []
    run_sources: set[str] = set()
    for runtime in runtime_dirs:
        runtime = Path(runtime)
        config = read_json(runtime / "config.json")
        run = run_key(config["run_id"])
        if run in run_sources:
            raise ProgressError("duplicate source for one supervisor run")
        run_sources.add(run)
        targets = config.get("targets")
        if not isinstance(targets, list) or not targets:
            raise ProgressError("run config has no targets")
        target_keys: set[str] = set()
        for target in targets:
            key = target["repository_key"]
            if key in target_keys or key not in fleet.mechs:
                raise ProgressError("duplicate or unknown run target")
            target_keys.add(key)
            if target.get("github_repository") != fleet.mechs[key].github:
                raise ProgressError("run repository identity differs from fleet")
            directory = runtime / key
            ledger = read_json(directory / "ledger.json")
            if (ledger.get("schema_version") not in {1, 2}
                    or ledger.get("repository_key") != key or ledger.get("run_id") != config["run_id"]):
                raise ProgressError("ledger identity differs from run config")
            cycle = _positive(ledger.get("cycle", 1), "cycle")
            stage = _positive(ledger["stage"], "stage", 6)
            observed_at = ledger["last_observed_at"]
            if generated is not None and _date(observed_at) > generated:
                raise ProgressError("supervisor observation is in the future")
            phase = ledger.get("phase")
            phase = phase if isinstance(phase, str) and phase in PHASES else "unknown"
            cursor = {
                "repository_key": key, "run_key": run, "cycle": cycle, "stage_number": stage,
                "stage_id": STAGE_KEYS[stage - 1], "phase": phase,
                "blocker_code": _blocker(ledger.get("blocked_reason"), phase),
                "observed_at": observed_at, "started_at": ledger["created_at"],
            }
            prior_cursor = next((c for c in history["cursors"]
                                 if c["repository_key"] == key and c["run_key"] == run), None)
            if prior_cursor:
                if (cursor["started_at"] != prior_cursor["started_at"]
                        or (cycle, stage) < (prior_cursor["cycle"], prior_cursor["stage_number"])
                        or _date(observed_at) < _date(prior_cursor["observed_at"])):
                    raise ProgressError("supervisor run cursor regressed")
                history["cursors"].remove(prior_cursor)
            history["cursors"].append(cursor)
            found = set()
            records = ledger.get("completed_stages")
            if not isinstance(records, list):
                raise ProgressError("ledger has no completed-stage history")
            for record in records:
                event, observation = _closure(directory, record, ledger, fleet.mechs[key].github)
                if (event["cycle"], event["stage_number"]) >= (cycle, stage):
                    raise ProgressError("closure is not before the current goal")
                if event["id"] in found:
                    raise ProgressError("duplicate closure in source ledger")
                found.add(event["id"])
                old = old_closures.get(event["id"])
                if old is not None and old != event:
                    raise ProgressError("previously verified closure changed")
                if old is None:
                    history["closures"].append(event)
                    old_closures[event["id"]] = event
                if observation:
                    observations.append(observation)
            prior_ids = {event["id"] for event in history["closures"]
                         if event["repository_key"] == key and event["run_key"] == run}
            if not prior_ids <= found:
                raise ProgressError("previously verified closures disappeared")
        old_targets = {cursor["repository_key"] for cursor in history["cursors"] if cursor["run_key"] == run}
        if not old_targets <= target_keys:
            raise ProgressError("previously observed run target disappeared")
    for observation in verified_pr_observations or []:
        item = copy.deepcopy(observation)
        key = item["repository_key"]
        if "run_id" in item:
            opaque = run_key(item.pop("run_id"))
            if "run_key" in item and item["run_key"] != opaque:
                raise ProgressError("PR association has conflicting run identity")
            item["run_key"] = opaque
        else:
            existing = any(
                association["repository_key"] == key and association["run_key"] == item.get("run_key")
                and association["cycle"] == item["cycle"]
                and association["stage_number"] == item.get("stage", item.get("stage_number"))
                and association["pr_id"] == _pr_id(key, item["number"])
                for association in history["associations"]
            )
            if not existing:
                raise ProgressError("opaque run key can only refresh an existing PR association")
        if "stage" in item:
            stage_value = item.pop("stage")
            if "stage_number" in item and item["stage_number"] != stage_value:
                raise ProgressError("PR association has conflicting stage identity")
            item["stage_number"] = stage_value
        _positive(item["stage_number"], "PR goal stage", 6)
        _positive(item["cycle"], "PR goal cycle")
        pr_cursor = next((c for c in history["cursors"]
                          if c["repository_key"] == key and c["run_key"] == item["run_key"]), None)
        if pr_cursor is None or (item["cycle"], item["stage_number"]) > (pr_cursor["cycle"], pr_cursor["stage_number"]):
            raise ProgressError("PR association has no observed goal")
        if generated is not None and _date(item["observed_at"]) > generated:
            raise ProgressError("PR observation is in the future")
        item["source"] = "github"
        observations.append(item)
    for observation in sorted(observations, key=lambda item: _date(item["observed_at"])):
        _ingest_pr(history, observation, fleet.mechs[observation["repository_key"]].github)
    generated_at = generated_at or datetime.now(timezone.utc).isoformat()
    final_time = _date(generated_at)
    if any(_date(item["observed_at"]) > final_time for item in history["cursors"] + history["pr_events"]):
        raise ProgressError("observation is in the future")
    validate_history(history, fleet)
    if previous_history is not None:
        validate_extension(previous_history, history, fleet)
    snapshot = snapshot_from_history(history, generated_at=generated_at, manifest=fleet)
    return history, snapshot
