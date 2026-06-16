---
name: cross-mech-sync
description: Propagate a change, fix, vendored file, or invariant across the four Mech repos (CultureMech / MIM / CommunityMech / TraitMech) safely and completely — establish ground truth from origin/main, pick the canonical version, sync the laggards via isolated git worktrees (never disturbing concurrent agents), verify, PR+merge, and keep NEXT_TASKS.md + the tracking issue in sync. Use for byte-identical vendored files, a data correction that spans source + derived artifacts + downstream repos, or any "this must land in more than one Mech" task. NOT for the data-pipeline sync (identifiers/CHEBI/KG matches) — that's cross-repo-sync.
category: integration
requires_database: false
requires_internet: true
version: 1.0.0
tags: [sync, cross-repo, cross-mech, vendored, byte-identical, worktree, pin, invariant, culturemech, mim, communitymech, traitmech]
---

# Cross-Mech Sync Skill

## Overview

A repeatable, **non-disruptive** procedure for landing the same change across the
Mech repos and leaving every copy + tracking artifact consistent. Use it whenever
a change must exist in more than one Mech, including:

- A **shared vendored file** that must stay byte-identical (e.g. the id↔label
  validator `scripts/validate_id_label_correspondence.py` and its two shared tests).
- A **data correction that fans out** — a wrong value in a source repo that also
  lives in derived artifacts (HTML pages, UMAP, SSSOM) and downstream repos
  (e.g. the boric-acid `CHEBI:33134`→`CHEBI:33118` fix: CultureMech YAML → MIM
  unified TSV → kg-microbe reviewed TSV + unified SSSOM + regenerated HTML/UMAP).
- A **convention/invariant** (a justfile recipe, a CI guard, a `NEXT_TASKS.md`).

For the standard *data-pipeline* sync (unified mapping, CHEBI backfill, KG-node
matches) use **`cross-repo-sync`** instead — that's a different job.

## The repos

| Mech | Path (relative to `culturebotai-claw/`) | GitHub | default branch |
|---|---|---|---|
| CultureMech | `../CultureMech` | `CultureBotAI/CultureMech` | `main` |
| MIM (MediaIngredientMech) | `../MediaIngredientMech` | `CultureBotAI/MediaIngredientMech` | `main` |
| CommunityMech | `../CommunityMech/CommunityMech` (nested!) | `CultureBotAI/CommunityMech` | `main` |
| TraitMech | `../TraitMech` | `CultureBotAI/TraitMech` | `main` |
| kg-microbe (downstream, not a Mech) | `../kg-microbe` | `CultureBotAI/kg-microbe` | `master` |

CLAUDE.md only documents the first three; **TraitMech is a real fourth Mech** —
always include it in "all Mech" sweeps. kg-microbe is downstream: touch it only
when the change genuinely flows there, and note its default branch is `master`.

## The five rules (learned the hard way)

1. **Ground truth = `origin/main`, never the working copy or NEXT_TASKS notes.**
   Working trees sit on other agents' feature branches; `NEXT_TASKS.md` entries
   drift from reality (one claimed "CommunityMech has no validator copy" long
   after it had been vendored). Read the real bytes:
   `git show origin/main:<path> | shasum -a 256`.

2. **Never switch a repo's branch to commit.** Repos routinely have concurrent
   agents mid-work (uncommitted tracked changes). Commit through an **isolated
   git worktree off `origin/main`** (see Workflow). Switching/​stashing their
   branch is the one thing that can wreck another agent's session.

3. **Pick the canonical version objectively.** For a byte-identical file, the
   canonical is the **majority** (2-of-3) and/or the copy **already pinned**.
   Sync the laggards *to* it — don't average or re-derive.

4. **Sync is incomplete until the derived artifacts are too.** A source fix that
   leaves stale HTML/UMAP/SSSOM is a half-fix. After the source change, sweep
   every repo for the old value and regenerate (or surgically correct) the
   generated outputs. `grep -rl "<old value>"` across each repo, excluding the
   legitimate cases (e.g. a vendored ontology snapshot where the id is correct).

5. **One coordinated change.** Pin/manifest edits must land in *every* copy in the
   same pass. Leaving one repo unpinned recreates the drift you just fixed.

## Workflow

### A. Establish ground truth

```bash
# For each repo, hash the shared file(s) on origin/main and compare.
for entry in "CultureMech:CultureBotAI/CultureMech" \
             "MediaIngredientMech:CultureBotAI/MediaIngredientMech" \
             "CommunityMech/CommunityMech:CultureBotAI/CommunityMech" \
             "TraitMech:CultureBotAI/TraitMech"; do
  repo="${entry%%:*}"; name=$(basename "$repo")
  cd "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/$repo" || continue
  git fetch origin -q
  for f in <PATHS...>; do
    h=$(git show "origin/main:$f" 2>/dev/null | shasum -a 256 | awk '{print $1}')
    echo "$name  ${h:0:16}  $f"
  done
done
```

Group by hash → the majority is canonical; outliers are the sync targets. `diff`
two copies to confirm the delta is benign (formatting/rename) before overwriting.

### B. Make the change in an isolated worktree (per laggard repo)

