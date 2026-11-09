#!/usr/bin/env python3
"""Fleet test, coverage, typecheck, lint, and GitHub Actions CI telemetry audit.

Inspects `claw`, all 14 manifest-declared Mechs, `CultureBotAI.github.io`, and
`kg-microbe` across three layers:
1. Static test & quality-gate parameters (offline, fast):
   - Test file count (`tests/**/test_*.py`), AST-counted `def test_*` functions,
     and `skip` / `xfail` marker counts.
   - GitHub Actions workflow inventory (`.github/workflows/*.y*ml`), path-filter
     detection (`paths:` / `paths-ignore:`), coverage floors
     (`--cov-fail-under`, `--fail-under`), `ruff` and `mypy` configuration,
     untyped `src/*` package detection when `mypy` lists explicit targets, and
     `Justfile` vs CI parity.
2. Optional local test execution (`--run-pytest`):
   - Runs pytest with `--durations=5` and reports pass/fail/skip counts, wall
     duration, and slowest tests.
3. Optional GitHub Actions run telemetry (`--with-ci-runs`):
   - Queries `/repos/<owner>/<repo>/actions/runs` via `gh api` (without token
     extraction) and computes pass rate, median/p90 duration, queue wait, and
     GitHub Pages build duration.

Strictly read-only.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kg_microbe_fleet import load_fleet_manifest  # noqa: E402
from kg_microbe_fleet.roots import (  # noqa: E402
    MechRootError,
    dotenv_value,
    resolve_culturebotai_site_root,
    resolve_mech_root,
)
from kg_microbe_fleet.roots import (  # noqa: E402
    claw_root as default_claw_root,
)

COV_FLOOR_RE = re.compile(r"--(?:cov-)?fail-under(?:=|\s+)(\d+(?:\.\d+)?)")
SKIP_XFAIL_RE = re.compile(r"\b(?:pytest\.mark\.(?:skip|skipif|xfail)|pytest\.(?:skip|xfail))\b")
PYTEST_SUMMARY_RE = re.compile(r"(\d+)\s+(passed|failed|skipped|xfailed|xpassed|error|errors)")


def inspect_test_tree(root: Path) -> dict[str, int]:
    """Count test files, test functions/methods (via AST), and skip/xfail markers."""
    tests_dir = root / "tests"
    if not tests_dir.is_dir():
        return {
            "test_file_count": 0,
            "test_function_count": 0,
            "skip_xfail_count": 0,
        }

    test_files = sorted(
        {
            *tests_dir.rglob("test_*.py"),
            *tests_dir.rglob("*_test.py"),
        }
    )
    func_count = 0
    skip_xfail = 0
    for tf in test_files:
        try:
            source = tf.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        skip_xfail += len(SKIP_XFAIL_RE.findall(source))
        try:
            tree = ast.parse(source, filename=str(tf))
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                    func_count += 1
        except SyntaxError:
            func_count += len(re.findall(r"^\s*(?:async\s+)?def\s+test_\w+", source, flags=re.MULTILINE))

    return {
        "test_file_count": len(test_files),
        "test_function_count": func_count,
        "skip_xfail_count": skip_xfail,
    }


def inspect_ci_and_justfile_config(root: Path) -> dict[str, Any]:
    """Inspect .github/workflows, Justfile, and pyproject.toml for test/lint/typecheck config."""
    wf_dir = root / ".github" / "workflows"
    workflow_files: list[str] = []
    workflows_with_path_filters: list[str] = []
    wf_texts: list[str] = []

    if wf_dir.is_dir():
        for wf in sorted([*wf_dir.glob("*.yaml"), *wf_dir.glob("*.yml")]):
            workflow_files.append(wf.name)
            try:
                txt = wf.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            wf_texts.append(txt)
            if re.search(r"^\s*paths(?:-ignore)?\s*:", txt, flags=re.MULTILINE):
                workflows_with_path_filters.append(wf.name)

    combined_wf = "\n".join(wf_texts)
    cov_floors = sorted({float(m) for m in COV_FLOOR_RE.findall(combined_wf)})

    justfile_text = ""
    for jf_name in ("Justfile", "justfile"):
        jf_path = root / jf_name
        if jf_path.is_file():
            try:
                justfile_text = jf_path.read_text(encoding="utf-8", errors="ignore")
                break
            except OSError:
                pass

    pyproject_text = ""
    pp_path = root / "pyproject.toml"
    if pp_path.is_file():
        try:
            pyproject_text = pp_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            pass

    if not cov_floors:
        cov_floors = sorted({float(m) for m in COV_FLOOR_RE.findall(justfile_text + "\n" + pyproject_text)})

    ruff_in_ci = bool(re.search(r"\bruff\b", combined_wf))
    mypy_in_ci = bool(re.search(r"\bmypy\b", combined_wf))
    pytest_in_ci = bool(re.search(r"\bpytest\b", combined_wf))
    just_has_test = bool(
        re.search(r"^(?:test|pytest|check|ci)\s*:", justfile_text, flags=re.MULTILINE)
    )

    # Check if src/* packages exist that are omitted from an explicit mypy target list in CI
    src_dir = root / "src"
    untyped_src_packages: list[str] = []
    if src_dir.is_dir() and mypy_in_ci:
        src_pkgs = sorted(
            p.name
            for p in src_dir.iterdir()
            if p.is_dir() and not p.name.startswith((".", "_")) and not p.name.endswith(".egg-info")
        )
        # If CI invokes mypy with explicit `src/<pkg>` paths rather than whole `src`, check coverage
        if re.search(r"\bsrc/[A-Za-z0-9_]+", combined_wf):
            for pkg in src_pkgs:
                if f"src/{pkg}" not in combined_wf:
                    untyped_src_packages.append(f"src/{pkg}")

    return {
        "workflow_count": len(workflow_files),
        "workflow_files": workflow_files,
        "workflows_with_path_filters": workflows_with_path_filters,
        "cov_fail_under": cov_floors,
        "pytest_in_ci": pytest_in_ci,
        "ruff_in_ci": ruff_in_ci,
        "mypy_in_ci": mypy_in_ci,
        "justfile_has_test_recipe": just_has_test,
        "untyped_src_packages": untyped_src_packages,
    }


def run_local_pytest(root: Path, timeout: float = 120.0) -> dict[str, Any]:
    """Run pytest -q --durations=5 in `root` and return execution metrics."""
    venv_python = root / ".venv" / "bin" / "python"
    python_exe = str(venv_python) if venv_python.is_file() else sys.executable
    env = dict(os.environ)
    src_path = root / "src"
    env["PYTHONPATH"] = f"{src_path}:{root}" if src_path.is_dir() else str(root)

    started = time.monotonic()
    try:
        proc = subprocess.run(
            [python_exe, "-m", "pytest", "-q", "-o", "cache_dir=/tmp/pytest_cache_fleet_audit", "--durations=5"],
            cwd=str(root),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        elapsed = round(time.monotonic() - started, 2)
    except subprocess.TimeoutExpired:
        return {
            "executed": True,
            "exit_code": None,
            "timed_out": True,
            "wall_seconds": round(timeout, 2),
            "counts": {},
            "slowest_tests": [],
        }
    except OSError as exc:
        return {
            "executed": False,
            "exit_code": None,
            "timed_out": False,
            "wall_seconds": 0.0,
            "counts": {},
            "slowest_tests": [],
            "error": str(exc),
        }

    counts: dict[str, int] = {}
    output = (proc.stdout or "") + "\n" + (proc.stderr or "")
    for num_s, label in PYTEST_SUMMARY_RE.findall(output):
        key = "errors" if label == "error" else label
        counts[key] = int(num_s)

    slowest: list[str] = []
    in_durations = False
    for line in (proc.stdout or "").splitlines():
        if "slowest" in line and "durations" in line:
            in_durations = True
            continue
        if in_durations:
            if line.startswith("="):
                break
            stripped = line.strip()
            if stripped:
                slowest.append(stripped)

    return {
        "executed": True,
        "exit_code": proc.returncode,
        "timed_out": False,
        "wall_seconds": elapsed,
        "counts": counts,
        "slowest_tests": slowest[:5],
    }


def _parse_iso(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except ValueError:
        return None


def _percentile(sorted_vals: list[float], pct: float) -> float | None:
    if not sorted_vals:
        return None
    idx = min(len(sorted_vals) - 1, max(0, int(round((pct / 100.0) * (len(sorted_vals) - 1)))))
    return round(sorted_vals[idx], 1)


def default_ci_runs_fetcher(github_slug: str, limit: int = 20, timeout: float = 20.0) -> list[dict[str, Any]]:
    """Fetch recent GitHub Actions workflow runs via `gh api`."""
    if not shutil.which("gh"):
        return []
    proc = subprocess.run(
        [
            "gh",
            "api",
            f"repos/{github_slug}/actions/runs?per_page={limit}",
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if proc.returncode != 0:
        return []
    try:
        payload = json.loads(proc.stdout)
        runs = payload.get("workflow_runs")
        return list(runs) if isinstance(runs, list) else []
    except json.JSONDecodeError:
        return []


def summarize_ci_runs(runs: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute pass rate, duration stats, queue delay, and Pages build time from workflow_runs."""
    completed = [r for r in runs if r.get("status") == "completed"]
    success_count = sum(1 for r in completed if r.get("conclusion") == "success")
    failure_count = sum(
        1 for r in completed if r.get("conclusion") in {"failure", "timed_out", "startup_failure"}
    )
    pass_rate = round(success_count / len(completed), 3) if completed else None

    durations: list[float] = []
    queue_waits: list[float] = []
    pages_durations: list[float] = []

    for run in completed:
        created = _parse_iso(run.get("created_at"))
        started = _parse_iso(run.get("run_started_at")) or created
        updated = _parse_iso(run.get("updated_at"))
        if created and started and started >= created:
            queue_waits.append((started - created).total_seconds())
        if started and updated and updated >= started:
            dur = (updated - started).total_seconds()
            durations.append(dur)
            name = str(run.get("name") or "").lower()
            if "pages" in name:
                pages_durations.append(dur)

    durations.sort()
    queue_waits.sort()
    pages_durations.sort()

    return {
        "runs_sampled": len(runs),
        "completed_runs": len(completed),
        "success_count": success_count,
        "failure_count": failure_count,
        "pass_rate": pass_rate,
        "median_duration_sec": round(statistics.median(durations), 1) if durations else None,
        "p90_duration_sec": _percentile(durations, 90.0),
        "median_queue_sec": round(statistics.median(queue_waits), 1) if queue_waits else None,
        "pages_median_duration_sec": round(statistics.median(pages_durations), 1) if pages_durations else None,
    }


