# agy port-pressure guard

The session supervisor can report leaked loopback listeners and, after an
operator-approved canary, recycle one verified-idle agy session by exact ID.
Its preferred opportunity is a verified goal boundary: after accepting the
completed goal's closure and before dispatching the next goal, it checks that
session against the configurable 500-listener threshold. An idle scan remains
available when host or per-process pressure exceeds its fallback thresholds.
This is a workaround for #725, not a change to the enterprise sandbox policy.
It never sends signals to an agent, changes the port range, or answers prompts.
The restart transaction never submits goal text. After a successful boundary
restart and rebind, the supervisor performs fresh dispatch checks for the one
legitimate next goal; it never replays the completed goal.

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
    "goal_boundary_limit": 500,
    "cooldown_seconds": 3600,
    "hourly_cap": 2,
    "restart_repository_keys": null,
    "binding_files": [
      {"role": "monitor", "path": "/absolute/path/to/monitor-targets.json"},
      {"role": "approval", "path": "/absolute/path/to/approval-targets.json"}
    ]
  }
}
```

`restart_repository_keys` optionally restricts recycling to named, configured
repository keys. `null` allows all configured targets; an empty list allows
none. Measurements and blocked-task reports still cover all targets. A target
outside the allowlist retains ordinary goal dispatch without a boundary recycle.
For a separately approved one-session canary, set this list to that session's
single repository key and set `hourly_cap` to `1`. Keep the full supervisor
target list and the original binding files; do not remove other monitored sessions.

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

The standalone report identifies fallback threshold offenders, unmanaged
offenders, the largest eligible candidate and excluded sessions. A host ratio
at or above 0.5, or any agy process strictly above 1,000 loopback listeners,
triggers the idle-scan fallback. Sessions at the two-listener baseline are not
useful restart candidates.

During ordinary supervision, a verified completed goal awaiting its next
`start_goal` dispatch is a separate trigger. At or above `goal_boundary_limit`
(500 by default), that exact session must recycle first, even when host pressure
is low. Native completion alone is insufficient: the supervisor's closure
verification must have accepted the prior goal. Stage zero, closure repair and
unrelated sessions are not boundary authority. The boundary uses stage keys
and retained closure identity, so it does not depend on six- or seven-stage
numbering.

Boundary recycling takes precedence over the idle fallback. Both paths share
the same one-recycle tick budget, transaction lock, cooldown, hourly cap and
first-failure latch. A boundary blocked by a prompt, background task, limit or
unknown measurement holds next-goal dispatch. In `mode: report`, an eligible
boundary reports that it would recycle and holds the next goal without sending
input; `mode: off` leaves ordinary goal dispatch unchanged. A successful recycle
does not allow a second fallback recycle in the same tick.

`blocked_tasks` reports active native tools, Terminal task indicators and verified
descendant processes. Ages use a full native timestamp or process start time;
an ambiguous displayed time remains unknown. Socket states are attributed only
when an observed child connection's remote endpoint matches this agy process's
loopback listener. A missing socket is unknown, not CLOSED. Even a confirmed
CLOSED connection never authorizes selecting or killing that running task.
This includes a shell whose child is `/usr/bin/pr`: a quoted inline GitHub body
containing backticks can invoke command substitution and leave that child
reading the tty for hours. An empty composer or newer completed native step
does not erase the live process ancestry. The guard reports the authoritative
age and socket evidence, and leaves the task alone. The canonical prevention
rule ([#913](https://github.com/CultureBotAI/culturebotai-claw/issues/913))
requires preparing PR and issue bodies in an owned file, passing
`--body-file <path>` for `gh pr` and `gh issue` create/edit/comment commands,
retaining the body artifact, and verifying the published text so Markdown prose
is never interpreted as shell code. Existing running background tasks remain
operator-owned; the guard reports and holds them, never kills them.

## Approved canary and subsequent operation

Deployment, Intel reporting, the canary and enabling automatic restarts require
separate operator approval. This PR's offline tests are not hardware acceptance.
The standalone `--port-pressure-restart` command remains a single idle-scan
maintenance tick. It cannot fall through to workflow/goal dispatch, even if no
restart is selected, and cannot override `mode: off`. Below its host/per-process
fallback thresholds it does not exercise the new 500-listener boundary path.

Before input, the guard repeats identity, idle, background-task, prompt, model
and three-source ID checks under the shared input lease. Its final interaction
is `/quit`. It requires fresh printed `agy --conversation=<id>` output, old PID
exit, and the same verified returned shell/cwd before sending an explicitly
quoted conversation/model/effort command. It verifies the new PID, current
identity/footer, absence of human prompts, and exactly two loopback listeners
before rebinding. The restart transaction contains no `/goal`, `--continue`,
`--last` or signal fallback.

A recognized dismissible `Meet Gemini 4 Argon` announcement may remain visible
while the current empty composer and model/effort footer prove readiness. The
guard neither fails merely because that announcement is present nor sends
Escape to dismiss it. A feedback survey such as `How's the CLI experience so
far?` with `[0] Skip` is a human prompt: hold and report, without selecting Skip.
After resume, an apparent sign-in screen is read again within a bounded startup
check before being classified as persistent. The guard never answers it; a
persistent sign-in, another prompt or failed readiness proof stops the
transaction. A historical sign-in line must not replace the current runtime
screen as evidence.

At most one restart occurs per tick. Successful restart history enforces the
per-session cooldown across PID changes and the rolling hourly cap. Durable
intent precedes `/quit`; an unfinished intent after a crash stops the next tick.
The first failure writes `port-pressure-disabled.json`, preserves quota history
and emits an alert in the JSON report. Corrupt state is preserved for inspection.
Do not delete state to bypass a limit or retry an uncertain restart. Reconcile
the old/new processes, IDs, all bindings and journal before an approved recovery.

Proposed goal-boundary canary, after its separate approval:

1. Select one existing assessed agy session that has reached verified goal
   closure and naturally holds at least 500 loopback listeners. Record its
   current identity, three agreeing IDs, model/effort, idle/task state, listener
   counts and exact pending next goal. Preserve the established ledger and
   evidence; do not manufacture completion or reset an intervention state.
2. Confirm the earlier approved report-only observations and the effective
   monitor/approval reload and shared-input-lock contracts. Set
   `restart_repository_keys` to only the approved canary's key, `hourly_cap` to
   `1`, and `mode: restart` through the owned existing supervisor;
   do not launch a competing loop or alter unrelated sessions.
3. Observe one authorized supervisor boundary dispatch. Require `/quit`, old-PID
   exit, fresh matching printed ID, explicit-ID resume with unchanged model and
   effort, exactly two listeners and all binding read-backs before the fresh
   next-goal dispatch checks.
4. Independently verify effective live monitor/approval bindings, unchanged
   conversation and goal history, exactly one legitimate next goal accepted,
   and no replay of the completed goal. Confirm the shared cooldown/cap history
   and that no second session recycled in that tick. On a prompt, mismatch or
   failure, retain the latch and evidence for operator reconciliation.

Only after approved canary acceptance may broader automatic recycling be
considered. Deployment, reporting and canary approvals are distinct; offline
tests or a transport-only fallback restart do not supply those approvals.
Remove the workaround after a fixed agy build is confirmed to stay at two
listeners after sandboxed commands.

The published procedure used for implementation is XMechBay PR5's
`mac-orchestration` graceful-exit contract and `docs/port-pressure-recovery.md`.
The supplied read-only `agy_exact_restart.sh` reference was reconciled on
2026-11-07, SHA-256
`4a7aa17b6dfa2c91e157639b73b768630266eb55db86f4cbf7efdb38e99ca555`.
The implementation retains its identity/idle/quit/printed-ID/explicit-resume
sequence while requiring all three IDs, treating model drift as failure,
verifying exactly two listeners and rebinding the assessed runtime. Those are
stricter checks than the shell reference's optional supervisor-ID comparison
and model-drift warning. The supplied November 4 and November 6 restart logs
are historical corroboration, not a live acceptance test of this implementation.
