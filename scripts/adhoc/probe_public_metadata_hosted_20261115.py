"""One anonymous hosted metadata diagnostic for #1223, 2026-11-15.

Inputs: the manifest's AIMech consumer and reviewed #1231 metadata client.
Output: one exclusive bounded JSON receipt; no authoritative audit, credentials,
retry, clone, downstream mutation, or publication. This probe cannot pass a gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / ".temp/public-metadata-hosted-20261115"
CLIENT_SHA = "e7d10776721fb72fb44446938a7d5dca81f0b398742875d9e3e798b1744656cf"
sys.path.insert(0, str(ROOT / "src"))

from kg_microbe_governance import load_governance_manifest  # noqa: E402
from kg_microbe_governance import public_repository_metadata as metadata  # noqa: E402


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def probe(output, *, plan=False):
    output = Path(output).resolve()
    if not output.is_relative_to(STATE.resolve()) or output.exists():
        raise ValueError("new private diagnostic output required")
    manifest_path = ROOT / "src/kg_microbe_governance/vendored_artifacts.json"
    client_path = ROOT / "src/kg_microbe_governance/public_repository_metadata.py"
    if Path(metadata.__file__).resolve() != client_path or sha(client_path) != CLIENT_SHA:
        raise ValueError("reviewed metadata client required")
    manifest = load_governance_manifest(manifest_path)
    repository = manifest.consumers["aimech"].github
    if repository != "CultureBotAI/AIMech":
        raise ValueError("expected manifest-declared public canary")
    inputs = {p: sha(p) for p in (manifest_path, client_path, Path(__file__))}
    receipt = {
        "purpose": "diagnostic_only_not_authoritative_audit",
        "repository": repository,
        "planned_requests": 1,
        "executed_requests": 0,
        "revision": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "inputs": {str(p.relative_to(ROOT)): value for p, value in inputs.items()},
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    if plan:
        return receipt, 0
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as handle:
        client = metadata.PublicRepositoryMetadata({repository})
        receipt["executed_requests"] = 1
        try:
            value = client.get(repository)
        except metadata.PublicMetadataFailure as error:
            receipt["outcome"] = "REFUSED"
            receipt["diagnostic"] = metadata.diagnostic_suffix(error).strip()
            code = 2
        else:
            receipt["outcome"] = "PUBLIC_MAIN_METADATA_CONFIRMED"
            receipt["metadata"] = {
                key: value[key] for key in ("full_name", "private", "default_branch")
            }
            code = 0
        receipt["finished_at"] = datetime.now(timezone.utc).isoformat()
        receipt["inputs_unchanged"] = inputs == {p: sha(p) for p in inputs}
        if not receipt["inputs_unchanged"]:
            receipt["outcome"] = "INPUTS_CHANGED"
            code = 2
        receipt["exit_code"] = code
        handle.write(json.dumps(receipt, indent=2) + "\n")
    if json.loads(output.read_bytes()) != receipt:
        raise ValueError("persisted diagnostic differs")
    return receipt, code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--plan", action="store_true")
    args = parser.parse_args()
    receipt, code = probe(args.output, plan=args.plan)
    print(json.dumps(receipt, indent=2))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
