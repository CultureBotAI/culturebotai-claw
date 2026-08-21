# Next Tasks — culturebotai-claw backlog

Deferred work, each entry with enough context to pick up cold. **Maintenance:**
update this file as work is started/finished — move done items out, add new
deferrals here instead of letting them live only in your head or a closed PR.
Keep the cross-Mech items in sync with the four Mech repos' `NEXT_TASKS.md`
(CultureMech / MIM / CommunityMech / TraitMech).

This repo is the **coordination hub**, so its backlog is mostly cross-Mech: items
that no single Mech owns, plus the orchestration tooling itself. Per-Mech work
belongs in that Mech's own `NEXT_TASKS.md`.

Last reconciled: 2026-07-30 (first reconcile — this file did not exist before).

Open issues: **#7** (DisMech adoption — infrastructure now complete, see below),
**#12** (cross-Mech web design review). No open PRs.

Shipped 2026-07-21 through 2026-07-25 (seven PRs): **#18** added `shared/idlabel/`
as a canonical copy of the id↔label validator set; **#19** reconciled the two
competing canonical-source schemes down to one; **#20** captured the kg-microbe
unified-mapping loader plus grounding/mapping QC tooling; **#21** made claw's CI
the fleet-wide enforcer of the vendored id-label files, which **#22** then
reverted as off-model; **#24** put the mirror check on a nightly schedule
(closes **#23**). Earlier in the window: **#13** hardened the ingredient-SSSOM
build against residual-cache drift and **#17** fixed plugin-importing justfile
recipes to run under `uv run`.

## The id-label canonical-source question is settled — read this before touching it

This lane churned through three different designs in four days and the Mech
repos' `NEXT_TASKS.md` files still carried the abandoned one. The settled
answer, as of **#22** and **#24**:

**CultureMech is the hub. `claw/shared/idlabel/` is a passive mirror of it.**
claw is not the fleet enforcer. Two directions are covered, and between them
they close the loop:

| Direction | Check | Lives in |
|---|---|---|
| mechs == hub | `scripts/audit_vendored_fleet.sh`, nightly `vendored-fleet-audit.yml` | CultureMech |
| mirror == hub | `matches-hub` job in `id-label-canon.yaml`, nightly | here |

**The superseded plan** — relocating the canonical source out of CultureMech and
into claw, repointing each Mech's `check_vendored_sync.sh` `CANON_REPO` at
`CultureBotAI/culturebotai-claw`, and making CultureMech a peer spoke with its
own `.vendored_canon_ref` — was reverted in **#22** as off-model for
claw-as-mirror. Do not restart it without reopening that decision. Two stale
justifications that traveled with it are also dead: "blocked on making claw
public" (claw is still private, and that now blocks nothing) and "claw Actions
are failing account-wide on exhausted private-repo runner minutes" (false —
scheduled runs have been green daily since 2026-07-25).

One correction worth preserving, because it nearly became folklore: **#21**'s
commit message claimed it "replaces the old CultureMech-hub fleet audit
(`audit_vendored_fleet.sh`) … retired on the CultureMech side." That retirement
never happened. The script is still present and still wired into CI on
CultureMech `main`, which is why **#22** could revert #21 without opening a
coverage gap.

Verified healthy as of 2026-07-30: `vendored-fleet-audit` green nightly;
`id-label canonical` and `Cross-repo validation` green nightly here; and MIM,
CommunityMech and TraitMech all pin the same
`scripts/.vendored_canon_ref` = `6be694f3d6308ac0f4c2e0dcf196e2ff73f6468f`
against `CultureBotAI/CultureMech`.

## The vendored drift job can be bypassed at PR time in all three spokes — PENDING, actionable

Found during the 2026-07-30 reconcile (MIM's backlog spotted it for itself; the
hub check confirmed it is fleet-wide). Each spoke's `vendored-sync` job lives in
`.github/workflows/label-correspondence.yaml` behind a `paths:` filter, and that
filter does **not** list most of the files the job exists to protect. A PR that
touches only the unlisted ones never fires the drift check.

Actual `trigger_paths` versus the 6 drift-checked files:

| Spoke | Lists `src/*/schema/**` (covers `mech_shared.yaml`) | Lists `chem_formula.py`, `check_vendored_sync.sh`, `.vendored_canon_ref`, `tests/test_id_label_*.py` |
|---|:--:|:--:|
| MIM | yes | **no** |
| CommunityMech | yes | **no** |
| TraitMech | **no** | **no** |

TraitMech is the worst case: its filter is only `mappings/**`,
`scripts/validate_id_label_correspondence.py`, `conf/id_label_targets.yaml` and
the workflow itself, so even a `mech_shared.yaml` edit — a file explicitly on the
6-file drift list — does not trigger the job there.

This is a PR-time hole, not an unguarded one: CultureMech's nightly
`vendored-fleet-audit.yml` still catches any divergence within a day. So the
failure mode is a vendored edit merging green and drift surfacing the next
morning against `main`, rather than drift going unnoticed. Fix is small — extend
each spoke's `trigger_paths` to cover the full vendored set, ideally by deriving
it from the same manifest `check_vendored_sync.sh` reads so the two cannot drift
apart in the way this item is literally an instance of. Note the irony worth
keeping: a guard against vendored-file drift was itself allowed to drift
per-repo.

