#!/usr/bin/env python3
"""Unified fleet development & repository maintenance cycle runner.

Executes the read-only fleet maintenance audit in two tiers:
- `--tier fast` (default, offline):
  1. Git, worktree, branch, stash, lock & temp-root hygiene (`fleet_git_and_temp_hygiene`)
  2. Stale content, code, data, writer & patch audit (`fleet_stale_content_audit`)
  3. Static test, coverage floor, lint, typecheck & workflow audit (`fleet_test_ci_status`)
  4. Governance & skill drift checks (`apply_cron_profile --check-active`,
     `update_governed_workflow_pins --check`, `kg-microbe-skills check`)
- `--tier full` (includes `fast` plus remote/network & full metadata inventories):
  5. GitHub Pages freshness + local `page_budgets` & `site_contract` audits
     (`fleet_pages_status --with-local-audits`)
  6. GitHub Actions CI run telemetry (`fleet_test_ci_status --with-ci-runs`)
  7. Fleet-wide metadata-only CRUD inventory (`repo_crud_inventory --all-fleet`)

Strictly read-only unless `--write-report PATH` is explicitly passed to save the
JSON/Markdown report.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fleet_git_and_temp_hygiene import collect_hygiene_report  # noqa: E402
from fleet_pages_status import (  # noqa: E402
    ApiError,
    GitHubClient,
    collect_local_audits,
)
from fleet_pages_status import (  # noqa: E402
    collect as collect_pages_status,
)
from fleet_stale_content_audit import collect_stale_content_report  # noqa: E402
from fleet_test_ci_status import collect_test_ci_report  # noqa: E402
from repo_crud_inventory import inventory_fleet  # noqa: E402

from kg_microbe_fleet import load_fleet_manifest  # noqa: E402
from kg_microbe_fleet.roots import claw_root as default_claw_root  # noqa: E402


def run_governance_checks(claw_root: Path) -> dict[str, Any]:
    """Run read-only cron-profile, workflow-pin, and skill-sync checks."""
    venv_python = claw_root / ".venv" / "bin" / "python"
    python_exe = str(venv_python) if venv_python.is_file() else sys.executable
    env_pythonpath = f"{claw_root / 'src'}:{claw_root}"
    env = dict(__import__("os").environ, PYTHONPATH=env_pythonpath)

    checks: dict[str, Any] = {}
    commands = {
        "cron_profile": [
            python_exe,
            str(claw_root / "scripts" / "apply_cron_profile.py"),
            "--check-active",
        ],
        "workflow_pins": [
            python_exe,
            str(claw_root / "scripts" / "update_governed_workflow_pins.py"),
            "--check",
        ],
        "skills_check": [
            python_exe,
            "-m",
            "kg_microbe_skills",
            "check",
        ],
        "template_baseline": [
            python_exe, "-m", "kg_microbe_skills.template_cli",
            "check-baseline", "--source-root", str(claw_root),
        ],
        "template_consumers": [
            python_exe, "-m", "kg_microbe_skills.template_fleet",
            "--claw-root", str(claw_root),
        ],
    }
    for name, cmd in commands.items():
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(claw_root),
                env=env,
                capture_output=True,
                text=True,
                timeout=30.0,
                check=False,
            )
            checks[name] = {
                "ok": proc.returncode == 0,
                "exit_code": proc.returncode,
                "details": proc.stdout.strip() if name == "template_consumers" else "",
                "summary": (proc.stdout or proc.stderr or "").strip().splitlines()[-1]
                if (proc.stdout or proc.stderr or "").strip()
                else "",
            }
        except (OSError, subprocess.TimeoutExpired) as exc:
            checks[name] = {
                "ok": False,
                "exit_code": None,
                "summary": str(exc),
            }
    return checks


def run_maintenance_cycle(
    *,
    tier: str = "fast",
    claw_root: Path | None = None,
    tmp_roots: list[Path] | None = None,
    run_pytest: bool = False,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Execute the requested maintenance tier and return a consolidated report."""
    current_time = now or datetime.now(timezone.utc)
    resolved_claw = claw_root.resolve() if claw_root is not None else default_claw_root()

    hygiene = collect_hygiene_report(
        claw_root=resolved_claw,
        tmp_roots=tmp_roots,
        now=current_time,
    )
    stale = collect_stale_content_report(
        claw_root=resolved_claw,
        mech="all",
        now=current_time,
    )
    test_ci = collect_test_ci_report(
        claw_root=resolved_claw,
        mech="all",
        run_pytest=run_pytest,
        with_ci_runs=(tier == "full"),
        now=current_time,
    )
    governance = run_governance_checks(resolved_claw)

    pages_report: dict[str, Any] | None = None
    crud_summary: dict[str, Any] | None = None
    if tier == "full":
        client = GitHubClient(
            token=__import__("os").getenv("GH_TOKEN") or __import__("os").getenv("GITHUB_TOKEN")
        )
        try:
            pages_report = collect_pages_status(
                client,
                with_local_audits=True,
                claw_root=resolved_claw,
            )
        except ApiError as exc:
            pages_report = {
                "error": str(exc),
                "local_audits": collect_local_audits(claw_root=resolved_claw),
            }
        fleet_crud = inventory_fleet(claw_root=resolved_claw)
        crud_repos = fleet_crud["repositories"]
        crud_summary = {
            "repositories_scanned": len(crud_repos),
            "total_candidates": fleet_crud["total_review_candidates"],
            "total_candidate_bytes": fleet_crud["total_review_candidate_bytes"],
            "incomplete_repos": [
                key for key, r in crud_repos.items() if not r.get("complete")
            ],
        }
    else:
        pages_report = {
            "local_audits": collect_local_audits(claw_root=resolved_claw),
        }

    all_findings: list[str] = [
        *hygiene.get("findings", []),
        *stale.get("findings", []),
        *test_ci.get("findings", []),
    ]
    for g_name, g_res in governance.items():
        if not g_res.get("ok"):
            all_findings.append(f"GOVERNANCE_{g_name.upper()}_FAILED: {g_res.get('summary')}")

    return {
        "generated_at": current_time.isoformat(),
        "tier": tier,
        "claw_root": str(resolved_claw),
        "manifest_mech_count": len(load_fleet_manifest().mechs),
        "hygiene": hygiene,
        "stale_content": stale,
        "test_ci": test_ci,
        "governance": governance,
        "pages": pages_report,
        "crud_summary": crud_summary,
        "findings": all_findings,
    }


