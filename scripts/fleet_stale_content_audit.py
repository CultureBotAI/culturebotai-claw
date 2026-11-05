#!/usr/bin/env python3
"""Read-only fleet audit for stale content, code, data, writers, and patch backlogs.

Inspects `claw` and the 14 manifest-declared Mechs across six dimensions:
1. Tracked repository weight (`kg_microbe_health.measure`) and `.git` object
   store size (`git count-objects -v`), flagging history bloat when `.git`
   greatly exceeds tracked working-tree bytes.
2. Legacy `test_*.py` / `*_test.py` files outside `tests/` and orphan `.pyc`
   files in `__pycache__` whose source `.py` file was removed.
3. Potentially unreferenced top-level scripts under `scripts/` (not mentioned in
   `Justfile`, `.github/workflows/`, `pyproject.toml`, `src/`, `tests/`, docs,
   or skills).
4. Ungoverned YAML writers (`kg_microbe_writers.audit`) lacking `--dry-run`/
   `--apply` safeguards, pre-write validation, or curation history.
5. Corpus record counts (`kg_microbe_corpus.statistics.list_records`) and
   staleness of `NEXT_TASKS.md` / `INFRA_TASKS.md`.
6. Unapplied or untracked patch artifacts in `claw/workspace/patches/`
   (`kg_microbe_patches.ledger`).

Strictly read-only: never modifies, deletes, or applies anything.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kg_microbe_corpus.statistics import CorpusError, list_records  # noqa: E402
from kg_microbe_fleet import load_fleet_manifest  # noqa: E402
from kg_microbe_fleet.roots import (  # noqa: E402
    MechRootError,
    resolve_mech_root,
)
from kg_microbe_fleet.roots import (  # noqa: E402
    claw_root as default_claw_root,
)
from kg_microbe_health.repository import HealthError  # noqa: E402
from kg_microbe_health.repository import measure as measure_health  # noqa: E402
from kg_microbe_patches.ledger import LEDGER_FILENAME, LedgerError  # noqa: E402
from kg_microbe_patches.ledger import load as load_patch_ledger  # noqa: E402
from kg_microbe_writers.audit import WriterProfile  # noqa: E402
from kg_microbe_writers.audit import audit as audit_writers  # noqa: E402

PYC_STEM_RE = re.compile(r"^(?P<stem>.+)\.cpython-\d+(?:\.opt-\d+)?\.pyc$")


def _git_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(
        GIT_OPTIONAL_LOCKS="0",
        GIT_TERMINAL_PROMPT="0",
        GIT_NO_LAZY_FETCH="1",
        GIT_CONFIG_NOSYSTEM="1",
        GIT_CONFIG_GLOBAL=os.devnull,
        LC_ALL="C",
    )
    return env


def _run_git(root: Path, *args: str, timeout: float = 15.0) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "git",
            "--no-optional-locks",
            "-c",
            "core.fsmonitor=false",
            "-c",
            f"core.excludesFile={os.devnull}",
            "-C",
            str(root),
            *args,
        ],
        capture_output=True,
        text=True,
        env=_git_env(),
        timeout=timeout,
        check=False,
    )


def measure_git_object_store_kib(root: Path) -> int | None:
    """Return total .git object store size (loose + packed) in KiB via git count-objects -v."""
    proc = _run_git(root, "count-objects", "-v")
    if proc.returncode != 0:
        return None
    total_kib = 0
    for line in proc.stdout.splitlines():
        key, _, val = line.partition(":")
        if key.strip() in {"size", "size-pack", "size-garbage"}:
            try:
                total_kib += int(val.strip())
            except ValueError:
                pass
    return total_kib


def find_stale_pyc_files(root: Path, max_dirs: int = 500) -> list[str]:
    """Find .pyc files in __pycache__ whose parent directory lacks the source .py."""
    stale: list[str] = []
    seen_dirs = 0
    stack = [root]
    skip_names = {".git", ".venv", "venv", "node_modules", "workspace", "site", "_site"}
    while stack and seen_dirs < max_dirs:
        current = stack.pop()
        seen_dirs += 1
        try:
            with os.scandir(current) as it:
                for entry in it:
                    if not entry.is_dir(follow_symlinks=False):
                        continue
                    if entry.name in skip_names:
                        continue
                    if entry.name == "__pycache__":
                        pycache_dir = Path(entry.path)
                        parent_dir = pycache_dir.parent
                        try:
                            with os.scandir(pycache_dir) as pyc_it:
                                for pyc_entry in pyc_it:
                                    m = PYC_STEM_RE.match(pyc_entry.name)
                                    if not m:
                                        continue
                                    stem = m.group("stem")
                                    if not (parent_dir / f"{stem}.py").exists():
                                        rel = Path(pyc_entry.path).relative_to(root).as_posix()
                                        stale.append(rel)
                        except OSError:
                            pass
                    else:
                        stack.append(Path(entry.path))
        except OSError:
            continue
    return sorted(stale)


def find_legacy_tests_outside_tests_dir(tracked_files: list[str]) -> list[str]:
    """Return tracked test_*.py / *_test.py files outside tests/."""
    legacy: list[str] = []
    for rel in tracked_files:
        if rel.startswith("tests/") or "/tests/" in rel:
            continue
        name = Path(rel).name
        if (name.startswith("test_") or name.endswith("_test.py")) and name.endswith(".py"):
            legacy.append(rel)
    return sorted(legacy)


def find_unreferenced_scripts(root: Path, tracked_files: list[str]) -> list[str]:
    """Identify top-level tracked scripts/ files not referenced elsewhere in the repo."""
    candidates: list[str] = []
    for rel in tracked_files:
        parts = Path(rel).parts
        if len(parts) != 2 or parts[0] != "scripts":
            continue
        name = parts[1]
        if name == "__init__.py" or not (name.endswith(".py") or name.endswith(".sh")):
            continue
        candidates.append(rel)
    if not candidates:
        return []

    file_texts: dict[str, str] = {}
    for rel in tracked_files:
        if rel.startswith(("data/", "kb/", "pages/", "docs/", "site/", "_site/")):
            continue
        suffix = Path(rel).suffix.lower()
        name = Path(rel).name
        if suffix not in {".py", ".sh", ".md", ".yaml", ".yml", ".toml", ".json"} and name not in {
            "Justfile",
            "justfile",
            "Makefile",
        }:
            continue
        try:
            file_texts[rel] = (root / rel).read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

    unreferenced: list[str] = []
    for rel in candidates:
        name = Path(rel).name
        stem = Path(rel).stem
        referenced = any(
            (name in text or stem in text)
            for other_rel, text in file_texts.items()
            if other_rel != rel
        )
        if not referenced:
            unreferenced.append(rel)
    return sorted(unreferenced)


def inspect_patch_backlog(claw_root: Path) -> dict[str, Any]:
    """Inspect claw/workspace/patches/ and patch_ledger.json read-only."""
    patches_dir = claw_root / "workspace" / "patches"
    if not patches_dir.is_dir():
        return {
            "exists": False,
            "ledger_entry": None,
            "patch_files": [],
            "untracked_patch_files": [],
            "error": None,
        }

    ledger_path = patches_dir / LEDGER_FILENAME
    ledger_dict: dict[str, Any] | None = None
    ledger_err: str | None = None
    try:
        entry = load_patch_ledger(ledger_path)
        if entry is not None:
            ledger_dict = {
                **entry.as_dict(),
                "days_outstanding": entry.days_outstanding,
            }
    except LedgerError as exc:
        ledger_err = str(exc)

    patch_files: list[dict[str, Any]] = []
    try:
        for item in sorted(os.scandir(patches_dir), key=lambda e: e.name):
            if not item.is_file(follow_symlinks=False) or item.name == LEDGER_FILENAME:
                continue
            st = item.stat(follow_symlinks=False)
            patch_files.append(
                {
                    "name": item.name,
                    "size_bytes": int(st.st_size),
                    "modified_at": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
                }
            )
    except OSError as exc:
        ledger_err = str(exc)

    # Any patch file beyond the single ledger-tracked xref patch set is untracked by the ledger
    untracked = [
        pf["name"]
        for pf in patch_files
        if pf["name"] != "kgm_xref_patches.tsv"
    ]
    return {
        "exists": True,
        "ledger_entry": ledger_dict,
        "patch_files": patch_files,
        "untracked_patch_files": untracked,
        "error": ledger_err,
    }


def _writer_profile(settings: dict[str, Any]) -> WriterProfile:
    return WriterProfile(
        search_dirs=tuple(settings["search_dirs"]),
        exclude=tuple(settings.get("exclude", ())),
        save_helpers=tuple(settings.get("save_helpers", ())),
        validators=tuple(settings.get("validators", ())),
        curation_markers=tuple(settings.get("curation_markers", ())),
    )


def audit_repository_stale_content(
    key: str,
    repo_name: str,
    root: Path | None,
    *,
    mech_spec: Any | None = None,
    config_error: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Audit one repository for stale content, code, data, and writer governance."""
    current_time = now or datetime.now(timezone.utc)
    row: dict[str, Any] = {
        "key": key,
        "repo": repo_name,
        "configured": root is not None,
        "root": str(root) if root is not None else None,
        "tracked_files": None,
        "tracked_bytes": None,
        "large_file_count": None,
        "git_object_store_kib": None,
        "git_vs_tracked_ratio": None,
        "legacy_tests_outside_tests": [],
        "stale_pyc_files": [],
        "unreferenced_scripts": [],
        "corpus_record_count": None,
        "writers_total": None,
        "writers_missing_safeguard": [],
        "writers_missing_validation": [],
        "writers_missing_curation_history": [],
        "backlog_docs": {},
        "error": config_error,
    }
    if root is None or not root.is_dir():
        if root is not None and not root.is_dir():
            row["error"] = f"directory does not exist: {root}"
        return row

    try:
        health = measure_health(key, root)
        row["tracked_files"] = health.tracked_files
        row["tracked_bytes"] = health.tracked_bytes
        row["large_file_count"] = health.large_files
    except HealthError as exc:
        row["error"] = str(exc)
        return row

    git_kib = measure_git_object_store_kib(root)
    row["git_object_store_kib"] = git_kib
    if git_kib is not None and row["tracked_bytes"]:
        row["git_vs_tracked_ratio"] = round((git_kib * 1024.0) / max(1, int(row["tracked_bytes"])), 2)

    ls_proc = _run_git(root, "ls-files", "-z")
    tracked_list = (
        [p for p in ls_proc.stdout.split("\0") if p]
        if ls_proc.returncode == 0
        else []
    )
    row["legacy_tests_outside_tests"] = find_legacy_tests_outside_tests_dir(tracked_list)
    row["stale_pyc_files"] = find_stale_pyc_files(root)
    row["unreferenced_scripts"] = find_unreferenced_scripts(root, tracked_list)

    for doc_name in ("NEXT_TASKS.md", "INFRA_TASKS.md"):
        doc_path = root / doc_name
        if doc_path.is_file():
            try:
                mtime = datetime.fromtimestamp(doc_path.stat().st_mtime, tz=timezone.utc)
                age_days = round(max(0.0, (current_time - mtime).total_seconds() / 86400.0), 1)
                row["backlog_docs"][doc_name] = {
                    "exists": True,
                    "age_days": age_days,
                }
            except OSError:
                pass

    if mech_spec is not None:
        if mech_spec.record_globs:
            try:
                records = list_records(root, list(mech_spec.record_globs))
                row["corpus_record_count"] = len(records)
            except CorpusError:
                pass

        writer_cap = mech_spec.capabilities.get("writer_audit")
        if writer_cap is not None and writer_cap.is_enabled:
            try:
                w_rows = audit_writers(root, _writer_profile(writer_cap.settings))
                row["writers_total"] = len(w_rows)
                row["writers_missing_safeguard"] = [
                    w.path for w in w_rows if not w.has_write_safeguard
                ]
                row["writers_missing_validation"] = [
                    w.path for w in w_rows if not w.validates_before_write
                ]
                row["writers_missing_curation_history"] = [
                    w.path for w in w_rows if not w.appends_curation_history
                ]
            except Exception as exc:  # noqa: BLE001
                row["error"] = str(exc)

    return row