def inspect_repository_test_ci(
    key: str,
    repo_name: str,
    github_slug: str,
    root: Path | None,
    *,
    config_error: str | None = None,
    run_pytest: bool = False,
    pytest_timeout: float = 120.0,
    with_ci_runs: bool = False,
    runs_limit: int = 20,
    ci_fetcher: Callable[[str, int], list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "key": key,
        "repo": repo_name,
        "github": github_slug,
        "configured": root is not None and root.is_dir(),
        "root": str(root) if root is not None else None,
        "tests": {
            "test_file_count": 0,
            "test_function_count": 0,
            "skip_xfail_count": 0,
        },
        "ci_config": None,
        "pytest_run": None,
        "ci_telemetry": None,
        "error": config_error,
    }
    if root is not None and root.is_dir():
        row["tests"] = inspect_test_tree(root)
        row["ci_config"] = inspect_ci_and_justfile_config(root)
        if run_pytest and row["tests"]["test_file_count"] > 0:
            row["pytest_run"] = run_local_pytest(root, timeout=pytest_timeout)

    if with_ci_runs and github_slug:
        fetcher = ci_fetcher or (lambda slug, lim: default_ci_runs_fetcher(slug, lim))
        runs = fetcher(github_slug, runs_limit)
        row["ci_telemetry"] = summarize_ci_runs(runs)

    return row


def collect_test_ci_report(
    *,
    claw_root: Path | None = None,
    mech: str = "all",
    run_pytest: bool = False,
    pytest_timeout: float = 120.0,
    with_ci_runs: bool = False,
    runs_limit: int = 20,
    ci_fetcher: Callable[[str, int], list[dict[str, Any]]] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    current_time = now or datetime.now(timezone.utc)
    resolved_claw = claw_root.resolve() if claw_root is not None else default_claw_root()
    manifest = load_fleet_manifest()

    repos: list[dict[str, Any]] = []
    if mech in {"all", "claw"}:
        repos.append(
            inspect_repository_test_ci(
                "claw",
                "culturebotai-claw",
                "CultureBotAI/culturebotai-claw",
                resolved_claw,
                run_pytest=run_pytest,
                pytest_timeout=pytest_timeout,
                with_ci_runs=with_ci_runs,
                runs_limit=runs_limit,
                ci_fetcher=ci_fetcher,
            )
        )

    target_mechs = (
        sorted(manifest.mechs)
        if mech == "all"
        else ([mech] if mech in manifest.mechs else [])
    )
    for key in target_mechs:
        spec = manifest.mechs[key]
        repo_name = spec.github.split("/")[-1]
        try:
            m_root: Path | None = resolve_mech_root(key, claw_root=resolved_claw)
            err = None
        except MechRootError as exc:
            m_root = None
            err = str(exc)
        repos.append(
            inspect_repository_test_ci(
                key,
                repo_name,
                spec.github,
                m_root,
                config_error=err,
                run_pytest=run_pytest,
                pytest_timeout=pytest_timeout,
                with_ci_runs=with_ci_runs,
                runs_limit=runs_limit,
                ci_fetcher=ci_fetcher,
            )
        )

    if mech == "all":
        try:
            site_root: Path | None = resolve_culturebotai_site_root(claw_root=resolved_claw)
            site_err = None
        except MechRootError as exc:
            site_root = None
            site_err = str(exc)
        repos.append(
            inspect_repository_test_ci(
                "culturebotai_site",
                "CultureBotAI.github.io",
                "CultureBotAI/CultureBotAI.github.io",
                site_root,
                config_error=site_err,
                run_pytest=run_pytest,
                pytest_timeout=pytest_timeout,
                with_ci_runs=with_ci_runs,
                runs_limit=runs_limit,
                ci_fetcher=ci_fetcher,
            )
        )

        kgm_raw = os.environ.get("KGM_ROOT") or dotenv_value(resolved_claw, "KGM_ROOT")
        kgm_sibling = resolved_claw.parent / "kg-microbe"
        kgm_root = Path(kgm_raw).resolve() if kgm_raw else (kgm_sibling.resolve() if kgm_sibling.is_dir() else None)
        if kgm_root is not None:
            repos.append(
                inspect_repository_test_ci(
                    "kg_microbe",
                    "kg-microbe",
                    "Knowledge-Graph-Hub/kg-microbe",
                    kgm_root,
                    run_pytest=run_pytest,
                    pytest_timeout=pytest_timeout,
                    with_ci_runs=with_ci_runs,
                    runs_limit=runs_limit,
                    ci_fetcher=ci_fetcher,
                )
            )

    findings: list[str] = []
    for repo in repos:
        if not repo["configured"]:
            continue
        cfg = repo.get("ci_config") or {}
        if cfg.get("untyped_src_packages"):
            findings.append(
                f"UNTYPED_SRC_PACKAGES: {repo['repo']} mypy CI list omits {', '.join(cfg['untyped_src_packages'])}"
            )
        if repo["tests"]["test_file_count"] == 0 and repo["key"] != "culturebotai_site":
            findings.append(f"NO_TESTS: {repo['repo']} has 0 test files under tests/")
        if not cfg.get("pytest_in_ci") and repo["tests"]["test_file_count"] > 0:
            findings.append(f"PYTEST_NOT_IN_CI: {repo['repo']} has tests but pytest is not wired in .github/workflows/")
        pr = repo.get("pytest_run")
        if pr and pr.get("exit_code") not in (None, 0):
            findings.append(f"PYTEST_FAILED: {repo['repo']} exited with code {pr['exit_code']}")
        tele = repo.get("ci_telemetry")
        if tele and tele.get("pass_rate") is not None and tele["pass_rate"] < 0.8:
            findings.append(
                f"LOW_CI_PASS_RATE: {repo['repo']} recent GitHub Actions pass rate is {tele['pass_rate'] * 100:.0f}%"
            )

    return {
        "generated_at": current_time.isoformat(),
        "claw_root": str(resolved_claw),
        "repositories": repos,
        "findings": findings,
    }


def render_report(report: dict[str, Any]) -> str:
    lines = [
        "Fleet Test, Coverage, Lint, Typecheck & CI Telemetry Status",
        f"Generated: {report['generated_at']}",
        "",
        f"{'REPO':<24} {'T_FILES':<8} {'T_FUNCS':<8} {'SKIP/XF':<8} {'COV_FLR':<8} {'WF':<4} {'RUFF':<5} {'MYPY':<5} {'CI_PASS':<8} {'MED_S'}",
    ]
    for repo in report["repositories"]:
        if not repo["configured"]:
            lines.append(
                f"{repo['repo']:<24} {'-':<8} {'-':<8} {'-':<8} {'-':<8} {'-':<4} {'-':<5} {'-':<5} {'-':<8} unconfigured"
            )
            continue
        t = repo["tests"]
        cfg = repo["ci_config"] or {}
        floors = ",".join(f"{int(f)}%" if f.is_integer() else f"{f}%" for f in cfg.get("cov_fail_under", [])) or "-"
        ruff_s = "yes" if cfg.get("ruff_in_ci") else "no"
        mypy_s = "yes" if cfg.get("mypy_in_ci") else "no"
        if cfg.get("untyped_src_packages"):
            mypy_s = f"gap({len(cfg['untyped_src_packages'])})"
        tele = repo.get("ci_telemetry")
        if tele and tele.get("pass_rate") is not None:
            pass_s = f"{tele['pass_rate'] * 100:.0f}%"
            med_s = f"{tele['median_duration_sec']}s" if tele.get("median_duration_sec") is not None else "-"
        else:
            pass_s = "-"
            med_s = "-"
        lines.append(
            f"{repo['repo']:<24} {t['test_file_count']:<8} {t['test_function_count']:<8} "
            f"{t['skip_xfail_count']:<8} {floors:<8} {cfg.get('workflow_count', 0):<4} "
            f"{ruff_s:<5} {mypy_s:<5} {pass_s:<8} {med_s}"
        )

    if any(r.get("pytest_run") for r in report["repositories"]):
        lines.extend(["", "Local Pytest Execution"])
        for repo in report["repositories"]:
            pr = repo.get("pytest_run")
            if not pr:
                continue
            status = "PASS" if pr.get("exit_code") == 0 else ("TIMEOUT" if pr.get("timed_out") else f"FAIL({pr.get('exit_code')})")
            lines.append(
                f"  {repo['repo']:<24} {status:<10} {pr.get('wall_seconds', 0):.2f}s  counts={pr.get('counts', {})}"
            )

    if report["findings"]:
        lines.extend(["", "Findings"])
        for finding in report["findings"]:
            lines.append(f"  - {finding}")
    else:
        lines.extend(["", "Findings: none"])
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    manifest = load_fleet_manifest()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mech",
        default="all",
        choices=["all", "claw", *sorted(manifest.mechs)],
        help="Target Mech key, 'claw', or 'all' (default)",
    )
    parser.add_argument(
        "--claw-root",
        type=Path,
        default=None,
        help="Explicit culturebotai-claw root directory",
    )
    parser.add_argument(
        "--run-pytest",
        action="store_true",
        help="Execute local pytest with --durations=5 in configured repositories",
    )
    parser.add_argument(
        "--pytest-timeout",
        type=float,
        default=120.0,
        help="Timeout in seconds per repository when --run-pytest is enabled",
    )
    parser.add_argument(
        "--with-ci-runs",
        action="store_true",
        help="Query recent GitHub Actions workflow runs via gh api",
    )
    parser.add_argument(
        "--runs-limit",
        type=int,
        default=20,
        help="Number of recent workflow runs to sample per repo with --with-ci-runs",
    )
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = collect_test_ci_report(
        claw_root=args.claw_root,
        mech=args.mech,
        run_pytest=args.run_pytest,
        pytest_timeout=args.pytest_timeout,
        with_ci_runs=args.with_ci_runs,
        runs_limit=args.runs_limit,
    )
    if args.as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