Do this as one cross-Mech sweep (the `cross-mech-sync` skill), not three
independent PRs.

**Filed 2026-07-30**, one per affected spoke since the fix is per-repo:
MIM **#160**, CommunityMech **#280**, TraitMech **#184** (TraitMech's also covers
its missing `src/**` path). Keep them closed together — a partial sweep leaves the
invariant looking enforced where it is not.

Distinct from CommunityMech **#278**, which is the same invariant seen from the
other side: `check_vendored_sync.sh` exists only in the spokes, so there is no
canonical copy in the hub to diff the checker itself against. #278 is about *what
is compared*; the three above are about *when the comparison runs*. Fixing either
leaves the other open, though one PR per repo can reasonably close both.

## Adopt DisMech knowledge-gaps + datasets + QC dashboard (#7) — INFRASTRUCTURE DONE, content adoption uneven

All three phases of the plan in #7 have shipped across all four Mechs. Verified
directly against the working copies on 2026-07-30 rather than from the issue's
checkboxes, which lag:

- **Phase 1, knowledge gaps** — `mech_shared.yaml` carries the `Discussion`
  supertype plus `DiscussionKindEnum` / `DiscussionStatusEnum` in all four repos,
  and each root record has a `discussions` slot (`culturemech.yaml:433`,
  `mediaingredientmech.yaml:244`, `communitymech.yaml:1357`, `traitmech.yaml:243`).
  All four have an `app/discussions/` browser and both the `gen-discussions-data`
  and `knowledge-gap-scan` recipes.
- **Phase 2, datasets** — all four reference the canonical shared `Dataset`.
  CommunityMech migrated its local `AssociatedDataset` to it while keeping its own
  slot name (`associated_datasets:`, `communitymech.yaml:1335`), so a grep for a
  `datasets:` slot misses it; the migration did happen.
- **Phase 3, QC dashboard** — all four render `dashboard/index.html`.
- **Cross-cutting** — `mech_shared.yaml` is byte-identical across all four
  (md5 `3cf80648642fcd1f824529bc40c572a5`) and is one of the 6 files on the
  shared-reference drift check, which is exactly the pinning the issue asked for.

**What actually remains is content, not schema.** Records carrying `discussions`:
TraitMech 10, MIM 8, **CultureMech 0, CommunityMech 0**. The harness is wired up
in both zero repos but has never been run against the corpus. Next action: run
`knowledge-gap-scan` in CultureMech and CommunityMech and curate the first batch,
then **close #7** — the schema/tooling work it tracks is finished, and leaving it
open makes four `NEXT_TASKS.md` files point at a coordination issue that no longer
has coordination work in it.

Note: #7's own checklist is still entirely unticked. Tick it or close it; do not
use it as a status source.

## Cross-Mech web design review (#12) — PENDING, deferred items only

The umbrella review against the `dataviz` and `artifact-design` skills landed its
main themes across five sites (dark theme, `prefers-reduced-motion`, vendored d3
v7.9.0, data-table/CSV fallbacks, CVD-validated palettes, marker floors). The
per-repo issues are all still open and each holds the deferred remainder:
CultureMech #89, MIM #110, CommunityMech #199, TraitMech #151, ProteinTraitsMech #5.

Known-deferred items, from #12: TraitMech `graph.html` draws no edges and has a
redundant double filter; MIM's force-graph shows meaningless numeric axes and
diverges on the token system; CommunityMech's network legend lists interaction
types that are absent, and `community.html.j2` is stale; ProteinTraitsMech's
off-brand "Cayman" browser palette (rebrand deferred) and a 4-card landing page
against a 3-card spec; and toggle-time refresh of JS-read plot colors in MIM.

Two things to know before picking this up. **CommunityMech has since moved** —
its #268 now renders only the interaction types a community actually has, which
is the legend complaint, so re-check that item before working it. And
**ProteinTraitsMech is a fifth Mech that is not checked out locally** alongside
the other four; #12 is the only place in this repo that references it. Anyone
working the full sweep needs to clone it first.

#12 says "Code review of the PRs: in progress" — that status is from 2026-07-05
and should be re-established rather than trusted.

## Autonomy groundwork — first three pieces shipped 2026-07-31

Design and rationale in `docs/AUTONOMOUS_LOOPS.md`. What actually landed:

- **Weekly knowledge-gap scan** — `.github/workflows/knowledge-gap-scan.yaml`
  runs the deterministic scan across all four Mechs, Mondays 09:00 UTC, **no
  agent**, publishing triage packets as artifacts. It lives here rather than in
  each Mech because the scanner library is in this private repo while the Mechs
  are public: a public Mech's CI cannot check claw out, but claw's CI can check
  the Mechs out. Dependency direction decides placement.
- **`history/` provenance layer** — canonical schema `shared/history/history.yaml`,
  scaffolder `src/kg_microbe_history/`, piloted in TraitMech. See
  `shared/history/README.md`.
