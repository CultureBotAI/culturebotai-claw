"""Restore exact historical review fixtures for CLAW #1291, 2026-11-16.

Inputs: sealed consumer admission policies/manifests and immutable local Git objects.
Outputs: plan on stdout; --apply adds missing fixtures and provenance records only.
Existing fixtures/records, runtime payloads and admission policies are never rewritten.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from merge_fixture_provenance_1211_20261115 import git

ROOT = Path(__file__).resolve().parents[2]
PROVENANCE = ROOT / "tests/fixtures/admitted-source-provenance.json"
SOURCES = (
    "src/kg_microbe_governance/artifacts/schema/record_review.yaml",
    "src/kg_microbe_governance/artifacts/scripts/record_review.py",
    "src/kg_microbe_governance/artifacts/docs/record-reviews.md",
)


def sha(content):
    return hashlib.sha256(content).hexdigest()


def prepare():
    raw = PROVENANCE.read_bytes()
    document = json.loads(raw)
    additions, payloads = [], {}
    for consumer in ("edgemech", "cofactormech", "assaymech"):
        releases = ROOT / "src/kg_microbe_governance/releases"
        policy = json.loads((releases / f"{consumer}-infrastructure-admission-v1.json").read_bytes())
        snapshot = releases / f"{consumer}-infrastructure-source-manifest.json"
        snapshot_raw = snapshot.read_bytes()
        if sha(snapshot_raw) != policy["source_manifest_sha256"]:
            raise ValueError("snapshot differs from sealed admission policy")
        canonical_manifest = git(ROOT, "show", policy["source_ref"]
                                 + ":src/kg_microbe_governance/vendored_artifacts.json")
        if canonical_manifest != snapshot_raw:
            raise ValueError("retained snapshot differs from immutable source manifest")
        for source in SOURCES:
            artifact = next(a for a in json.loads(snapshot_raw)["artifacts"] if a["source"] == source)
            object_name = policy["source_ref"] + ":" + source
            content = git(ROOT, "show", object_name)
            blob = git(ROOT, "rev-parse", object_name).decode().strip()
            if (sha(content) != artifact["sha256"]
                    or hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest() != blob):
                raise ValueError("immutable source bytes differ from sealed artifact/blob identity")
            retained = {r["fixture"] for r in document["records"] + additions
                        if r["source_path"] == source and r["sha256"] == artifact["sha256"]}
            if len(retained) > 1:
                raise ValueError("ambiguous retained fixture identity")
            folder = "edgemech-admitted-source" if consumer == "edgemech" else "native-admitted-source"
            fixture = next(iter(retained), "tests/fixtures/" + folder + "/" + Path(source).name)
            target = ROOT / fixture
            if target.exists() and target.read_bytes() != content:
                raise ValueError("existing fixture differs; refusing overwrite")
            if fixture in payloads and payloads[fixture] != content:
                raise ValueError("distinct historical payloads require distinct fixture paths")
            payloads[fixture] = content
            row = {
                "consumer": consumer, "source_repository": "CultureBotAI/culturebotai-claw",
                "source_ref": policy["source_ref"], "source_path": source, "source_blob": blob,
                "sha256": sha(content), "bytes": len(content), "fixture": fixture,
                "snapshot": snapshot.relative_to(ROOT).as_posix(), "snapshot_sha256": sha(snapshot_raw),
            }
            existing = [r for r in document["records"]
                        if r["consumer"] == consumer and r["source_path"] == source]
            if existing and existing != [row]:
                raise ValueError("existing provenance differs; refusing overwrite")
            if not existing:
                additions.append(row)
    return raw, document, additions, payloads


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    raw, document, additions, payloads = prepare()
    print(json.dumps({"apply": args.apply, "added_records": additions,
                      "new_fixtures": {path: sha(content) for path, content in payloads.items()
                                       if not (ROOT / path).exists()}}, indent=2))
    if args.apply:
        if PROVENANCE.read_bytes() != raw:
            raise ValueError("provenance changed during preparation")
        for path, content in payloads.items():
            target = ROOT / path
            if not target.exists():
                with target.open("xb") as stream:
                    stream.write(content)
        document["records"].extend(additions)
        PROVENANCE.write_text(json.dumps(document, indent=2) + "\n")


if __name__ == "__main__":
    main()