def collect_stale_content_report(
    *,
    claw_root: Path | None = None,
    mech: str = "all",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Collect the fleet stale content, code, data, writer, and patch audit."""
    current_time = now or datetime.now(timezone.utc)
    resolved_claw = claw_root.resolve() if claw_root is not None else default_claw_root()
    manifest = load_fleet_manifest()

    repos: list[dict[str, Any]] = []
    if mech in {"all", "claw"}:
        repos.append(
            audit_repository_stale_content(
                "claw",
                "culturebotai-claw",
                resolved_claw,
                now=current_time,
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
            audit_repository_stale_content(
                key,
                repo_name,
                m_root,
                mech_spec=spec,
                config_error=err,
                now=current_time,
            )
        )

    patches = inspect_patch_backlog(resolved_claw)

    findings: list[str] = []
    if patches.get("ledger_entry") and patches["ledger_entry"].get("runs", 0) > 1:
        le = patches["ledger_entry"]
        findings.append(
            f"UNAPPLIED_PATCH_BACKLOG: {le['rows']} patch(es) unchanged across {le['runs']} runs ({le['days_outstanding']}d outstanding)"
        )
    if patches.get("untracked_patch_files"):
        findings.append(
            f"UNTRACKED_PATCH_FILES: {', '.join(patches['untracked_patch_files'])} in workspace/patches/ not tracked in patch_ledger.json"
        )
    for repo in repos:
        if not repo["configured"]:
            continue
        if repo["legacy_tests_outside_tests"]:
            findings.append(
                f"LEGACY_TESTS_OUTSIDE_TESTS: {repo['repo']} has {len(repo['legacy_tests_outside_tests'])} test file(s) outside tests/"
            )
        if repo["stale_pyc_files"]:
            findings.append(
                f"STALE_PYC: {repo['repo']} has {len(repo['stale_pyc_files'])} orphan .pyc file(s)"
            )
        if repo["writers_missing_safeguard"]:
            findings.append(
                f"WRITERS_WITHOUT_SAFEGUARD: {repo['repo']} has {len(repo['writers_missing_safeguard'])} YAML writer(s) without --dry-run/--apply"
            )
        if repo["git_vs_tracked_ratio"] and repo["git_vs_tracked_ratio"] > 5.0 and (repo["git_object_store_kib"] or 0) > 50_000:
            findings.append(
                f"GIT_HISTORY_BLOAT: {repo['repo']} .git object store ({repo['git_object_store_kib']} KiB) is {repo['git_vs_tracked_ratio']}x tracked tree size"
            )

    return {
        "generated_at": current_time.isoformat(),
        "claw_root": str(resolved_claw),
        "patches": patches,
        "repositories": repos,
        "findings": findings,
    }


def render_report(report: dict[str, Any]) -> str:
    lines = [
        "Fleet Stale Content, Code, Data, Writer & Patch Audit",
        f"Generated: {report['generated_at']}",
        "",
        f"{'REPO':<24} {'FILES':<7} {'MB':<7} {'GIT_MB':<7} {'RECORDS':<8} {'LEGACY_T':<9} {'UNREF_S':<8} {'WRITERS(NO_SAFE)'}",
    ]
    for repo in report["repositories"]:
        if not repo["configured"] or repo["tracked_files"] is None:
            lines.append(
                f"{repo['repo']:<24} {'-':<7} {'-':<7} {'-':<7} {'-':<8} {'-':<9} {'-':<8} {repo.get('error') or 'unconfigured'}"
            )
            continue
        mb = f"{(repo['tracked_bytes'] or 0) / 1_000_000:.1f}"
        git_mb = (
            f"{(repo['git_object_store_kib'] or 0) / 1024.0:.1f}"
            if repo["git_object_store_kib"] is not None
            else "-"
        )
        recs = str(repo["corpus_record_count"]) if repo["corpus_record_count"] is not None else "-"
        leg_t = str(len(repo["legacy_tests_outside_tests"]))
        unref_s = str(len(repo["unreferenced_scripts"]))
        if repo["writers_total"] is not None:
            w_str = f"{repo['writers_total']} ({len(repo['writers_missing_safeguard'])} unsafe)"
        else:
            w_str = "-"
        lines.append(
            f"{repo['repo']:<24} {repo['tracked_files']:<7} {mb:<7} {git_mb:<7} {recs:<8} {leg_t:<9} {unref_s:<8} {w_str}"
        )

    patches = report["patches"]
    lines.extend(["", "Patch Backlog (claw/workspace/patches)"])
    if not patches.get("exists"):
        lines.append("  no workspace/patches directory")
    else:
        le = patches.get("ledger_entry")
        if le:
            lines.append(
                f"  ledger: {le['rows']} rows, runs={le['runs']}, first_seen={le['first_seen'][:10]}, outstanding={le['days_outstanding']}d"
            )
        for pf in patches.get("patch_files", []):
            lines.append(f"  file: {pf['name']} ({pf['size_bytes']} bytes, modified {pf['modified_at'][:10]})")

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
    parser.add_argument("--json", action="store_true", dest="as_json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    report = collect_stale_content_report(
        claw_root=args.claw_root,
        mech=args.mech,
    )
    if args.as_json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
