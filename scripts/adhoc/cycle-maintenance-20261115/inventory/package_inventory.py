"""Package the EXACT retained 2026-11-15 inventory/review; issues 1230/1265/1266.

Inputs: immutable historical audit/review bytes at the hashes below. Outputs:
current repaired helpers plus an explicitly historical public summary in a NEW
non-aliasing directory. This is not a general review assessor: unknown inputs
are refused. No tests, API calls, Git operations or original writes occur.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
import re
from pathlib import Path

ARCHIVE_HASHES = {
    "audit/capture_pr_audit.py": "55fd5597a10666531e9a425d9b86bf46c104b701d515ebd8f3ee214d4feabfde",
    "audit/pr-checks-before.json": "1d2b4fe1e254aa83f011fc1fa8c17812cd876b2e41d2b28d9a6e52c897378c3f",
    "audit/open-pulls-before-pages.json": "19f9b55469063fc54e0dec7b723abfad60d8f49e2cdf4661396c55ae527ec89d",
    "audit/open-pulls-after-pages.json": "19f9b55469063fc54e0dec7b723abfad60d8f49e2cdf4661396c55ae527ec89d",
    "audit/independent-open-count-and-queue.json": "87cec1b1534010d23a484484175115d7a04c8bd356ff10121c68b524e4ea0e3b",
    "review/review_mutations.py": "e06eca553f915f26c201947018858fb70f9847b05a3b093b58d4b863d463bc7d",
    "review/REVIEW.md": "a393153a9aeccc138178774d002b7bbf7b81da882d73a83ff408a8e01f6fc976",
}
SUMMARY_SHA256 = "b6b63834eb203eef395ad73e7c6af376fe821a278c4cac21f2d2f449ecaaea83"
HELPERS = ("capture_pr_audit.py", "review_pr1197_mutations.py", "package_inventory.py")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def read_bound(path, expected):
    if path.is_symlink() or not path.is_file():
        raise ValueError("historical input must be a regular non-symlink file: " + path.name)
    raw = path.read_bytes()
    if digest(raw) != expected:
        raise ValueError("unrecognized historical input: " + path.name)
    return raw


def validate_destination(output, sources):
    canonical = output.resolve()
    if output.absolute() != canonical or output.exists() or output.is_symlink():
        raise ValueError("packaging requires a new canonical output directory")
    if any(canonical.is_relative_to(source.resolve()) or source.resolve().is_relative_to(canonical)
           for source in sources):
        raise ValueError("output aliases or contains an input directory")
    return canonical


def prepare(audit, review):
    """Validate all inputs before allowing any output publication."""
    roots = {"audit": audit.resolve(strict=True), "review": review.resolve(strict=True)}
    raw = {}
    for name, expected in ARCHIVE_HASHES.items():
        area, filename = name.split("/", 1)
        raw[name] = read_bound(roots[area] / filename, expected)
    here = Path(__file__).resolve().parent
    archive = here / "historical-inventory-and-review.json"
    if not archive.exists() and not archive.is_symlink():
        archive = here / "inventory-and-review.json"
    historical_raw = read_bound(archive, SUMMARY_SHA256)
    historical = json.loads(historical_raw)
    spec = importlib.util.spec_from_file_location("inventory_capture", here / "capture_pr_audit.py")
    capture = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(capture)
    rows = json.loads(raw["audit/pr-checks-before.json"])
    reference = capture.identities(rows)
    for name in ("open-pulls-before-pages.json", "open-pulls-after-pages.json"):
        rest = [row for page in json.loads(raw["audit/" + name]) for row in page]
        if capture.identities(rest, rest=True) != reference:
            raise ValueError("archived REST and check identities disagree")
    connection = json.loads(raw["audit/independent-open-count-and-queue.json"])["data"]["repository"]["pullRequests"]
    if (connection["pageInfo"]["hasNextPage"] is not False
            or connection["totalCount"] != len(reference)
            or capture.identities(connection["nodes"]) != reference):
        raise ValueError("archived GraphQL and check identities disagree")
    selected = [{key: row[key] for key in
        ("number", "headRefOid", "headRefName", "isDraft", "mergeable", "mergeStateStatus")}
        for row in sorted(rows, key=lambda item: item["number"])]
    if selected != historical["initial_prs"]:
        raise ValueError("retained public inventory differs from bound source rows")
    if historical["pr1197_review"]["review_sha256"] != digest(raw["review/REVIEW.md"]):
        raise ValueError("retained review claims lack their exact historical report")
    output = {name: (here / name).read_bytes() for name in HELPERS}
    output["historical-inventory-and-review.json"] = historical_raw
    summary = copy.deepcopy(historical)
    summary.update(purpose="Exact historical evidence with separately repaired helper packaging",
                   new_review_execution=False, historical_summary_sha256=SUMMARY_SHA256,
                   historical_input_sha256=ARCHIVE_HASHES,
                   previous_packaged_helpers=historical["helpers"],
                   repair_issues=[1263, 1264, 1265, 1266])
    summary["helpers"] = [{"path": name, "packaged_sha256": digest(output[name]),
        "packaging_edits": {
            "capture_pr_audit.py": "Import-safe capture; exact collection agreement; new directory and explicit drift receipt (1264)",
            "review_pr1197_mutations.py": "Paired passing controls and structured selected-test failures; setup errors rejected (1263)",
            "package_inventory.py": "Bind exact historical inputs; refuse aliases/collisions; validate before publication (1265/1266)",
        }[name]} for name in HELPERS]
    output["inventory-and-review.json"] = (json.dumps(summary, indent=2) + "\n").encode()
    for name, content in output.items():
        text = content.decode()
        if (re.search(r"/(?:Users|home)/[A-Za-z0-9]", text)
                or re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", text)):
            raise ValueError("public hygiene review required: " + name)
    return output


def package(audit, review, output):
    output = validate_destination(output, [audit, review, Path(__file__).resolve().parent])
    files = prepare(audit, review)
    # Exclusive directory and file creation prevent races from replacing inputs.
    output.mkdir(parents=True, exist_ok=False)
    for name, raw in files.items():
        with (output / name).open("xb") as stream:
            stream.write(raw)
    return json.loads(files["inventory-and-review.json"])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-dir", required=True, type=Path)
    parser.add_argument("--review-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    package(args.audit_dir, args.review_dir, args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
