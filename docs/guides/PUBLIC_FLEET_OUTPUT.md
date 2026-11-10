# Public fleet membership

The canonical fleet remains the complete internal inventory. A Mech may declare
`tags` as a list of unique lowercase, hyphen-separated strings; omitted tags
mean an empty list. The reserved tag `exclude-from-public` removes a member from
public fleet outputs. It does not change repository visibility, governance
membership, root configuration, lock ownership, or internal operations.

This is a suite-representation policy, not a publication restriction on the
member itself. An excluded member may have a public GitHub repository and its
own GitHub Pages site. ScaleupMech may publish independently while remaining
absent from the X-Mech pages, suite indexes, aggregate statistics and shared
public progress projection. Its own website and native publishing workflows
must not be disabled solely because of this tag.

Use `load_fleet_manifest().public()` before reading member-specific inputs,
serializing identities, or computing public totals. The returned manifest has
the same capability catalogue and governance authority but only public members.
An empty projection remains empty. Do not maintain a separate list of excluded
repository names, and do not hide already-serialized members with CSS.

For shell consumers:

```bash
uv run python -m kg_microbe_fleet list --public --format json
```

Without `--public`, the CLI continues to report the full fleet. JSON identities
carry their validated tags. Public JSON contains no excluded-member identities,
paths, tags, counts, or audit rows.

The X-Mech site must use the public projection for manifest snapshots, audit
rows, infrastructure entries, navigation, cards, data downloads, census and
statistics. Existing saved source data must be checked against that membership
before aggregation: filtering only the final cards leaves contributions in
record, vocabulary, overlap, review and PR totals. Pin the site's snapshot to
the reviewed CLAW revision implementing this contract before deployment.

CLAW's progress publisher and Pages builder project their histories and
recompute snapshots using public membership. Local operational progress remains
complete. Public history reconciliation cannot replace or erase excluded local
progress. A public bundle with unapproved members must fail closed.

ScaleupMech declares `exclude-from-public` at admission. Tests also tag other
members and supply distinct nonzero contributions so they exercise policy,
rather than relying on ScaleupMech's currently empty corpus.

This policy governs public fleet/site products. The canonical governance
manifest and admission evidence are operational source artifacts, not public
fleet statistics. It is not a mechanism for making a GitHub repository private
or erasing previously published Git history.
