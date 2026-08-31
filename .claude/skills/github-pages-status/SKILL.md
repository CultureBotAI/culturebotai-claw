---
name: github-pages-status
description: "Check every CultureBotAI Mech GitHub Pages site, especially whether the published site is current with that repository's default branch — and whether the commits it is behind actually touch the files the site is served from. Use for fleet Pages health, freshness, deployment lag, a broken site, or \"are all Mech docs current?\". Read-only; it never rebuilds or deploys."
category: cross-repo
requires_database: false
requires_internet: true
version: 1.1.0
tags: [github-pages, docs, status, freshness, fleet, mech, deployment, read-only]
---

# GitHub Pages status

Run the fleet checker from the `culturebotai-claw` root:

```bash
uv run python scripts/fleet_pages_status.py
```

Membership comes from `src/kg_microbe_fleet/fleet.yaml`, which is the authority.
The organization is *also* listed, and any Mech-named repository publishing a
site without being a manifest member is reported under Coverage rather than
quietly folded in — that gap is a finding, not a detail. Discovery is from
GitHub rather than local clones, so a newly created or uncloned Mech cannot
disappear from an "all Mechs" answer.

## Interpret the result

Treat these as separate evidence:

- `LIVE` is the HTTP response from the deployed URL.
- `DEPLOY` is the newest deployment attempt's state. The published revision is
  taken from the newest *successful* `github-pages` deployment, so a failed
  attempt cannot be mistaken for live content.
- `SITE VS MAIN` answers whether the **published site** is current, which is
  not the same as whether its SHA equals main's:
  - `CURRENT` — the published SHA is main.
  - `current (N behind)` — main is N commits ahead, and **none of them touch
    the files the site is served from**. The site a reader sees is up to date.
    This is the common case: measured across the fleet, every Mech was one
    commit behind and every one of those commits changed a justfile recipe,
    `.env.example` or a vendored script.
  - `STALE (N file(s))` — main carries N changed files inside the served tree.
    This is the only verdict that means readers are seeing old content.
  - `DEPLOYING` — a deployment is queued or running; the newest commit is
    publishing now. Not staleness.
  - `DEPLOYED_AHEAD`, `DIVERGED`, `UNKNOWN` stay distinct; do not simplify them
    to “stale.”

  The narrowing uses the served path GitHub reports (`source.path`). For a site
  built by a **workflow**, the inputs are only known to the workflow, so the
  change set cannot be narrowed — the report says so and the commit count is an
  **upper bound**. Quote it that way rather than as a stale-page count.

Exit `0` means every discovered Mech has Pages enabled, its newest deployment
attempt succeeded or is still running, the served content matches main, the
site is reachable, and fleet discovery was not truncated. Exit `1` means
the printed findings need attention or coverage is incomplete. Exit `2` means
fleet discovery or command usage failed.

Report the table and Coverage section together. Never quote the current count
without the discovered-repository denominator or suppress a nonzero exit.

**Do not report a bare "N commits behind" as staleness.** That number was the
whole reason this skill exists: it made eight healthy sites look uniformly out
of date. Say whether the commits touched the site, or say that they could not be
narrowed.

## Options

```bash
uv run python scripts/fleet_pages_status.py --json
uv run python scripts/fleet_pages_status.py --org CultureBotAI
uv run python scripts/fleet_pages_status.py --repo-limit 500
uv run python scripts/fleet_pages_status.py --deployment-limit 50
uv run python scripts/fleet_pages_status.py --no-live-check
```

Use `--json` for downstream processing. `--no-live-check` is appropriate only
when HTTP reachability is explicitly out of scope; freshness still uses remote
GitHub deployment and branch data. `GH_TOKEN` or `GITHUB_TOKEN` is used when
present, but public CultureBotAI repositories can normally be checked without a
token. If GitHub rate-limits an unauthenticated run, report the incomplete check
and rerun with a read-only token; do not infer health from local clones.

## Boundaries

This skill is read-only. A stale, failed, or unreachable result authorizes
diagnosis only—not a workflow dispatch, rebuild, configuration edit, or deploy.
If remediation is requested later, inspect the failing repository's Pages
workflow and obtain any authorization required for cross-repository changes.
