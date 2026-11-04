# agy port-pressure guard

The session supervisor can report leaked loopback listeners and, after an
operator-approved canary, recycle one verified-idle agy session by exact ID.
This is a workaround for #725, not a change to the enterprise sandbox policy.
It never sends signals to an agent, changes the port range, or answers prompts.
It never submits goal text during a maintenance transaction.

Existing supervisor configurations without `port_pressure` keep the guard off.
An explicit `port_pressure` object defaults to `mode: report`. The single off
switch is `port_pressure.mode = "off"`; the supervisor rereads it each tick.
Mode `restart` additionally requires an explicit apply invocation. An ordinary
observe invocation cannot restart anything.

## Operator-reviewed configuration

Keep the existing assessed run, session identities, workflow, runtime directory
and input lock directory. Add this object to that supervisor configuration:

```json
{
  "port_pressure": {
    "mode": "report",
    "host_ratio": 0.5,
    "per_pid_limit": 1000,
    "cooldown_seconds": 3600,
    "hourly_cap": 2,
    "binding_files": [
      {"role": "monitor", "path": "/absolute/path/to/monitor-targets.json"},
      {"role": "approval", "path": "/absolute/path/to/approval-targets.json"}
    ]
  }
}
```

Both binding files must use the native target-list format: either a list or an
object containing `targets`. Their exact old PID, start identity, TTY and cwd
must match. They may name the same file. The supervisor's own `--config` file is
the third binding. Other targets and settings are preserved. All three bindings
are preflighted before `/quit`, checked for concurrent edits, atomically replaced
one file at a time and read back. The supervisor also replaces its in-memory
identity, drops its native cache, and records old/new PIDs in session status.
A partial update stops the guard and leaves a recovery journal; it is not retried.

The approval monitor must acquire the same per-TTY input lock and reload its
target file before acting. File rebinding does not prove an external monitor
reloads cached settings: verifying effective live monitor behavior is a required
part of the approved canary. Do not enable automatic recycling with an adapter
whose reload/input-lock contract has not been checked.

Each eligible target also needs an explicitly reviewed restart identity:

```json
{
  "port_pressure_identity": {
    "agy_executable": "/absolute/path/to/agy",
    "model": "gemini-3-pro",
    "effort": "high",
    "model_label": "Gemini 3 Pro",
    "effort_label": "high"
  }
}
```

These are illustrative values, not deployment defaults. Record the actual
executable, CLI model/effort and current UI labels. The adapter currently accepts
complete model/effort fields separated by `|` or `·`, or the native
`Gemini 3.1 Pro (High)` shape, on the current Gemini footer after the empty
composer. The shortcut legend preceding the model is excluded. Historical,
partial, mixed-line or unfamiliar labels
refuse maintenance. The running executable must match the configured executable.
An agy UI/log format change requires review and fixtures before use.

The native index, this run's `status.json` goal conversation ID and the PID's
own open `cli-*.log` must agree with the configured exact conversation ID.
Missing/ambiguous IDs stop the guard. The current log adapter recognizes keyed
`conversation_id`, `conversationId` or `Conversation ID` UUID fields. It never
substitutes the most recent thread or an ID found only in screen history.

## Report-only command on the approved Intel deployment

Run these only after deployment and report-only execution are approved, from
the approved Claw checkout. Set `MECH_SESSION_CONFIG` to the existing assessed
supervisor configuration's absolute path; do not substitute a newly invented
session identity or copy another host's PID/TTY values.

```bash
uv run openclaw-cli config validate
uv run --no-sync python scripts/mech_session_supervisor.py \
  --config "$MECH_SESSION_CONFIG" --port-pressure-report
```

The standalone report command does not acquire the workflow supervisor's loop
lock, change its heartbeat, advance stages or send Terminal input. It uses the
guard's own transaction lock. It prints JSON and retains
`port-pressure-report.json` in the configured runtime directory. An unsafe or
unknown observation exits nonzero and creates the durable failure latch.

Measurements come directly from `lsof -nP ... -iTCP -FpcfntT` and the measured
`net.inet.ip.portrange.first/last` bounds. `host_listeners` counts host LISTEN
rows; per-PID counts include only loopback LISTEN rows. Their ratio is a listener
row count divided by range size, not a claim about distinct occupied ports.
The XMechBay watch's `occupancy_ratio` has different semantics and is not silently
imported. Failed, partial, malformed or missing measurements remain unknown.

The report identifies threshold offenders, unmanaged offenders, the largest
eligible candidate and excluded sessions. A host ratio at or above 0.5, or any
agy process strictly above 1,000 loopback listeners, triggers consideration.
Sessions at the two-listener baseline are not useful restart candidates.

`blocked_tasks` reports active native tools, Terminal task indicators and verified
descendant processes. Ages use a full native timestamp or process start time;
an ambiguous displayed time remains unknown. Socket states are attributed only
when an observed child connection's remote endpoint matches this agy process's
loopback listener. A missing socket is unknown, not CLOSED. Even a confirmed
CLOSED connection never authorizes selecting or killing that running task.

## Approved canary and subsequent operation

Deployment, Intel reporting, the canary and enabling automatic restarts require
separate operator approval. This PR's offline tests are not hardware acceptance.
After approval, scope the assessed guard configuration to the one chosen canary,
set `mode: restart`, and use `--port-pressure-restart` for a single maintenance
tick. That command cannot fall through to workflow/goal dispatch, even if no
restart is selected. It also cannot override `mode: off`.

Before input, the guard repeats identity, idle, background-task, prompt, model
and three-source ID checks under the shared input lease. Its final interaction
is `/quit`. It requires fresh printed `agy --conversation=<id>` output, old PID
exit, and the same verified returned shell/cwd before sending an explicitly
quoted conversation/model/effort command. It verifies the new PID, current
identity/footer, absence of human prompts, and exactly two loopback listeners
before rebinding. No `/goal`, `--continue`, `--last` or signal fallback exists.

At most one restart occurs per tick. Successful restart history enforces the
per-session cooldown across PID changes and the rolling hourly cap. Durable
intent precedes `/quit`; an unfinished intent after a crash stops the next tick.
The first failure writes `port-pressure-disabled.json`, preserves quota history
and emits an alert in the JSON report. Corrupt state is preserved for inspection.
Do not delete state to bypass a limit or retry an uncertain restart. Reconcile
the old/new processes, IDs, all bindings and journal before an approved recovery.

For the canary, independently verify effective monitor/approval bindings, exactly
two listeners, unchanged model/effort/conversation and no submitted goal text.
Only after that approval may normal supervisor apply ticks use `mode: restart`.
Remove the workaround after a fixed agy build is confirmed to stay at two
listeners after sandboxed commands.

The published procedure used for implementation is XMechBay PR5's
`mac-orchestration` graceful-exit contract and `docs/port-pressure-recovery.md`.
The separately referenced `scripts/adhoc/agy_exact_restart.sh` still
requires source reconciliation before deployment; its unavailable contents
must not be represented as having been read or tested.
