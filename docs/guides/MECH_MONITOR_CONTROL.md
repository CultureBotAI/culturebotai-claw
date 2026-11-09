# Mech monitor lifecycle

Use “start monitoring”, “stop monitoring”, “restart monitoring”, or “monitor
status” with the repository-local `mech-monitor-control` skill. Claude-compatible
command discovery also exposes `/monitor start`, `/monitor stop`,
`/monitor restart`, and `/monitor status`.

The same operations are available directly from this checkout:

```bash
just monitor-status
just monitor-start
just monitor-stop
just monitor-restart

python3 scripts/mech_monitor_control.py status --json
python3 scripts/mech_monitor_control.py stop --service supervisor --json
python3 scripts/mech_monitor_control.py start --service approvals --json
```

The default scope is both configured services:

- **approvals**: the existing approval monitor and its bounded token recovery.
- **supervisor**: the receipt-gated Mech goal and commit-sequence supervisor.

Stopping these services leaves agent sessions running and preserves their work.
Starting resumes the saved policies and assessed session bindings, including
automatic goal dispatch after the supervisor verifies the existing closure gates.
The controller does not launch/quit agy, change prompt choices, reset counters,
or rewrite goal identities.
The progress-site publisher is separate and is not controlled here.

## Results and failure handling

The controller uses a nonblocking lifecycle lock, an ownership registry with
process start identity, and exact configured command and working-directory
checks. Stop writes the service's STOP marker, sends SIGTERM only to verified
owned monitor processes, and waits for graceful exit. It never force-kills.
Repeated start/stop requests are idempotent. Ambiguous duplicate processes or
reused PIDs require investigation rather than a guessed kill.

Start preflights every selected service before removing STOP markers or spawning
anything. It requires live matching session bindings and checks any configured
source hashes. It waits for fresh matching-PID status after launching. If startup
fails, only newly launched processes are rolled back; previously running services
are preserved. The timeout is a shared lifecycle wait budget, bounded to 60
seconds; process and binding preflight checks add their own bounded inspection
time. After a timeout, inspect status and logs instead of deleting state.

`status` distinguishes an actual running process with fresh status from a stopped
service, a stale heartbeat, or an ownership conflict. Session-binding information
is separate from process health. A stopped service may still have a historical
status file that says `running: true`; that file alone never proves liveness.
Exit 0 means the requested control operation succeeded; exit 1 reports a control
or health error, and exit 2 is invalid CLI usage. Inspect per-service state and
binding information even when the command succeeds.

If agy sessions have quit or been replaced, start refuses stale bindings. Use
[session binding and recovery](MECH_SESSION_WORKFLOWS.md) to assess replacements
and preserve their goal/PR lineage before updating the deployment. Do not reuse a
PID merely because it now exists, relabel another conversation, or discard an
uncertain instruction. The lifecycle controller intentionally does not infer
new session bindings.

## Local deployment configuration

The default configuration is `workspace/monitoring/config.json`, kept out of Git
along with process identities, state and logs. Another known deployment can be
selected with `--config /absolute/path/config.json`. The controller itself uses
only Python's standard library; each monitored service retains its existing
interpreter and dependencies.

A version-1 configuration has `state_dir` and one or both named services. This
example is a shape reference: replace all `/absolute/...` paths with verified
paths from the existing deployment before using it.

```json
{
  "version": 1,
  "state_dir": "/absolute/CLAW/workspace/monitoring/control",
  "services": {
    "approvals": {
      "kind": "approval",
      "argv": ["/absolute/python", "/absolute/CLAW/workspace/monitoring/approval-runtime/monitor.py", "--allow-file-edits", "--allow-file-access"],
      "cwd": "/absolute/CLAW/workspace/monitoring/approval-runtime",
      "stop_file": "/absolute/CLAW/workspace/monitoring/approval-runtime/STOP",
      "status_file": "/absolute/CLAW/workspace/monitoring/approval-runtime/status.json",
      "log_file": "/absolute/CLAW/workspace/monitoring/approval-runtime/events.log",
      "session_targets_file": "/absolute/CLAW/workspace/monitoring/approval-runtime/token-recovery-targets.json",
      "heartbeat_max_age_seconds": 300
    },
    "supervisor": {
      "kind": "supervisor",
      "argv": ["/absolute/CLAW/.venv/bin/python", "/absolute/CLAW/scripts/mech_session_supervisor.py", "--config", "/absolute/CLAW/workspace/session-orchestration/RUN/config.json", "--apply", "--loop", "--interval", "30"],
      "cwd": "/absolute/CLAW",
      "stop_file": "/absolute/CLAW/workspace/session-orchestration/RUN/STOP",
      "status_file": "/absolute/CLAW/workspace/session-orchestration/RUN/heartbeat.json",
      "log_file": "/absolute/CLAW/workspace/session-orchestration/RUN/supervisor.log",
      "heartbeat_max_age_seconds": 300
    }
  }
}
```

The flags in this example describe an existing authorized deployment; the
controller does not grant new approval permissions. Keep the user's established
choices. Each service may include `source_sha256`, a mapping of absolute source
paths to reviewed SHA-256 digests, to refuse start after an unreviewed runtime
change. Hashes are checked on start, not as a prerequisite to stopping a process.

The supervisor's `--config` supplies its session targets. Approval targets come
from `session_targets_file` and include the saved PID, TTY, process-start identity
and cwd. Both services must share the same per-TTY input-lock directory, and both
must use compatible current-tail observation/send guards. Preserve the original
status, recovery state, targets and STOP marker when moving an existing approval
runtime out of temporary storage. Reject approval-runtime startup when its
required identity/recovery configuration cannot load; an unguarded fallback is
not a valid deployment.

Do not overwrite or share the controller's `registry.json`, `events.jsonl`, or
`lifecycle.lock` with a service's files. The controller rejects symlinked state
paths and unsafe file types. On macOS, whitespace-bearing command arguments are
rejected because `ps` cannot prove argument boundaries; use a deployment path
whose command arguments can be identified exactly. macOS Terminal automation
permissions and the existing native-reader constraints still apply.

## Prompt discovery

The skill source is `.claude/skills/mech-monitor-control/SKILL.md`, registered as
CLAW-local in the skill catalogue. Codex can discover the same source through a
link in its personal skills directory; keep one authoritative copy rather than
maintaining different lifecycle instructions in each client.
