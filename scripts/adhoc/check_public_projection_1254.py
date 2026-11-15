"""Verify public fleet boundaries in fresh pytest processes (issue #1254).

Inputs: this isolated checkout and its existing Python environment.
Outputs: JSON red/green receipts on stdout and optional --output path.
Retains and updates the #1146/#1148 regression proof, 2026-11-15.
Run with no concurrent edits or tests; every modified source is restored.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASES = {
    "membership": (
        "src/kg_microbe_fleet/__init__.py",
        (("if mech.is_public}", "}"),),
        "tests/test_fleet_public.py",
    ),
    "aggregation": (
        "src/kg_microbe_progress/__init__.py",
        (("    public = fleet.public()", "    public = fleet"),
         ("    filtered = public_history(history, fleet)", "    filtered = copy.deepcopy(history)")),
        "tests/test_progress_public_membership.py::test_public_projection_removes_history_and_nonzero_contributions",
    ),
    "publisher": (
        "scripts/mech_progress_publish.py",
        (('    bundle = public_bundle(bundle["history"], bundle["snapshot"], fleet)', "    bundle = bundle"),
         ("    validate_bundle(history, snapshot, fleet.public())", "    validate_bundle(history, snapshot, fleet)")),
        "tests/test_progress_public_membership.py::test_transport_and_site_never_serialize_excluded_member",
    ),
    "pages": (
        "scripts/build_mech_progress_site.py",
        (('    bundle = public_bundle(bundle["history"], bundle["snapshot"])', "    bundle = bundle"),),
        "tests/test_progress_public_membership.py::test_transport_and_site_never_serialize_excluded_member",
    ),
    "local-history": (
        "scripts/mech_progress_publish.py",
        (("            merged = copy.deepcopy(local)", "            merged = copy.deepcopy(remote)"),),
        "tests/test_progress_public_membership.py::test_remote_public_updates_preserve_excluded_local_history",
    ),
    "status": (
        "scripts/mech_progress_status.py",
        (('            bundle = public_bundle(bundle["history"], bundle["snapshot"], manifest)',
          "            bundle = bundle"),
         ("            manifest = manifest.public()", "            manifest = manifest")),
        "tests/test_progress_status.py::test_published_status_excludes_nonzero_internal_member",
    ),
    "sealed-cohort": (
        "tests/test_governance_infrastructure_admission.py",
        (('    fleet["mechs"] = {\n        key: fleet["mechs"][key]\n'
          '        for key in json.loads(admitted_manifest)["consumers"]\n    }\n', ""),),
        "tests/test_governance_infrastructure_admission.py::test_post_admission_catalogue_addition_permits_withheld_capability_and_rejects_drift",
    ),
    "durability": (
        "scripts/mech_progress_status.py",
        (('                durability = [row for row in durability if row["repository_key"] in manifest.mechs]',
          "                durability = durability"),),
        "tests/test_progress_status.py::test_published_durability_validates_internal_targets_then_filters",
    ),
}


def run(selector: str) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ, PYTHONPATH=f"{ROOT / 'src'}:{ROOT}")
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "--tb=short", selector],
        cwd=ROOT, env=environment, text=True, capture_output=True, check=False,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=CASES)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    receipts = []
    for name in ([args.case] if args.case else CASES):
        relative, replacements, selector = CASES[name]
        path = ROOT / relative
        original = path.read_bytes()
        mutant = original.decode()
        for old, new in replacements:
            if mutant.count(old) != 1:
                raise ValueError(f"Ambiguous mutation {name}: {relative}")
            mutant = mutant.replace(old, new)
        baseline = run(selector)
        if baseline.returncode:
            raise RuntimeError(baseline.stdout + baseline.stderr)
        try:
            path.write_text(mutant)
            mutated = run(selector)
            if mutated.returncode != 1 or "failed" not in mutated.stdout:
                raise RuntimeError(f"Mutation survived: {name}\n{mutated.stdout}{mutated.stderr}")
        finally:
            path.write_bytes(original)
        restored = run(selector)
        if restored.returncode or path.read_bytes() != original:
            raise RuntimeError(restored.stdout + restored.stderr)
        receipts.append({
            "case": name, "source": relative, "selector": selector,
            "source_sha256": hashlib.sha256(original).hexdigest(),
            "baseline_exit": baseline.returncode, "mutant_exit": mutated.returncode,
            "restored_exit": restored.returncode,
        })
        print(f"{name}: green/red/green", file=sys.stderr, flush=True)
    document = {
        "issue": 1254, "checked_at": datetime.now(timezone.utc).isoformat(),
        "fresh_pytest_processes": True, "cases": receipts,
    }
    encoded = json.dumps(document, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded)
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
