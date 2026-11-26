# Edge recovery source provenance — 2026-11-25 campaign

CLAW owns this preservation work for [EdgeMech issue 228](https://github.com/CultureBotAI/EdgeMech/issues/228).
It makes the actual recovery/checkpoint producer code reviewable. It does not
introduce a recovery runner or confer permission to repeat a historical action.

The fixed local inventory ends at **2026-11-26T04:34:24.017Z**. Independent review
classified 63 root calls: 24 recovery producers or controls and 39 read-only
probes. Three delegated audit/metadata writers, two review-metadata writers and
two native recovery-state writers bring the included total to **31 calls**.
The archive contains **89 source files**, including **27 Python heredocs**.
`archive/MANIFEST.json` maps every private original source hash and byte count
to its public derived source hash and byte count. Complete wrappers are retained,
including computed commands; decoded shell/Python source is included where a
native command event supplies it. These are source files, not hash-only stubs.

## Historical source, private originals, and safety boundary

Every `archive/**/*.txt` file is **inert historical source**. The suffix is
intentional: do not import it, pipe it into a shell, or remove the suffix to run
it. The original control logic, including historical limitations such as Python
`assert` guards, is preserved for review rather than endorsed as a safe runner.
No archived control, goal, worker, provider or checkpoint action was replayed.

Private copies retain the exact decoded tool-input UTF-8, exact executed shell
strings and exact heredoc contents. Their hashes refer to those source bytes,
not the JSON-escaped serialization of a rollout line. Private linkage records
also pin the rollout bytes observed during extraction, event line, call ID,
timestamp, original source/result event hashes and native command status.
The independently enumerated inventory is retained alongside them, including
the later terminal-poll result for the initially yielded audit writer. No active
client attachment is relabeled as a successfully completed command. The refused
composer-change attempt and the later successful submission are both retained.

Public variants replace private home paths, session/UUID/pane/socket/TTY/client
bindings and process identifiers with named `PRIVATE_*` placeholders. Explicit
process-label substitutions also cover identifiers attached to prose. Public
schema keys such as `call_id` retain their original spelling. The full token-to-
original map stays private; the byte verifier reverses substitutions and requires
exact equality with each pinned original. This is a preservation-time derivation:
**the originals were not parameterized retroactively and the public variants were
not used for the historical recovery.**

## Included producer/source inventory

| Archive ID | Purpose and outputs |
| --- | --- |
| root-2590 | Attach the ordinary control client; retain actual tool/session result |
| root-2603 | Save pre-resume screen and resume-command intent |
| root-2619 | Submit the existing goal resume and record consumption |
| root-2633 | Produce and paste the coordinator follow-up |
| root-2647 | Record follow-up submission and preserve the worker draft |
| root-2661 | Record the worker cursor adjustment |
| root-2675 | Clear the preserved draft; control-only call |
| root-2691 | Verify draft clear and produce the current-facts note |
| root-2703 | Submit current facts and record delivery |
| root-2857 | Produce and paste review/canary priorities |
| root-2862 | Preserve the refused composer-change submission attempt |
| root-2884 | Preserve the later guarded successful submission |
| root-2954 | Produce the fresh CLAW-tools checkpoint |
| root-2963 | Attach the ordinary recovery control client |
| root-2975 | Record exact coordinator normal-quit intent |
| root-2980 | Submit normal quit and retain the screen/receipt |
| root-2992 | Verify old exit and reopen the exact saved session |
| root-3016 | Exclusively record exact-goal selection consumption before input |
| root-3042 | Produce and paste recovery follow-up |
| root-3047 | Record follow-up submission |
| root-3054 | Produce the unchanged-settings readback |
| root-3074 | Produce the successful native-tools recovery checkpoint |
| root-3091 | Produce and paste the preparation-review handoff |
| root-3101 | Record preparation-review delivery |
| metadata-1265 | Produce the retained census/worker audit; initial yield and terminal poll both retained privately |
| metadata-1332 | Produce resume ACK/progress/task-entry snapshots and checkpoint |
| metadata-1426 | Produce network-recovery ACK/progress/task-entry snapshots and dated reports |
| review-metadata-2053 | Produce the independent PR233 review |
| review-metadata-2207 | Produce the independent preparation evidence/helper review |
| native-recovery-1948 | Preserve prior native state and helper/evidence hashes |
| native-recovery-1962 | Produce and publish acceptance, first-worker, coordinator progress, queue and recovery checkpoint via shell/jq |

## Bounded exclusions

The initial network-canary intent/events/reply/stderr/handoff arrived from an
external parent agent through its existing remote connection. Their hashes are
recorded in `PROVENANCE.json`; the producing source/thread was not supplied and
is outside this local producer archive. The local search covers the four named
local owner rollouts through the cutoff, not every host or session. No remote
host was contacted to reconstruct missing producer code.

The original November 20 bootstrap/trust helpers remain owned by
[CLAW PR1299](https://github.com/CultureBotAI/culturebotai-claw/pull/1299).
Preparation/scientific helper source at Edge commit
`97c675ed3f614995d18dc3f1e8548fb83dc5cfd8` remains Edge-owned and separately
reviewed. Later direct-CLI/prose routing of the preservation agreement and a new
checkpoint-writer review is ongoing supervision, explicitly outside this fixed
recovery archive. This archive claims neither all later controls nor scientific
review completion.

## Maintained offline tooling

`preserve_sources.py` accepts a private reviewed inventory (or explicit selection),
optional private binding JSON and two fresh, absolute, disjoint output roots.
Its outputs are the private exact source/linkage archive and the public inert
source/manifest. Reviewed inventory mode checks source event, call ID, timestamp,
source bytes and the matching result event against independent pins **before
creating either root**. Missing/ambiguous result bindings fail closed. Selected
native completion events use the documented bounded call window; missing native
terminal status remains unclaimed. Existing output trees are never overwritten.
This is trusted-caller local archival tooling, not a hostile filesystem service.

`validate_archive.py` takes those private/public roots, checks file hashes and
complete public-source coverage, reverses every private binding, and compiles
Python source in memory without executing it. It writes no recovery state.

Run the tools only for authorized preservation; use fresh archive paths for a
new generation. They do not resolve a live pane, acquire a runtime handle,
contact a provider or execute extracted source. Newly written helpers belong in
tracked `scripts/adhoc` on an owned branch **before use**, with purpose, inputs,
outputs, date, issue provenance and independent review where required. Private
bindings, output receipts and validation logs stay in durable private storage.

The focused tests exercise exact source/result linkage, refusal before output,
privacy substitution and byte rehydration. `VALIDATION.json` records checks and
fresh-process negative mutations. Successful archival validates provenance only;
it does not convert a historical failure into success or authorize replay.
