# Observing Mech sessions in tmux

New persistent Mech sessions use tmux. A Terminal window is an optional attached
view; closing or detaching it does not establish that the agent exited. The
session endpoint is the explicit tmux socket, server incarnation, exact session,
window ID and pane ID. The native agent has its own PID, start time, pane TTY and
working directory. Keep these identities distinct from an attached viewer's TTY.

`scripts/mech_session_tmux.py` observes pinned local macOS endpoints. It never
sends input, starts or stops a session, writes native stores or registries,
adopts a workflow, or grants dispatch permission. It emits private JSON to
stdout. Real identities and snapshots belong in ignored `workspace/` or `.temp/`
storage, not public examples, repository configuration, or published progress.

The existing agy supervisor remains Terminal-only. This observer does not turn
its `--apply` path into a tmux dispatcher. Existing task, merge, prompt and
workflow holds remain effective. A live transport is not evidence that a task
has completed or that it is safe to send input.

## Inspect one candidate

Run on the host owning the tmux server, using its installed Python and tmux.
Inspect the exact current pane and native PID first. This synthetic command
prints a candidate binding and a verification result; it does not install the
binding anywhere:

```bash
python3 scripts/mech_session_tmux.py inspect \
  --key examplemech --tmux /usr/local/bin/tmux \
  --socket /private/example/mech-fleet \
  --session ExampleMech --pane %3 --pid 104 \
  --root /private/example/ExampleMech \
  --native-mode embedded \
  --thread 00000000-0000-0000-0000-000000000001 \
  --rollout /private/example/sessions/rollout-example-00000000-0000-0000-0000-000000000001.jsonl
```

`--socket` is mandatory. An inaccessible named socket fails; the adapter never
falls back to the default server. A replacement server at the same path, a
reused PID, a dead or replaced pane, a changed native working directory or an
unrelated process sharing a TTY invalidates the binding. All transport checks
run before and after capture. Importing the adapter performs no discovery.

The output's `binding` contains the socket device/inode, server process identity,
exact tmux IDs, pane shell identity, native process identity, root and optional
native thread expectation. An optional `viewer` field may describe an attached
Terminal tab, but the adapter neither reads it nor uses it as process authority.

For a Codex client connected to a shared daemon, use `--native-mode managed`.
Its transport can be verified while its native identity remains `unknown`:
the client does not own the daemon's rollout descriptor. A saved rollout file or
a UUID passed on a command line is insufficient proof of the currently attached
daemon thread. The adapter does not connect to a daemon or synthesize stronger
evidence. A separate reviewed read-only native API integration would be required.

In embedded mode, native verification requires exactly one primary rollout
owned by the pinned native process and matching thread/cwd metadata. Primary
`cli` and `vscode` origin metadata are supported because a saved desktop-origin
thread can later be resumed by an embedded CLI. This verifies identity only:
the adapter reads the bounded metadata header, not task history or completion.

## Observe reviewed bindings

A private registry has this envelope, with the actual inspected `binding`
objects in `targets`:

```json
{
  "schema_version": 1,
  "role": "observer_only",
  "targets": []
}
```

The empty list above is illustrative, not a runnable registry. One to 64 targets
are accepted. Duplicate keys or socket/pane endpoints are rejected before any
observation. The registry is read without being changed:

```bash
python3 scripts/mech_session_tmux.py observe \
  --registry workspace/tmux-observer/registry.json
```

The exit status is nonzero if registry validation fails or any transport cannot
be verified. An unknown native identity is reported separately and does not
mislabel a verified transport as stale. Screen output contains a digest,
character count and conservative visible-state classification, never screen text.
`empty_composer_visible` is deliberately not called idle or completed. Goal,
approval, question, draft, working and unknown states retain their distinctions.

## Integrate an existing passive monitor

Keep the monitor's old Terminal bindings held. Prepare a separate candidate
registry using the exact replacement endpoints and preserve any old/new thread
mapping as private provenance. Test the adapter and inspect one real embedded
session first. Verify the same read-only path on a managed session before using
that mode more broadly. Run a bounded full observation only after the canaries
show the expected identities and limitations.

A private monitor can import `observe_binding(binding)` and store its result in
its own heartbeat/snapshot protocol. Import the reviewed source at an immutable
pin, and keep that pin in the monitor's existing source-integrity checks. Preserve
legacy Terminal observation for unmigrated sessions, keep unbound candidates
unbound, and never copy an attached viewer's TTY into the native process binding.
Do not infer workflow admission or goal closure from the adapter's output.

Changing a running monitor is a separate reviewed deployment: back up its
configuration next to the original, stop it through its owned lifecycle,
install the reviewed source and private registry, restart, and verify heartbeat,
source pin, counts and unchanged workflow ledgers. A reviewable source change
or successful one-shot canary does not itself reconfigure a running service.

Tests live in `tests/test_mech_session_tmux.py`; they use synthetic process,
socket and screen fixtures and never touch live sessions. The contract is tracked
with claw issue 1238.
