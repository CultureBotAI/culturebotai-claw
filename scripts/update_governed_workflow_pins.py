#!/usr/bin/env python3
"""Preview or apply reviewed action releases to the canonical workflow contract.

No schedules or downstream checkouts are changed. --check is offline; release
resolution uses only GitHub's API and does not execute the action or a model.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from kg_microbe_governance import GovernanceError
from kg_microbe_governance.workflow_pins import (
    CONTRACT_PATH,
    MANIFEST_PATH,
    SHA,
    UV_VERSION,
    VERSION,
    check_workflow_pins,
    load_pin_contract,
    render_workflow,
    workflow_entries,
)

ROOT = Path(__file__).resolve().parents[1]


def resolve_tag(repository: str, version: str) -> str:
    """Resolve a named upstream tag, dereferencing annotated tags to a commit."""
    response = subprocess.run(
        ["gh", "api", f"repos/{repository}/git/ref/tags/{version}"],
        check=True, capture_output=True, text=True, timeout=60,
    )
    obj = json.loads(response.stdout)["object"]
    for _ in range(5):
        if obj["type"] == "commit":
            sha = obj["sha"]
            if not isinstance(sha, str) or not SHA.fullmatch(sha):
                raise GovernanceError(f"{repository}@{version}: invalid upstream commit SHA")
            return sha
        if obj["type"] != "tag" or not SHA.fullmatch(obj["sha"]):
            break
        response = subprocess.run(
            ["gh", "api", f"repos/{repository}/git/tags/{obj['sha']}"],
            check=True, capture_output=True, text=True, timeout=60,
        )
        obj = json.loads(response.stdout)["object"]
    raise GovernanceError(f"{repository}@{version}: tag did not resolve to a commit")


def update_plan(root: Path, contract: dict) -> dict[Path, str]:
    """Validate every candidate before preparing writes, including registry hashes."""
    plan = {CONTRACT_PATH: json.dumps(contract, indent=2) + "\n"}
    document = json.loads((root / MANIFEST_PATH).read_text())
    for entry in workflow_entries(root):
        source = Path(entry["source"])
        content = render_workflow((root / source).read_text(), contract)
        plan[source] = content
        match = next(item for item in document["artifacts"] if item["id"] == entry["id"])
        match["sha256"] = hashlib.sha256(content.encode()).hexdigest()
    plan[MANIFEST_PATH] = json.dumps(document, indent=2) + "\n"
    return {path: content for path, content in plan.items()
            if (root / path).read_text() != content}


def apply_plan(root: Path, plan: dict[Path, str]) -> None:
    """Stage complete output and replace each file atomically; restore on failure."""
    staged: dict[Path, Path] = {}
    originals = {path: (root / path).read_bytes() for path in plan}
    replaced = []
    try:
        for path, content in plan.items():
            target = root / path
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as output:
                staged[path] = Path(output.name)
                output.write(content.encode())
            staged[path].chmod(target.stat().st_mode & 0o777)
        for path, temporary in staged.items():
            os.replace(temporary, root / path)
            replaced.append(path)
    except OSError:
        for path in reversed(replaced):
            (root / path).write_bytes(originals[path])
        raise
    finally:
        for temporary in staged.values():
            temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None, *, root: Path = ROOT) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", action="append", default=[], metavar="OWNER/REPO@vX.Y.Z")
    parser.add_argument("--uv-version", help="Exact uv version; retain it unless deliberately upgrading")
    parser.add_argument("--apply", action="store_true", help="Apply the printed canonical-only patch")
    parser.add_argument("--check", action="store_true", help="Offline CI contract check; never writes")
    parser.add_argument("--verify-upstream", action="store_true", help="Check recorded tags against GitHub")
    args = parser.parse_args(argv)
    if args.check and (args.action or args.uv_version or args.apply or args.verify_upstream):
        parser.error("--check cannot be combined with updating or upstream verification")
    try:
        if args.check:
            check_workflow_pins(root)
            print("Governed action pins, version labels, uv runtime and checksums match.")
            return 0
        contract = load_pin_contract(root / CONTRACT_PATH)
        for specification in args.action:
            action, separator, version = specification.partition("@")
            if not separator or action not in contract["actions"] or not VERSION.fullmatch(version):
                parser.error("--action requires a contracted action and a full release tag")
            contract["actions"][action] = {"sha": resolve_tag(action, version), "version": version}
        if args.uv_version:
            if not UV_VERSION.fullmatch(args.uv_version):
                parser.error("--uv-version requires an exact X.Y.Z version")
            resolve_tag("astral-sh/uv", args.uv_version)
            contract["uv_version"] = args.uv_version
        if args.verify_upstream:
            for action, pin in contract["actions"].items():
                actual = resolve_tag(action, pin["version"])
                if actual != pin["sha"]:
                    raise GovernanceError(f"{action}@{pin['version']}: recorded SHA differs from upstream")
            resolve_tag("astral-sh/uv", contract["uv_version"])
            print("Recorded action release tags and uv version verified against upstream.")
        plan = update_plan(root, contract)
        for path, content in plan.items():
            print("".join(difflib.unified_diff(
                (root / path).read_text().splitlines(keepends=True),
                content.splitlines(keepends=True), fromfile=f"a/{path}", tofile=f"b/{path}",
            )), end="")
        if args.apply:
            apply_plan(root, plan)
            check_workflow_pins(root)
        print(f"{'Applied' if args.apply else 'Preview:'} {len(plan)} canonical files; downstream rollout separate.")
        return 0
    except (GovernanceError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
