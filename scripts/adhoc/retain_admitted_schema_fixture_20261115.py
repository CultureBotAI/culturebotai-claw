"""Retain the immutable shared-schema admission fixture for #1221, 2026-11-15.

Inputs: the three sealed admission policies/manifests and their local Git objects.
Outputs: plan on stdout; --apply adds the authentic fixture and provenance rows.
No network, pin changes, canonical payload changes or production sync exceptions.
"""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "src/kg_microbe_governance/artifacts/schema/mech_shared.yaml"
FIXTURE = "tests/fixtures/edgemech-admitted-source/mech_shared.yaml"
PROVENANCE = ROOT / "tests/fixtures/admitted-source-provenance.json"


def sha(content):
    return hashlib.sha256(content).hexdigest()


def prepare():
    raw = PROVENANCE.read_bytes()
    document = json.loads(raw)
    rows = []
    payload = None
    for consumer in ("edgemech", "cofactormech", "assaymech"):
        release = ROOT / "src/kg_microbe_governance/releases"
        policy = json.loads((release / f"{consumer}-infrastructure-admission-v1.json").read_bytes())
        snapshot = release / f"{consumer}-infrastructure-source-manifest.json"
        snapshot_raw = snapshot.read_bytes()
        artifact = next(item for item in json.loads(snapshot_raw)["artifacts"] if item["source"] == SOURCE)
        object_name = policy["source_ref"] + ":" + SOURCE
        content = subprocess.check_output(["git", "show", object_name], cwd=ROOT)
        blob = subprocess.check_output(["git", "rev-parse", object_name], cwd=ROOT, text=True).strip()
        assert sha(content) == artifact["sha256"], "immutable Git source differs from sealed manifest"
        assert hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest() == blob
        assert payload is None or payload == content, "consumers require distinct fixtures"
        payload = content
        row = {
            "consumer": consumer,
            "source_repository": "CultureBotAI/culturebotai-claw",
            "source_ref": policy["source_ref"],
            "source_path": SOURCE,
            "source_blob": blob,
            "sha256": sha(content),
            "bytes": len(content),
            "fixture": FIXTURE,
            "snapshot": snapshot.relative_to(ROOT).as_posix(),
            "snapshot_sha256": sha(snapshot_raw),
        }
        existing = [item for item in document["records"] if item["consumer"] == consumer and item["source_path"] == SOURCE]
        assert not existing or existing == [row], "existing provenance differs"
        if not existing:
            rows.append(row)
    return raw, document, rows, payload


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    raw, document, rows, content = prepare()
    target = ROOT / FIXTURE
    if target.exists() and target.read_bytes() != content:
        raise ValueError("retained fixture differs; refusing overwrite")
    print(json.dumps({"apply": args.apply, "added_rows": rows, "fixture_sha256": sha(content)}, indent=2))
    if args.apply:
        if PROVENANCE.read_bytes() != raw:
            raise ValueError("provenance changed during preparation")
        if not target.exists():
            with target.open("xb") as stream:
                stream.write(content)
        document["records"].extend(rows)
        PROVENANCE.write_text(json.dumps(document, indent=2) + "\n")


if __name__ == "__main__":
    main()
