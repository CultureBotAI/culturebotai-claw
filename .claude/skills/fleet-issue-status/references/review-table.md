# Shared issue inventory and review table

The status script owns acquisition and rendering. The review skills own the
judgments. Keep both views in one report:

| View | Order | Review information |
| --- | --- | --- |
| Repository summary | Open-issue count descending; manifest-order ties; failures last | Reviewed, unreviewed, keep, close, defer counts |
| Issue ledger | Same repository order | Priority, proposed action, reason, evidence, revisit date/trigger |

Repository volume determines which queue to review first, not which issue has
the greatest consequence. Within the evidence review, retain the separate
priority/theme/readiness ranking. Failed and truncated queues make count ranking
provisional; zero-issue queues remain visible.

## Portable fields

The per-issue TSV appends these fields after its original 13 columns; JSON and
Markdown expose the same review decisions:

| Field | Meaning |
| --- | --- |
| issue_key | Full canonical owner/repository#number; never a bare number |
| review_priority | P0, P1, P2, P3, or Unranked; consequence assessed against evidence |
| review_action | unreviewed initially; keep, close, or defer after assessment |
| review_reason | Why this recommendation follows from remaining acceptance criteria |
| review_evidence | Commit/code/PR/comment links or durable evidence paths, with baseline |
| defer_until | Concrete revisit date or event; required for defer |

Use the priority rubric in the fleet review skill. Source labels remain in the
labels field and are not automatically converted into reviewed priority. A
fixed issue has no remaining implementation priority: close candidates use
Unranked. Defer does not mean low impact: a high-priority issue can be deferred
pending an explicit dependency or decision. Record that reason and revisit trigger.

## Retain decisions across refreshes

Pass `--triage-file` a JSON object keyed by the exact issue_key. Each decision
binds to the issue's fetched updatedAt value using updated_at. Example shape
(the example identity and issue number are illustrative, not a real verdict):

```json
{
  "CultureBotAI/culturebotai-claw#123": {
    "updated_at": "2026-11-13T10:00:00Z",
    "review_priority": "P2",
    "review_action": "defer",
    "review_reason": "The remaining acceptance test depends on the next schema release.",
    "review_evidence": "Saved review evidence identifies the pending schema change and baseline SHA.",
    "defer_until": "Recheck when the schema release is published"
  }
}
```

Create a separate decision file in the review directory; do not edit the generated
TSV as the durable source of judgments. Omitted issues remain unreviewed. Invalid,
unknown, or stale decisions fail rather than being silently carried forward.
If a key disappears because an issue closed or the requested scope changed,
reconcile it into the historical review ledger before removing it from the active
overlay. Never discard the only copy of the old decision.

An unchanged issue timestamp does not prove the code, comments, linked PRs, or
external evidence are unchanged. The full review still reads all comments and
refreshes the published-code baseline before carrying a verdict forward. Record
that baseline in review_evidence. Keep themes, readiness, owner/task packets, and
closed-during-review history in the complete review ledger; the open-issue intake
is not a replacement for that evidence.

Generate the enriched table from the same collector using `--triage-file` with
`--markdown` or `--json`; TSV emission is enabled by default. Keep the raw initial
snapshot alongside the refreshed report and decision file. None of these fields
performs a GitHub mutation.
