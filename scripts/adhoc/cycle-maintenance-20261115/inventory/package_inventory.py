"""Package public maintenance inventory/review evidence; 2026-11-15, issue1230.

Inputs: retained read-only audit directory and PR1197 review directory.
Outputs: parameterized capture/review helpers, hashes and a public-only summary.
Raw PR comments, author identities, local paths and private operations stay out.
Original helper bytes/evidence are not changed. No Git or GitHub mutation.
"""
import argparse
import hashlib
import json
from pathlib import Path


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--audit-dir", required=True, type=Path)
    parser.add_argument("--review-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    audit = (args.audit_dir / "capture_pr_audit.py").read_bytes()
    code = audit.decode().replace("ROOT = Path(__file__).resolve().parent", '''import argparse
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output-dir", type=Path, required=True,
                    help="Private durable evidence directory; raw metadata may contain author identities")
ROOT = parser.parse_args().output_dir.resolve()
ROOT.mkdir(parents=True, exist_ok=True)''')
    assert code != audit.decode()
    (args.output_dir / "capture_pr_audit.py").write_text(code)
    review = (args.review_dir / "review_mutations.py").read_bytes()
    (args.output_dir / "review_pr1197_mutations.py").write_bytes(review)
    rows = json.loads((args.audit_dir / "pr-checks-before.json").read_text())
    summary = {"repository": "CultureBotAI/culturebotai-claw", "date": "2026-11-15",
               "purpose": "Initial frozen maintenance inventory; current remote state must be rechecked",
               "related_issue": 1230,
               "initial_prs": [{key: row[key] for key in
                   ("number", "headRefOid", "headRefName", "isDraft", "mergeable", "mergeStateStatus")}
                   for row in sorted(rows, key=lambda item: item["number"])],
               "helpers": [
                   {"path": "capture_pr_audit.py", "original_sha256": digest(audit),
                    "packaged_sha256": digest(code.encode()),
                    "packaging_edits": "Require explicit private durable output directory; preserve read-only API behavior"},
                   {"path": "review_pr1197_mutations.py", "original_sha256": digest(review),
                    "packaged_sha256": digest(review), "packaging_edits": "None; byte-identical portable helper"}],
               "pr1197_review": {"head": "345a63c31e44cf77e7323d7c2647a4d7d8d61683",
                   "verdict": "pass", "new_findings": 0, "tests_passed": 753, "tests_skipped": 1,
                   "downstream_reference_tests_deselected": 176, "mutations_killed": 4,
                   "review_sha256": digest((args.review_dir / "REVIEW.md").read_bytes())}}
    (args.output_dir / "inventory-and-review.json").write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
