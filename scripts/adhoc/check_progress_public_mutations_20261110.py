"""Verify public progress guards; inputs: source/tests; output: pytest evidence.

Serves the fleet public-membership integration PR, 2026-11-10. Each mutation
runs in a fresh pytest process and original source bytes are always restored.
Run only in an isolated checkout with no concurrent progress edits/tests.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CASES = (
    (
        "projection includes excluded contributions",
        "src/kg_microbe_progress/__init__.py",
        (
            ("    public = fleet.public()\n    try:", "    public = fleet\n    try:"),
            ("    filtered = public_history(history, fleet)", "    filtered = copy.deepcopy(history)"),
        ),
        "test_public_projection_removes_history_and_nonzero_contributions",
    ),
    (
        "publisher bypasses projection",
        "scripts/mech_progress_publish.py",
        (
            ('    bundle = public_bundle(bundle["history"], bundle["snapshot"], fleet)', "    bundle = bundle"),
            ("    validate_bundle(history, snapshot, fleet.public())", "    validate_bundle(history, snapshot, fleet)"),
        ),
        "test_transport_and_site_never_serialize_excluded_member",
    ),
    (
        "Pages bypasses projection",
        "scripts/build_mech_progress_site.py",
        ((('    bundle = public_bundle(bundle["history"], bundle["snapshot"])'), "    bundle = bundle"),),
        "test_transport_and_site_never_serialize_excluded_member",
    ),
)


def main() -> int:
    for name, relative, replacements, test in CASES:
        path = ROOT / relative
        original = path.read_bytes()
        mutant = original.decode()
        for old, new in replacements:
            if mutant.count(old) != 1:
                raise ValueError(f"ambiguous mutation in {relative}")
            mutant = mutant.replace(old, new)
        try:
            path.write_text(mutant)
            result = subprocess.run(
                [sys.executable, "-m", "pytest", "-q", "--tb=short",
                 f"tests/test_progress_public_membership.py::{test}"],
                cwd=ROOT, text=True, capture_output=True,
            )
            print(name, "DETECTED" if result.returncode == 1 else "UNEXPECTED", flush=True)
            print(result.stdout, flush=True)
            if result.returncode != 1 or "1 failed" not in result.stdout:
                return 1
        finally:
            path.write_bytes(original)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
