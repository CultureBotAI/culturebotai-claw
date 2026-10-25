#!/usr/bin/env python3
"""Archive verified Mech snapshots and separately attributed chat responses.

This command reads existing evidence. It never collects, publishes, or changes
supervisor/publisher state. The report directory is local and may contain
private supplementary observations.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from mech_progress_status import format_summary, freshness_warnings

from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_progress import ProgressError, atomic_write_json, read_json, validate_bundle

DEFAULT_REPORT = Path("workspace/reports/mech-stats")


def stamp(value: str) -> datetime:
    if not isinstance(value, str):
        raise ProgressError("timestamp must be text")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.utcoffset() is None:
        raise ProgressError("timestamp must include a timezone")
    return parsed


def encode(value) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def regular_bytes(path: Path) -> bytes:
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as stream:
        metadata = os.fstat(stream.fileno())
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > 64 * 1024 * 1024:
            raise ProgressError("report input must be a bounded regular file")
        return stream.read()


def save_evidence(root: Path, relative: str, raw: bytes) -> dict:
    # Reject redirected output before creating directories or files.
    relative_path = Path(relative)
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ProgressError("evidence must stay inside the report")
    directory = root
    for component in relative_path.parts[:-1]:
        directory = directory / component
        if directory.is_symlink():
            raise ProgressError("evidence directory must not be a symlink")
        directory.mkdir(exist_ok=True)
    path = root / relative
    if path.exists() or path.is_symlink():
        if regular_bytes(path) != raw:
            raise ProgressError("archived evidence changed")
    else:
        descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=".evidence-")
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            descriptor = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
    return {"path": relative, "sha256": sha(raw)}


def evidence_path(root: Path, reference: dict) -> Path:
    if set(reference) != {"path", "sha256"}:
        raise ProgressError("invalid evidence reference")
    relative = Path(reference["path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise ProgressError("evidence must stay inside the report")
    path = root / relative
    if not path.resolve().is_relative_to(root.resolve()):
        raise ProgressError("evidence escapes the report directory")
    if sha(regular_bytes(path)) != reference["sha256"]:
        raise ProgressError("archived evidence hash mismatch")
    return path


def snapshot_facts(snapshot: dict) -> dict:
    return {
        "as_of": snapshot["generated_at"],
        "mech_count": len(snapshot["repositories"]),
        "totals": snapshot["totals"],
        "summary": format_summary(snapshot),
        "tracking": snapshot["tracking"],
        "per_mech": [{key: row[key] for key in (
            "key", "name", "github_url", "counters", "history_coverage",
            "current", "last_observed_at",
        ) if key in row} for row in snapshot["repositories"]],
    }


def reported_counts(text: str) -> dict:
    """Parse only the leading stats line, never numbers in stale qualifications."""
    match = re.match(
        r"\A(\d+) Mechs?, (\d+) PRs? \((\d+) merged, (\d+) open"
        r"(?:, (\d+) closed without merge)?\), (\d+) completed goals?, "
        r"(\d+) completed cycles?(?:\.|\n|$)", text,
    )
    if match is None:
        raise ProgressError("response does not start with an unambiguous stats line")
    values = [int(value or 0) for value in match.groups()]
    result = dict(zip(("mech_count", "unique_prs", "merged_prs", "open_prs", "closed_prs",
                       "completed_goals", "completed_cycles"), values))
    if result["unique_prs"] != sum(result[key] for key in ("merged_prs", "open_prs", "closed_prs")):
        raise ProgressError("reported PR counts do not add up")
    return result


def response_record(value: dict, snapshot_id: str | None, recorded_at: str) -> dict:
    required = {"source_id", "source", "text_kind", "text", "responded_at", "prompt"}
    optional = {"prompted_at", "source_ref", "reported_counts", "reported_summary", "superseded_by"}
    if not required <= set(value) or set(value) - required - optional:
        raise ProgressError("response needs source_id, source, text_kind, text, responded_at, and prompt")
    for key in ("source_id", "source", "text"):
        if not isinstance(value[key], str) or not value[key].strip():
            raise ProgressError(f"response {key} must be nonempty text")
    if value["text_kind"] not in {"verbatim", "summary"}:
        raise ProgressError("response text_kind must be verbatim or summary")
    if value["responded_at"] is not None:
        stamp(value["responded_at"])
    if value["prompt"] is not None and not isinstance(value["prompt"], str):
        raise ProgressError("response prompt must be text or null")
    if value.get("prompted_at") is not None:
        stamp(value["prompted_at"])
    summary = value.get("reported_summary", value["text"])
    if "reported_summary" in value and (not isinstance(summary, str) or not summary
                                         or value["text"].count(summary) != 1):
        raise ProgressError("reported summary must be an exact unique excerpt of the response")
    if ("reported_counts" in value or "reported_summary" in value
            or re.match(r"\A\d+ Mechs?,", summary)):
        counts = reported_counts(summary)
        if "reported_counts" in value and value["reported_counts"] != counts:
            raise ProgressError("reported counts differ from the original response text")
        value = {**value, "reported_counts": counts}
    if "source_ref" in value:
        reference = value["source_ref"]
        if (not isinstance(reference, dict) or set(reference) != {
                "transcript_path", "prompt_line", "response_line", "message_id"}
                or not all(isinstance(reference[key], str) and reference[key]
                           for key in ("transcript_path", "message_id"))
                or any(type(reference[key]) is not int or reference[key] < 1
                       for key in ("prompt_line", "response_line"))):
            raise ProgressError("invalid response transcript reference")
    if "superseded_by" in value and (not isinstance(value["superseded_by"], str) or not value["superseded_by"]):
        raise ProgressError("superseded response needs a successor source_id")
    return {**value, "snapshot_id": snapshot_id, "recorded_at": recorded_at}


def same_response(existing: dict, candidate: dict) -> bool:
    """Compare content without rewriting legacy rows that lack derived counts."""
    values = {key: value for key, value in existing.items()
              if key not in {"snapshot_id", "recorded_at"}}
    normalized = response_record(values, existing["snapshot_id"], existing["recorded_at"])
    return all(key in normalized and normalized[key] == value
               for key, value in candidate.items() if key != "recorded_at")


def validate_report(root: Path, report: dict) -> None:
    required = {"schema_version", "snapshots", "responses"}
    if not required <= set(report) or set(report) - required - {"response_only_observations"} or report["schema_version"] != 1:
        raise ProgressError("unsupported stats report")
    if not isinstance(report["snapshots"], list) or not isinstance(report["responses"], list):
        raise ProgressError("stats report records must be lists")
    identities = set()
    order = []
    for record in report["snapshots"]:
        identity = record["id"]
        if identity in identities:
            raise ProgressError("duplicate snapshot")
        identities.add(identity)
        archive = record["evidence"]
        bundle_path = evidence_path(root, archive["bundle"])
        fleet_path = evidence_path(root, archive["fleet"])
        expected_id = sha(encode([archive["bundle"]["sha256"], archive["fleet"]["sha256"]]))
        if identity != expected_id:
            raise ProgressError("snapshot identity differs from evidence")
        fleet = load_fleet_manifest(fleet_path)
        bundle = read_json(bundle_path)
        validate_bundle(bundle["history"], bundle["snapshot"], fleet)
        facts = snapshot_facts(bundle["snapshot"])
        if any(record.get(key) != value for key, value in facts.items()):
            raise ProgressError("report counts or per-Mech facts differ from evidence")
        for supplement in archive["supplements"]:
            evidence_path(root, supplement)
        checked = stamp(record["freshness_at_recording"]["checked_at"])
        if record["freshness_at_recording"]["warnings"] != freshness_warnings(bundle["snapshot"], checked):
            raise ProgressError("freshness qualification differs from evidence")
        stamp(record["recorded_at"])
        order.append(stamp(record["as_of"]))
    if order != sorted(order):
        raise ProgressError("snapshot timeline is not chronological")
    seen = set()
    response_only = report.get("response_only_observations", [])
    if not isinstance(response_only, list):
        raise ProgressError("response-only observations must be a list")
    all_responses = report["responses"] + response_only
    for record in all_responses:
        linked = record in report["responses"]
        if (record["source_id"] in seen
                or (linked and record["snapshot_id"] not in identities)
                or (not linked and record["snapshot_id"] is not None)):
            raise ProgressError("duplicate response or missing response snapshot")
        seen.add(record["source_id"])
        stamp(record["recorded_at"])
        values = {key: value for key, value in record.items() if key not in {"snapshot_id", "recorded_at"}}
        checked_response = response_record(values, record["snapshot_id"], record["recorded_at"])
        if not linked and "reported_counts" not in record:
            raise ProgressError("response-only observations require explicit reported counts")
        if linked and "reported_counts" in checked_response:
            snapshot = next(row for row in report["snapshots"] if row["id"] == record["snapshot_id"])
            facts = {"mech_count": snapshot["mech_count"], **snapshot["totals"]}
            if any(facts[key] != count for key, count in checked_response["reported_counts"].items()):
                raise ProgressError("response counts do not match the linked snapshot")
    for record in all_responses:
        if "superseded_by" in record and (record["superseded_by"] not in seen or record["superseded_by"] == record["source_id"]):
            raise ProgressError("superseded response does not reference another response")
    successors = {row["source_id"]: row["superseded_by"] for row in all_responses
                  if "superseded_by" in row}
    resolved = set()
    for start in successors:
        visited, cursor = set(), start
        while cursor in successors and cursor not in resolved:
            if cursor in visited:
                raise ProgressError("response supersession contains a cycle")
            visited.add(cursor)
            cursor = successors[cursor]
        resolved.update(visited)


def record_response_history(report_dir: Path, entries: list[dict], *,
                            supersedes: dict[str, str] | None = None,
                            now: datetime | None = None) -> dict:
    """Import attributed transcript replies without inventing missing snapshots.

    Entries explicitly select a validated snapshot_id or null. An unlinked
    reply retains reported counters only; it never becomes verified evidence.
    """
    now = now or datetime.now(timezone.utc)
    if report_dir.is_symlink():
        raise ProgressError("report directory must not be a symlink")
    descriptor = os.open(report_dir / ".record.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as lock:
        if not stat.S_ISREG(os.fstat(lock.fileno()).st_mode):
            raise ProgressError("report lock must be regular")
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = report_dir / "report.json"
        report = read_json(path)
        validate_report(report_dir, report)
        before = encode(report)
        report.setdefault("response_only_observations", [])
        for entry in entries:
            values = {key: value for key, value in entry.items() if key != "snapshot_id"}
            values["reported_counts"] = reported_counts(values.get("reported_summary", values["text"]))
            row = response_record(values, entry["snapshot_id"], now.isoformat())
            existing = next((item for item in report["responses"] + report["response_only_observations"]
                             if item["source_id"] == row["source_id"]), None)
            if existing:
                if not same_response(existing, row):
                    raise ProgressError("response source_id already records different content")
            else:
                report["responses" if row["snapshot_id"] is not None else "response_only_observations"].append(row)
        for older, newer in (supersedes or {}).items():
            row = next(item for item in report["responses"] + report["response_only_observations"] if item["source_id"] == older)
            if "superseded_by" in row and row["superseded_by"] != newer:
                raise ProgressError("response already has a different successor")
            row["superseded_by"] = newer
        for collection in ("responses", "response_only_observations"):
            report[collection].sort(key=lambda row: (row["responded_at"] is None,
                stamp(row["responded_at"] or row["recorded_at"]), row["source_id"]))
        validate_report(report_dir, report)
        if before != encode(report):
            atomic_write_json(path, report)
        return {"responses": len(report["responses"]),
                "response_only_observations": len(report["response_only_observations"]),
                "status": "unchanged" if before == encode(report) else "recorded"}


def record_stats(bundle_path: Path, report_dir: Path, *, manifest_path: Path | None = None,
                 response: dict | None = None, observations_path: Path | None = None,
                 source: str = "saved tracker bundle", now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    stamp(now.isoformat())
    if not isinstance(source, str) or not source.strip():
        raise ProgressError("snapshot source must be nonempty text")
    if manifest_path is None:
        adjacent = bundle_path.parent / "fleet.yaml"
        try:
            adjacent.lstat()
        except FileNotFoundError:
            pass
        else:
            manifest_path = adjacent
    if manifest_path is not None and not stat.S_ISREG(manifest_path.lstat().st_mode):
        raise ProgressError("pinned manifest must be a regular file")
    fleet = load_fleet_manifest(manifest_path)
    fleet_raw = regular_bytes(fleet.source)
    bundle = read_json(bundle_path)
    validate_bundle(bundle["history"], bundle["snapshot"], fleet)
    bundle_raw = encode(bundle)
    identity = sha(encode([sha(bundle_raw), sha(fleet_raw)]))
    response = response_record(response, identity, now.isoformat()) if response is not None else None
    supplemental = None
    if observations_path is not None:
        supplemental = regular_bytes(observations_path)
        # Retained as raw supplemental provenance, never used to derive counts.
        parsed = json.loads(supplemental)
        if not isinstance(parsed, list) or any(not isinstance(item, dict) for item in parsed):
            raise ProgressError("supplementary observations must be a JSON list of objects")
        json.dumps(parsed, allow_nan=False)
    if report_dir.is_symlink():
        raise ProgressError("report directory must not be a symlink")
    report_dir.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(report_dir / ".record.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "w") as lock:
        if not stat.S_ISREG(os.fstat(lock.fileno()).st_mode):
            raise ProgressError("report lock must be regular")
        fcntl.flock(lock, fcntl.LOCK_EX)
        path = report_dir / "report.json"
        report = read_json(path) if path.exists() or path.is_symlink() else {"schema_version": 1, "snapshots": [], "responses": []}
        validate_report(report_dir, report)
        before = encode(report)
        prior_response = next((row for row in report["responses"] if response and row["source_id"] == response["source_id"]), None)
        if prior_response and not same_response(prior_response, response):
            raise ProgressError("response source_id already records different content")
        entry = next((row for row in report["snapshots"] if row["id"] == identity), None)
        if entry is None:
            base = f"snapshots/{identity}"
            entry = {
                "id": identity, "recorded_at": now.isoformat(),
                "source": {"description": source, "bundle_path": str(bundle_path.resolve())},
                **snapshot_facts(bundle["snapshot"]),
                "freshness_at_recording": {"checked_at": now.isoformat(),
                    "warnings": freshness_warnings(bundle["snapshot"], now)},
                "evidence": {
                    "bundle": save_evidence(report_dir, f"{base}/bundle.json", bundle_raw),
                    "fleet": save_evidence(report_dir, f"{base}/fleet.yaml", fleet_raw),
                    "supplements": [],
                },
            }
            report["snapshots"].append(entry)
        if supplemental is not None:
            reference = save_evidence(report_dir, f"snapshots/{identity}/observations-{sha(supplemental)}.json", supplemental)
            if reference not in entry["evidence"]["supplements"]:
                entry["evidence"]["supplements"].append(reference)
        if response is not None and prior_response is None:
            report["responses"].append(response)
        report["snapshots"].sort(key=lambda row: stamp(row["as_of"]))
        # Unknown message times remain null; archive order is never presented as message order.
        report["responses"].sort(key=lambda row: (row["responded_at"] is None,
            stamp(row["responded_at"] or row["recorded_at"]), row["source_id"]))
        validate_report(report_dir, report)
        changed = before != encode(report)
        if changed:
            atomic_write_json(path, report)
        return {"status": "recorded" if changed else "unchanged", "report": str(path.resolve()),
                "snapshots": len(report["snapshots"]), "responses": len(report["responses"]),
                "snapshot_id": identity, "summary": format_summary(bundle["snapshot"])}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, default=Path("workspace/progress-publisher/bundle.json"))
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--report-dir", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--response-file", type=Path, help="attributed response JSON; omission records only a snapshot")
    parser.add_argument("--observations", type=Path, help="optional raw supplementary PR observations")
    parser.add_argument("--source", default="saved tracker bundle")
    args = parser.parse_args(argv)
    try:
        result = record_stats(args.bundle, args.report_dir, manifest_path=args.manifest,
            response=read_json(args.response_file) if args.response_file else None,
            observations_path=args.observations, source=args.source)
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(f"Stats were not recorded: {error}", file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
