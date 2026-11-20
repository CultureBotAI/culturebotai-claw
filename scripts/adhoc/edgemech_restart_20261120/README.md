# EdgeMech restart helper provenance — 2026-11-20

CLAW owns these bootstrap and control helpers because it resolves the EdgeMech
repository, coordinates its metadata lease and controls the isolated startup.
This directory addresses [EdgeMech issue 228](https://github.com/CultureBotAI/EdgeMech/issues/228).
It does not enable disabled generic fleet review capabilities.

The original helpers and startup artifacts remain unchanged in the private
campaign. Their SHA256 values and byte counts are recorded in PROVENANCE.json.
That is a repair-time association of preserved evidence, not a claim that the
old receipts originally recorded their producer hashes. The private startup
HELPER-PROVENANCE.json resolves the actual locations and links this PR and its
independent review. The originals retain their historical execution provenance;
these parameterized successors have **not** run against a live coordinator or
answered a live prompt.

The private originals contain host paths, pane/session identities and connection
details, so their bytes and startup transcripts are not copied into public Git.
The maintained files have distinct hashes. PROVENANCE.json maps each private
original hash to its maintained source hash; it does not claim byte equivalence.
Original receipts, authorization, failed startup and later observations are
preserved rather than regenerated.

## prepare_coordinator.py

Purpose: create one isolated EdgeMech coordinator clone from exact selected PR
metadata, preserving the previously selected code commit and allowing only
Markdown changes between it and the selected head.

Inputs are an explicit CLAW root, request file, selected/prior PR JSON containing
headRefOid and headRefName, a fresh absolute destination and private receipt,
and a feature branch. The helper validates configuration, resolves EdgeMech
through RepositorySettings and checks its identity and clean state inside the
EdgeMech LockManager context. It requires **an explicit absolute
OPENCLAW_WORKSPACE** in the merged selected CLAW .env/environment and uses that
workspace's locks directory. Exported values take precedence. Relative or absent
workspace settings are refused; the isolated helper checkout's default workspace
must not silently become a different coordination ledger.

Output is one private actual checkout receipt binding the helper, request and
selected/prior metadata hashes, canonical and isolated identities, selected
commit and observed changed paths. Input changes during cloning fail closed.
A partial clone is retained on failure; the helper does not delete it, retry,
launch a worker, write canonical records, merge or answer a prompt. The shared
clone depends on its source object store. This bootstrap is for the reviewed
documentation-only selection; it is not a generic code-adoption mechanism.

Use --help for required options. The invocation requires --apply in addition to
the caller's existing user authorization. Run it with the configured CLAW Python
environment. A new selection or failed attempt needs its own review and fresh
paths; do not rerun it to reproduce an old receipt.

## answer_exact_trust_once.py

Purpose: send exactly one “1, Enter” for a separately and explicitly authorized
checkout-trust prompt. It is not a general approval runner.

Inputs are private authorization JSON, exact binding JSON, an absolute fresh
private receipt path, explicit absolute tmux binary/socket paths, and --apply.
The binding contains pane, checkout, session_name, pane_pid, pane_tty,
tmux_binary and tmux_socket. An optional control_client selects an already
authorized normal tmux control client; this helper never creates one or changes
existing viewers.

The authorization must name source=explicit_user_response, action=Trust and
continue, the exact pane, checkout and receipt, and binding_sha256 for the
**complete exact binding-file bytes**. If a control_client is selected, its name
must also match authorization.control_client. A newly supplied binding file,
socket or pane incarnation cannot reuse the old authorization. These files
record prior user permission; constructing them is not itself permission.

The helper captures only the current visible pane, requires the entire
whitespace-normalized known trust panel, and checks the live session/PID/TTY/
checkout binding. Different wording, extra prompts or old trust text followed by
another prompt are refused. This deliberately narrow panel contract must be
reviewed if the UI changes.

Before any input it exclusively creates, flushes and fsyncs the consumed receipt
(and syncs its parent directory where supported). That receipt stays consumed
after a failure, interruption or lost tool result. A separate result records the
actual command return code and an after-screen hash when available; success
means only that the input command returned zero. It never claims the native
session continued, the task was accepted or scientific work completed. Those
require separate owner readback. There is no automatic retry.

## Validation and future helpers

The focused tests use synthetic identities and mocked tmux/Git mutations. The
actual startup is not a test fixture and is never re-run for provenance.
VALIDATION.json records the observed focused checks and mutation tests; the
separate review is linked by the private startup provenance record and PR.

New campaign helper source belongs under tracked scripts/adhoc/ from the outset,
with purpose, inputs, outputs, date and issue provenance. Private runtime data,
credentials and full evidence stay in durable private campaign storage. Keep
code review, transport success, native continuation and scientific coverage as
separate claims. This PR grants no new prompt, merge, provider or release authority.
