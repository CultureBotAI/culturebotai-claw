# The Mech standard

What a repository must hold to in order to be a Mech, what it may reuse, and
what is nobody's business but its own.

This did not exist before 2026-08-30. It is derived from measuring the five
established Mechs — CultureMech, MediaIngredientMech, CommunityMech, TraitMech,
ProteinTraitsMech — not from deciding in advance what they ought to look like.
Every tier below carries the count it was derived from, so a reader can tell a
convention that actually holds from one that two repositories happen to share.

AntibioticMech and CellStructureMech are deliberately **excluded** from the
derivation: they are the repositories this standard is meant to judge, so
letting them vote on it would make the exercise circular.

> **Since this was derived**, CellStructureMech has joined the fleet manifest and
> the vendored-consumer registry (claw#247), which is Tier 1.12 — so the worked
> example below of a repository "conforming by accident of origin" now describes
> AntibioticMech alone. Joining also turned claw's `main` red, because admitting
> a consumer advances the canonical ref and invalidates every existing pin
> (claw#257): **adding a Mech to vendored governance is a fleet-wide re-pin**,
> which nothing in the model said and nothing checked. That is now the sharpest
> thing this document has to say about Tier 1.12.

> **How to read the counts.** `5/5` means every established Mech does this.
> `3/5` means three do. A count is evidence, not an argument — where the
> majority is wrong, this document says so and says which Mechs are right.

---

## Tier 1 — Universal

Present in all five. A repository without these is not a Mech; it is a data
repository that resembles one.

| # | Requirement | Evidence |
|---|---|---|
| 1.1 | An installed package at `src/<lowercase-name>/` containing `schema/`, and record-shaped data under `data/` | 5/5 |
| 1.2 | Records modelled in LinkML, with the schema in-repo | 5/5 |
| 1.3 | `schema/mech_shared.yaml`, **byte-identical** to claw's canonical copy | 5/5, md5 `3cf80648…` |
| 1.4 | `schema/history.yaml`, **byte-identical** to claw's canonical copy | 5/5, md5 `3742bc20…` |
| 1.5 | `curation_history` on every curated record, appended through `just new-history` | 5/5 — `new-history` is the only non-`default` recipe all five share |
| 1.6 | A `justfile` whose recipes are the repository's real interface; CI calls recipes, not inlined shell | 5/5 have `default` |
| 1.7 | `uv` with `pyproject.toml` and a committed `uv.lock` | 5/5 |
| 1.8 | Strict closed-schema validation, run in CI on every PR | 5/5 — `validate-strict.yaml` is the **only** workflow filename common to all five |
| 1.9 | A `tests/` suite run in CI | 5/5 (PTM reaches it through `just test`, not a literal `pytest` line) |
| 1.10 | `ruff` lint in CI | 5/5 |
| 1.11 | A `.claude/` directory carrying at least the repository's own skills | 5/5, 14–27 skill files each |
| 1.12 | Membership in claw's `src/kg_microbe_fleet/fleet.yaml`, and registration as a consumer in `vendored_artifacts.json` | 5/5 |

**1.12 is the one that makes the rest enforceable.** A Mech absent from the
fleet manifest is skipped by every fleet-wide audit, every workflow matrix, and
the vendored-sync check — silently, because "not a member" and "member that
passes" are indistinguishable from outside. Conforming to 1.3 and 1.4 today
without 1.12 means conforming *by accident of origin*, with nothing to keep it
true after the first divergent commit.

### On naming

Do not standardise on filenames. The same function is spelled `tests.yaml`
(CultureMech, MIM), `pytest.yaml` (TraitMech) and `checks.yml` (PTM). A
requirement here names a **function**; how a repository spells it is its own
business.

---

## Tier 2 — Sometimes reused

Shared by 2–4 of the five. Each is a real capability with a real cost. A Mech is
expected to **declare a decision** about each in the fleet manifest — `enabled`,
or `disabled`/`not_applicable` *with a reason* — rather than simply not have it.

| Capability | Count | Notes |
|---|---|---|
| `audit-writers` — every YAML-writing script declares dry-run/validate/history behaviour | 4/5 | Now shared as `kg-microbe-writers audit`, declared per Mech through the `writer_audit` capability. The four per-repo copies are still in place; removing them is #132 Phase 7's remaining work. |
| ID↔label correspondence checking | 4/5 workflow; vendored script in 5/5 | |
| `vendored-sync` — verify vendored artifacts against claw's pin | 4/5 | Absent in PTM, which also carries the most drift |
| QC dashboard (`gen-qc-dashboard`) | 4/5 | |
| Discussion export (`gen-discussions-data`) | 4/5 | |
| Knowledge-gap scan | 4/5 | |
| Research providers / Edison capture | 4/5 | `_edison_capture.py` vendored byte-identical where present |
| A generated site published from the repository | 3/5 build in CI; 4/7 track HTML | |
| `mypy` | 2/5 | Genuinely optional today |
| Declared source catalogue (`download.yaml`) | 2/5 enabled | |
| Page size/count budgets | 1/5 | Only PTM; tracked as claw#230 |

**The absence rule.** Tier 2 is where "we didn't get to it" and "this does not
apply to us" must be told apart, and prose cannot do it. Both become a manifest
declaration; only one becomes a reason. TraitMech curating traits and having no
ingredient corpus is `not_applicable`. A Mech that publishes a site and has no
budgets is `disabled`, and that is a backlog item, not a decision.

---

## Tier 3 — Rare and domain-specific

Present in exactly one Mech. **These are not gaps in the other four**, and a
new Mech should not adopt any of them without its own reason.

- CultureMech — ChEBI consistency, concentration plausibility, merged-YAML freshness
- MediaIngredientMech — SSSOM QC, evidence QC, round-trip QC, flat-coverage QC
- CommunityMech — KGX release, network quality, docs-currency
- TraitMech — canonical example taxonomy, PR shepherd, PR-checks-present, in-CI Claude review
- ProteinTraitsMech — page-size audit, reproducibility audit

The lesson from claw's Phase 6 is that a shared implementation is worth building
when two or more Mechs already have one to consolidate — and is a trap when
none do. Do not promote a Tier 3 item to Tier 2 on the argument that it *would*
be useful elsewhere.

---

## Where the new Mechs are ahead

Two practices in AntibioticMech and CellStructureMech are better than anything
the established five do, and should propagate **inward**:

**One executable definition of green.** Both route the entire gate through a
single `scripts/run_qc.py` — lint, docs statistics, provenance, tests,
closed-schema validation, corpus reproduction, site, corpus report — so a
passing local run and a passing CI run mean the same thing by construction. The
established five spread the same work across 4–12 workflow files, where local
and CI can and do diverge. This is the direction claw's Phase 5 thin-caller work
is independently converging on.

**`persist-credentials: false` on checkout.** Present in 1 of 1 workflows in
each new Mech; **0 of 48 workflows across all five established Mechs.** Without
it the job's `.git/config` keeps a credential any later step can read. Filed
against the fleet as claw#244.

A standard derived by majority vote would have recorded both of these backwards.
They are recorded here as requirements the established Mechs owe, not as
deviations the new ones should correct.

---

## Known fleet debt this standard does not paper over

- **`audit_writers.py` is still duplicated** in CultureMech,
  MediaIngredientMech, CommunityMech and TraitMech. A shared
  implementation now exists in claw (#261); the copies remain until they are
  removed. Measuring them (#260) showed the drift was not stylistic: a script in
  this fleet writes YAML five ways, and **no copy detects more than three**. The
  shared version gains 15 writers the copies miss and drops 25 rows that are not
  writers. ProteinTraitsMech's file shares the name and nothing else, and is
  deliberately out of scope.
- **Vendored artifacts have drifted** where the sync check is absent or not
  enforced: MediaIngredientMech on 3 artifacts, ProteinTraitsMech on 2.
- ~~**Manifest `reason:` strings assert facts nothing checks** (claw#236).~~
  Fixed: a reason now declares the paths it asserts about and in which
  direction, checked against the repository's `origin/main` in both directions.

A new Mech should not replicate any of these to "match the fleet".

---

## Adopting the standard in a new repository

In dependency order, because each step makes the next enforceable:

1. **Join the fleet manifest** (1.12) — declare `package_path`, `schema_paths`,
   `record_globs`, and a decision for every Tier 2 capability.
2. **Register as a vendored consumer** and pull the artifact set, so 1.3/1.4
   stay true rather than merely being true today.
3. **Adopt `history.yaml` and `just new-history`** (1.4, 1.5). A repository with
   `curation_history` in its records but no canonical history schema has the
   data without the contract that governs it.
4. **Wire the remaining Tier 1 gates into CI** (1.8–1.10).
5. **Declare, do not silently omit, each Tier 2 capability.**

---

*Derived 2026-08-30 from the five established Mechs at their then-current
`main`, and re-checked 2026-08-31. The counts are reproducible: they come from
each repository's tracked files, `justfile` recipes, `.github/workflows/`, and
claw's `vendored_artifacts.json`.*

*They are also prose, and prose about other repositories rots — the one-day
re-check already moved two of them (workflow count 46 → 48, skill files 14–31 →
14–27) because MediaIngredientMech gained workflows and lost a skill. Nothing
checks them, which is the same gap #236 closed for capability reasons and which
claw#278 proposes closing here. Re-derive rather than trust this document.*
