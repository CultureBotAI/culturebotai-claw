"""Render bounded MIM stewardship evidence without mutating GitHub or a corpus.

2026-11-26 fleet-ops: inputs are maintained acquisition snapshots, prior routing,
fresh CI logs and explicit reviewed decisions. Outputs are new private reports.
Prior routing is not a scientific verdict; every unassessed decision is reset.
"""

from __future__ import annotations

import argparse
import collections
import csv
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

REPO = "CultureBotAI/MediaIngredientMech"
TARGETS = {
    1547,
    1546,
    1544,
    1543,
    1542,
    1541,
    1468,
    1500,
    1456,
    1452,
    1451,
    1440,
    1449,
    1446,
    1445,
    1444,
    1443,
    1438,
    1436,
    1429,
}


def read(path):
    return json.loads(path.read_text())


def pin(path):
    data = path.read_bytes()
    return {"path": str(path), "sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def unique(items):
    found = {x["number"]: x for x in items}
    if len(found) != len(items):
        raise ValueError("duplicate issue/PR identity")
    return found


def comments(root, item):
    name = f"comments-{item['number']}"
    if (root / (name + "-pages.json")).exists():
        return [row for page in read(root / (name + "-pages.json")) for row in page]
    if (root / (name + ".json")).exists():
        return read(root / (name + ".json"))
    return []


def signature(item, discussion):
    return {
        "title": item["title"],
        "body": item.get("body"),
        "state": item["state"],
        "labels": sorted(x["name"] for x in item["labels"]),
        "comments": [(x["id"], x.get("body"), x.get("updated_at")) for x in discussion],
    }


def render(args):
    baseline, final = args.campaign / "baseline", args.campaign / "final"
    initial = unique(read(baseline / "issues.json"))
    issues = dict(initial)
    for page in read(final / "issue-delta-pages.json"):
        for item in page:
            if "pull_request" in item:
                continue
            if item["state"] == "open":
                issues[item["number"]] = item
            else:
                issues.pop(item["number"], None)
    prs = unique(read(final / "pr-details.json"))
    counts = read(final / "counts.json")["data"]["repository"]
    if (
        counts["nameWithOwner"] != REPO
        or len(issues) != counts["issues"]["totalCount"]
        or len(prs) != counts["pullRequests"]["totalCount"]
    ):
        raise ValueError("final identity/count mismatch")
    previous = read(args.previous_report)
    prior_rows = unique(previous["issue_rows"])
    prior_issues = unique(read(args.previous_snapshot / "issues.json"))
    prior_prs = unique(previous["pr_rows"])
    decisions = read(args.decisions)
    if set(decisions) - {str(n) for n in issues}:
        raise ValueError("decision outside final open set")
    rows, changed, added = [], [], []
    comment_total = 0
    for n, item in sorted(issues.items(), reverse=True):
        discussion_root = final if (final / f"comments-{n}-pages.json").exists() else baseline
        discussion = comments(discussion_root, item)
        if len(discussion) != item["comments"] or len({x["id"] for x in discussion}) != len(
            discussion
        ):
            raise ValueError(f"comment coverage mismatch for issue{n}")
        comment_total += len(discussion)
        same = n in prior_issues and signature(item, discussion) == signature(
            prior_issues[n], comments(args.previous_snapshot, prior_issues[n])
        )
        if n not in prior_issues:
            added.append(n)
        elif not same:
            changed.append(n)
        decision = decisions.get(str(n), {})
        theme = decision.get("theme", prior_rows.get(n, {}).get("theme"))
        if theme is None:
            raise ValueError(f"new issue{n} needs explicit routing")
        rows.append(
            {
                "key": f"{REPO}#{n}",
                "number": n,
                "url": item["html_url"],
                "title": item["title"],
                "theme": theme,
                "review_priority": decision.get("review_priority", "Unranked"),
                "review_action": decision.get("review_action", "unreviewed"),
                "review_reason": decision.get(
                    "review_reason",
                    "Routing retained only; scientific/code acceptance was not independently assessed in this bounded pass.",
                ),
                "review_evidence": decision.get(
                    "review_evidence",
                    "Fresh body/comment acquisition and previous routing comparison; not closure evidence.",
                ),
                "defer_until": decision.get("defer_until", ""),
                "source_updated_at": item["updated_at"],
                "comments_fetched": len(discussion),
                "prior_content_and_comments_equal": same,
            }
        )
    pr_rows = []
    log_counts = collections.Counter()
    baseline_prs = unique(read(baseline / "pr-details.json"))
    for n, item in sorted(prs.items(), reverse=True):
        targeted = n in TARGETS
        log_state = None
        if targeted:
            if item["headRefOid"] != baseline_prs[n]["headRefOid"]:
                raise ValueError(f"target PR{n} changed head during review")
            log = baseline / f"pr{n}-pytest.log"
            error = baseline / f"pr{n}-pytest.error"
            text = log.read_text()
            if error.read_text().strip():
                log_state = "log retrieval error; no terminal suite evidence"
            elif not text:
                log_state = "empty successful log response; no terminal suite evidence"
            elif "runner has received a shutdown signal" in text:
                log_state = "runner shutdown/cancellation; no terminal suite verdict"
            else:
                log_state = "unclassified retained log; further assessment needed"
            log_counts[log_state] += 1
        pr_rows.append(
            {
                "number": n,
                "key": f"{REPO}#{n}",
                "url": item["url"],
                "title": item["title"],
                "theme": prior_prs.get(n, {}).get("theme", "new PR requires routing"),
                "head": item["headRefOid"],
                "base_branch": item["baseRefName"],
                "is_draft": item["isDraft"],
                "targeted": targeted,
                "failed_checks": [
                    {
                        "name": c.get("name"),
                        "url": c.get("detailsUrl"),
                        "conclusion": c.get("conclusion"),
                    }
                    for c in item["statusCheckRollup"]
                    if c.get("conclusion") in {"FAILURE", "CANCELLED", "TIMED_OUT"}
                ],
                "pytest_log_state": log_state,
                "action": "retained open and branch unchanged; NOT repaired or closed"
                if targeted
                else "routed; no substantive PR disposition claimed",
                "remaining_blockers": [
                    "#1431 current native scientific/publication/derived-product qualification",
                    "#1450 decisive exact-head pytest result; cause not established",
                ]
                if targeted
                else [],
                "evidence_scope": "Current body, comments, exact head and checks; pytest retrieval attempted for every target. Seven data-gate logs reread at PR1547 only; older exact-job analysis retained in existing tracker."
                if targeted
                else "Full intake and thematic routing only",
            }
        )
    if set(issues) != {x["number"] for x in rows} or set(prs) != {x["number"] for x in pr_rows}:
        raise ValueError("routing coverage mismatch")
    if TARGETS - set(prs):
        raise ValueError("target PR absent; explicit reconciliation required")
    actions = []
    for n in [1431, 1450]:
        url = (args.campaign / f"issue{n}-action.txt").read_text().strip()
        if not url.startswith(f"https://github.com/{REPO}/issues/{n}#issuecomment-"):
            raise ValueError("missing actual issue action receipt")
        actions.append(
            {
                "kind": "issue_comment",
                "issue": n,
                "url": url,
                "body": pin(args.campaign / f"issue{n}-comment.md"),
            }
        )
    report = {
        "repository": REPO,
        "at_utc": datetime.now(timezone.utc).isoformat(),
        "state": "20 failing PRs assessed and retained with named blockers; zero repaired/closed",
        "published_main": counts["defaultBranchRef"],
        "coverage": {
            "initial_issues": len(initial),
            "final_issues": len(issues),
            "final_prs": len(prs),
            "issue_bodies_acquired": len(issues),
            "issue_comments_acquired": comment_total,
            "issue_intake_complete": True,
            "issues_routed": len(rows),
            "prs_routed": len(pr_rows),
            "substantively_assessed_issue_ids": [1431, 1450],
            "selected_related_bodies_read": [1545, 1548, 1496, 1497],
            "issues_unassessed": len(rows) - 2,
            "failing_prs_assessed": len(TARGETS),
            "failing_prs_repaired": 0,
            "failing_prs_closed": 0,
            "remaining_failing_prs": len(TARGETS),
            "unchanged_issue_body_comment_sets_since_prior": sum(
                x["prior_content_and_comments_equal"] for x in rows
            ),
            "changed_issue_ids_since_prior": changed,
            "new_issue_ids_since_prior": added,
            "pytest_log_outcomes": dict(log_counts),
            "coverage_limit": "Complete acquisition/routing is not full scientific or code review. Prior routing was retained with explicit body/comment equality flags; prior verdicts were not carried forward.",
        },
        "actions": actions,
        "issue_rows": rows,
        "pr_rows": pr_rows,
        "theme_counts": dict(collections.Counter(x["theme"] for x in rows)),
        "next_goal": "One existing-owner bounded continuation: reconcile genuine current application/output/native-verification evidence without duplicate apply; preserve all source and ledger history. Separately diagnose exact-head pytest termination under #1450. Then sequence selected CM/KGM inputs, both scientific reports and current derived-product/final-artifact qualification under #1431. No new record discovery/PRs until the queue is below25 and checks pass.",
        "decision_needed": "Select/authorize one existing owner continuation; no goal resume was performed here. Scientific holds and separate KGM install/rebuild gates remain. Retention inventory is owned by the root supervisor, with no deletion by this task.",
        "preserved": [
            "all MIM source branches and exact heads",
            "application/final-SSSOM source/outputs and immutable ledgers",
            "scientific holds",
            "native sessions",
            "KGM gates",
        ],
        "checks": [
            "CLAW config validate passed",
            "RepositorySettings exact MIM root/origin; canonical worktree clean",
            "live complete issue/count/comment checks",
            "all20 exact PR heads/checks and pytest log attempts",
            "latest seven publication-gate logs and exact workflow",
            "no corpus parsing/build/test/apply/rerun was started",
        ],
        "source_producer": {
            "helper": pin(Path(__file__)),
            "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
        },
        "evidence": {
            "baseline": str(baseline),
            "final_delta": str(final),
            "previous_routing": pin(args.previous_report),
        },
    }
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / "review.json").write_text(json.dumps(report, indent=2) + "\n")
    for filename, data, columns in [
        (
            "issue-ledger.tsv",
            rows,
            [
                "key",
                "theme",
                "review_priority",
                "review_action",
                "review_reason",
                "review_evidence",
                "source_updated_at",
            ],
        ),
        ("pr-ledger.tsv", pr_rows, ["key", "theme", "head", "action", "pytest_log_state"]),
    ]:
        with (args.output / filename).open("w", newline="") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=columns, delimiter="\t", extrasaction="ignore"
            )
            writer.writeheader()
            writer.writerows(data)
    lines = [
        "# MIM stewardship checkpoint",
        "",
        report["state"],
        "",
        f"Published main `{counts['defaultBranchRef']['target']['oid']}`; {len(issues)} issues and {len(prs)} PRs acquired and routed. Only #1431/#1450 receive substantive keep decisions; other issue verdicts remain unreviewed.",
        "",
        "## Actions",
        "",
    ] + [
        f"- [Updated #{a['issue']}]({a['url']}) with fresh bounded failure evidence and retained holds."
        for a in actions
    ]
    lines += [
        "",
        "All20 failing PRs remain unresolved, meaningful dependent candidates. No safe small CI repair followed from runner shutdown/missing logs; no branch was closed to clear checks. Existing runtime patch selection is already present. No code, data, ledger, session or KGM mutation occurred.",
        "",
        "## Batches",
        "",
        "Routing is not scientific adjudication. Unchanged prior bodies/comments retain the same routing; changed/new entries remain explicit.",
        "",
        "| Primary theme | Issues |",
        "|---|---:|",
    ]
    lines += [f"| {k} | {v} |" for k, v in sorted(report["theme_counts"].items())]
    lines += [
        "",
        "Evidence-backed priority: P1 #1431 publication/data qualification and P1 #1450 incomplete hosted execution are separate gates. #1545 lifetime behavior is not proven to cause runner loss. #1496/#1497 source-form holds remain intact. #1548 licence disclosure is separate bounded website work; its rendered pages were not re-audited here.",
        "",
        "## Target PRs",
        "",
        "| PR | Exact head | Pytest evidence | Disposition |",
        "|---|---|---|---|",
    ]
    lines += [
        f"| [#{x['number']}]({x['url']}) | `{x['head']}` | {x['pytest_log_state']} | Retain; #1431/#1450 blockers |"
        for x in pr_rows
        if x["targeted"]
    ]
    lines += [
        "",
        "## Next bounded goal",
        "",
        report["next_goal"],
        "",
        report["decision_needed"],
        "",
        "Full per-item ledgers and exact coverage limits are in review.json, issue-ledger.tsv and pr-ledger.tsv. No all-green, scientific completion, merge, new PR, paid call or cleanup claim follows.",
    ]
    (args.output / "review.md").write_text("\n".join(lines) + "\n")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "coverage": report["coverage"],
                "theme_counts": report["theme_counts"],
            },
            indent=2,
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--previous-report", type=Path, required=True)
    parser.add_argument("--previous-snapshot", type=Path, required=True)
    parser.add_argument("--decisions", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    render(parser.parse_args())


if __name__ == "__main__":
    main()
