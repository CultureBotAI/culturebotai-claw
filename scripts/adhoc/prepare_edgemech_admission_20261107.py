#!/usr/bin/env python3
"""Prepare exact additive admission data for CLAW #960, 2026-11-07.

Inputs: unchanged historical release, reviewed source pin and exact Edge main.
Outputs: versioned admission declaration and byte-exact historical manifest copy.
Run under the retained CLAW edit lease. No downstream writes or remote calls.
"""

import json
import subprocess
from pathlib import Path

import yaml

from kg_microbe_governance.artifacts.scripts.check_vendored_sync import CANONICAL_MANIFEST_PATH
from kg_microbe_governance.cycle_release_audit import FLEET_PATH, RELEASE_PATH, parse_release
from kg_microbe_governance.infrastructure_admission import (
    ADMISSION_ID,
    ADMISSION_PATH,
    ADMITTED,
    HISTORICAL_MANIFEST_PATH,
    NATIVE_TESTS,
    canonical_sha,
    sha,
    validate_packaged_transition,
)
from plugins.repository_settings import RepositoryTarget

ROOT = Path(__file__).resolve().parents[2]
SOURCE = "7e672227fb246a8359ad57b6d3975ce5ed329007"
BOOTSTRAP = "e853bf22b9f708bfd381910107aec9283a3bcee3"


def blob(ref, path):
    return subprocess.run(["git", "show", f"{ref}:{path}"], cwd=ROOT,
                          check=True, capture_output=True).stdout


def main():
    target = RepositoryTarget("claw", ROOT, "CultureBotAI/culturebotai-claw")
    if target.open().active_branch.name != "feat/edgemech-milestones-766-767-20261107":
        raise ValueError("Unexpected admission worktree branch")
    historical = (ROOT / RELEASE_PATH).read_bytes()
    release = parse_release(historical)
    baseline = blob(release["release_ref"], CANONICAL_MANIFEST_PATH)
    current = (ROOT / CANONICAL_MANIFEST_PATH).read_bytes()
    if current != blob(SOURCE, CANONICAL_MANIFEST_PATH):
        raise ValueError("Source pin does not carry the exact current governance manifest")
    for artifact in json.loads(current)["artifacts"]:
        payload = (ROOT / artifact["source"]).read_bytes()
        if payload != blob(SOURCE, artifact["source"]) or sha(payload) != artifact["sha256"]:
            raise ValueError("Source pin does not carry the reviewed canonical payload")
    entry = yaml.safe_load((ROOT / FLEET_PATH).read_bytes())["mechs"][ADMITTED.key]
    policy = {
        "version": 1, "admission_id": ADMISSION_ID, "authority": "infrastructure_only",
        "historical_declaration_sha256": sha(historical), "historical_manifest_sha256": sha(baseline),
        "source_ref": SOURCE, "source_manifest_sha256": sha(current),
        "consumer": {"key": ADMITTED.key, "github": ADMITTED.github, "package_path": ADMITTED.package_path},
        "bootstrap_main_ref": BOOTSTRAP, "fleet_entry_sha256": canonical_sha(entry),
        "excluded_native_tests": sorted(NATIVE_TESTS),
    }
    for path, content in ((HISTORICAL_MANIFEST_PATH, baseline),
                          (ADMISSION_PATH, (json.dumps(policy, indent=2) + "\n").encode())):
        with (ROOT / path).open("xb") as handle:
            handle.write(content)
    validate_packaged_transition(ROOT)
    print(json.dumps({"admission_sha256": sha((ROOT / ADMISSION_PATH).read_bytes()),
                      "source_ref": SOURCE, "bootstrap_main_ref": BOOTSTRAP,
                      "historical_manifest_sha256": sha(baseline)}, sort_keys=True))


if __name__ == "__main__":
    main()
