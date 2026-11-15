#!/usr/bin/env python3
"""Verify boss's actual dispatch preflight for claw #670 / PR #669 (2026-10-25).

Input: the dispatch Bash fence in .claude/skills/boss/SKILL.md, or the Markdown
snapshot in BOSS_SKILL_SOURCE for a mutation check. Output: unittest results.
Shell fixtures live in this file; temporary files contain event data and a
fixed fake agent executable. The fixtures intercept tmux/mktemp and never create
live sessions or Git worktrees. Explicit-socket/cwd regression added 2026-11-14.
"""
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = Path(os.environ.get("BOSS_SKILL_SOURCE", ROOT / ".claude/skills/boss/SKILL.md"))
FIXTURE = r'''
set -euo pipefail
SLUG=review
FLEET_WORKTREE_ROOT=/unused/fixture
mktemp() { printf 'mktemp\n' >> "$EVENTS"; printf '%s\n' /unused/fixture/review.ABC12Z; }
rmdir() { printf 'rmdir %s\n' "$*" >> "$EVENTS"; }
tmux() {
  printf '%s\n' "$*" >> "$EVENTS"
  [ "$1" = -N ] && [ "$2" = -S ] && [ "$3" = "$EXPECTED_SOCKET" ] || return 96
  shift 3
  case "$1" in
    list-sessions)
      if [ "$INVENTORY_EXIT" -ne 0 ]; then
        printf '%s\n' "$INVENTORY_TEXT" >&2
      else
        printf '%s\n' "$INVENTORY_TEXT"
      fi
      return "$INVENTORY_EXIT" ;;
    list-panes)
      [ "$*" = 'list-panes -a -F #{session_name}|#{window_id}|#{pane_id}|#{pane_pid}|#{pane_tty}|#{pane_current_path}' ] || return 97
      printf 'existing|@0|%%0|123|/dev/fixture|/fixture/worktree\n'
      return "$PANES_EXIT" ;;
    *) printf 'Unexpected tmux mutation: %s\n' "$*" >&2; return 98 ;;
  esac
}
'''


def dispatch_block():
    section = SKILL.read_text().split("### Dispatch a worker", 1)[1]
    return section.split("```bash\n", 1)[1].split("\n```", 1)[0]


def preflight():
    return dispatch_block().split('run_locked_command "fetch-main-', 1)[0]


