#!/usr/bin/env python3
"""Revert each safety check in the two reusable #729 helpers and confirm a test goes red.

Purpose: AGENTS.md requires a test for a distinction to be driven by an input
where the two sides differ, and mutation is how that is shown. Each mutant
below undoes one check added to cleanup_merged_pr_branch.py
(culturebotai-claw#854-#856, #858, #867-#872) or
commit_and_push_mech_branch_locked.py (#857, #858, #868, #871). The named test
must fail with the mutant applied, and each test
file must pass without it.
Inputs: none; run from the claw checkout or worktree holding the script.
Outputs: one line per mutant (KILLED or SURVIVED) and a nonzero exit if any
survives or an unmutated test file fails. Each script is restored after every
mutant, also on error. Each run is a fresh Python process running pytest.
Serves: culturebotai-claw PR 851. Written 2026-11-06.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLEANUP = ("scripts/adhoc/cleanup_merged_pr_branch.py", "tests/test_cleanup_merged_pr_branch.py")
COMMIT = ("scripts/adhoc/commit_and_push_mech_branch_locked.py", "tests/test_commit_and_push_mech_branch_locked.py")

CLEANUP_MUTANTS = [
    ("no unmerged check", 'if pr["state"] != "MERGED":', "if False:", "test_an_unmerged_or_forked_pr_is_refused"),
    ("no fork check", 'if pr["isCrossRepository"]:', "if False:", "test_an_unmerged_or_forked_pr_is_refused"),
    ("no remote-head check", "if remote and remote != head:", "if False:",
     "test_a_push_after_the_merge_keeps_every_copy_of_the_branch"),
    ("no lease", 'git(checkout, "push", "-q", f"--force-with-lease=refs/heads/{branch}:{head}",',
     'git(checkout, "push", "-q",', "test_the_remote_delete_is_leased_on_the_merged_head"),
    # Both layers of the exact-name match are reverted, back to the original `--heads origin <name>`;
    # either layer alone still protects, so reverting one survives by design.
    ("suffix match", ('git(checkout, "ls-remote", "origin", ref)', 'if line.endswith(f"\\t{ref}")'),
     ('git(checkout, "ls-remote", "--heads", "origin", branch)', "if line"),
     "test_only_the_exact_branch_name_is_matched_on_the_remote"),
    ("no ignored files", 'STATUS = ("status", "--porcelain", "--ignored=traditional", "--untracked-files=normal")',
     'STATUS = ("status", "--porcelain", "--untracked-files=normal")',
     "test_an_ignored_result_file_blocks_removing_the_worktree"),
    ("status obeys config", 'STATUS = ("status", "--porcelain", "--ignored=traditional", "--untracked-files=normal")',
     'STATUS = ("status", "--porcelain", "--ignored")', "test_a_status_setting_cannot_hide_untracked_or_ignored_files"),
    ("no hidden-entry check", "    if hidden:\n", "    if False:\n",
     "test_an_edit_hidden_by_skip_worktree_blocks_removing_the_worktree"),
    ("paths unresolved", "    worktree = worktree.resolve() if worktree is not None else None\n", "",
     "test_a_relative_worktree_is_the_one_checked_and_the_one_removed"),
    ("no lock", 'with LockManager().lock(key, "cleanup-merged-branch"):', "with open(os.devnull):",
     "test_a_held_lock_on_the_repository_stops_everything"),
    ("constant lock key", 'LockManager().lock(key, "cleanup-merged-branch")', 'LockManager().lock("x", "cleanup-merged-branch")',
     "test_a_held_lock_on_the_repository_stops_everything"),
    ("update-ref without old value", 'git(checkout, "update-ref", "-d", f"refs/heads/{branch}", head)',
     'git(checkout, "update-ref", "-d", f"refs/heads/{branch}")', "test_the_local_delete_compares_against_the_merged_head"),
    ("branch config kept", '                git(checkout, "config", "--remove-section", f"branch.{branch}", check=False)\n', "",
     "test_the_merged_branch_is_removed_everywhere_and_caches_do_not_block"),
    ("dry run deletes", "        if not apply:\n", "        if False:\n", "test_a_dry_run_checks_everything_and_deletes_nothing"),
    ("partial failure unreported", "            raise PartialFailure(done, exc, recovery) from exc\n", "            raise\n",
     "test_a_failure_after_a_deletion_reports_what_was_done_and_how_to_recover"),
    ("no cache allowance", 'if line and not (line.startswith("!! ") and _regenerable(line)):', "if line:",
     "test_the_merged_branch_is_removed_everywhere_and_caches_do_not_block"),
    ("no worktree-head check", "if actual != head:", "if False:", "test_a_detached_commit_in_the_worktree_blocks_removing_it"),
    ("no other-worktree check", "if local and others:", "if False:", "test_a_branch_checked_out_in_another_worktree_is_kept"),
    ("no origin check", "        verify_origin(key, checkout, repo)\n", "",
     "test_the_real_origin_check_refuses_an_origin_that_is_not_the_repository"),
    ("no workspace check", "if not Path(workspace).is_absolute():", "if False:",
     "test_without_an_absolute_workspace_nothing_runs"),
    ("claw not keyed", "        return CLAW_KEY\n", '        return "x"\n', "test_the_lock_key_is_claw_or_the_manifest_mech"),
]
COMMIT_MUTANTS = [
    ("main accepted", "if branch in default_branches(worktree):", "if False:",
     "test_main_is_refused_and_nothing_is_committed"),
    ("origin/HEAD ignored", 'names.add(origin_head.stdout.strip().removeprefix("origin/"))', "pass",
     "test_a_default_branch_named_by_origin_head_is_refused"),
    ("no workspace check", 'if not Path(os.environ.get("OPENCLAW_WORKSPACE", "")).is_absolute():', "if False:",
     "test_without_an_absolute_workspace_nothing_is_committed"),
    ("main not hardcoded", 'names = {"main"}', "names = set()", "test_main_is_refused_even_when_origin_names_no_default"),
    ("detached accepted", 'if branch == "HEAD":', "if False:", "test_a_detached_head_is_refused"),
    ("status unchecked", 'if not status or any(line[1] != " " for line in status):', "if False:",
     "test_unstaged_or_untracked_work_beside_the_staged_change_is_refused"),
    ("no lock", 'with LockManager().lock(args.mech, "review-fix-push"):', "with open(os.devnull):",
     "test_a_held_lock_on_the_mech_stops_the_commit"),
    ("message file unresolved", "args.message_file.resolve()", "args.message_file",
     "test_a_relative_message_file_is_read_from_the_current_directory"),
]
SUITES = [(CLEANUP, CLEANUP_MUTANTS), (COMMIT, COMMIT_MUTANTS)]


def pytest(selector: str) -> int:
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", selector],
                          cwd=ROOT, capture_output=True, text=True, check=False).returncode


def run_mutants(script: Path, test_file: str, mutants: list) -> int | None:
    """Return how many mutants survived, or None if an anchor is not unique."""
    original = script.read_text(encoding="utf-8")
    survived = 0
    try:
        for name, before, after, test in mutants:
            befores, afters = (before, after) if isinstance(before, tuple) else ((before,), (after,))
            mutated = original
            for anchor, replacement in zip(befores, afters):
                if original.count(anchor) != 1:
                    print(f"{name}: anchor {anchor!r} occurs {original.count(anchor)} times")
                    return None
                mutated = mutated.replace(anchor, replacement)
            script.write_text(mutated, encoding="utf-8")
            killed = pytest(f"{test_file}::{test}") != 0
            survived += not killed
            print(f"{'KILLED  ' if killed else 'SURVIVED'} {script.name}: {name} ({test})")
    finally:
        script.write_text(original, encoding="utf-8")
    return survived


def main() -> int:
    survived = total = 0
    for (script, test_file), mutants in SUITES:
        if pytest(test_file) != 0:
            print(f"the unmutated {test_file} fails")
            return 1
        result = run_mutants(ROOT / script, test_file, mutants)
        if result is None:
            return 1
        survived += result
        total += len(mutants)
    stray = ROOT / "workspace"
    if stray.exists():
        print(f"note: a mutant created {stray}; remove it before committing")
    print(f"{total - survived}/{total} killed")
    return 1 if survived else 0


if __name__ == "__main__":
    sys.exit(main())
