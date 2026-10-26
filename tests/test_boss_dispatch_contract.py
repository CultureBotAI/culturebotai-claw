#!/usr/bin/env python3
"""Verify boss's actual dispatch preflight for claw #670 / PR #669 (2026-10-25).

Input: the dispatch Bash fence in .claude/skills/boss/SKILL.md, or the Markdown
snapshot in BOSS_SKILL_SOURCE for a mutation check. Output: unittest results.
Shell fixtures live in this file; temporary files contain event data
only. The fixtures intercept tmux/mktemp and never create live sessions/worktrees.
"""
from pathlib import Path
import os
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SKILL = Path(os.environ.get("BOSS_SKILL_SOURCE", ROOT / ".claude/skills/boss/SKILL.md"))
FIXTURE = r'''
set -euo pipefail
SLUG=review
FLEET_WORKTREE_ROOT=/unused/fixture
mktemp() { printf '%s\n' /unused/fixture/review.ABC12Z; }
tmux() {
  printf '%s\n' "$*" >> "$EVENTS"
  case "$1" in
    list-sessions)
      if [ "$INVENTORY_EXIT" -ne 0 ]; then
        printf '%s\n' "$INVENTORY_TEXT" >&2
      else
        printf '%s\n' "$INVENTORY_TEXT"
      fi
      return "$INVENTORY_EXIT" ;;
    list-windows)
      [ "$*" = "list-windows -t =mechs -F #I #W" ] || return 97
      printf '0 hub\n'
      return "$WINDOWS_EXIT" ;;
    *) printf 'Unexpected tmux mutation: %s\n' "$*" >&2; return 98 ;;
  esac
}
'''


def preflight():
    section = SKILL.read_text().split("### Dispatch a worker", 1)[1]
    block = section.split("```bash\n", 1)[1].split("\n```", 1)[0]
    return block.split('run_locked_command "fetch-main-', 1)[0]


class DispatchContractTests(unittest.TestCase):
    def run_fixture(self, text="mechs\nother-session", exit_code=0, windows_exit=0):
        with tempfile.TemporaryDirectory(prefix="boss-contract-fixture-") as tmp:
            events = Path(tmp) / "events.txt"
            env = dict(os.environ, EVENTS=str(events), INVENTORY_TEXT=text,
                       INVENTORY_EXIT=str(exit_code), WINDOWS_EXIT=str(windows_exit))
            script = FIXTURE + preflight() + '\nprintf "RESULT:%s|%s\\n" "$SESSION" "$BRANCH"\n'
            result = subprocess.run(["/bin/bash", "-s"], input=script, env=env,
                                    text=True, capture_output=True)
            return result, events.read_text().splitlines() if events.exists() else []

    def test_mixed_case_id_normalized_and_existing_host_windows_listed(self):
        result, events = self.run_fixture()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("RESULT:review-abc12z|feat/review-abc12z", result.stdout)
        self.assertEqual(events, ["list-sessions -F #S", "list-windows -t =mechs -F #I #W"])

    def test_exact_existing_task_session_refused(self):
        result, events = self.run_fixture("review-abc12z")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("Refusing existing tmux session", result.stderr)
        self.assertEqual(events, ["list-sessions -F #S"])

    def test_session_prefix_is_not_an_exact_collision(self):
        result, events = self.run_fixture("review-abc12z-other")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(events, ["list-sessions -F #S"])

    def test_expected_no_server_errors_are_empty_inventory(self):
        for text in ("no server running on /tmp/tmux-501/default",
                     "error connecting to /tmp/tmux-501/default (No such file or directory)"):
            with self.subTest(text=text):
                result, events = self.run_fixture(text, exit_code=1)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn("RESULT:review-abc12z", result.stdout)
                self.assertEqual(events, ["list-sessions -F #S"])

    def test_other_inventory_errors_stop_dispatch(self):
        result, events = self.run_fixture("error connecting to /tmp/tmux-501/default (Permission denied)", 1)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("Cannot inventory tmux sessions", result.stderr)
        self.assertNotIn("RESULT:", result.stdout)
        self.assertEqual(events, ["list-sessions -F #S"])

    def test_existing_host_window_inventory_failure_stops_dispatch(self):
        result, _ = self.run_fixture(windows_exit=3)
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertNotIn("RESULT:", result.stdout)


if __name__ == "__main__":
    unittest.main()