class DispatchContractTests(unittest.TestCase):
    socket = "/fixture/selected fleet.sock"
    panes_event = ('list-panes -a -F #{session_name}|#{window_id}|#{pane_id}|'
                   '#{pane_pid}|#{pane_tty}|#{pane_current_path}')

    def events_for(self, *commands):
        return [f"-N -S {self.socket} {command}" if command.startswith("list-")
                else command for command in commands]

    def run_fixture(self, text="existing\nother-session", exit_code=0, panes_exit=0,
                    socket=None):
        with tempfile.TemporaryDirectory(prefix="boss-contract-fixture-") as tmp:
            events = Path(tmp) / "events.txt"
            env = dict(os.environ, EVENTS=str(events), INVENTORY_TEXT=text,
                       INVENTORY_EXIT=str(exit_code), PANES_EXIT=str(panes_exit),
                       BOSS_TMUX_BIN="tmux", EXPECTED_SOCKET=self.socket,
                       BOSS_TMUX_SOCKET=self.socket if socket is None else socket)
            script = FIXTURE + preflight() + '\nprintf "RESULT:%s|%s\\n" "$SESSION" "$BRANCH"\n'
            result = subprocess.run(["/bin/bash", "-s"], input=script, env=env,
                                    text=True, capture_output=True)
            return result, events.read_text().splitlines() if events.exists() else []

    def test_mixed_case_id_normalized_and_selected_server_panes_listed(self):
        result, events = self.run_fixture()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("RESULT:review-abc12z|feat/review-abc12z", result.stdout)
        self.assertEqual(
            events,
            self.events_for("list-sessions -F #S", self.panes_event, "mktemp"),
        )

    def test_exact_existing_task_session_refused(self):
        result, events = self.run_fixture("review-abc12z")
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertIn("Refusing existing tmux session", result.stderr)
        self.assertEqual(
            events,
            self.events_for("list-sessions -F #S", self.panes_event, "mktemp",
                            "rmdir /unused/fixture/review.ABC12Z"),
        )

    def test_session_prefix_is_not_an_exact_collision(self):
        result, events = self.run_fixture("review-abc12z-other")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(events, self.events_for("list-sessions -F #S", self.panes_event, "mktemp"))

    def test_missing_server_stops_before_creating_task_state(self):
        for text in ("no server running on /tmp/tmux-501/default",
                     "error connecting to /tmp/tmux-501/default (No such file or directory)"):
            with self.subTest(text=text):
                result, events = self.run_fixture(text, exit_code=1)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertNotIn("RESULT:", result.stdout)
                self.assertEqual(events, self.events_for("list-sessions -F #S"))

    def test_other_inventory_errors_stop_dispatch(self):
        result, events = self.run_fixture("error connecting to /tmp/tmux-501/default (Permission denied)", 1)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("Cannot inventory selected tmux server", result.stderr)
        self.assertNotIn("RESULT:", result.stdout)
        self.assertEqual(events, self.events_for("list-sessions -F #S"))

    def test_pane_inventory_failure_stops_dispatch(self):
        result, events = self.run_fixture(panes_exit=3)
        self.assertEqual(result.returncode, 3, result.stderr)
        self.assertNotIn("RESULT:", result.stdout)
        self.assertEqual(events, self.events_for("list-sessions -F #S", self.panes_event))

    def test_missing_or_relative_socket_is_refused(self):
        for socket in ("", "relative.sock"):
            with self.subTest(socket=socket):
                result, events = self.run_fixture(socket=socket)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertEqual(events, [])

    def run_launch_fixture(self, exit_code=0):
        with tempfile.TemporaryDirectory(prefix="boss-launch-fixture-") as tmp:
            root = Path(tmp).resolve()
            worktree = root / "task ' quote $dollar"
            server = root / "unrelated-server-cwd"
            binary = root / "bin"
            for path in (worktree, server, binary):
                path.mkdir()
            agent = binary / "claude"
            agent.write_text('#!/bin/sh\nprintf "agent\\n" >> "$EVENTS"\n'
                             'printf "%s\\n" "$PWD" > "$AGENT_CWD"\nexit "$FAKE_AGENT_EXIT"\n')
            agent.chmod(0o700)
            tmux_binary = binary / "tmux"
            tmux_binary.write_text('''#!/bin/sh
test "$#" -eq 9 || exit 97
test "$1" = -N && test "$2" = -S && test "$3" = "$BOSS_TMUX_SOCKET" || exit 97
shift 3
test "$*" = 'set-option -p -t %42 remain-on-exit on' || exit 97
printf 'retention\n' >> "$EVENTS"
''')
            tmux_binary.chmod(0o700)
            observed = root / "agent-cwd.txt"
            events = root / "events.txt"
            child_exit = root / "agent-exit.txt"
            env = dict(os.environ, WORKTREE=str(worktree), SERVER_CWD=str(server),
                       AGENT_CWD=str(observed), AGENT_EXIT=str(child_exit), EVENTS=str(events),
                       FAKE_AGENT_EXIT=str(exit_code), SESSION="fixture-task", TMUX_PANE="%42",
                       BOSS_TMUX_BIN=str(tmux_binary), BOSS_TMUX_SOCKET=self.socket,
                       PATH=str(binary) + os.pathsep + os.environ["PATH"])
            # Model a server that inherits an unrelated cwd. Execute the actual
            # argv tail from the skill without contacting a tmux server.
            fixture = r'''
set -euo pipefail
fleet_tmux() {
  test "$1" = new-session
  shift
  while [ "$#" -gt 0 ] && [ "$1" != /bin/sh ]; do shift; done
  test "$#" -gt 0
  child_exit=0
  (cd "$SERVER_CWD" && "$@") || child_exit=$?
  printf '%s\n' "$child_exit" > "$AGENT_EXIT"
  printf '%%42\n'
}
'''
            launch = dispatch_block().split("# 2. Launch plain Claude", 1)[1].split("# 3.", 1)[0]
            result = subprocess.run(["/bin/bash", "-s"],
                                    input=fixture + "# 2. Launch plain Claude" + launch + '\nprintf "%s\\n" "$PANE"\n',
                                    env=env, text=True, capture_output=True)
            return (result, events.read_text().splitlines() if events.exists() else [],
                    observed.read_text().strip() if observed.exists() else None,
                    str(worktree), child_exit.read_text().strip())

    def test_launch_enters_literal_worktree_despite_inherited_server_cwd(self):
        result, events, observed, worktree, exit_code = self.run_launch_fixture()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "%42")
        self.assertEqual(observed, worktree)
        self.assertEqual(events, ["retention", "agent"])
        self.assertEqual(exit_code, "0")

    def test_failed_agent_startup_sets_pane_retention_first(self):
        # Regression for #1241: a nonzero agent exit must happen after retention
        # is enabled, so a real tmux server preserves its failed pane/output.
        result, events, _, _, exit_code = self.run_launch_fixture(exit_code=23)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout.strip(), "%42")
        self.assertEqual(events, ["retention", "agent"])
        self.assertEqual(exit_code, "23")


if __name__ == "__main__":
    unittest.main()