def render_cycle_report(report: dict[str, Any]) -> str:
    lines = [
        f"Fleet Development & Repository Maintenance Cycle (tier={report['tier']})",
        f"Generated: {report['generated_at']}",
        f"CLAW Root: {report['claw_root']}",
        "",
        "=== 1. Git, Worktree, Lock & Temp Hygiene ===",
    ]
    hygiene = report["hygiene"]
    temp = hygiene["temp"]
    ws = hygiene["workspace"]
    configured_repos = sum(1 for r in hygiene["repositories"] if r["configured"])
    dirty_repos = sum(
        1
        for r in hygiene["repositories"]
        if r["configured"] and (r["dirty_tracked_count"] > 0 or r["untracked_count"] > 0)
    )
    total_wts = sum(len(r["worktrees"]) for r in hygiene["repositories"] if r["configured"])
    total_stashes = sum(r["stash_count"] for r in hygiene["repositories"] if r["configured"])
    lines.extend(
        [
            f"  Repositories configured: {configured_repos}/{len(hygiene['repositories'])} (dirty/untracked={dirty_repos}, worktrees={total_wts}, stashes={total_stashes})",
            f"  CLAW workspace entries: {len(ws['entries'])}, locks: {len(ws['locks'])}",
            f"  Temp items across {', '.join(temp['scanned_roots'])}: {temp['total_items']} ({temp['total_bytes']} bytes), provenance_scripts={len(temp['provenance_scripts'])}",
            "",
            "=== 2. Stale Content, Code, Data, Writers & Patches ===",
        ]
    )
    stale = report["stale_content"]
    total_tracked_mb = sum((r["tracked_bytes"] or 0) for r in stale["repositories"] if r["configured"]) / 1_000_000.0
    total_records = sum((r["corpus_record_count"] or 0) for r in stale["repositories"] if r["configured"])
    unsafe_writers = sum(len(r["writers_missing_safeguard"]) for r in stale["repositories"] if r["configured"])
    lines.extend(
        [
            f"  Fleet tracked weight: {total_tracked_mb:.1f} MB across configured repos; corpus records={total_records}",
            f"  YAML writers missing --dry-run/--apply safeguard: {unsafe_writers}",
        ]
    )
    le = stale["patches"].get("ledger_entry")
    if le:
        lines.append(
            f"  Patch backlog: {le['rows']} rows ({le['runs']} runs, {le['days_outstanding']}d outstanding)"
        )

    lines.extend(["", "=== 3. Test, Coverage, Lint, Typecheck & CI ==="])
    tci = report["test_ci"]
    total_tfiles = sum(r["tests"]["test_file_count"] for r in tci["repositories"] if r["configured"])
    total_tfuncs = sum(r["tests"]["test_function_count"] for r in tci["repositories"] if r["configured"])
    lines.append(f"  Fleet test suite: {total_tfiles} test files, {total_tfuncs} test functions")

    lines.extend(["", "=== 4. Governance & Local Site Audits ==="])
    for name, res in report["governance"].items():
        verdict = "PASS" if res["ok"] else "FAIL"
        lines.append(f"  {name:<18} {verdict:<6} {res['summary']}")
        if res.get("details"):
            lines.append(res["details"])

    pages = report.get("pages") or {}
    local_audits = pages.get("local_audits") or []
    if local_audits:
        budget_pass = sum(1 for a in local_audits if a.get("budget_ok") is True)
        contract_pass = sum(1 for a in local_audits if a.get("site_contract_ok") is True)
        lines.append(
            f"  Local site audits: {len(local_audits)} Mechs checked (page_budgets pass={budget_pass}, site_contract pass={contract_pass})"
        )

    if report.get("crud_summary"):
        cs = report["crud_summary"]
        lines.append(
            f"  CRUD cache candidates: {cs['total_candidates']} ({cs['total_candidate_bytes']} bytes)"
        )

    if report["findings"]:
        lines.extend(["", f"=== Findings ({len(report['findings'])}) ==="])
        for finding in report["findings"]:
            lines.append(f"  - {finding}")
    else:
        lines.extend(["", "=== Findings: none ==="])
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tier",
        choices=["fast", "full"],
        default="fast",
        help="Execution tier: 'fast' (offline/local) or 'full' (includes GitHub Pages, CI runs, and CRUD scan)",
    )
    parser.add_argument(
        "--claw-root",
        type=Path,
        default=None,
        help="Explicit culturebotai-claw root directory",
    )
    parser.add_argument(
        "--tmp-root",
        type=Path,
        action="append",
        dest="tmp_roots",
        default=None,
        help="Override temp root(s) to scan",
    )
    parser.add_argument(
        "--run-pytest",
        action="store_true",
        help="Also execute local pytest suites during the cycle",
    )
    parser.add_argument(
        "--write-report",
        type=Path,
        default=None,
        help="Optional path to write the JSON or Markdown report",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = run_maintenance_cycle(
        tier=args.tier,
        claw_root=args.claw_root,
        tmp_roots=args.tmp_roots,
        run_pytest=args.run_pytest,
    )
    rendered = (
        json.dumps(report, indent=2, sort_keys=True)
        if args.as_json
        else render_cycle_report(report)
    )
    if args.write_report is not None:
        args.write_report.parent.mkdir(parents=True, exist_ok=True)
        args.write_report.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
