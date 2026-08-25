# Multi-Claude coordination

This repository coordinates concurrent work across the Mechs selected by the
packaged fleet manifest. The current implementation combines manifest-scoped
repository discovery, short-lived file leases, Claude Code project hooks, and
advisory status records. It is a local-machine coordination boundary, not a
distributed lock service.

## Sources of truth

- `src/kg_microbe_fleet/fleet.yaml` defines every Mech, its repository identity,
  configuration environment variable, and capabilities. A target participates
  in this protocol only when `coordination_hooks` is enabled.
- `plugins/repository_settings.py` resolves configured checkout roots and
  verifies that each checkout's Git identity matches the manifest. Scripts must
  not reconstruct fleet membership or assume sibling-directory layouts.
- `plugins/lock_manager.py` implements leases. Runtime state lives below the
  configured `OPENCLAW_WORKSPACE`, which defaults to `workspace` under this
  orchestration checkout.
- `scripts/install_hooks.sh` installs and registers the Claude Code enforcement
  boundary for every configured, applicable target.

Use manifest keys as lock resource names. Do not maintain a second list of
repositories in scripts, docs, or hook logic.

## Lease contract

`LockManager` creates `workspace/locks/<resource>.lock` atomically. A successful
acquisition records an unguessable lease token, owner, operation, process,
timestamps, and expiry. Only the manager that owns the live token can release
the lease. Expired leases are reclaimed through a guarded transition so a stale
reader cannot remove a new owner's lock.

Lock paths and records are treated as security-sensitive coordination state.
Symlinks, non-regular files, oversized or malformed records, unsafe resource
names, and unreadable state fail closed. A global lease blocks all repository
operations; a repository lease blocks that manifest resource. Use the
`LockManager.lock(...)` context manager so release occurs in `finally`, and keep
leases around the shortest shared metadata transition possible. The working
examples in `CLAUDE.md`, `README.md`, and the `boss` skill use the current API.

Never delete a `.lock` file directly during normal operation. Ownership and
expiry decisions belong to `LockManager`.

## Installing Claude Code hooks

Configure the manifest-defined root environment variables for the checkouts
that should receive hooks, then run `scripts/install_hooks.sh` from this
orchestration checkout. An unset root is reported as unconfigured; an invalid
configured root is an error. `OPENCLAW_WORKSPACE` may select a trusted runtime
workspace at installation time. Relative workspace paths must stay within this
checkout.

The installer writes owned files below `.claude/hooks/kg-microbe/` and merges
registrations into `.claude/settings.json`. It does not overwrite generic user
hooks. An identical managed file is left alone, a marker-owned older version is
upgraded, and an unowned collision in the managed namespace stops installation
unless the user explicitly chooses `--force`.

Settings updates reject duplicate or non-standard JSON, symlinks, non-regular
targets, invalid hook structures, and concurrent replacement. Writes are
atomic and preserve unrelated valid settings and hooks, including fields added
by newer Claude Code versions. In addition to local structural checks, the
registrar runs the installed Claude Code build's non-session `doctor` command
against a temporary copy of the complete prospective project/local settings.
Installation stops if that build rejects the document or cannot return a
recognizable validation result. Exact managed handlers are normalized to a
single synchronous `{type, command}` entry so options such as `async`,
`asyncRewake`, `if`, `timeout`, `args`, or `shell` cannot disable or alter
enforcement.

The installer also reads `.claude/settings.local.json` without modifying it. It
stops before installing hook files when that file is malformed, unsafe, or sets
`disableAllHooks` or `allowManagedHooksOnly`. The same flags are rejected in
project settings.

Restart active Claude Code sessions after installation. Use Claude Code's
`/hooks` view to confirm the project handlers are active. User-level and
administrator-managed policy can suppress project hooks and is outside what a
project installer can inspect; a successful install therefore cannot prove
that a higher scope has not disabled them.

## Registered event behavior

| Event | Matcher | Behavior |
| --- | --- | --- |
| `PreToolUse` | `Edit|Write|NotebookEdit` | Validate the event and target path, then check the target Mech and global leases. |
| `PreToolUse` | `Bash` | Validate the event/cwd and check the target Mech and global leases for every shell command. |
| `PreToolUse` | `Bash` | Separately classify real in-project `git commit` invocations and perform the commit-specific check. |
| `PostToolUse` | `Edit|Write|NotebookEdit` | Record a completed edit and return the local status to `idle`. |
| `PostToolUse` | `Bash` | Record completion only when stdin describes a successful in-project `git commit`. |

Claude Code provides event JSON on stdin. The installed helpers reject malformed
or duplicate-key input. Edit targets must resolve within the baked project root.
Bash events must start in that project. Commit classification rejects sibling
or nested repository targets, Git directory overrides, ambiguous shell state,
and malformed shell syntax.

Both Bash pre-handlers are independently safe; their order is irrelevant. The
general Bash handler always checks the lease, while the commit handler no-ops
only for a valid non-commit event. Registered pre-handler wrappers normalize
every script failure, including missing or non-executable infrastructure, to
exit code `2`, the Claude Code blocking status. A successful check exits `0`.
Post handlers are advisory: irrelevant events exit `0`, while a genuine status
write failure is surfaced as nonzero but cannot retroactively block the tool.

Claude Code hooks are not a filesystem sandbox. The Bash guard protects the
installed project's lease and rejects an out-of-project event cwd, but it cannot
prove that every argument in an otherwise in-project arbitrary shell command
avoids external paths. Cross-Mech automation must still resolve the intended
manifest target, use an isolated worktree where appropriate, and acquire that
target's lease. The `boss` and `cross-mech-sync` skills define those workflows.

## Status and operational workflow

Post hooks write atomic YAML records under
`workspace/status/<manifest-key>_claude_status.yaml`. A completed edit or commit
sets `status: idle`, clears `current_operation`, and records completion details.
Status is observability data, not a lock and not permission to write.

For coordinated work:

1. Resolve applicable targets from `kg_microbe_fleet`; do not infer paths.
2. Give each writer its own branch and worktree when concurrent Git work is
   possible.
3. Acquire the exact repository or global lease for the bounded shared
   transition.
4. Perform the operation and release only the lease owned by that manager.
5. Treat hook denial, unreadable lock state, invalid configuration, or unknown
   repository identity as a hard stop.
6. Use status files for observation and Git/PR state for durable handoff.

## Scope limitation

The default `workspace/` directory is gitignored runtime state. It coordinates
processes that can see the same filesystem, but it is invisible to another
machine and to CI unless they share that workspace through a separate trusted
mechanism. Do not describe these leases as cross-machine or distributed
enforcement. Remote concurrency needs a remote authority such as GitHub
Actions concurrency, a service-backed lease, or another explicitly designed
control plane.
