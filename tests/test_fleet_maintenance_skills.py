"""Unit tests for the fleet development and repository maintenance skills and scripts."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import fleet_git_and_temp_hygiene as hygiene_mod  # noqa: E402
import fleet_maintenance_cycle as cycle_mod  # noqa: E402
import fleet_pages_status as pages_mod  # noqa: E402
import fleet_stale_content_audit as stale_mod  # noqa: E402
import fleet_test_ci_status as test_ci_mod  # noqa: E402
import repo_crud_inventory as crud_mod  # noqa: E402


def _init_git_repo(path: Path, remote_url: str = "https://github.com/CultureBotAI/culturebotai-claw.git") -> None:
    path.mkdir(parents=True, exist_ok=True)
    env = {
        **os.environ,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_AUTHOR_NAME": "Test",
        "GIT_AUTHOR_EMAIL": "test@example.org",
        "GIT_COMMITTER_NAME": "Test",
        "GIT_COMMITTER_EMAIL": "test@example.org",
    }
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], env=env, check=True)
    subprocess.run(["git", "-C", str(path), "remote", "add", "origin", remote_url], env=env, check=True)
    (path / "README.md").write_text("# test\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(path), "add", "README.md"], env=env, check=True)
    subprocess.run(["git", "-C", str(path), "commit", "-q", "-m", "initial"], env=env, check=True)


class TestFleetGitAndTempHygiene:
    def test_scan_temp_roots_deduplicates_and_flags_provenance_scripts(self, tmp_path: Path) -> None:
        real_tmp = tmp_path / "real_tmp"
        real_tmp.mkdir()
        symlink_tmp = tmp_path / "sym_tmp"
        symlink_tmp.symlink_to(real_tmp)

        helper_script = real_tmp / "fix_mappings.py"
        helper_script.write_text("print('hi')\n", encoding="utf-8")

        old_scratch = real_tmp / "mech_audit.tsv"
        old_scratch.write_text("a\tb\n", encoding="utf-8")
        four_days_ago = (datetime.now(timezone.utc) - timedelta(days=4.2)).timestamp()
        os.utime(old_scratch, (four_days_ago, four_days_ago))

        cache_dir = real_tmp / "aimech-pip-audit-cache"
        cache_dir.mkdir()
        (cache_dir / "entry.json").write_text("{}", encoding="utf-8")

        temp_clone = real_tmp / "cross-mech-sync-work"
        temp_clone.mkdir()
        (temp_clone / ".git").mkdir()

        now = datetime.now(timezone.utc)
        summary = hygiene_mod.scan_temp_roots([real_tmp, symlink_tmp], now=now)

        assert len(summary["scanned_roots"]) == 1
        assert summary["total_items"] == 4
        assert str(helper_script) in summary["provenance_scripts"]
        assert summary["by_category"]["PROVENANCE_PROMOTE_REQUIRED"] == 1
        assert summary["by_category"]["SCRATCH_DATA_OR_LOG"] == 1
        assert summary["by_category"]["TOOL_CACHE_OR_PROFILE"] == 1
        assert summary["by_category"]["TEMP_GIT_CHECKOUT"] == 1

        by_name = {item["name"]: item for item in summary["items"]}
        assert by_name["mech_audit.tsv"]["reaper_risk"] is True
        assert by_name["fix_mappings.py"]["reaper_risk"] is False

    def test_inspect_locks_readonly_preserves_expired_and_malformed_locks(self, tmp_path: Path) -> None:
        lock_dir = tmp_path / "locks"
        lock_dir.mkdir()
        now = datetime(2026, 11, 3, 18, 0, 0, tzinfo=timezone.utc)
        host = socket.gethostname()

        active_lock = lock_dir / "culturemech.lock"
        active_lock.write_text(
            "\n".join(
                [
                    "repository: culturemech",
                    "operation: sync",
                    "owner: test",
                    f"hostname: {host}",
                    f"pid: {os.getpid()}",
                    "acquired_at: '2026-11-03T17:50:00+00:00'",
                    "expires_at: '2026-11-03T18:50:00+00:00'",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        expired_lock = lock_dir / "traitmech.lock"
        expired_lock.write_text(
            "\n".join(
                [
                    "repository: traitmech",
                    "operation: old_op",
                    "owner: test",
                    f"hostname: {host}",
                    f"pid: {os.getpid()}",
                    "acquired_at: '2026-11-03T15:00:00+00:00'",
                    "expires_at: '2026-11-03T16:00:00+00:00'",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        dead_pid_lock = lock_dir / "aimech.lock"
        dead_pid_lock.write_text(
            "\n".join(
                [
                    "repository: aimech",
                    "operation: crashed_op",
                    "owner: test",
                    f"hostname: {host}",
                    "pid: 99999999",
                    "acquired_at: '2026-11-03T17:55:00+00:00'",
                    "expires_at: '2026-11-03T18:55:00+00:00'",
                ]
            )
            + "\n",
            encoding="utf-8",
        )

        orphan_guard = lock_dir / "cmmmech.lock.guard"
        orphan_guard.write_text("", encoding="utf-8")

        malformed_lock = lock_dir / "dufmech.lock"
        malformed_lock.write_text(":::not_yaml\n", encoding="utf-8")

        records = hygiene_mod.inspect_locks_readonly(lock_dir, now=now)
        by_file = {r["file"]: r for r in records}

        assert by_file["culturemech.lock"]["status"] == "ACTIVE"
        assert by_file["traitmech.lock"]["status"] == "EXPIRED"
        assert by_file["aimech.lock"]["status"] == "DEAD_PID"
        assert by_file["cmmmech.lock.guard"]["status"] == "ORPHAN_GUARD"
        assert by_file["dufmech.lock"]["status"] == "MALFORMED"
        # Read-only guarantee: expired and malformed lock files must still exist on disk
        assert expired_lock.is_file()
        assert malformed_lock.is_file()
        assert orphan_guard.is_file()

    def test_scan_workspace_and_inspect_repo_git_hygiene(self, tmp_path: Path) -> None:
        claw_root = tmp_path / "culturebotai-claw"
        _init_git_repo(claw_root)

        # Create dirty tracked file, untracked file, and simulated MERGE_HEAD
        (claw_root / "README.md").write_text("# modified\n", encoding="utf-8")
        (claw_root / "untracked.txt").write_text("scratch\n", encoding="utf-8")
        (claw_root / ".git" / "MERGE_HEAD").write_text("deadbeef\n", encoding="utf-8")

        # Create workspace entries
        ws = claw_root / "workspace"
        reg_wt = ws / "registered-wt"
        reg_wt.mkdir(parents=True)
        orphan_wt = ws / "orphan-wt"
        orphan_wt.mkdir(parents=True)
        (orphan_wt / ".git").write_text("gitdir: /nonexistent\n", encoding="utf-8")
        state_dir = ws / "kgm_snapshot"
        state_dir.mkdir(parents=True)
        (state_dir / "data.tsv").write_text("id\n", encoding="utf-8")

        # Shadowed sibling checkout
        configured_mech = tmp_path / "custom" / "CommunityMech"
        _init_git_repo(configured_mech, "https://github.com/CultureBotAI/CommunityMech.git")
        sibling_mech = tmp_path / "CommunityMech"
        sibling_mech.mkdir(parents=True)

        row = hygiene_mod.inspect_repo_git_hygiene(
            "communitymech",
            "CommunityMech",
            configured_mech,
            sibling_path=sibling_mech,
        )
        assert row["configured"] is True
        assert row["branch"] == "main"
        assert row["sibling_shadow"] is not None
        assert "differs from .env-configured root" in row["sibling_shadow"]["detail"]

        claw_row = hygiene_mod.inspect_repo_git_hygiene("claw", "culturebotai-claw", claw_root)
        assert claw_row["dirty_tracked_count"] == 1
        assert claw_row["untracked_count"] >= 1
        assert "MERGE_HEAD" in claw_row["operations"]

        ws_summary = hygiene_mod.scan_workspace(claw_root, {reg_wt.resolve()})
        by_name = {e["name"]: e["kind"] for e in ws_summary["entries"]}
        assert by_name["registered-wt"] == "REGISTERED_WORKTREE"
        assert by_name["orphan-wt"] == "ORPHAN_WORKTREE"
        assert by_name["kgm_snapshot"] == "RUNTIME_STATE"


class TestFleetStaleContentAudit:
    def test_legacy_tests_stale_pyc_and_unreferenced_scripts(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        _init_git_repo(repo)

        (repo / "test_root_legacy.py").write_text("print('legacy')\n", encoding="utf-8")
        (repo / "tests").mkdir()
        (repo / "tests" / "test_proper.py").write_text("def test_ok(): assert True\n", encoding="utf-8")
        (repo / "scripts").mkdir()
        (repo / "scripts" / "used_tool.py").write_text("print('used')\n", encoding="utf-8")
        (repo / "scripts" / "orphan_tool.py").write_text("print('orphan')\n", encoding="utf-8")
        (repo / "Justfile").write_text("run:\n    python scripts/used_tool.py\n", encoding="utf-8")

        pycache = repo / "src" / "__pycache__"
        pycache.mkdir(parents=True)
        (repo / "src" / "kept.py").write_text("x = 1\n", encoding="utf-8")
        (pycache / "kept.cpython-313.pyc").write_bytes(b"0000")
        (pycache / "deleted_mod.cpython-313.pyc").write_bytes(b"0000")

        tracked = [
            "README.md",
            "Justfile",
            "test_root_legacy.py",
            "tests/test_proper.py",
            "scripts/used_tool.py",
            "scripts/orphan_tool.py",
            "src/kept.py",
        ]
        assert stale_mod.find_legacy_tests_outside_tests_dir(tracked) == ["test_root_legacy.py"]
        assert stale_mod.find_stale_pyc_files(repo) == ["src/__pycache__/deleted_mod.cpython-313.pyc"]
        assert stale_mod.find_unreferenced_scripts(repo, tracked) == ["scripts/orphan_tool.py"]

    def test_inspect_patch_backlog_detects_ledger_and_untracked_files(self, tmp_path: Path) -> None:
        patches_dir = tmp_path / "workspace" / "patches"
        patches_dir.mkdir(parents=True)
        (patches_dir / "patch_ledger.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "entry": {
                        "fingerprint": "abc123",
                        "rows": 42,
                        "first_seen": "2026-10-01T00:00:00+00:00",
                        "last_seen": "2026-10-10T00:00:00+00:00",
                        "runs": 3,
                    },
                }
            ),
            encoding="utf-8",
        )
        (patches_dir / "kgm_xref_patches.tsv").write_text("id\txref\n", encoding="utf-8")
        (patches_dir / "extra_untracked_patch.tsv").write_text("id\txref\n", encoding="utf-8")

        backlog = stale_mod.inspect_patch_backlog(tmp_path)
        assert backlog["exists"] is True
        assert backlog["ledger_entry"]["rows"] == 42
        assert backlog["ledger_entry"]["runs"] == 3
        assert backlog["ledger_entry"]["days_outstanding"] == 9
        assert backlog["untracked_patch_files"] == ["extra_untracked_patch.tsv"]


class TestFleetTestCiStatus:
    def test_inspect_test_tree_and_ci_config_detects_untyped_packages(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        tests_dir = repo / "tests"
        tests_dir.mkdir(parents=True)
        (tests_dir / "test_alpha.py").write_text(
            "\n".join(
                [
                    "import pytest",
                    "@pytest.mark.skip(reason='later')",
                    "def test_one(): pass",
                    "async def test_two(): pass",
                    "def helper(): pass",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        tree_stats = test_ci_mod.inspect_test_tree(repo)
        assert tree_stats["test_file_count"] == 1
        assert tree_stats["test_function_count"] == 2
        assert tree_stats["skip_xfail_count"] == 1

        wf_dir = repo / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "tests.yaml").write_text(
            "\n".join(
                [
                    "name: Tests",
                    "on:",
                    "  push:",
                    "    paths:",
                    "      - 'src/**'",
                    "jobs:",
                    "  test:",
                    "    steps:",
                    "      - run: uvx ruff check src tests",
                    "      - run: uv run mypy src/pkg_typed",
                    "      - run: pytest --cov-fail-under=75",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        (repo / "src" / "pkg_typed").mkdir(parents=True)
        (repo / "src" / "pkg_untyped").mkdir(parents=True)
        (repo / "Justfile").write_text("test:\n    pytest\n", encoding="utf-8")

        cfg = test_ci_mod.inspect_ci_and_justfile_config(repo)
        assert cfg["workflow_count"] == 1
        assert cfg["workflows_with_path_filters"] == ["tests.yaml"]
        assert cfg["cov_fail_under"] == [75.0]
        assert cfg["ruff_in_ci"] is True
        assert cfg["mypy_in_ci"] is True
        assert cfg["pytest_in_ci"] is True
        assert cfg["justfile_has_test_recipe"] is True
        assert cfg["untyped_src_packages"] == ["src/pkg_untyped"]

    def test_summarize_ci_runs_computes_pass_rate_and_durations(self) -> None:
        runs = [
            {
                "name": "Tests",
                "status": "completed",
                "conclusion": "success",
                "created_at": "2026-11-03T10:00:00Z",
                "run_started_at": "2026-11-03T10:00:05Z",
                "updated_at": "2026-11-03T10:01:05Z",
            },
            {
                "name": "Deploy GitHub Pages",
                "status": "completed",
                "conclusion": "success",
                "created_at": "2026-11-03T11:00:00Z",
                "run_started_at": "2026-11-03T11:00:10Z",
                "updated_at": "2026-11-03T11:00:50Z",
            },
            {
                "name": "Tests",
                "status": "completed",
                "conclusion": "failure",
                "created_at": "2026-11-03T12:00:00Z",
                "run_started_at": "2026-11-03T12:00:02Z",
                "updated_at": "2026-11-03T12:02:02Z",
            },
        ]
        summary = test_ci_mod.summarize_ci_runs(runs)
        assert summary["runs_sampled"] == 3
        assert summary["completed_runs"] == 3
        assert summary["success_count"] == 2
        assert summary["failure_count"] == 1
        assert summary["pass_rate"] == pytest.approx(0.667, rel=1e-2)
        assert summary["median_duration_sec"] == 60.0
        assert summary["median_queue_sec"] == 5.0
        assert summary["pages_median_duration_sec"] == 40.0


class TestUpgradedPagesAndCrudInventory:
    def test_pages_github_client_falls_back_to_gh_api_when_no_token(self, monkeypatch: pytest.MonkeyPatch) -> None:
        client = pages_mod.GitHubClient(token=None)
        monkeypatch.setattr(
            pages_mod.GitHubClient,
            "_gh_api_json",
            lambda self, path: {"ok": True, "path": path},
        )
        assert client.json("/repos/CultureBotAI/TraitMech/pages") == {
            "ok": True,
            "path": "/repos/CultureBotAI/TraitMech/pages",
        }

    def test_crud_inventory_fleet_collects_claw_and_mechs(self, tmp_path: Path) -> None:
        claw_root = tmp_path / "culturebotai-claw"
        _init_git_repo(claw_root)
        (claw_root / ".gitignore").write_text(".pytest_cache/\n.env\n", encoding="utf-8")
        env = {
            **os.environ,
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@example.org",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@example.org",
        }
        subprocess.run(["git", "-C", str(claw_root), "add", ".gitignore"], env=env, check=True)
        subprocess.run(["git", "-C", str(claw_root), "commit", "-q", "-m", "ignore"], env=env, check=True)
        (claw_root / ".env").write_text("", encoding="utf-8")
        (claw_root / ".pytest_cache").mkdir()
        (claw_root / ".pytest_cache" / "CACHEDIR.TAG").write_text("Signature: 8a477f597d28d172789f06886806bc55\n", encoding="utf-8")

        report = crud_mod.inventory_fleet(claw_root=claw_root, include_claw=True)
        assert report["claw_root"] == str(claw_root.resolve())
        assert "claw" in report["repositories"]
        assert report["repositories"]["claw"]["complete"] is True
        assert any(c["path"] == ".pytest_cache" for c in report["repositories"]["claw"]["candidates"])


class TestFleetMaintenanceCycle:
    def test_fast_maintenance_cycle_and_report_rendering(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        claw_root = tmp_path / "culturebotai-claw"
        _init_git_repo(claw_root)
        (claw_root / ".env").write_text("", encoding="utf-8")
        tmp_scan = tmp_path / "tmp_scan"
        tmp_scan.mkdir()

        monkeypatch.setattr(
            cycle_mod,
            "run_governance_checks",
            lambda root: {
                "cron_profile": {"ok": True, "exit_code": 0, "summary": "OK"},
                "workflow_pins": {"ok": True, "exit_code": 0, "summary": "OK"},
                "skills_check": {"ok": True, "exit_code": 0, "summary": "OK"},
            },
        )
        out_file = tmp_path / "report.txt"
        rc = cycle_mod.main(
            [
                "--tier",
                "fast",
                "--claw-root",
                str(claw_root),
                "--tmp-root",
                str(tmp_scan),
                "--write-report",
                str(out_file),
            ]
        )
        assert rc == 0
        assert out_file.is_file()
        text = out_file.read_text(encoding="utf-8")
        assert "Fleet Development & Repository Maintenance Cycle (tier=fast)" in text
        assert "=== 1. Git, Worktree, Lock & Temp Hygiene ===" in text
        assert "=== 2. Stale Content, Code, Data, Writers & Patches ===" in text
        assert "=== 3. Test, Coverage, Lint, Typecheck & CI ===" in text
        assert "=== 4. Governance & Local Site Audits ===" in text
