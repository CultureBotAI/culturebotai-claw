---
name: unify-skills
description: Canonicalise a skill that several Mechs carry separately — pick the target from measured duplication, decide what is genuinely shared versus legitimately per-Mech, write the template with managed regions, declare it, and verify. Use when the fleet has copies of one skill that have drifted, or when a skill should exist in Mechs that lack it. NOT for installing an adapter into a Mech; that is a downstream mutation under the cross-repository checklist.
category: workflow
requires_database: false
requires_internet: false
version: 1.0.0
tags: [skills, canonical, fleet, templates, drift]
---

# Unify a skill across the fleet

Claw publishes canonical skill templates. A template owns marked regions; the
Mech owns everything outside them. That is what makes unification possible
without flattening the part worth having.

This skill is the loop that produces one. It encodes what the templates so far
cost to learn, and most of that is about what **not** to unify.

## 1. Pick the target from measurement

```bash
uv run kg-microbe-skills inventory
```

Read the verdict column, not the counts:

- **`duplicated`** — two or more repositories hold byte-identical copies. That is
  not agreement; it is a copy nobody has kept in sync. Strongest candidate.
- **`divergent`** — several carry the name, no two alike. Weaker on its own:
  divergence is sometimes correct, and step 2 decides.
- **`canonical`** — already managed. Skip.

Prefer high reach. A name three Mechs carry is worth more than one two carry,
and one carried by seven Mechs that all wrote it themselves is the most valuable
target in the list.

## 2. Read every copy before writing anything

Read all of them, in full. The four traps below were all found this way, and
none is visible from the inventory.

**The majority can be wrong.** `fetch-source` was byte-identical in three Mechs
and near-identical in a fourth; all four taught a hardened `curl` writing
straight to the destination. The fifth, ProteinTraitsMech, routed through a
validating helper — and was the only correct one. Canonicalising the majority
would have propagated a defect to seven repositories with claw's authority behind
it. **Ask which copy is right, not which is common.**

**Disagreement is sometimes correct.** `manage-identifiers` is carried by four
Mechs using three different schemes — minted sequential, upstream-first, external
CURIE with placeholder — and each is right for its corpus. The template
canonicalised the *invariants and the choice*, not the policy. If the copies
differ because the corpora differ, unify the layer underneath and leave the
policy alone.

**Do not assert what only some Mechs have.** The `id-label-correspondence`
template first described a LinkML schema binding in the present indicative,
generalised from the three adapters that had it. Four of the seven targets did
not, and claw *owns* that region — so four repositories would have been told
their schema does something it does not, with nowhere sanctioned to say
otherwise. Check every claim against every target, not against the copies you
read it in.

**A copy is right about itself and wrong about its neighbours.** Two of four
`manage-identifiers` copies asserted false things about siblings: that MIM mints
sequential ids (it has zero, deliberately) and that MIM is a single-file
collection (it is 2,952 files). Both were once true. Nothing checks a sentence
about another repository, so never write one — cite the check instead.

## 3. Decide the regions

Mark as canonical only what is true of every target and worth claw's authority:
rules, invariants, the reasoning behind a choice, failure modes.

Leave to the Mech: the commands it actually runs, its paths and prefixes, its
worked example, and which step of a rollout it is on. Flattening those leaves
adapters that look unified and have lost the only content worth having.

A useful test: if the sentence would be *false* for one target, or if a Mech
would reasonably want to edit it, it does not belong in a managed region.

## 4. Write the template

Add `src/kg_microbe_skills/canonical/<name>.md`. Substitutions available:
`{{ mech_key }}`, `{{ display_name }}`, `{{ github }}`, `{{ environment_variable }}`,
`{{ package_path }}`, `{{ schema_paths }}`, `{{ record_globs }}`.

Wrap each managed section:

```markdown
<!-- canonical:begin the-rule -->
...
<!-- canonical:end the-rule -->
```

Cite claw's own files in prose rather than as backticked paths. A bare path in a
rendered adapter resolves against the **Mech**, where it does not exist, and the
reference audit correctly reports it missing.

## 5. Declare it

Add an entry to `src/kg_microbe_skills/skills.yaml` under `canonical:`, with a
`capability` selecting the target Mechs and a `reason` that records the
measurement and the judgement — what the copies actually were, which one was
right, and what was deliberately left un-unified.

If no capability expresses what really decides who needs the skill, use a
stand-in and **say so in the reason**, referencing #316. Several already do.
Choosing a capability that merely sounds right selects the wrong Mechs.

## 6. Verify

```bash
uv run kg-microbe-skills catalogue                       # template appears, targets right
uv run kg-microbe-skills render --skill <name> --mech X  # for every target
uv run kg-microbe-skills check                           # references resolve
uv run --extra dev python -m pytest tests/test_skill_catalogue.py -q
```

Then check the splice refuses. Rendering against a Mech's existing adapter must
raise a `CatalogueError` naming the absent regions, not silently overwrite:

```python
from pathlib import Path
from kg_microbe_skills.catalogue import canonical_text, render_adapter
render_adapter(canonical_text("<name>"), "<mech>",
               existing=Path("<mech>/.claude/skills/<name>/SKILL.md").read_text())
```

## What this skill does not do

**It does not install anything.** `render` prints. Writing an adapter into a Mech
checkout is a downstream mutation: it goes through the cross-repository
checklist — resolve through `RepositorySettings`, confirm the worktree and its
GitHub origin, take the lock, dry-run, and get approval — as its own change.

## Related

- `kg-microbe-skills inventory` measures the duplication this acts on;
  `catalogue` lists what is already managed.
- `cross-mech-sync` is the procedure for landing a change across Mechs once
  there is something to land.
