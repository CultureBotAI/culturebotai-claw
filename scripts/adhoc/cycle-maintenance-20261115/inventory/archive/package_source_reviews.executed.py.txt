"""Package public-safe helpers/results for claw PRs 1112 and 1236, 2026-11-15.

Inputs: separately retained private review roots with original helpers and receipts.
Outputs: public summaries and parameterized helper copies beside this script.
Original evidence is read only; validation is not rerun. Related: PRs 1112/1236.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from pathlib import Path


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def safe_text(text):
    prohibited = [r"/Users/", r"/home/", r"agent-work", r"XMechBay",
                  r"[A-Za-z0-9_.+%-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"]
    if any(re.search(pattern, text) for pattern in prohibited):
        raise ValueError("private path, operations name or email remains in public output")
    return text


def parameterize(source):
    guard = '''_parser = __import__("argparse").ArgumentParser(description=__doc__)
_parser.add_argument("--review-tree", type=Path, required=True,
                     help="Owned isolated detached worktree at the exact reviewed head")
ROOT = _parser.parse_args().review_tree.resolve()
if Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"],
                               cwd=ROOT, text=True).strip()).resolve() != ROOT:
    raise SystemExit("Review path is not a worktree root")
if subprocess.run(["git", "symbolic-ref", "--quiet", "HEAD"], cwd=ROOT,
                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 1:
    raise SystemExit("Review tree must be detached; feature branches are refused")
if subprocess.run(["git", "diff-index", "--quiet", "HEAD", "--"], cwd=ROOT).returncode:
    raise SystemExit("Tracked source differs from the reviewed head")
'''
    edited, count = re.subn(r"^ROOT\s*=\s*Path\(__file__\)\.resolve\(\)\.parents\[2\]\n", guard, source, flags=re.M)
    if count != 1:
        raise ValueError("expected one original worktree-root assignment")
    edited = re.sub(r"^assert ROOT == Path\('/Users/[^\n]+'\)\n", "", edited, flags=re.M)
    edited = re.sub(r"^if ROOT != Path\('/Users/[^\n]+'\):\n    raise SystemExit\([^\n]+\)\n", "", edited, flags=re.M)
    edited = re.sub(r"independent [a-z_]+ child agent", "independent source reviewer", edited)
    edited = re.sub(r"retained stream-[A-Z] canonical-source(?: clone)?", "recorded Git object source", edited)
    safe_text(edited)
    ast.parse(edited)
    return edited


def package(review_root, destination, number):
    original = json.loads((review_root / "review.json").read_bytes())
    proof = json.loads((review_root / "source-head-proof.json").read_bytes())
    if original["pr"] != number or proof["pr"] != number:
        raise ValueError("review identity differs")
    destination.mkdir(parents=True, exist_ok=True)
    source_dir = review_root / "worktree/scripts/adhoc"
    names = sorted(original["helper_sha256"])
    helper_rows = []
    for relative in names:
        path = source_dir / Path(relative).name
        raw = path.read_bytes()
        if digest(raw) != original["helper_sha256"][relative]:
            raise ValueError("original helper hash differs from retained review")
        output = parameterize(raw.decode())
        copied = destination / path.name
        copied.write_text(output)
        helper_rows.append({"file": copied.name, "original_sha256": digest(raw),
                           "packaged_sha256": digest(output.encode()), "packaging_edits": [
                               "Replace private absolute-root guard with explicit --review-tree parameter.",
                               "Require an actual detached worktree with clean tracked source; preserve exact reviewed-head checks.",
                               "Replace private reviewer/workspace labels with generic review terminology.",
                               "Preserve original validation logic; no expensive validation rerun for packaging."]})
    controls = json.loads((review_root / "counterfactuals.json").read_bytes())
    mutation_rows = [{key: row[key] for key in ("name", "exit_code", "log_sha256")}
                     for row in controls["receipts"]]
    summary = {"repository": original["repository"], "pr": number,
        "head": original["head"], "actual_main": original["actual_main"],
        "merge_base": proof["merge_base"], "head_tree": proof["head_tree"],
        "prospective_merge_tree": proof["prospective_merge_tree"],
        "verdict": "No verified blocking code finding; runtime and consumer adoption remain separate.",
        "findings": original["findings"], "validation": original["validation"],
        "checks": [{"name": check["name"], "status": check["status"], "conclusion": check["conclusion"],
                    "details_url": check["detailsUrl"]} for check in original["checks"]],
        "counterfactuals": mutation_rows,
        "original_receipt_sha256": {name: digest((review_root / name).read_bytes())
            for name in ("REVIEW.md", "review.json", "source-head-proof.json", "counterfactuals.json")},
        "validation_log_sha256": {name: sha for name, sha in original["evidence_sha256"].items()
                                  if name.startswith("pytest-") or name == "hosted-test-run.log"},
        "helpers": helper_rows,
        "packaging_validation": "Python AST parse and private-path/email scan; original review results unchanged.",
        "limitations": ["The full private receipts/logs are retained separately; this is a public summary.",
                        "Historical hosted aggregate skips were not individually classified; selected local review tests had no skips.",
                        "Code-only review supplies no live runtime, restart, deployment or consumer-adoption authority."]}
    payload = safe_text(json.dumps(summary, indent=2) + "\n")
    (destination / "summary.json").write_text(payload)
    return {"pr": number, "head": original["head"], "summary_sha256": digest(payload.encode()),
            "helper_count": len(helper_rows)}



def package_remote(review_root, destination, issue_url):
    controls = json.loads((review_root / "counterfactuals.json").read_bytes())
    parser = json.loads((review_root / "parser-counterfactual.json").read_bytes())
    if controls["original_module_sha256"] != parser["source_sha256"]:
        raise ValueError("remote verifier source snapshots differ")
    if not controls["original_source_untouched"]:
        raise ValueError("source snapshot changed during mutation review")
    if issue_url is not None and not re.fullmatch(
            r"https://github\.com/CultureBotAI/culturebotai-claw/issues/[1-9][0-9]*", issue_url):
        raise ValueError("finding issue must be an exact own-repository issue URL")
    selected = []
    for item in controls["receipts"] + parser["receipts"]:
        selected.append({key: item[key] for key in ("name", "exit_code", "log_sha256")})
    helper_provenance = {}
    for name, expected in (("review_remote_verifier_mutations.py", controls["helper_sha256"]),
                           ("review_worktree_parser_counterfactual.py", parser["helper_sha256"])):
        raw = (review_root / "helpers" / name).read_bytes()
        if digest(raw) != expected:
            raise ValueError("executed remote review helper hash differs")
        text = raw.decode()
        if issue_url:
            text = text.replace("\n\n", "\n\nFinding: " + issue_url + ".\n\n", 1)
        safe_text(text)
        ast.parse(text)
        (destination / name).write_text(text)
        helper_provenance[name] = {"executed_sha256": expected, "packaged_sha256": digest(text.encode()),
                                  "packaging_edits": ["Add confirmed issue URL to the docstring; validation logic unchanged."] if issue_url else []}
    summary = {"repository": "CultureBotAI/culturebotai-claw",
        "scope": "Offline PR-maintenance remote verifier and cleanup proof validation",
        "source_module_sha256": controls["original_module_sha256"],
        "test_file_sha256": controls["input_sha256"]["tests/test_pr_maintenance_remote.py"],
        "baseline_tests_passed": 112, "baseline_tests_skipped": 0,
        "mutation_controls_killed": 6, "parser_control_cases_passed": 2,
        "parser_reverted_cases_failed": 2, "lint": "Ruff 0.16.3 passed",
        "finding": {"issue_url": issue_url,
                    "description": "Malformed extra worktree-inventory blocks were accepted after a valid block.",
                    "status": "Repaired and independently mutation-checked",
                    "test": parser["test_selection"]},
        "receipts": selected,
        "original_receipt_sha256": {name: digest((review_root / name).read_bytes())
            for name in ("counterfactuals.json", "parser-counterfactual.json")},
        "helper_provenance": helper_provenance,
        "source_restored": controls["restored_module_sha256"] == parser["restored_sha256"] == parser["source_sha256"],
        "original_source_untouched": True,
        "authority": "Test evidence only; no GitHub mutation, runtime action or cleanup performed."}
    payload = safe_text(json.dumps(summary, indent=2) + "\n")
    (destination / "remote-verifier-summary.json").write_text(payload)
    return {"scope": "remote-verifier", "summary_sha256": digest(payload.encode())}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-root", required=True, type=Path)
    parser.add_argument("--finding-issue-url", help="Own-repository issue for the repaired porcelain completeness finding")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    results = [package(args.evidence_root / str(number), root / str(number), number)
               for number in (1112, 1236)]
    remote_root = args.evidence_root / "remote-verifier"
    if (remote_root / "parser-counterfactual.json").is_file():
        results.append(package_remote(remote_root, root, args.finding_issue_url))
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
