# Public fleet membership

The canonical fleet remains the complete internal inventory. A Mech may declare
`tags` as a list of unique lowercase, hyphen-separated strings; omitted tags
mean an empty list. The reserved tag `exclude-from-public` removes a member from
public fleet outputs. It does not change repository visibility, governance
membership, root configuration, lock ownership, or internal operations.

This is a suite-representation policy, not a publication restriction on the
member itself. An excluded member may have a public GitHub repository and its
own GitHub Pages site. Its own website and native publishing workflows must not
be disabled solely because of this tag.

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

The projection API does not change any member's policy or register new members.
Tests tag existing members in isolated fixtures and supply distinct nonzero
contributions, so they exercise the policy independently of admission or corpus
state. ScaleupMech admission and its proposed exclusion remain separate work
under [#1254](https://github.com/CultureBotAI/culturebotai-claw/issues/1254).

This contract preserves the public-output portion of retired PR #1146, source
head `f3667a24959ae27053b4948a417dbf74d4fbf55a`. It does not revive that combined
admission, rewrite newer CofactorMech or AssayMech governance, replay settings
helpers, or alter the public discussion export contract. The companion site
must refresh PR #551 onto current site code and pin this reviewed contract
before using it; this library change does not deploy that site.

This policy governs public fleet/site products. The canonical governance
manifest and admission evidence are operational source artifacts, not public
fleet statistics. It is not a mechanism for making a GitHub repository private
or erasing previously published Git history.
