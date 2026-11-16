"""Prepare review-only Scaleup admission evidence for #1254/#1076, 2026-11-15.

Inputs: immutable Scaleup Git tree, live repository metadata, current canonical
artifacts, and retained #1074 capability proposal. Outputs: bounded JSON evidence
and a conservative candidate YAML under docs/reviews; no fleet or remote writes.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import yaml

from kg_microbe_governance.artifacts.scripts.check_vendored_sync import parse_manifest
from kg_microbe_governance.infrastructure_admission import NATIVE_TESTS

ROOT = Path(__file__).resolve().parents[2]
REPOSITORY = "CultureBotAI/ScaleupMech"
REPOSITORY_ID = 1450887724
REVISION = "3a512d53e9b9d797cace768fea896a196ec24588"
RETAINED_SOURCE = "1d2b648a3631d4af374bb56c6d8315bf6d2674bf"
FLEET_PATH = "src/kg_microbe_fleet/fleet.yaml"
MANIFEST_PATH = "src/kg_microbe_governance/vendored_artifacts.json"


def command(*args: str) -> bytes:
    return subprocess.run(args, cwd=ROOT, check=True, capture_output=True).stdout


def api(path: str):
    return json.loads(command("gh", "api", path))


def capture() -> tuple[dict, dict]:
    repository = api(f"repos/{REPOSITORY}")
    if (repository["full_name"] != REPOSITORY or repository["id"] != REPOSITORY_ID
            or repository["private"] is not False or repository["default_branch"] != "main"):
        raise ValueError("Scaleup identity/public default-branch evidence changed")
    commit = api(f"repos/{REPOSITORY}/commits/main")
    observed = commit["sha"]
    if observed != REVISION:
        raise ValueError("Scaleup main moved; review the new revision before recapture")
    tree_sha = commit["commit"]["tree"]["sha"]
    tree = api(f"repos/{REPOSITORY}/git/trees/{tree_sha}?recursive=1")
    if tree["sha"] != tree_sha:
        raise ValueError("Git tree response does not identify the committed root tree")
    if tree["truncated"]:
        raise ValueError("Truncated Git tree cannot establish artifact completeness")
    blobs = {row["path"]: row for row in tree["tree"] if row["type"] == "blob"}
    native_paths = [
        "scripts/.vendored_canon_ref", ".github/workflows/validate-strict.yaml",
        "workflow/mech-template.json", "justfile", "CLAUDE.md", ".agents/skills",
    ]
    native = {}
    for path in native_paths:
        raw = base64.b64decode(api(f"repos/{REPOSITORY}/git/blobs/{blobs[path]['sha']}")["content"])
        native[path] = {"git_blob": blobs[path]["sha"], "mode": blobs[path]["mode"],
                        "sha256": hashlib.sha256(raw).hexdigest(), "content": raw.decode()}
    manifest_raw = (ROOT / MANIFEST_PATH).read_bytes()
    manifest = parse_manifest(manifest_raw)
    required = [a for a in manifest.artifacts if not a.consumers or a.artifact_id in NATIVE_TESTS]
    artifacts = []
    for artifact in required:
        target = artifact.target.replace("{package_path}", "src/scaleupmech")
        source = (ROOT / artifact.source).read_bytes()
        if hashlib.sha256(source).hexdigest() != artifact.sha256:
            raise ValueError(f"Canonical artifact digest mismatch: {artifact.artifact_id}")
        current_blob = hashlib.sha1(b"blob " + str(len(source)).encode() + b"\0" + source).hexdigest()
        found = blobs.get(target)
        artifacts.append({
            "id": artifact.artifact_id, "path": target,
            "present": found is not None,
            "observed_git_blob": found["sha"] if found else None,
            "observed_mode": found["mode"] if found else None,
            "current_canonical_sha256": artifact.sha256,
            "matches_current_canonical_content": bool(found and found["sha"] == current_blob),
            "matches_current_canonical_mode": bool(found and found["mode"] == f"100{artifact.mode:03o}"),
        })
    entry = yaml.safe_load(command("git", "show", f"{RETAINED_SOURCE}:{FLEET_PATH}"))["mechs"]["scaleupmech"]
    current = yaml.safe_load((ROOT / FLEET_PATH).read_bytes())
    if set(entry["capabilities"]) != set(current["capability_catalogue"]):
        raise ValueError("Current capability catalogue changed; review every candidate decision")
    reasons = {
        "id_label_validation": "Native validator files are present; a scale-transfer ontology adapter remains unverified.",
        "curation_history": "Native history schema is present; the append-only scale-transfer write workflow remains unverified.",
        "record_review": "Native review profile and helpers are present; generic record-review capability promotion needs separate review.",
        "strict_validation": "Native scale-transfer validation is present; shared general-agent recipe compatibility remains unverified.",
        "schema_sync": "The native scale-transfer schema is present; shared generation adapter compatibility remains unverified.",
        "release_management": "Native infrastructure is present; shared release recipe compatibility remains unverified.",
        "build_coordination": "Native infrastructure is present; shared build recipe compatibility remains unverified.",
        "documentation": "Native documentation is present; shared documentation recipe compatibility remains unverified.",
        "testing": "Native tests are present; shared general-agent test recipe compatibility remains unverified.",
        "refactoring": "Native development infrastructure is present; shared refactoring adapter compatibility remains unverified.",
        "edison_key_discovery": "The reviewed scale-transfer admission does not adopt an Edison provider integration.",
        "source_catalogue": "Scale-transfer source-catalogue capability promotion awaits a reviewed native adapter.",
        "corpus_statistics": "The inspected scaffold has no tracked scale-transfer YAML records; populated census fields remain unmeasured.",
        "writer_audit": "Scale-transfer writer behavior and shared writer-audit compatibility remain unverified.",
        "taxon_links": "The native scale-transfer schema is present; exact organism-link slots and TaxonMech coverage remain unverified.",
    }
    for name, reason in reasons.items():
        entry["capabilities"][name]["reason"] = reason
    entry["serialization"]["reason"] = (
        "The inspected scaffold has no tracked scale-transfer YAML records. "
        "Measure native round trips after separately reviewed seed adoption."
    )
    if api(f"repos/{REPOSITORY}/commits/main")["sha"] != observed:
        raise ValueError("Scaleup main moved during capture")
    evidence = {
        "version": 1, "captured_at": datetime.now(timezone.utc).isoformat(),
        "authority": "review_only", "claw_source_head": command("git", "rev-parse", "HEAD").decode().strip(),
        "repository": REPOSITORY, "repository_id": REPOSITORY_ID,
        "private": False, "default_branch": "main", "revision": observed,
        "git_tree": {"sha": tree["sha"], "truncated": False, "entries": tree["tree"]},
        "canonical_manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
        "native_files": native, "required_artifacts": artifacts,
        "tracked_record_paths": sorted(p for p in blobs if p.startswith("data/scale_transfers/") and p.endswith(".yaml")),
        "retained_proposal": RETAINED_SOURCE,
        "limits": ["Git tree includes every committed path, independently of ignore rules.",
                   "Local ignored and uncommitted native files were not inspected.",
                   "Artifact presence or current-byte correspondence does not authorize a governance pin or deployment."],
    }
    candidate = {
        "version": 1, "authority": "review_only", "issue": "https://github.com/CultureBotAI/culturebotai-claw/issues/1254",
        "evidence_revision": observed, "manifest_key": "scaleupmech",
        "public_projection_tags": ["exclude-from-public"], "manifest_entry": entry,
        "merge_queue_candidate": {".github/workflows/validate-strict.yaml": ["validate-strict"]},
        "admission_holds": [
            "Protected framework must distinguish public governance access from suite exclusion.",
            "Protected admission must handle existing governed scaffold bytes without claiming an empty bootstrap.",
            "Publish and authenticate a new immutable source and sealed admission; preserve historical policies.",
            "Adopt the ordinary governed source through a reviewed native PR and prove full protected fleet coverage.",
        ],
    }
    return evidence, candidate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "docs/reviews/2026-11-15-scaleup-admission")
    parser.add_argument("--replace-uncommitted", action="store_true",
                        help="Replace this branch's uncommitted candidate after an implementation correction")
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.relative_to(ROOT / "docs/reviews")
    if output.exists() and not args.replace_uncommitted:
        raise ValueError("Retained admission evidence is append-only; choose a new review directory")
    if args.replace_uncommitted and command("git", "ls-files", "--", str(output)).strip():
        raise ValueError("Refusing to replace tracked admission evidence")
    evidence, candidate = capture()
    output.mkdir(parents=True, exist_ok=True)
    (output / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")
    (output / "candidate.yaml").write_text(yaml.safe_dump(candidate, sort_keys=False))
    print(f"Saved review-only admission evidence to {output}")


if __name__ == "__main__":
    main()
