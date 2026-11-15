"""Offline fixture/mutation controls for retire_owned_worktree, 2026-11-15.
Inputs: owning source checkout and a new durable private evidence directory.
Outputs: private fixture/log copies and public-safe JSON on stdout. Only tiny
synthetic Git repositories are retired; no task checkout or GitHub is mutated.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

PREFIX = Path("scripts/adhoc/cycle-maintenance-20261115/cleanup-inventory")
FILES = ("retire_owned_worktree.py", "test_retire_owned_worktree.py")
SOURCE_PATHS = {FILES[0]: PREFIX / FILES[0], FILES[1]: Path("tests") / FILES[1]}
CASES = [
    ("withdrawn-proof-guard", "", "", "test_proof_revocation_during_inventory_refuses_before_any_change[proof]"),
    ("staged-only-guard", 'require(actual == expected, "dirty staged/index state: preserve exact bytes/patch/index separately before restoration")',
     'require(True, "counterfactual staged guard removed")',
     "test_refusals_do_not_change_live_fixture_state[staged]"),
    ("late-extra-guard", 'require(actual_names - {".git"} == expected_names, "new/missing filesystem entry after inventory")',
     'require(True, "counterfactual late-extra guard removed")',
     "test_new_file_after_inventory_is_not_removed"),
]


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--evidence-dir", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    evidence = args.evidence_dir.absolute()
    if (evidence.exists() or evidence.is_symlink() or not evidence.parent.is_dir()
            or evidence.is_relative_to(Path("/tmp")) or evidence.is_relative_to(Path("/private/tmp"))):
        parser.error("use a fresh absent directory under an existing durable parent")
    evidence.mkdir(mode=0o700)
    originals = {name: (root / SOURCE_PATHS[name]).read_bytes() for name in FILES}
    observations = []
    for name, before, after, test in CASES:
        for mutated in (False, True):
            directory = evidence / f"{name}-{'mutated' if mutated else 'control'}"
            directory.mkdir()
            for filename, raw in originals.items():
                text = raw.decode()
                if mutated and filename == FILES[0] and name == "withdrawn-proof-guard":
                    archived = (root / PREFIX / "retire_owned_worktree.initial.py.txt").read_bytes()
                    if sha(archived) != "b1819e118861c2ba019406b711fbb342e11769662f07dc232173a2d2b61eb3d5":
                        raise ValueError("original reviewed source archive changed")
                    text = archived.decode()
                elif mutated and filename == FILES[0]:
                    if text.count(before) != 1:
                        raise ValueError("mutation anchor changed")
                    text = text.replace(before, after)
                (directory / filename).write_text(text)
            env = os.environ.copy()
            env["PYTHONPATH"] = os.pathsep.join([str(root), str(root / "src")])
            env["PYTHONPYCACHEPREFIX"] = str(directory / "bytecode")
            env["CLAW_RETIREMENT_TEST_HELPER"] = str(directory / FILES[0])
            command = [sys.executable, "-m", "pytest", "-q", str(root / SOURCE_PATHS[FILES[1]]) + "::" + test, "-p", "no:cacheprovider"]
            proc = subprocess.run(command, cwd=root, env=env, capture_output=True, text=True, timeout=60)
            (directory / "stdout.log").write_text(proc.stdout)
            (directory / "stderr.log").write_text(proc.stderr)
            expected = 1 if mutated else 0
            marker = "1 failed" if mutated else "1 passed"
            observations.append({"case": name, "mutation": mutated, "exit_code": proc.returncode,
                "expected_exit": expected, "passed": proc.returncode == expected and marker in proc.stdout,
                "summary": (re.findall(r"1 (?:failed|passed).*? in [\d.]+s", proc.stdout) or ["unavailable"])[-1],
                "stdout_sha256": sha(proc.stdout.encode()), "stderr_sha256": sha(proc.stderr.encode())})
    unchanged = originals == {name: (root / SOURCE_PATHS[name]).read_bytes() for name in FILES}
    passed = unchanged and all(row["passed"] for row in observations)
    result = {"authority": "offline_fixture_validation_only", "source_sha256": {name: sha(raw) for name, raw in originals.items()},
              "helper_sha256": sha(Path(__file__).read_bytes()), "sources_unchanged": unchanged,
              "observations": observations, "passed": passed, "live_cleanup_performed": False}
    (evidence / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