- **Skill filenames normalised to `SKILL.md`** fleet-wide (63 skills).

**Homebrew hardcodes: cleared 2026-07-31.** All 25 recipes now use `uv run
python`, which is what the rest of these justfiles already used — the Homebrew
lines were the outliers. Fleet-wide count of `/opt/homebrew/bin/python` is now
**0**, including two stray shebangs in CultureMech scripts.

Three things the sweep surfaced that were worth more than the path swap itself:

- **`python3` was the wrong target.** On this machine `python3` is miniforge
  3.13.12, not Homebrew 3.13.8 — different interpreters, different site-packages.
  Swapping to `python3` would have silently changed which packages resolve.
  `uv run python` is deterministic and identical locally and in CI.
- **`matplotlib` was an undeclared dependency in all four Mechs.** `kg_microbe_qc`
  imports it unconditionally, so every `gen-qc-dashboard` only ever worked because
  Homebrew's python happened to have it installed globally. Now declared in all
  four `pyproject.toml` files; all four dashboards verified rendering.
- **Ten recipes reach into claw** via `PYTHONPATH`. Each justfile now carries a
  `claw_src` / `claw_root` variable pair and a private `_require-claw` helper that
  fails loudly when the shared module is missing, replacing ten copies of inline
  bash. Verified the guard fires in all four repos.

`knowledge-gap-scan.yaml` was updated to `uv sync` per Mech to match. That is
heavier than the previous `pip install pyyaml` — CultureMech pulls a large tree —
and the first scheduled run is what will tell us whether any Mech's sync is too
slow or fragile for CI.

## Orchestration tooling — no known defects

State as of 2026-07-30, recorded so the next reconcile has a baseline:

- `.claude/workflows/dynamic-review.js` and the canonical
  `~/.claude/workflows/dynamic-review.js` are **byte-identical** (19,431 bytes).
  CLAUDE.md requires these stay in sync; they do. Re-check on every reconcile,
  because nothing enforces it automatically — that check is a human habit, and a
  candidate for a real CI job if it ever drifts.
- Both scheduled workflows (`cross-repo-validation.yaml`, `id-label-canon.yaml`)
  have run green every day from 2026-07-25 through 2026-07-30.
- The SSSOM builder hardening from **#13** (residual-cache guard + prune) and the
  three earlier URL/prefix fixes (**#3** / **#4** / **#5**) are all merged; no
  follow-ups were left open.

## Fleet state at last reconcile

Snapshot of the other four backlogs, so this file can be used as the entry point.
Each Mech's own `NEXT_TASKS.md` is authoritative for its detail.

- **CultureMech** — on `validate-media-recipes`, which holds a media-type schema
  axis plus an 11,088-record `composition_type` backfill; issue #146 tracks it.
  Note #146's own text has gone stale: the branch **is** on the remote, and the
  merge of `main` into it has been done and was clean. Also open: #145 (moving a
  record silently invalidates tracked derived artifacts), #142
  (`organism_culture_type` unset on 80% of records that have target organisms),
  #141 (curation scripts reflow whole records, burying the real change), plus
  **#150** and **#151** filed 2026-07-30 for the unfinished halves of the
  closed #118 and #116.

  **Three issues here are closed on GitHub but not finished** — #116, #118 and
  #138. In each case the PR body says explicitly that it does not close the
  issue, and the issue was closed anyway. #118 and #116 now have successor issues
  (#150 / #151); **#138's residue is still untracked** and needs someone who knows
  what it left behind. Do not read "closed" as "done" for those three.
- **MIM** — `main` is clean and its backlog was reconciled on 2026-07-30 in its
  own #158. Open: #148, #147 (macOS filename-casing corruption), #138, #137, #114,
  #110.
- **CommunityMech** — on branch `next-tasks-reconcile-0730` with open PR #275
  (its own reconcile) and open PR #274 (repairs `network-quality.yml`, which was
  invalid YAML and had failed every run for at least 15 runs, #272). Newest issue
  is #276, a GTDB grounding backfill: 140 records partially grounded, 72 with none.
- **TraitMech** — `main` clean apart from an uncommitted
  `data/traits/metabolism/cellulolysis.yaml` edit, which is the first repair of
  the fragmentation problem below, not a stray change. Open: #151 (design review),
  plus **#183** and **#184** filed 2026-07-30. Its METPO round-trip stays blocked
  on upstream minting
  ([berkeleybop/metpo#535](https://github.com/berkeleybop/metpo/issues/535)),
  with no upstream activity since 2026-06-16.

  **#183 is the largest untracked defect found in this reconcile.** 220 of 353
  causal graphs (62%) split into more than one connected component, and 1,264 of
  4,136 nodes (30%) are unreachable from their graph's largest component.
  `audit_causal_graphs.py` checks only dangling edges and fully-orphaned nodes,
  so none of this registers and the gate stays green. Verified independently from
  the hub, not taken from the backlog. Any connectivity check must land
  non-blocking first — at 62% it fails `just qc` on day one.
