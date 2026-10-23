---
name: mech-monitor-control
description: Start, stop, restart, or check the local agy approval monitor and Mech goal supervisor. Use for requests such as "start monitoring", "stop monitoring", or "are the monitors running?" in the Mech orchestration context.
metadata:
  tags: [claw, monitoring, lifecycle]
---

# Mech monitoring controls

Use the checked lifecycle command instead of composing `kill`, background shell
launches, or deleting PID/STOP files by hand. This skill's repository-local copy
is the source of truth. If installed through a symlink, resolve it to locate the
CLAW checkout; do not infer a different deployment from the current directory.

From that checkout, run the requested action:

```bash
python3 scripts/mech_monitor_control.py status --json
python3 scripts/mech_monitor_control.py start --json
python3 scripts/mech_monitor_control.py stop --json
python3 scripts/mech_monitor_control.py restart --json
```

An explicit start/stop/restart request authorizes that lifecycle action; do not
ask for the same authorization again. A status question runs only `status`.
Default scope is both services. Use `--service approvals` or `--service supervisor`
when the user names only one. The default deployment is
`workspace/monitoring/config.json`; use an explicit `--config` only for a known
user-selected deployment. The equivalent shortcuts are `just monitor-start`,
`just monitor-stop`, `just monitor-restart`, and `just monitor-status`.

Report each service's actual result, including stopped, starting, stale heartbeat,
or stale session bindings. A successful process spawn is not proof that sessions
are monitored. If a command fails, report its concrete reason; do not delete its
registry or retry by bypassing process checks. If the controller reports missing
configuration, consult [monitor setup](../../../docs/guides/MECH_MONITOR_CONTROL.md).

Stopping monitoring leaves agy sessions and their work intact. Starting resumes
the configured prompt choices and goal supervisor; it does not launch agy or
change the approval rules. Preserve ledgers, receipts, counters, recovery budgets,
and native goal identities. When sessions were replaced or quit, report the stale
bindings. Reassess replacement sessions using the existing session-workflow guide
before updating bindings within the requested monitoring scope; never reset
progress to make start pass. A changed goal or ambiguous session needs assessment,
not a guessed identity.