```bash
REPO=/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/<repo>
WT=/tmp/sync-<slug>
cd "$REPO" && git fetch origin -q
git worktree remove --force "$WT" 2>/dev/null || true
git worktree add -q "$WT" origin/main          # detached copy of main; live tree untouched
cd "$WT" && git checkout -q -b <branch>

# ... apply the change here: copy canonical bytes in, edit recipes, etc. ...
# e.g. sync a file to the canonical copy from a sibling repo:
#   (cd "$REPO_OF_CANONICAL" && git show origin/main:<path>) > "$WT/<path>"

git add <paths> && git commit -m "<msg>

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
git push -q -u origin <branch>
```

After pushing: `gh pr create -R <slug> --base main --head <branch> ...`, then
merge (below), then **always** `cd "$REPO" && git worktree remove --force "$WT"`.

### C. Verify before merge

- Vendored-file pin: `just verify-validator-pin` → all files `OK`.
- Tests: `uv run pytest <the synced tests> -q`.
- CI: `gh pr view <n> -R <slug> --json mergeable,mergeStateStatus,statusCheckRollup`
  → `MERGEABLE` / `CLEAN` and checks `SUCCESS`.
- Scope: `gh pr view <n> -R <slug> --json files` — confirm no stray files.

### D. Merge + clean up

```bash
gh pr merge <n> -R <slug> --squash --delete-branch
# verify: state MERGED, remote+local branch gone
git ls-remote --heads origin <branch> | grep -c <branch>   # expect 0
```

### E. Keep the bookkeeping in sync

- Update **`NEXT_TASKS.md`** in each affected repo (mark done / move out; keep the
  cross-Mech items consistent across the sibling files — they duplicate by hand
  and drift). Edit it inside the same worktree so it lands in the same PR.
- Comment + close the tracking issue (often in `culturebotai-claw`); record any
  **decision** made (e.g. "TraitMech deferred — net-new adoption, not a sync").

## The vendored byte-identical invariant (reference)

`scripts/validate_id_label_correspondence.py` + `tests/test_id_label_empty_adapter.py`
+ `tests/test_id_label_unknown_prefix.py` are vendored byte-identical across
CultureMech / MIM / CommunityMech and guarded by a pin **manifest**:

```just
VENDORED_IDLABEL_FILES := "scripts/validate_id_label_correspondence.py tests/test_id_label_empty_adapter.py tests/test_id_label_unknown_prefix.py"

verify-validator-pin:        # CI runs `sha256sum -c scripts/.validate_id_label_correspondence.sha256`
refresh-validator-pin:       # rebuilds the sidecar by hashing each VENDORED_IDLABEL_FILES entry
```

- The `.sha256` sidecar is a multi-line manifest; all three repos carry an
  **identical** sidecar (hash the sidecar itself to confirm: same → invariant holds).
- **`conf/id_label_targets.yaml` is intentionally NOT pinned** — it is per-repo
  (different adapters / targets / exceptions). Only the *concept* of
  `ignored_prefixes` stays consistent, not the file.
- To change a vendored file: edit it, run `just refresh-validator-pin` in **every**
  copy in one coordinated pass, commit the matching sidecar everywhere.
- **TraitMech** is not yet in the trio (no validator). Adopting it is a net-new
  task (vendor the files, author a TraitMech-specific conf for its trait-page
  surfaces, add the recipes + CI), then add it to `VENDORED_IDLABEL_FILES`.

## Worked examples (this is what "done" looks like)

- **claw#6 — extend the pin to the shared tests.** Ground-truth showed `.py` in
  sync but CommunityMech's two tests drifted (cosmetic). Synced them to the
  CultureMech/MIM canonical, adopted the `VENDORED_IDLABEL_FILES` manifest, regen
  sidecar → identical 3-line manifest across all three; CI enforces it. TraitMech
  decision recorded as deferred. (CommunityMech PR #151.)
- **Boric-acid `CHEBI:33134`→`CHEBI:33118`.** One wrong id (1H-phosphole, not boric
  acid) spanned 4 surfaces: CultureMech YAML (source) → MIM unified TSV →
  kg-microbe reviewed TSV + unified SSSOM (surgical row removal — the generator
  *seeds from its own output*, so a re-run wouldn't purge it) → regenerated
  CultureMech HTML/UMAP. Left the vendored ChEBI ontology snapshot (`data/kgm/`)
  alone — 33134 = 1H-phosphole is *correct* there. Lesson: trace every surface;
  distinguish the error from legitimate uses of the same id.

## Pitfalls

- **gh `--json files` caps at ~100 entries** — a "100" count on a big regen is the
  page limit, not the true count; check `git show --stat` for the real number.
- **Generators that seed from their own previous output** (kg-microbe's
  `consolidate_chemical_mappings.py`) won't purge a stale entity on a plain re-run
  — surgically remove it, or the bad row survives via union semantics.
- **Deterministic vs. churny generators.** Confirm UMAP/render uses a fixed
  `random_state` before committing a regen, or you commit pure noise. Watch for
  per-output wall-clock timestamps that diff every file (fix the generator, then
  force a clean rebuild).
- **Bare `python` in justfile recipes** fails outside the project env — recipes
  should use `uv run python`.
- **Don't commit unrelated dirty files** the worktree picks up nothing, but the
  live tree may have `uv.lock` / cache churn — stage only the paths you changed.
