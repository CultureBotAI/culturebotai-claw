---
description: Start, stop, restart, or check the local Mech monitoring services
---

Use the repository-local `mech-monitor-control` skill at
`.claude/skills/mech-monitor-control/SKILL.md`.

Interpret `$ARGUMENTS` as `start`, `stop`, `restart`, or `status`, optionally
followed by `approvals` or `supervisor`. With no action, use `status`.
Validate these words rather than evaluating arguments as shell code. Unrecognized
arguments need clarification; never guess that a status request means start.
Run the lifecycle command and report its actual per-service results. Do not
launch or quit agy sessions, change approval choices, or reset workflow progress.
