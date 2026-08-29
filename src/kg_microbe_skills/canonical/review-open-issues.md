---
name: review-open-issues
description: "Sweep and prioritize {{ display_name }}'s complete open GitHub issue queue against what this repository actually guarantees — its schema, its curated corpus, its validation gates, and the vendored artifacts it shares with the rest of the fleet. Use for full backlog triage or deciding what is genuinely urgent; it is read-only and is not permission to close issues, mutate another repository, or implement fixes."
category: workflow
requires_database: false
requires_internet: true
version: 1.0.0
tags: [issues, triage, backlog, priority, read-only, reporting]
---

# Review and prioritize open issues

Produce a complete, dependency-aware triage of {{ display_name }}'s open
issues.

This is a read-only review. It does not implement fixes, close or edit issues,
or touch another repository. Its output is a ranking with reasons.

## Scope

- Repository: `{{ github }}`
- Package: `{{ package_path }}`
- Schema: {{ schema_paths }}
- Curated records: {{ record_globs }}
- Checkout resolved through `{{ environment_variable }}`

## Sweep the whole queue first

```bash
gh issue list -R {{ github }} --state open --limit 200 \
  --json number,title,labels,createdAt,updatedAt,comments
```

Read every one before ranking any. A queue triaged in the order it happens to
be listed reproduces the listing order, not a judgement.

## Rank by what is weakened, not by age

For each issue, answer three questions:

1. **What does it break?** A wrong ontology grounding in {{ record_globs }} is
   published data other repositories consume. A flaky test is a signal problem.
   A missing docstring is neither.
2. **Who is standing on it?** A defect in a vendored artifact reaches every
   Mech. One in `{{ package_path }}` reaches this repository's consumers. One
   in a one-off script reaches whoever runs it next.
3. **Is it load-bearing for something else open?** An issue that blocks three
   others outranks its own severity.

Recency is not a signal. An issue filed today about a typo is below one filed
in April about a gate that silently passes.

## Say what you could not determine

An issue you could not rank because it needs a decision, a credential, or a
corpus you cannot read is a real finding. Report it as unranked with the reason
rather than guessing a position for it — a confident ranking that quietly
omits what it could not see is worse than a shorter one that says so.

## Output

A ranked list, each entry carrying: the issue number, one line on what it
weakens, who depends on that, and what would have to be true to close it.
Group anything you could not rank at the end under its reason.
