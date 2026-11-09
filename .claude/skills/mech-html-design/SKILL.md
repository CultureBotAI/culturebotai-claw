---
name: mech-html-design
description: Review or improve Mech HTML data browsers, record pages, navigation, and interactions using the fleet's established patterns. Compare applicable features across Mechs, trace generated pages to their sources, and verify rendered behavior while preserving scientific meaning and repository identity.
metadata:
  category: cross-repo
  requires_internet: true
  version: 1.0.1
  tags: [fleet, html, design, accessibility, navigation]
---

# Mech HTML design

Use the fleet's existing page patterns to make scientific records easier to
find, compare, inspect, and trace to evidence. Keep each Mech's visual identity
and domain-specific displays. A chemical structure, protein sequence, community
interaction, and pathway reaction do not need identical layouts.

## Establish the surface

When invoked from a Mech or a global skill link, locate claw through
`OPENCLAW_ORCHESTRATION_ROOT` or the resolved location of this skill and verify
its Git identity. Run fleet configuration commands there, not in an arbitrary
current directory.

Resolve the current published claw revision and its manifest before a fleet
comparison. From that pinned checkout, enumerate the full selected scope:

```bash
uv run python -m kg_microbe_fleet list --format json
uv run python -m kg_microbe_fleet targets --capability testing --dotenv .env
```

The first command selects Mechs; the second only locates identity-validated
checkouts. Omit the dotenv argument when using exported configuration. Explicit
extra repositories remain named additions, not silent manifest members. A
disabled site-check capability does not imply that the Mech has no site.

For each target, inspect its current default-branch SHA, instructions, Pages
workflow, source templates/builders, CSS/JavaScript, generated output, and
relevant open issues and PRs. Distinguish the checkout, build artifact, and live
deployment. A missing generated file before the build is not a design defect.
Before claiming absence, include hidden and ignored files in the search and
check the published Git tree. Record inaccessible surfaces as unknown.

Read [the pattern guide](references/patterns.md) to choose an existing model.
Follow its source links and recheck the current implementation before reusing
it; the examples are entry points, not declarations of present fleet parity.

## Compare by reader task

Make a matrix covering **display**, **navigation**, and **interaction** for
every selected repository. Each applicable gap needs a concrete reader action,
source location or rendered reproduction, and acceptance criterion. Use
present, missing, partly present, in progress, not applicable, or unknown;
include the issue/PR owner when another change already covers it.

- **Find records:** labelled search that covers the stated corpus; facets when
  the data supports useful choices; counts that distinguish loaded, matching,
  and total records. Test identifiers, labels and any advertised synonyms.
- **Understand a record:** human-readable names beside stable identifiers,
  definitions and units where present, typed relationships, provenance and
  evidence attached to the claims they support. Link to the actual source
  record. Missing evidence is not negative evidence; a diagram is not proof.
- **Move between views:** visible return to the catalogue, coherent relative
  links on nested Pages routes, useful category context, and a route to the
  maintained [Mech directory](https://culturebotai.github.io/mechs/). Useful
  sibling links may remain a selected subset; do not copy an exhaustive fleet
  list into every footer.
- **Operate controls:** native links/buttons and labelled inputs, visible focus,
  keyboard disclosure and removal, accurate expanded/pressed state, announced
  result changes, reset, and distinguishable loading/error/empty states.
- **Read at different sizes:** viewport metadata, one main content landmark,
  semantic tables with contained horizontal scrolling, readable long identifiers,
  and existing theme preference maintained across catalogue/detail navigation.

Applicability comes from the reader task and actual data. A small static table
need not acquire pagination; a large sharded corpus must not become one giant
DOM. A repository with no supported public HTML surface is not automatically
required to launch a website. Maps, graphs, dark themes, export formats, and
domain-specific facets are not universal feature requirements.

## Implement in the owning source

A review request authorizes the audit; honor any existing authorization for
issues and fixes. Reuse matching issues and check overlapping PRs. For changes
across repositories, use [cross-mech-sync](../cross-mech-sync/SKILL.md): validated
identities, isolated worktrees, short metadata locks, and each repository's
normal review and merge gates. Preserve unrelated work.

Change maintained templates, scripts, or layouts; regenerate tracked output
through its builder. If a shared governed artifact must change, use its declared
authority and release procedure rather than editing consumer copies. Prefer an
existing local pattern before introducing a new component or library. Do not
regenerate embeddings, call paid research services, or alter curated scientific
records merely to test an HTML change.

Treat query strings and record prose as text, not HTML. Escape at the rendering
boundary and validate links according to the repository's link policy. Keep
working server-rendered records usable without JavaScript where the existing
site provides that fallback. Render a visible failure and recovery route when
a browser genuinely requires a fetched index; never turn failed loading into
an empty-corpus claim.

## Verify the result

Use the repository's build and relevant tests, then exercise the built pages in
a browser. Match verification to changed surfaces: catalogue, nested detail,
category, or map. Test narrow and desktop widths, keyboard-only operation,
search/filter/reset, zero results, literal markup in queries, failed data loads,
and theme continuity where relevant. Check console errors and broken requests.
For regressions, show that the test or reproduction fails on the baseline.

For deferred record views, wait for the expected record identifier and populated
scientific sections or tables before measuring layout or accepting a detail-page
check. Assert that the expected content actually appeared; checking a loading
shell proves only the shell. Wait for styles and fonts to settle as well. Exercise
later pagination or disclosure updates that install more content, and check that
their tables remain readable and keyboard-scrollable. Where JavaScript is
disabled, verify the site's supported fallback rather than expecting fetched
record content.

Use the shared site check on actual built output when the capability is enabled:

```bash
uv run kg-microbe-site check --mech "$MECH_KEY" --site "$BUILT_SITE"
```

Its structure/link checks and declared-token contrast checks are useful but do
not prove keyboard behavior or all computed color pairs. An unexamined token is
a coverage gap, not a measured contrast failure. Scope browser contrast probes
to the rendered foreground/background and active theme.

Refresh affected main branches, issue/PR state, and the manifest before claiming
fleet coverage. After an authorized merge, verify generated artifacts and the
actual Pages deployment; an open or queued PR is unfinished work. Report the
reuse matrix, issue and PR links, observed checks, and any remaining gaps.
