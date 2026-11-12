# MIM Mapping Semantics

This document is the authoritative reference for what the predicates in
`mappings/ingredient_mappings.sssom.tsv` actually mean, why MIM uses a
**registry/identity row pattern** alongside ontology mappings, the most common
mistakes a curator can make, and what to do when CI rejects a row.
Section 7 applies the same identity rules to ingredient causal graphs: what may
anchor a graph, how a graph reaches the species a cell actually meets, and when
it may link to a record in another Mech.

It is written for a curator who has never read the kg-microbe code. You should
not need to look at any other repository to understand the rules. Where a rule
is enforced by the SSSOM validator (`scripts/validate_sssom_invariants.py`),
the rule's identifier (Rule A, B1, B2, B3, B4, D) is given inline so you can match
a CI failure to the section that explains it.

> **Status of validator rules**: Rules A, B1, B2, B3, B4, and D are all
> implemented in `scripts/validate_sssom_invariants.py` and enforced by
> CI. Rule B1 is strict-by-default (a missing registry row contributes
> to exit-2). Rule B4 silently skips per-prefix when the kg-microbe
> ontology transform file isn't checked out locally — typical in CI —
> and is therefore best-effort there. Sections below describe each
> rule's contract.

The SSSOM file has the following columns; every example below uses these:

```
subject_id  subject_label  predicate_id  object_id  object_label  object_source  mapping_justification  source  mapping_date  confidence  comment  other  validation_method
```

A "row" is one tab-separated line in that file.

---

## Permanent record identity

Every ingredient has a required opaque `mim_id`, such as `MIM:0000001`.
SSSOM subjects and current MIM record joins use that ID. The record's
`identifier` remains its existing external, registry or unresolved mapping
value; `ontology_mapping` remains a separate scientific assertion. Preserve
former valid identifiers in `legacy_identifiers`. An identifier disproved for
this particular owner must not remain a resolving alias: the reviewed native
curation-successor route (#1373) removes that assertion while retaining its exact
beforeimage, declared delta, historical reviews and attributed curation history.
This is no global retirement of the external term. Genuine filename/registry
aliases remain; false raw labels retain native `REJECTED_LABEL` provenance.
Mapped, unmapped and rejected mapping states all retain permanent record IDs.

IDs come from the append-only mint registry and lifecycle ledger; a rename,
label correction, mapping update or directory move never re-mints the record.
Filenames are kept. Retired or merged IDs remain registered and resolve to
an active replacement. See [stable MIM IDs](docs/STABLE_MIM_IDS.md).

The named MIM subjects in historical worked examples below (for example
`MIM:Vermont_Soil`) are legacy aliases, not a current ID-allocation rule.
Resolve them to the record's numeric `mim_id` before constructing a new row.
Do not rewrite earlier releases or their review receipts. Neither allocating
an ID nor resolving an alias grants mapping or scientific-review authority.

### Reviewed source identities (candidate contract #1299)

The separate `reviewed-source-bindings-v1` product can assert an original
source entity `skos:exactMatch MIM:<seven-digit-id>` only after explicit,
independent scientific review of the complete source entity, every captured
occurrence and the current owning record. This is a source identity assertion,
not an ontology grounding assertion. Labels, retained aliases, a shared
external identifier, a minted MIM ID or a supported external row alone never
authorize it. A source ID reused across conflicting preparations cannot gain
multiple global identities by changing labels; withhold it until its scope is
resolved. The current contract covers all occurrences of one source ID and
does not invent occurrence-level subjects.

A reviewed MIM-only source identity may be supported while its owner's external
mapping remains `UNMAPPED`. Do not fabricate an ontology target, change that
status to `MAPPED`, or grant other claims approval. Preserve unresolved,
ambiguous and held source cases, along with all original occurrence payloads,
in the withheld accounting. Each justified external mapping remains a separate
MIM-to-external assertion with its original predicate, full row, evidence and
SUPPORTED/WITHHOLD disposition. The canonical SSSOM owner rules and historical
identity-projection proofs remain unchanged.

Consumer spelling `MIM.ingredient:<seven-digit-id>` expands to the same
`https://culturebotai.github.io/MediaIngredientMech/ingredient/MIM_` URI as
`MIM:`. Preserve original CURIEs in provenance. Never infer `subclass_of` from
source identity or from broad/close/narrow mappings; typed form relations and
true subsumption each need their own evidence. A supported candidate is not
production publication permission. See [source identity candidates](docs/SOURCE_IDENTITY_CANDIDATES.md)
for the native review, complete-accounting and consumer validation contract.

## 0. Grounding quality and identity predicates are independent

`ontology_mapping.mapping_quality` records how the ontology grounding was
established or how closely the stored label fits the target. It does **not**
directly select the predicate on the row pointing to the record's own primary
`identifier`:

- a primary-label resolution is `EXACT_MATCH`;
- a resolution through a unique ontology synonym is `SYNONYM_MATCH`;
- a resolution established by an explicit CAS-to-ontology lookup is
  `CAS_RN_LOOKUP` when the record's CAS RN uniquely resolves by ontology xref
  to that target;
- ambiguous, circular, or conflicting evidence must be reviewed rather than
  promoted to one of those grades.

When a mapping was established by CAS, keep `CAS_RN_LOOKUP` even if the label
also happens to equal a primary label or synonym. The lexical agreement is
useful supporting evidence, but replacing the CAS grade with a lexical grade
discards the method provenance. Merely having a CAS field is not sufficient:
the lookup must be recorded in curation history/evidence and the current CAS
must agree uniquely with the current target. A CAS shared by multiple ontology
entities does not, without additional independent evidence, identify which one
was selected and therefore requires review. CAS provenance also does not
override an identity conflict in the labels: concentration-qualified
preparations and incompatible hydrate forms must be re-grounded rather than
having their existing target merely re-graded. Explicit counterion, salt, or
oxidation-state conflicts likewise require identity review, as do explicit
racemate/enantiomer or cis/trans qualifiers that disagree with an unspecified
or different target. A CAS xref on the current target is evidence to examine,
not permission to erase the conflict.

`match_level` is a separate, lower-level description of string processing
(`EXACT`, `NORMALIZED`, `FUZZY`, and so on); it does not replace the evidence
contract above.

Rule D then applies independently: a row whose object is the record's own
primary identifier is an identity row and must use `skos:exactMatch`. Thus a
record graded `SYNONYM_MATCH` or `CAS_RN_LOOKUP` can—and normally does—publish
an own-identifier `skos:exactMatch` without contradiction (#317, #438).

---

## 1. Predicate semantics

MIM uses four [SKOS](https://www.w3.org/2004/02/skos/) mapping predicates.
Their meanings are **not interchangeable** — picking the wrong one corrupts
the downstream graph. Each predicate has a precise behavioral contract that
both producers (the claw builder, human curators) and consumers (kg-microbe's
`consolidate_chemical_mappings.py`, KGX exports, CommunityMech joins) rely on.

### `skos:exactMatch`

> **MIM:X and Y have reviewed matching chemical/material scope.
> Canonical ID replacement follows the applicable release profile.**

For `MIM:Glucose skos:exactMatch CHEBI:17234`, MIM's reviewed identity
policy permits using the target for that scoped ingredient concept.
`skos:exactMatch` itself is not `owl:sameAs` and does not make a source
record, product preparation or occurrence interchangeable in every context.
The [ingredient scope profile](docs/INGREDIENT_SCOPE_PROFILE.md) makes scope
and identity authorization explicit; source-specific product detail and
registry history remain separately owned claims.

Use `skos:exactMatch` when:

- The MIM ingredient and the ontology term are the same chemical/material at
  the same level of specificity (e.g. `MIM:Glucose` ↔ `CHEBI:17234 "glucose"`,
  `MIM:Sodium_chloride` ↔ `CHEBI:26710 "sodium chloride"`).
- You are emitting a **registry/identity row** (see Section 2), pairing a
  `MIM:<seven-digit-id>` subject with its `kgmicrobe.{ingredient,compound}:<slug>`
  primary id.

Do **not** use `skos:exactMatch` when:

- The ontology term is a parent/broader category and the MIM ingredient is a
  more specific child (use `skos:broadMatch`).
- The two terms refer to similar but distinct entities (use `skos:closeMatch`).

### `skos:closeMatch`

> **MIM:X and Y are similar but not identical. DO NOT substitute one for the
> other in a graph; the relationship is informational.**

If `MIM:X skos:closeMatch Y` is present, a consumer may surface the link
to a human (e.g. "see also Y") but **must not** merge the two nodes,
re-route edges, or treat them as the same identity.

Use `skos:closeMatch` when:

- Two ingredients are related but not at parent/child level — near-synonyms
  whose biological roles diverge, or a record retaining a related term for
  human reference.
  **Not** for hydration states or stereoisomers where a specific term exists:
  Section 3 requires those to take their own identifier rather than a weakened
  predicate against the parent.
- You want to record a related ontology term for human reference without
  asserting any formal subsumption.

Do **not** use `skos:closeMatch` as a "soft exactMatch" when you are unsure.
If you are unsure, the correct action is to leave the row out and flag the
ingredient for review, not to weaken the predicate.

### `skos:broadMatch`

> **MIM:X is a form of Y, or a kind of Y (Y is the closest broader term).
> Used to anchor MIM records to OBO parents. Downstream consumers MUST emit
> this as `biolink:broad_match` — NOT as `biolink:subclass_of`, and NEVER as
> identity (#245).**

`skos:broadMatch` is a sub-property of `skos:broader`, and `A skos:broader B`
means **B is broader than A**. So `MIM:Vermont_Soil skos:broadMatch
ENVO:00001998` reads "soil is broader than Vermont Soil" — which is the
intent. MIM published `skos:narrowMatch` for this until #390; that is the
inverse relation, because `skos:narrowMatch` is a sub-property of
`skos:narrower` and asserted the OBO parent was *narrower* than the MIM
record. The grade name and the predicate still agree: a record graded
`NARROW_MATCH` is narrower, therefore its ontology term is broader.

This predicate is **asymmetric**: substitution is only legal in one
direction (specific → general for inference like "Vermont Soil is soil"),
and even that direction is only valid for broader-than reasoning, not
identity. The MIM child and the ontology parent are **different graph
nodes**. The row does not say *which* broader-than relation holds — strict
subclass, salt of, hydrate of, solution of, racemate of — and that is why it
must not be projected as `subclass_of`; see "The parent anchor means
'form of'" below.

Use `skos:broadMatch` when:

- The MIM ingredient is more specific than any available ontology term
  and you want to anchor it to the closest parent. Example: there is no
  CHEBI/ENVO term for "Vermont Soil" specifically, so `MIM:Vermont_Soil`
  broadMatches `ENVO:00001998 "soil"`.
- You are asserting that Y is the closest broader term, not identity. The
  parent term retains its own identity; the MIM subject does not collapse
  into it. A salt anchored to its parent acid, a hydrate anchored to its
  anhydrous compound and a solution anchored to its solute are all correct
  uses (Section 3, step 2).

Do **not** use `skos:broadMatch` when:

- A more specific ontology term exists. Find that term and use
  `skos:exactMatch` instead.
- The MIM ingredient is a sibling of the ontology term, not a child.
- The subject has no validated identity basis (Section 2). Rule B1 requires
  either the complete active permanent-owner/mint/lifecycle proof or the
  applicable historical filename/registry identity row. Neither branch grants
  scientific support to the asymmetric mapping.

### `skos:narrowMatch`

> **Inverse of broadMatch. MIM:X is broader than Y; Y is a form of, or a
> kind of, MIM:X. Consumers emit `biolink:narrow_match`, not a reversed
> `subclass_of` (#245).**

Used rarely in MIM, since the typical pattern is "MIM ingredient → OBO
parent" (i.e. broadMatch). The semantic guarantee is symmetric to
broadMatch: asymmetric, closest-broader-term only, not identity. If you find
yourself reaching for `narrowMatch`, double-check that the relationship
really runs broad-to-narrow in the direction the row claims, and is not a
mislabeled `broadMatch`.

The corpus published **0** `skos:narrowMatch` rows after the #390 flip, so a
new one is worth a second look.

---

## 2. Registry/identity row pattern

Permanent numeric MIM subjects have an identity independent of external
grounding (#1371). Rule B1 accepts an exact current active MAPPED owner only
after validating the complete owner inventory, immutable mint/lifecycle ledgers,
subject label and permanent namespace expansion. It does not synthesize a
filename-derived handle or claim an external exact match. A missing, ambiguous,
inactive, mismatched or incomplete permanent proof fails closed. Legacy subjects
retain their existing filename/registry requirement; Rule B5 and all external
scientific gates still apply. See [the identity contract](docs/STABLE_SSSOM_IDENTITY.md).

Where an actual curated registry identity exists, MIM retains two **independent
kinds of mapping rows**:

1. **Ontology row** — `MIM:<seven-digit-id> skos:broadMatch <ENVO|CHEBI|FOODON|…>:<id>`
   anchors the MIM child to its OBO parent. The object_id is an external
   ontology term.
2. **Registry/identity row** — `MIM:<seven-digit-id> skos:exactMatch
   kgmicrobe.{ingredient,compound}:<slug>` declares that the MIM subject
   has its own primary id in the kg-microbe namespace. The object_id is a
   first-class kg-microbe CURIE.

The registry row remains required for the legacy B1 branch. A permanent subject
with the complete validated identity proof does not require a made-up registry
sibling. The native builder retains an actual curated registry primary as its
own exact row; it must never select a competing namespace or mint a new handle
merely to satisfy this invariant. An existing registry row remains the channel
for that particular kg-microbe identity assertion, separate from the permanent
MIM owner and reviewed ontology mapping. MIM-only source output is valid when
no reviewed external match exists; ordinary source and release gates still apply.

### Historical worked example: `MIM:Vermont_Soil`

`MIM:Vermont_Soil` is one of many soil-source ingredients in the MIM
data set. There is no ENVO term for Vermont soil specifically; the
closest parent is `ENVO:00001998 "soil"`. Vermont_Soil is mapped using
**two rows** in `mappings/ingredient_mappings.sssom.tsv`:

```tsv
subject_id      subject_label  predicate_id      object_id                          object_label  object_source  mapping_justification        source                                                                                                          mapping_date  confidence  comment
MIM:Vermont_Soil  Vermont Soil  skos:broadMatch  ENVO:00001998                       soil          obo:envo.owl   semapv:ManualMappingCuration  MIM:cbclaw_envo_promotion|MIM:specificity-loss-review (mint_kgm_ingredient)|MIM:curator=auto_classify_ingredient_type  2026-05-02    0.9
MIM:Vermont_Soil  Vermont Soil  skos:exactMatch   kgmicrobe.ingredient:vermont_soil  Vermont Soil  kgm:ingredient  semapv:ManualMappingCuration  MIM:cbclaw_envo_promotion|MIM:specificity-loss-review (mint_kgm_ingredient)|MIM:curator=auto_classify_ingredient_type  2026-05-02    0.99        Registry/identity row preserving kgmicrobe.ingredient:vermont_soil alongside parent ENVO:00001998.
```

What the two rows together say:

- "Vermont Soil **is a kind of** soil" — the broadMatch row.
- "Vermont Soil **also has a kg-microbe primary id**, namely
  `kgmicrobe.ingredient:vermont_soil`, distinct from the parent
  `ENVO:00001998`" — the registry row.

### Why both rows are required

Imagine the registry row were missing — only the broadMatch row exists.
A downstream consumer that calls `find_chebi_by_name("Vermont Soil")`
walks the SSSOM by `subject_label`, finds the broadMatch row, and
returns its `object_id`: **`ENVO:00001998`** (the parent "soil"). The
consumer has now silently substituted the parent for the child. Every
recipe that uses Vermont Soil will be indexed against the generic
"soil" node, the Vermont-specific identity is lost, and any downstream
graph join treats Vermont Soil and (say) Cape Cod Soil and Amazon
Rainforest Soil as the same node. This is exactly the bug Codex
adversarial review #558 round 3 flagged.

With the registry row present, the same consumer call resolves to the
exactMatch row first and returns `kgmicrobe.ingredient:vermont_soil` —
the child's own primary id. The broadMatch row remains separately typed.
Subclass inference needs genuine independently reviewed is-a evidence; salts,
hydrates, solutions and racemates are not automatically subclasses.

### Naming convention

A `kgmicrobe.*` mapping target retains its own historical semantic slug.
It is not derived from the numeric MIM subject. Locate the current record by
`mim_id` and use its preserved mapping identifier and the applicable scientific
mapping rule. For example, the historical alias `MIM:Vermont_Soil` can lead to
a permanent MIM ID whose local mapping remains
`kgmicrobe.ingredient:vermont_soil`; never mint `kgmicrobe.ingredient:0000001`
from a record's numeric suffix.

For new local mapping targets, slug normalization remains lowercase,
underscore-separated, with no special characters. The `ingredient` vs `compound` namespace split mirrors the
type assigned by the auto-classifier (`scripts/classify_ingredient_type.py`
in claw): pure compounds use `kgmicrobe.compound:`, complex/biological
materials use `kgmicrobe.ingredient:`.

---

## 3. Identity granularity — one record per substance

Section 2 says how to express "MIM's thing is more specific than the ontology's
thing". This section says **when** that applies, and settles a cluster of
questions that were being answered case by case: hydrates, salts, stereoisomers,
two records sharing an id, and one substance under two ids.

### The rule

> **One MIM record per distinct substance. A record's `identifier` is the most
> specific stable id that denotes *that* substance. Never express a more
> specific thing by sharing a broader term's identifier.**

### What counts as "a distinct substance": orderability

MIM is a **practically oriented** resource. Its consumers are building growth
media, so a record should denote **a specific chemical someone can order** —
and where the sources disagree about which form that is, **pick one by
convention** rather than splitting the record or retreating to a generic term.

**But procurement detail does not live in the identity.** Refined 2026-08-18,
after the first version of this rule pushed a record onto `aldehydo-` terms
purely because ChEBI hangs the commercial CAS there:

* **the `identifier` optimises for how the node READS in the knowledge graph** —
  MIM is the naming authority there, so prefer the term a person would recognise;
* **the purchasable form goes in `supplied_form`** (name, `cas_rn`, form,
  supplier, catalogue number), which is multivalued because one ingredient is
  legitimately buyable in several forms;
* **the CAS-RN is published as a synonym**, so it stays findable on the node
  without being its name. `scripts/publish_cas_as_synonym.py` writes `CAS:<rn>`
  into the SSSOM `other` column, which kg-microbe splits into synonyms for
  symmetric rows and carries into KGX.

  **`CAS:<rn>` there is a display string, not a CURIE (#410).** The uppercase
  prefix is deliberate and does not match the `cas:` declared in the mapping
  set's curie_map or used by the 255 `cas:`-prefixed `object_id`s. `other` is a
  free-text, pipe-separated synonym field — every entry in it is a name, and a
  consumer that tries to expand one against the curie_map is reading the column
  wrong regardless of case. The prefix exists so the number is self-describing
  as a *label*: a bare `9004-32-4` is indistinguishable from a catalogue code or
  a concentration once it is sitting in a synonym list. Lowercasing it to `cas:`
  would make it look expandable, which is the opposite of what is wanted.

So "map to what you can order" is about **not retreating to a generic term**, not
about letting a catalogue decide the label.

Worked example (#394). `Carboxymethyl cellulose` has four source occurrences and
they do not agree: two write it plain (KOMODO 1111, DSMZ 1111) and two write
"sodium salt" (JCM 1052, DSMZ 1684) — and DSMZ 1111's own preparation note
specifies the sodium salt anyway. Upstream, CultureBotHT's `compounds_to_cas.csv`
already maps both the plain and the sodium name to the same CAS. The record
resolves to **CHEBI:234035** because it carries `cas:9004-32-4`, the product on
the shelf; the plain term `CHEBI:85146` carries `cas:9000-11-7`, which is a
different purchase. Here identity and orderability agree, so nothing is in
tension — where they do NOT agree, identity follows readability and
`supplied_form` records the purchase.

**This does not license collapsing genuinely different products.** A hydrate and
its anhydrous form have different CAS numbers, different formula weights, and are
ordered separately — they stay separate records, and the rest of this section
governs them. Orderability breaks ties about *which term names one purchasable
thing*; it does not merge two things a curator would buy from different catalogue
lines.

**The counterweight is mandatory: keep the detail.** Conflating is about the
record's *identity*, never about discarding information. Every raw form stays a
synonym, so `label_index` still answers for the plain string and the salt string
alike, and the SSSOM keeps its asymmetric rows to the broader terms. A record
that conflates without preserving its synonyms has lost data, not simplified it.

**A reviewed non-name is not a raw form.** When an upstream enrichment proposes
a label that is not an identity-bearing name for the record, retain the text and
its source as a synonym entry typed `REJECTED_LABEL`. This is a provenance-only
disposition: it must not resolve through `label_index`, appear in searchable
synonym exports, or enter the SSSOM `other` column. An upstream
`skos:closeMatch`, `skos:broadMatch`, or `skos:narrowMatch` label must likewise
not be promoted to a synonym by discarding its predicate. The rejected entry is
kept precisely so the same enrichment candidate cannot silently return later.

**Owned-name exclusivity at export (#669).** Classify published `other` tokens
as **KEEP**, **SUPPRESS**, **DROP** or **MERGE**. KEEP leaves an otherwise
admissible token unchanged. SUPPRESS omits a token whose preferred name belongs
to another resolved record, preserves its sourced YAML synonym and identity,
and records one subject/token pair in `mappings/suppressed_aliases.tsv` with
credited owners and provenance. Preferred-name ownership takes precedence over
another record's synonym; the resolving preferred owner comes first in
`label_index`. SUPPRESS is an export decision, not a finding that the source
synonym is scientifically false. DROP and new `REJECTED_LABEL` dispositions
require cited claim-specific evidence; preserve an existing rejected YAML label
and its original source as provenance. A generated-only token need not be
invented as a YAML synonym to document its DROP. MERGE requires a source-backed
same-substance and supplied-form review under this section; a name collision or
shared parent ID is insufficient. During the approved staged rollout associated
with #669 and the replacement of #912, explicitly deferred Rule K baseline
obligations retain their canonical tokens and allowances. They are unresolved
obligations, not scientific approvals or completed suppressions, and must not
appear in the canonical sidecar until actually suppressed. The policy marker
identifies the sidecar contract; it does not declare a staged canonical file
globally free of owned-name collisions. Batch reports identify the exact scope.

Sharing the parent's id is the identity-collapse bug of Section 2, arriving by a
different route. `MgSO4·7H2O` mapped to `CHEBI:32599 magnesium sulfate` does not
say "a hydrate of magnesium sulfate"; it says "this **is** magnesium sulfate",
and every downstream join then treats 246.47 g/mol and 120.37 g/mol as one node.
Formula weight is exactly what a medium recipe depends on.

The contrast is in the data: `MgSO4 x 7 H2O` sits on `CHEBI:31795 magnesium
sulfate heptahydrate` and is **correct** — a specific term existed and was used.
`MgSO4·7H2O` is the same substance on the generic term, and is the defect.

### Decision procedure

Work down the list and stop at the first that applies.

1. **An ontology term denotes exactly this substance** — including its
   hydration, salt and stereochemical state. Use it: `identifier` = that term,
   `skos:exactMatch`, one row.
   `Sodium glutamate monohydrate` → `CHEBI:232425 monosodium L-glutamate hydrate`.

2. **No exact term, but the substance has its own CAS.** `identifier` =
   `cas:<its own CAS>`, `skos:broadMatch` to the nearest ontology parent, plus
   the mandatory registry row (Section 2, Rule B1).
   `Sodium hypophosphite monohydrate` → `cas:10039-56-2`, broadMatch
   `sodium hypophosphite`. The parent row says the anhydrous compound is the
   nearest broader term; it does not claim the hydrate is a subclass of it
   (#245).

   The registry row's `kgmicrobe.*` CURIE is **not a competing identifier** — it
   is the kg-microbe-namespace handle for the same MIM subject, required by
   Rule B1 and emitted by the claw builder. "One substance under two
   identifiers" in the table below means two *ontology/registry-of-record* ids,
   not the subject's own registry handle.

   **This is already the established pattern**: 34 hydrate-labelled subjects
   carry `cas:` exactMatch plus a parent broadMatch plus the Rule B1 registry
   row. Note that a further **22** `cas:`-identified hydrate records have no
   parent row and no registry row, and become non-compliant with this step the
   moment it lands — they are a backlog, not counter-examples.

3. **No exact term and no CAS.** Mint `kgmicrobe.compound:<slug>` (pure
   compounds) or `kgmicrobe.ingredient:<slug>` (complex/biological materials),
   `broadMatch` to the nearest parent, plus the registry row.

4. **The label is genuinely under-specified and an unspecified-sense parent term
   exists** — *and the record carries no independent evidence of which specific
   sense it is*. Then the label denotes the unspecified sense: use that term
   with `exactMatch`, and do not reach for a specific child. A bare `arabitol`
   with no locant is `CHEBI:22605 arabinitol`.

   **The evidence escape hatch is the point, not an exception.** MIM's existing
   `Arabitol` record is grounded to `CHEBI:18403 L-arabinitol` and that is
   correct: it carries `cas 7643-75-6` (ChEBI's own xref for the L-term, present
   from the record's `CREATED` event, so not derived from the mapping) plus five
   independently-swept L-form synonyms. It uses `closeMatch`, which asserts no
   identity. A short label does not override record-level evidence — that is why
   #230 closed as premise-disproven. Apply this rule to a label with *nothing
   else attached*.

5. **The label is under-specified and only specific terms exist.** Emit **no
   mapping row** and set `mapping_status: AMBIGUOUS`. Section 1 is explicit that
   `closeMatch` is not a soft `exactMatch` for when you are unsure — if you
   cannot tell which term is meant, the row must be left out and the record
   flagged, not weakened.
   `2-tetrachloroethane` reaches both `CHEBI:34024` and `CHEBI:36026` and gets
   neither.

### Protonation state (bare anion labels)

Steps 1–5 decide *sense*: hydration, salt form, stereochemistry, locants. They do
not decide **protonation**, and a bare anion label (`Fumarate`, `Aspartate`,
`Succinate`) forces that choice. The rule:

> **Read the parent term's definition.** If it says the anion is obtained by
> deprotonation of **"at least one"** carboxy group, the term is *deliberately*
> protonation-agnostic — it already covers the mono- and di-anion, so a bare
> label belongs on it. **Stay.** If the parent carries no such definition and has
> `X(n-)` children, it is merely unspecified — **descend** to the species present
> at growth-medium pH, following the sibling precedent.

The distinction is not visible offline: the local `chebi.db` carries **no
definitions**, so this test requires the live ChEBI/OLS4 entry.

Worked both ways:

| record | parent | definition | outcome |
|---|---|---|---|
| `Malate` | CHEBI:25115 | "…deprotonation of **at least one**…" | stay |
| `Succinate` | CHEBI:26806 | same | stay |
| `Azelaate`, `Glutarate`, `Oxalate` | — | same | stay |
| `Aspartate` | CHEBI:132943 | **none** | descend → `CHEBI:29995 aspartate(2-)` |
| `Ascorbate` | CHEBI:22651 | — | stay: no `X(n-)` child exists at all |
| `Protocatechuate` | CHEBI:36241 | — | stay: already the −1 anion, nothing below |

`Aspartate` descends on the same evidence its sibling `Glutamate` did — the
family precedent is `CHEBI:29987 glutamate(2-)` — and because 30 bare `-ate`
labels in this corpus sit on charged terms while only the "at least one" group
does not.

**For a salt, the `broadMatch` parent follows the label**: where the label says
"…Acid sodium salt" the parent is that acid, where it names a neutral compound,
that compound. This avoids the acid-vs-anion choice entirely. Only reach for the
anion when ChEBI has no acid term — and check that it really has none: the
earlier example here, `2-oxobutyric acid sodium salt` → `CHEBI:16763
2-oxobutanoate`, rested on the claim that ChEBI lacked the acid, but
`CHEBI:30831 2-oxobutanoic acid` exists, and the record was re-anchored to it
(#312).

### What this decides

| Symptom | What it means | Action |
|---|---|---|
| Two records share one identifier | Same substance, or one is more specific | Same → merge. More specific → give it its own id per 1–3. |
| One substance under two identifiers | One of them is wrong | Pick by the precedence in 1–3; re-ground the other. |
| A hydrate/salt sits on the anhydrous/free term | Specificity collapsed into the parent | Step 1 if a specific term exists, else step 2. |
| One label resolves to several identifiers | Legitimate shared synonym, or a real duplicate | If the records are the same substance it is a duplicate — merge. If not, resolve via `docs/data/label_index.csv`: **take the first row for that label** and use its `identifier`. Rows are ordered MAPPED before non-MAPPED, then `preferred_term` before `synonym`, so the first row is the best available answer. That settles 18 of the 87; the rest are synonym-vs-synonym and need a curation decision (#232). |

## What the predicate does downstream (kg-microbe, priority 11)

Read this before choosing a predicate. It is not only a statement about meaning
— it decides what happens to the ontology term in the knowledge graph.

kg-microbe consumes this file as the **authoritative** ingredient-mapping source
(`.claude/skills/chemical-mapping/SKILL.md`, priority 11), syncing it straight
from this repo as a sibling checkout. Its rule:

> symmetric matches (`skos:exactMatch`, `skos:closeMatch`) **overwrite the
> canonical name** with MIM's `subject_label`; asymmetric
> (`narrowMatch`/`broadMatch`) keep the ontology label canonical and add the
> MIM term as a synonym.

So:

| predicate | effect on the ontology term in kg-microbe |
|---|---|
| `skos:exactMatch` / `skos:closeMatch` | **renamed** to MIM's `subject_label` |
| `skos:broadMatch` / `skos:narrowMatch` | keeps its label; MIM's term added as a synonym, and a `biolink:broad_match` child-to-parent edge is emitted (`subclass_of` until kg-microbe#1120 lands) |

**2,805 of 2,946 rows are symmetric, and 835 carry a label that differs from the
ontology's** — every one renames a node. That is deliberate: a recipe says `KOH`,
not "potassium hydroxide", and MIM is the naming authority for media
ingredients. But it makes `preferred_term` quality load-bearing in a way it was
not before. A typo in a MIM label becomes the KG's name for that term.

**Consequence for identity and grading.** A wrong primary identifier published
through a symmetric own-identifier row asserts a false identity and renames the
target; that is the doubled harm behind #322. Independently, #317's
`mapping_quality` defects overstate how a grounding was established, but do not
select the Rule D predicate or cause the downstream rename. Regrading an
own-identifier row from `EXACT_MATCH` to `SYNONYM_MATCH` or `CAS_RN_LOOKUP`
therefore leaves both its `skos:exactMatch` predicate and downstream naming
effect unchanged.

That cuts both ways, so check before regrading in bulk: an `EXACT_MATCH` to a
class term can reflect a correct identity when the MIM record **is** that class.
`Aromatic
hydrocarbon` → `CHEBI:33658 "arene"` is one such row, and it does rename the
ChEBI class downstream — deliberately, since MIM is the naming authority and
`aromatic hydrocarbon` is the more recognisable name for `arene`.

### The asymmetric predicates follow SKOS, and the set says so (#390)

MIM once defined `skos:narrowMatch` as *"MIM:X is a kind-of Y"*, which is the
inverse of the spec: `skos:narrowMatch` is a sub-property of `skos:narrower`, so
`A narrowMatch B` asserts **B is narrower than A**. Every parent-anchoring row
therefore claimed the OBO parent was the more specific concept. Both definitions
in Section 1 were inverted, consistently, so the corpus was internally coherent
and externally wrong.

Nothing broke, because kg-microbe read MIM's intent rather than the spec. That
is also why this could not be fixed by flipping the rows alone: the reader
compensated, so a flip on one side would have inverted every asymmetric edge.

**The mapping set now declares its semantics in its own header**, which is what
made the cutover safe:

```
# predicate_semantics: skos
```

A consumer reads that key at the top level of the SSSOM header and applies the
SKOS reading. **Absence means legacy** — the pre-#390 inverted convention — and
so does any unrecognised value. Failing closed this way makes the two halves
order-independent: an old file, or a *rebuild of old content*, carries no
declaration and is read as legacy however new the reader is. A date threshold
could not do that, because `mapping_set_version` is build time and a rebuild of
unfixed content would stamp a post-cutover date onto legacy rows.

The declaration and the flipped rows live in the same file, so they are atomic
by construction — a published set can never assert one and contain the other.

Consequences for curators:

- The parent-anchoring predicate is now **`skos:broadMatch`** (Section 1).
- A record graded `NARROW_MATCH` still means "this record is narrower"; its
  published predicate is `broadMatch` because the *ontology term* is broader.
- Rule B1 keys on both asymmetric predicates and was unaffected.
- `skos:narrowMatch` is now rare-to-nonexistent in the corpus; treat a new one
  as a likely mislabelled `broadMatch`.

### The parent anchor means "form of", not subsumption (#245)

Section 1 used to say a consumer *must* emit `broadMatch` as
`biolink:subclass_of`. That was measured against ChEBI on 2026-09-22 (set at
`c5993f67`, 165 `broadMatch` rows), classifying each CHEBI parent by whether
it carries an InChIKey — a fully specified molecule — or is a class:

| subject shape | parent is a… | rows |
|---|---|---:|
| salt-named (`…sodium salt`, `…hydrochloride`) | specific molecule | 31 |
| hydrate-named (`MgSO4 x 6 H2O`) | specific molecule | 10 |
| solution-named (`84 g/L NaHCO3 solution`) | specific molecule | 3 |
| other (racemates, cation-named salts, polymers, concentrates) | specific molecule | 25 |
| any | class (`sodium salt`, `ionic liquid`, `hydroxyflavone`) | 26 |
| any | non-CHEBI parent (NCIT, MeSH, FOODON, ENVO, MICRO, UBERON) | 70 |

**69 of the 95 CHEBI-parent rows point at a fully specified molecule.** ChEBI
relates a salt to its parent acid, and a hydrate to its anhydrous form, with
`has part`, not `is_a`: in `chebi.db` no term carries both `BFO:0000051` and
`rdfs:subClassOf` to the same target (0 of 4,117 has-part edges, 0 of the
201 on hydrate-labelled terms). A `subclass_of` edge for those rows is
therefore false in the source ontology, and a prepared solution is not a
kind of its solute under any model. The 26 class-parent rows are genuine
subclass assertions ("3'-sialyllactose sodium salt is a sodium salt"). The
70 non-CHEBI rows were not classified; their typical shape is a material
under a material class ("Vermont Soil is a soil"), where subclass would
hold. The row itself does not distinguish the shapes.

**Ruling: keep `skos:broadMatch`, change nothing in the data, and state what
it means.** A MIM `broadMatch` row asserts that the object is the closest
broader term for the subject — the subject is a *form of* it (salt, hydrate,
solution, racemate) or a *kind of* it — and asserts nothing more specific
than that. Consequences:

- Consumers **must not** project a MIM `broadMatch` row as
  `biolink:subclass_of` / `rdfs:subClassOf`. Emit `biolink:broad_match`
  (Biolink's predicate whose exact mapping is `skos:broadMatch`). The parent
  link stays in the graph for navigation and grouping; no subsumption claim
  that ChEBI contradicts is made. The kg-microbe reader change is a predicate and
  relation swap at the MediaDive parent-edge emission (kg-microbe#1120).
- `skos:narrowMatch`, the inverse, carries the same reading in the other
  direction: `biolink:narrow_match`, not a reversed `subclass_of`.
- Curators keep following Section 3 step 2. Anchoring a hydrate to its
  anhydrous molecule, or a salt to its parent acid, is correct and required —
  it is not an error to be "fixed" by re-pointing the row at `CHEBI:35505
  hydrate` or `CHEBI:24866 salt`. A class parent is equally fine when it is
  the nearest one.
- `skos:closeMatch` was rejected for the 69 rows: it carries no direction,
  and Rule B1's registry-row obligation is keyed on the asymmetric
  predicates, so those records would have lost it. A new salt-of/hydrate-of
  predicate was rejected because no consumer reads one and `has part` on the
  SSSOM subject would assert a partonomy MIM does not curate (Section 6).

Transition: MIM's own KGX exporter (`src/mediaingredientmech/export/kgx.py`)
and the 2026-09-21 semantic-review bundle still project `subclass_of`; that
is tracked as #734 and is a release decision, not a curation one.

### What *not* to do

**Do not rename a record so its name matches a term it does not denote.** If
`Sodium glutamate monohydrate` is grounded to the anhydrous term, the fix is to
re-ground the record (step 1 or 2), not to rename it "monosodium L-glutamate".
Renaming destroys the raw label a medium actually used, removes it as an SSSOM
`subject_label` — which is how downstream consumers resolve raw strings — and
converts a visible mapping error into an invisible one.

> **Carve-out: correcting a DAMAGED or foreign-language label.** Since MIM
> became kg-microbe's naming authority, `subject_label` is the KG's canonical
> name for the term a symmetric row points at, so a misspelling or a
> source-language label is published as that ontology term's name. Those may be
> corrected — **and the original kept as a `RAW_TEXT` synonym**, which is what
> makes this compatible with the rule above: the raw string still resolves
> through `label_index`, so nothing a medium used is lost.
>
> The distinction is *what the label denotes*. `1-Naphtylacetic Acid` ->
> `1-Naphthylacetic acid` and `1,3-Butandiol` -> `1,3-Butanediol` name the same
> substance either way; only the spelling changes, and the record does not move.
> Renaming `Sodium glutamate monohydrate` to match an anhydrous term changes
> what is claimed. Correct spelling, never identity.
>
> Keep the SSSOM `subject_id`. Per-record filenames are not renamed
> (`collect_existing_filenames` keeps the existing stem), so a corrected record
> keeps subjects like `MIM:13-Butandiol`. A stable subject matters more than a
> tidy one — re-deriving it from the new label is the #293/#307 mistake and
> silently matches nothing.

**Do not treat a record's auto-derived chemistry as evidence of its identity.**
`AUTO_BACKFILL_CHEBI_CHEMISTRY` copies formula, InChI and SMILES *from the
current mapping*, so they agree with it by construction.

Check `chemical_properties.data_source` before trusting a CAS, too — a
`data_source` of the form `PubChem (via CHEBI:…)` was also derived from the
mapping under test. Until #878, `MgSO4·H2O` carried `cas_rn 10034-99-8`
sourced `PubChem (via CHEBI:31795)` **and** external-sweep synonyms that were
all *heptahydrate* spellings, so a curator reading both as corroboration would
have confirmed the wrong term twice. Evidence counts only when its provenance is
independent of the mapping being tested — e.g. a CAS present from the record's
`CREATED` event, or a name lookup on the record's own label.

**Do not conclude a term does not exist without quoting the full search.** The
32 hydrate families exist partly because specific terms were not found; at least
one (`CHEBI:232425`) was in the local build the whole time.

---

## 4. Common mistakes

Each of the four most common mistakes a curator (or an automated
pipeline) makes is below, with a worked TSV example, the rule that
catches it, and the antidote. When CI rejects a row, the reject_reason
column names the rule that fired; this section explains each rule by
id.

Rules A, B1, B2, B3, and B4 are all enforced today; rejects from any
of them produce entries in `mappings/needs_curator_review.tsv` and
make CI fail. The TSV examples and antidotes below apply equally to
each rule.

### Mistake 1 — Auto-classifier label drift (Rule A)

The auto-classifier scripts in claw
(`scripts/classify_ingredient_type.py`,
`scripts/categorize_residual_p25.py`) sometimes propose mappings where
the subject and object share **zero token overlap**, indicating the
proposed object is not actually related to the subject. The most
notorious example: a row that maps `MIM:KH2PO4` (potassium phosphate
monobasic) to `CHEBI:31346 "calcium sulfate dihydrate"`:

```tsv
subject_id     subject_label                     predicate_id      object_id     object_label              object_source  mapping_justification        source                                          mapping_date  confidence
MIM:KH2PO4     potassium phosphate monobasic     skos:broadMatch  CHEBI:31346   calcium sulfate dihydrate  obo:chebi.owl  semapv:ManualMappingCuration  MIM:curator=auto_classify_ingredient_type  2026-05-02    0.85
```

`subject_label` = "potassium phosphate monobasic"; `object_label` =
"calcium sulfate dihydrate". After lowercasing and stop-word removal,
the token sets are `{potassium, phosphate, monobasic}` and
`{calcium, sulfate, dihydrate}`. Intersection: empty. The `source`
column carries `MIM:curator=auto_classify_ingredient_type`, so this is
a machine-generated proposal with no human review.

**Rule A** rejects the row. The validator demands at least one of:

- `confidence` ≥ 0.95, OR
- token overlap ≥ 1 between `subject_label` and `object_label`, OR
- a non-auto curator tag in `source` (a human touched the row), OR
- an independent CAS-RN or PubChem CID xref in the subject's MIM YAML
  (`chemical_properties.cas_rn` or `chemical_properties.pubchem`)
  that corroborates the chemistry from a registry other than the
  ontology.

None of those is satisfied here, so the row goes to
`mappings/needs_curator_review.tsv` with
`reject_reason = "Rule A: zero token overlap, no human curator, no CAS/PubChem corroboration"`.

**Antidote**: do not merge the row. Either (a) re-curate the mapping
(KH2PO4 should map to CHEBI:63036 "potassium dihydrogen phosphate" or
its parent), (b) add `chemical_properties.cas_rn` to the YAML if a
registry confirms the chemistry, or (c) leave the row in
`needs_curator_review.tsv` and reject the proposal.

### Mistake 2 — Double-typed pair (Rule B2)

A pair of rows for the same `(subject_id, object_id)` under two
different predicates says contradictory things. Most commonly,
the same MIM subject is asserted to be **both** identical to and a
child of the same ontology term:

```tsv
subject_id          subject_label  predicate_id      object_id      object_label  object_source  mapping_justification        source                                  mapping_date  confidence
MIM:Vermont_Soil    Vermont Soil   skos:exactMatch   ENVO:00001998  soil          obo:envo.owl   semapv:ManualMappingCuration  MIM:cbclaw_envo_promotion           2026-05-02    0.9
MIM:Vermont_Soil    Vermont Soil   skos:broadMatch  ENVO:00001998  soil          obo:envo.owl   semapv:ManualMappingCuration  MIM:specificity-loss-review        2026-05-02    0.9
```

Both rows have the same `(subject_id, object_id) = (MIM:Vermont_Soil,
ENVO:00001998)`. The first row asserts identity; the second asserts
parent/child. They cannot both be true.

**Rule B2** rejects this: at most one row per `(subject_id, object_id)`
pair. **Rule B3** also rejects this specific shape: for any subject
`MIM:<seven-digit-id>` and any OBO-parent target `Y`, if `broadMatch Y` is
asserted, then `exactMatch Y` must NOT be.

**Antidote**: pick `broadMatch` (the parent IS broader; Vermont Soil
is not literally identical to all soil) and remove the `exactMatch`
row. Then add the registry row to
`kgmicrobe.ingredient:vermont_soil` per Section 2.

### Mistake 3 — Missing registry row (Rule B1)

A `broadMatch` row is present, but no registry exactMatch row
accompanies it:

```tsv
subject_id          subject_label  predicate_id      object_id      object_label  object_source  mapping_justification        source                       mapping_date  confidence
MIM:Vermont_Soil    Vermont Soil   skos:broadMatch  ENVO:00001998  soil          obo:envo.owl   semapv:ManualMappingCuration  MIM:cbclaw_envo_promotion  2026-05-02    0.9
```

That's the only row for `MIM:Vermont_Soil`. There is no second row
mapping `MIM:Vermont_Soil` to a `kgmicrobe.{ingredient,compound}:`
CURIE. As described in Section 2, this means downstream consumers
that resolve "Vermont Soil" by `subject_label` get back the parent
`ENVO:00001998` instead of a Vermont-specific child id.

**Rule B1** rejects this: every `MIM:<seven-digit-id>` subject that has any row
must have exactly one row of the form `MIM:<seven-digit-id> skos:exactMatch
kgmicrobe.{ingredient,compound}:<slug>`.

**Antidote**: mint the registry CURIE first, then add the registry row.
For Vermont_Soil, mint `kgmicrobe.ingredient:vermont_soil` (lowercased,
underscored slug) and add:

```tsv
MIM:Vermont_Soil    Vermont Soil   skos:exactMatch   kgmicrobe.ingredient:vermont_soil    Vermont Soil    kgm:ingredient   semapv:ManualMappingCuration  MIM:cbclaw_envo_promotion|MIM:specificity-loss-review (mint_kgm_ingredient)  2026-05-02    0.99    Registry/identity row preserving kgmicrobe.ingredient:vermont_soil alongside parent ENVO:00001998.
```

Both rows now coexist for the same MIM subject and play complementary
roles per Section 2.

### Mistake 4 — Locally-edited object_label (Rule B4)

A curator hand-edits the `object_label` to a non-canonical synonym, or
the ontology has updated its primary label and MIM still carries the
old one:

```tsv
subject_id          subject_label  predicate_id      object_id      object_label  object_source  mapping_justification        source                       mapping_date  confidence
MIM:Vermont_Soil    Vermont Soil   skos:broadMatch  ENVO:00001998  soils         obo:envo.owl   semapv:ManualMappingCuration  MIM:cbclaw_envo_promotion  2026-05-02    0.9
```

`object_label = "soils"` instead of the canonical ENVO label `"soil"`.

**Rule B4** flags this whenever the local kg-microbe ontology
transforms are present
(`../kg-microbe/data/transformed/ontologies/envo_nodes.tsv` in this
case): the validator looks up the canonical label and exact-synonym
set for `ENVO:00001998` and rejects rows where `object_label`
matches neither. In CI environments without those transforms (the
typical case on PR CI), Rule B4 emits a warning and skips per-prefix,
so the rule does not block PRs that don't have access to the
canonical label source.

This rule prevents the "stale child label leaking onto parent"
pollution that kg-microbe's `purge_asymmetric_pollution()` exists to
clean up: if a curator typed in "Vermont soil" as the `object_label`
of a `broadMatch ENVO:00001998` row, downstream consumers might index
"Vermont soil" against the ENVO parent — exactly the kind of identity
collapse Section 2 describes.

**Antidote**: use the canonical OBO-published label
(`object_label = "soil"`). Do not hand-edit the label to match the
subject; use a synonym already registered in the ontology, or update
`subject_label` if the ingredient really should be more general.

### Why this list is short on purpose

Other mistakes exist (wrong predicate direction, malformed CURIE
prefixes, missing required columns), but they are caught by the
SSSOM toolchain before they reach this validator. The four mistakes
above are the ones that pass syntactic checks and break **graph
semantics** downstream. Rule A through Rule B4 exist specifically to
catch those.

---

## 5. Curator workflow

When CI rejects a row, the validator writes the row plus a
`reject_reason` column to `mappings/needs_curator_review.tsv` and exits
with code 2 (CI-blocking). The PR will not merge until the row is
resolved. You have three options.

### Option A — Fix the YAML and let claw regenerate

This is the right option when the row reflects genuinely incorrect data.

1. Locate the underlying ingredient YAML in
   `data/ingredients/mapped/<Slug>.yaml` (or
   `data/ingredients/unmapped/<Slug>.yaml` for in-progress entries).
   Find the current record by its `mim_id`; the numeric subject does not map
   to a file stem. `CurieNormalizer.resolve()` can resolve an unambiguous
   historical subject first. Keep filenames unchanged unless a separate
   curation change requires a rename; the permanent ID survives either way.
2. Fix the field that produced the bad row. Examples by rule:
   - **Rule A**: re-curate the `ontology_mappings` entry for the
     ingredient — remove the wrong CHEBI/ENVO id and set the correct
     one. If an external CAS-RN or PubChem CID corroborates the
     chemistry, add it under `chemical_properties.cas_rn` /
     `chemical_properties.pubchem` so future reruns of Rule A grant
     benefit-of-the-doubt automatically.
   - **Rule B1**: regenerate the SSSOM via the claw builder — its
     `_row_from_yaml` synthesizes the
     `kgmicrobe.{ingredient,compound}:<slug_lc>` registry row
     automatically whenever the subject has a narrow/broad parent
     row, choosing the namespace from the parent ontology prefix
     (chemistry registries → `compound`, food / environmental /
     anatomical / tissue ontologies → `ingredient`). A B1 reject
     after a fresh build means either the YAML's `ontology_mapping`
     was hand-edited away from a narrow/broad relationship or the
     SSSOM was edited directly — re-run `just build-sssom` from
     claw and the reject should clear.
   - **Rule B2/B3**: pick one predicate. If the ontology term is a
     proper parent, keep the broadMatch and drop the exactMatch.
   - **Rule B4**: update `object_label` in the YAML's
     `ontology_mappings` entry to the canonical OBO label.
3. Regenerate `mappings/ingredient_mappings.sssom.tsv` from the
   updated YAMLs. The SSSOM build lives in the sibling
   `culturebotai-claw` repository — run from that checkout:
   `cd ../culturebotai-claw && just build-sssom && just publish-sssom`.
   (MIM does not host the builder; only the published TSV.)
4. Re-run the validator: `cd MediaIngredientMech && just qc-sssom`
   (or equivalently, `python3 scripts/validate_sssom_invariants.py`,
   which is what CI invokes). The row should now pass. Commit the
   regenerated SSSOM along with the YAML change.

This is the **default option** and the one the audit trail rewards: the
fix is durable because future regenerations of the SSSOM will produce
the same correct row.

### Option B — Park the row in `needs_curator_review.tsv` for triage

This is the right option when the row may eventually be valid but you
don't have time / context to resolve it now, and you want CI to merge
the rest of the change set without waiting.

1. The validator already wrote the row to
   `mappings/needs_curator_review.tsv` with a `reject_reason` column.
   Leave it there; do not move it back to the main SSSOM.
2. Open a curation issue describing what is needed to resolve the row
   (e.g. "Need a domain-expert review of MIM:Wood_Ash → CHEBI parent
   selection — current auto-classifier proposed wrong target").
3. Reference the issue in your PR description so reviewers know the row
   is parked deliberately, not lost.

The CI gate fails on rows in the **main** SSSOM that violate any rule;
rows that live in `needs_curator_review.tsv` are explicitly exempt.
That is the entire reason the file exists.

### Option C — Reject the proposal entirely

This is the right option when the row should never have been proposed
and there is no underlying ingredient that needs the mapping at all.

1. Delete the offending row from the source YAML's `ontology_mappings`
   list. If the entire ingredient was created in error, also delete the
   YAML file.
2. Regenerate the SSSOM as in Option A.
3. Confirm the row no longer appears in either the main TSV or
   `needs_curator_review.tsv` after regeneration.

This option is more invasive than B (it deletes data, not just parks
it) so reach for it only when you are sure. If in doubt, use Option B
and let the curation issue surface the question.

### Reading the validator output

`just qc-sssom` (and the equivalent direct invocation
`python3 scripts/validate_sssom_invariants.py`) print a per-row
report to stderr. On a failing run the validator emits a single FAIL
header followed by one line per rejected row:

```
FAIL: 1 row(s) in ingredient_mappings.sssom.tsv fail Rule A (auto-classifier token-overlap gate).
  row 47: MIM:KH2PO4 'potassium phosphate monobasic' -> CHEBI:31346 'calcium sulfate dihydrate' — zero token overlap; no human curator; no CAS/PubChem corroboration
```

Exit codes:
- **0** — all rows pass.
- **1** — input file not found (configuration error).
- **2** — one or more rows reject; the violating rows are written
  to `mappings/needs_curator_review.tsv` with a `reject_reason`
  column and CI fails.

Rule B1 is **strict by default**: every narrow/broadMatch subject
must carry a sibling
`MIM:<seven-digit-id> skos:exactMatch kgmicrobe.{ingredient,compound}:<slug_lc>`
registry row, and a missing registry row contributes to exit-2 just
like Rules A, B2, and B3. The original 162-subject backlog (that
PR #4 shipped warn-only to accommodate) was cleared by the claw
SSSOM builder change in
`culturebotai-claw/scripts/build_mim_ingredient_sssom.py`
(`_row_from_yaml` now synthesizes the registry row whenever a
narrow/broad parent row is emitted), so every fresh build of
`mappings/ingredient_mappings.sssom.tsv` is B1-clean by
construction.

For one-off diagnostic use (e.g. while bisecting which subjects
regressed after a builder-side schema change) you can pass
`--lenient-b1` to downgrade B1 back to warn-only. Do **not** use it
in CI: the strict default is what protects downstream consumers
from the identity-collapse class of bug Section 2 describes. The
legacy `--strict-b1` opt-in flag from the warn-only stage is
accepted as a no-op so any tooling that still passes it keeps
working.

### Where the rules live

- **Validator implementation**: `scripts/validate_sssom_invariants.py`
  enforces Rules A, B1 (strict-by-default), B2, B3, and B4 (best-effort,
  silently skips per-prefix when the kg-microbe transforms are absent).
- **Justfile recipe**: `just qc-sssom` runs the validator; `just qc`
  runs it as part of the full quality-check composite.
- **CI workflow**: `.github/workflows/qc-sssom.yaml` invokes
  `python3 scripts/validate_sssom_invariants.py` directly (it does
  not call `just`) on every PR that modifies
  `mappings/ingredient_mappings.sssom.tsv`,
  `mappings/needs_curator_review.tsv`, or
  `scripts/validate_sssom_invariants.py`, and on every push to `main`.

If you need to add a new rule (e.g. enforcement of a new mapping
convention introduced by a future curation pass), follow the existing
Rule A / Rule B-series pattern: name the rule, define what it catches
in plain terms here, implement it in
`scripts/validate_sssom_invariants.py`, and update the CI workflow only
if the rule needs additional inputs (it usually does not).

---

## 6. Component partonomy is not identity or a variant relationship

`IngredientRecord.components` asserts one-level material **has-part** relations for
a medium or mixture. A component CURIE identifies the part; it never identifies the
whole record. Therefore:

- do not ground a mixture to one component's CURIE or copy one component's CAS-RN
  onto the mixture — that would assert that the whole *is* the part;
- do not translate a component edge into `skos:exactMatch`, `closeMatch`,
  `narrowMatch`, or `broadMatch`; those predicates describe grounding of the whole;
- do not use component edges to relate chemical forms. `components` records no
  relationship among records that differ in hydration, stereochemistry, salt
  form, or grade. Whether those details create a distinct identity or live in
  `supplied_form` is governed by Section 3; `components` decides neither. A
  causal-graph bridge (Section 7) may say what a supplied form becomes in the
  medium, but it is not a component edge and decides no identity either;
- do not infer a complete culturing recipe from a component list. Completeness is
  explicit in `component_assertion` and is relative to its cited evidence.

`components[].reference_scope` states whether the part identity is represented by
at least one active MIM record (`MIM_CATALOG`), deliberately remains an external
ontology/registry CURIE (`EXTERNAL_TERM`), or is named but ungrounded (`UNMAPPED`).
It is not a unique document key: duplicate-identifier families remain a separately
tracked catalog defect.

**Causal graphs mirror `components`; they never extend it (Section 7).** A graph
edge with `bridge_kind: COMPONENT` restates one entry of this list: its object
node's `component_ref` equals a `components[].component_id` of the same record,
its basis is `RECORD_COMPONENT`, and it inherits that entry's
`component_assertion`. A graph never adds, removes or changes a component, and no
chemistry edge starts at a component node, because the component's own record
owns its speciation and mechanism. The other bridge kinds (`HYDRATE_PART`,
`ION_PART`, `PROTONATION`, `TAUTOMER`, `STRUCTURAL_FORM`, `FORM_OF_PARENT`) are
not component edges. They say what one supplied substance becomes in the medium,
not what a mixture contains, so a hydrate's anhydrous part or a salt's ion never
goes into `components`, and a `components` entry never stands in for a bridge.
`COMPONENT`, `HYDRATE_PART` and `ION_PART` edges all use `BFO:0000051` (has
part); `bridge_kind` is what tells them apart.

See `docs/stock_components.md` and run `just qc-component-partonomy` for the full
shape and cross-record invariants.

---

## 7. Causal graphs: supplied form, active species and cross-Mech links

An ingredient record may carry `causal_graphs`: evidence-backed mechanism graphs
that explain how the ingredient, as supplied, acts on cultured microbes.
`docs/CAUSAL_GRAPH_CONTRACT.md` describes the graph shape, the node types, the
full predicate table, the evidence model and the curation procedure. This section
owns the identity rules: what may anchor a graph, how a graph gets from the
supplied form to the species a cell meets, and when a graph may link to another
Mech's record. Like the rest of this file, it outranks the schema and that page.

> **Status.** The `causal_graphs` schema, structural rule tests and reference
> pages are included. No maintained record gains a graph in this change. The
> offline semantic gate (`just qc-causal-graphs`, with committed snapshots) is
> planned; the error codes below specify its future checks. Schema validation
> does not verify the scientific claims or permit carrying forward approvals.
> Wait for the semantic gate before curating graphs into maintained records,
> and obtain fresh scientific approval after every record-byte change.

**Principle.** The anchor is the record exactly as Section 3 identifies it: the
supplied form. Species the cell meets are separate nodes with their own
groundings. A bridge says what the supplied form becomes; it never says what the
record is. A blocked bridge is a prompt to re-check identity under Section 3,
never a reason to relax a guard.

### 7.1 Identity gate

Violations fail with `IDENTITY_GATE` unless another code is named; the schema
enforces the first condition of A2 itself.

- **A1. One anchor.** Each graph has exactly one `INGREDIENT` node, and its
  `grounding` equals the record's `identifier` (`ANCHOR_MISMATCH` otherwise).
- **A2. Only a resolved identity anchors a graph.** A record may carry graphs
  only when all of the following hold:
  - `mapping_status` is `MAPPED`, and `ingredient_type` is not `NAMED_MEDIUM`
    (schema rules). A named medium is CultureMech's recipe, and its
    constituents' own records carry the mechanisms. A record with no
    `ingredient_type` may carry graphs;
  - `ontology_mapping.mapping_quality` is not `PLACEHOLDER`;
  - `identifier` is not listed in `mappings/duplicate_identifier_baseline.tsv`,
    whatever the row's disposition. On 2026-10-05 every row there was an
    unresolved family (`UNREVIEWED`, `HYDRATE_FAMILY_UNREVIEWED`,
    `NEEDS_OWN_ID`, `NEEDS_OWN_ID_MEMBER_UNDECIDED`); for example `CHEBI:31795`
    sits on both `MgSO4 x 7 H2O` and `MgSO4·H2O`;
  - no other non-`REJECTED` record carries the same `identifier`. `REJECTED`
    merge tombstones do not count: `Dextrose.yaml` (`CHEBI:17634`) does not
    block `D-glucose.yaml`, and `Na2moo42h2o.yaml` (`CHEBI:75213`) does not
    block `Na2moo4_X_2_H2o.yaml`.
- **A3. Identity cannot re-enter under a second id.** No node other than the
  anchor may carry the anchor's CURIE, or any CURIE that the record's own SSSOM
  rows map with `skos:exactMatch` or `skos:closeMatch`.
- **A4. `xrefs` carry exact equivalents only**, declared either by the owning
  sibling record (`mapped_xrefs` with mapping source `ec2go` or `rhea2ec`) or by
  the ontology (GO `hasDbXref`). Verified pairs: `GO:0061599` ↔ `RHEA:35047`,
  `GO:0015412` ↔ `EC:7.3.2.5`, `GO:0015420` ↔ `EC:7.6.2.8`, `GO:0004325` ↔
  `EC:4.98.1.1`. Anything else fails with `XREF_UNDECLARED`. A parent, a related
  form or the record identifier is a separate node joined by an edge, never an
  xref.
- **A5. Graphs change no identity.** They write no SSSOM rows and never change
  `identifier`, `ontology_mapping` or `components`. Hydrates, salts and
  stereoisomers stay distinct substances (Section 3), and a bridge never
  justifies a merge.
- **A6. `supplied_form` is never a node.** A catalogue entry or CAS number
  describes the purchase, not a species.
- **A7. One node per CURIE per graph** (claw's duplicate-grounding check).
  Compartments are expressed through protein locations, not by repeating a
  chemical node.

### 7.2 Bridge kinds (closed set)

A chemistry edge carries a `bridge_kind`. The set is closed: each kind fixes its
`predicate_id` and the basis it must verify, and the gate recomputes every
bridge from ChEBI facts committed in `mappings/ontology_facts.tsv`, so CI needs
no ontology database. Chemistry edges carry no organism context (L4). Every
example below was checked against a local ChEBI build (`chebi.db`) on 2026-10-05.

| `bridge_kind` | `predicate_id` | Required basis | Recomputed check | Examples |
|---|---|---|---|---|
| `HYDRATE_PART` | `BFO:0000051` (has part) | `ONTOLOGY_AXIOM` | The subject is entailed under `CHEBI:35505` (hydrate); ChEBI asserts subject has part object; the subject's SMILES components minus water equal the object's. | Pass: `CHEBI:75836` → `CHEBI:75832` (FeSO4·7H2O → FeSO4) and `CHEBI:75213` → `CHEBI:75215` (Na2MoO4·2H2O → Na2MoO4), both asserted. |
| `ION_PART` | `BFO:0000051` plus `stoichiometry` | `ONTOLOGY_AXIOM` when ChEBI asserts or entails it; otherwise `CHEMICAL_STRUCTURE` | The ion's SMILES is an exact `.`-separated component of the salt's SMILES; its count equals `stoichiometry`; each component resolves to exactly one non-deprecated ChEBI term by SMILES; the component charges sum to the salt's charge. A transition-metal cation with a carbon-containing component also needs `LITERATURE` (complexation). A missing SMILES fails closed. | Pass: `CHEBI:75832` → `CHEBI:29033` iron(2+) and `CHEBI:75215` → `CHEBI:36264` molybdate (asserted); `CHEBI:63005` → `CHEBI:17632` nitrate (entailed through `CHEBI:51082` nitrate salt); `CHEBI:32149` → `CHEBI:16189` sulfate (no axiom; `O=S(=O)([O-])[O-].[Na+].[Na+]` has one sulfate component, and −2 + 2(+1) = 0). Blocked: `CHEBI:53438` iron(3+) sulfate → iron(2+) (no `[Fe+2]` component). |
| `PROTONATION` | `RO:0018033` (is deprotonated form of) / `RO:0018034` (is protonated form of) | `ONTOLOGY_AXIOM` | One asserted ChEBI hop per edge; hops may chain. | `CHEBI:61548` `RO:0018033` `CHEBI:4170` (asserted). |
| `TAUTOMER` | `RO:0018036` (is tautomer of) | `ONTOLOGY_AXIOM` | Asserted in ChEBI. | — |
| `STRUCTURAL_FORM` | `rdfs:subClassOf` (is a), from the specific form to the supplied class | `ONTOLOGY_AXIOM` + `CHEMICAL_STRUCTURE` | Asserted direct subclass; the form has a SMILES and no isotopic InChI layer (`/i`); the supplied class has no SMILES; formula and charge are equal; no other non-isotopic direct subclass shares the form's InChIKey first block with a different key. | Pass: `CHEBI:4167` D-glucopyranose → `CHEBI:17634` D-glucose. Blocked: `CHEBI:17634` → `CHEBI:17234` glucose (D-glucose has no structure); `CHEBI:4167` → `CHEBI:37661` glucopyranose (rival `CHEBI:37627` L-glucopyranose shares the block `WQZGKKKJIJFFOK`); the isotopologues `CHEBI:88300` and `CHEBI:134625`. |
| `FORM_OF_PARENT` | `skos:broadMatch` (has broader match) | `RECORD_SSSOM` | First hop only, from a `cas:` or `kgmicrobe.*` anchor to the ChEBI parent named by the record's own SSSOM `skos:broadMatch` row (Section 3, step 2); the parent must have a structure. | — |
| `COMPONENT` | `BFO:0000051` (has part) | `RECORD_COMPONENT` | The object node's `component_ref` equals a `components[].component_id`; no chemistry edge starts at a component node (Section 6). | — |

Bridges chain from the anchor toward the species. For example, `CHEBI:75836`
iron(2+) sulfate heptahydrate has part (`HYDRATE_PART`) `CHEBI:75832` iron(2+)
sulfate (anhydrous), which has part (`ION_PART`, stoichiometry 1) `CHEBI:29033`
iron(2+).

The guards exist because the simpler rules were wrong. "Is a" over any entailed
ChEBI subclass admits isotopologues and the wrong stereoisomer: `CHEBI:88300` and
`CHEBI:134625` are asserted direct subclasses of D-glucose. Has-part read off a
formula, with no charge check, admits the wrong oxidation state. Relaxing a guard
re-admits exactly these cases.

### 7.3 Link admissibility

**L1. Exact reciprocal grounding.** A graph links to another record, in MIM or a
sibling Mech, only through a node whose `grounding` equals that record's
identifier. An edge between a MIM node grounded C and a sibling node S is
admitted only if the pinned record S states that relation for exactly C.
"Pinned" means at the commit recorded for that Mech in `conf/sibling_pins.yaml`;
the gate reads the statement from the committed snapshot
`mappings/cross_mech_assertions.jsonl`, never from a live checkout. The match
between S's own grounding and C is reported as one of:

- **`EXACT`**: the same CURIE.
- **`GENERIC_SPECIALISATION`** (info): S grounds a Rhea generic class (its SMILES
  contains `*` or its formula contains R), and C is an asserted ChEBI subclass of
  it. Example: `EC:7.6.2.8` has input `CHEBI:140785` R-cob(III)alamin, and
  `CHEBI:17439` cyanocob(III)alamin is an asserted subclass of it.
- **`OBSOLETE_REPLACED`** (warning; blocks `MECHANISTIC`): S uses a deprecated
  ChEBI id whose `IAO:0100001` replacement is C. Example: `TCDB:9.A.8` lists
  `CHEBI:34754`, replaced by `CHEBI:29033` iron(2+). Follow the one declared
  replacement, never a chain: the deprecated ids in `TCDB:2.A.55` now resolve to
  carotenoids.
- **`XREF_EQUIVALENT`** (warning): S's ligand CURIE equals a ChEBI database xref
  of C, under the declared prefix synonym `pdb.ligand` ≡ `pdb-ccd`. Example: the
  BioLiP ligand `pdb.ligand:CNC` matches `CHEBI:17439` through its xref
  `pdb-ccd:CNC`.
- **`SHARED_MEMBER`** (warning): a cited family record that shares a
  `QUALIFIED` protein example with the node states the relation. Example:
  `PANTHER:PTHR43185` maps the FeoB family to `GO:0005886` plasma membrane, and
  its `QUALIFIED` example `UniProtKB:P33650` is the FeoB node's protein example.

Anything else fails with `RECIPROCAL_GROUNDING_MISMATCH`. If S states only the
opposite direction, the edge gets `RECIPROCAL_DIRECTION_MISMATCH` (warning) and
needs a `DATABASE_RECORD` or `LITERATURE` basis to establish its direction.
Example: ProteinTraitsMech writes `EC:1.16.1.6` with `CHEBI:17439` as an output,
while UniProt `Q9Y4U1` states `PhysiologicalDirection=right-to-left;
Xref=Rhea:RHEA:16115`.

**What the sibling record must state (`SIBLING_RECORD`).** Each predicate
mirrors the sibling's own assertion type, which is what makes the check
mechanical. The endpoint rules for every predicate are in
`docs/CAUSAL_GRAPH_CONTRACT.md`.

| Predicate | Typical edge | The pinned sibling record must state |
|---|---|---|
| transports (`RO:0002020`) | transport function, including a TCDB family → chemical | The chemical is in its `chemical_participants` with role `TRANSPORTED`. |
| has input / has output (`RO:0002233` / `RO:0002234`) | activity, process or pathway → chemical | Its own graph has the same predicate to the same grounding. |
| has participant (`RO:0000057`) | activity, process or pathway → chemical | The chemical is a participant, or a grounded node of its graph. |
| part of (`BFO:0000050`) | activity or process → process or pathway | PathwayMech participants or edges place the activity or process in the pathway. |
| input of / output of (`RO:0002352` / `RO:0002353`) | chemical → pathway, process or activity | A PathwayMech `consumes` / `produces` edge with the chemical as subject. |
| participates in (`RO:0000056`) | chemical → trait or process | A TraitMech `MECHANISTIC` graph grounds the chemical. |
| enables (`RO:0002327`) | protein family or structure → activity | The family's xrefs meet the activity's xref closure (depth ≤ 2 through ProteinTraitsMech `mapped_xrefs` / `xrefs`), or a CellStructureMech `functions[].grounding` names the activity. |
| contributes to (`RO:0002326`) | subunit family → activity or process | The same xref closure. |
| involved in (`RO:0002331`) | family or activity → process or pathway | Its xrefs name the process or pathway. |
| located in (`RO:0001025`) | family or activity → structure or location | Its `xrefs` or `mapped_xrefs` name the location, or `SHARED_MEMBER` applies. |
| molecularly interacts with (`RO:0002436`) | family or structure ↔ chemical | The family xrefs a GO binding term whose `RO:0004009` is the chemical (with `ONTOLOGY_AXIOM`), or a BioLiP record's ligand is the chemical and its receptor is one of the node's protein examples. |
| satisfies cofactor requirement (`MIM.vocab:satisfies_cofactor_requirement`) | chemical → `COFACTOR_REQ_*` quality | The requirement record's `xrefs` contain exactly the chemical's grounding. |
| has characteristic (`RO:0000053`); causally upstream of (`RO:0002411`, `RO:0002304`, `RO:0002305`) | see the predicate table | The record states the same relation for exactly these groundings (L1). |

The remaining predicates never take `SIBLING_RECORD`: has part, is a, has broader
match, the protonation and tautomer steps, has primary input / output, has
intermediate, starts with / ends with and results in transport across rest on
ontology, structure or record bases; positively / negatively regulates and
causally influences rest on literature. Is small molecule inhibitor of rests on
literature, and an AntibioticMech record with the same grounding is reported as
a co-reference, not as support.

**L2. Chemistry moves only toward what the supplied form becomes**: its parts,
its ions, their protonation or tautomer states, and its structural forms. It
never moves up to a broader class to reach a sibling. Claims grounded on
`CHEBI:17234` glucose (such as TraitMech's lactic acid fermentation trait,
`traitmech:000026`) belong on `Glucose.yaml`, not `D-glucose.yaml`. And the
cobalamin requirement `COFACTOR_REQ_CHEBI_30411` is not reachable from
cyanocobalamin, because `CHEBI:17439` is not a subclass of `CHEBI:30411`.

**L3. Every node is reachable from the anchor** (claw's structure audit). Each
bridged species must touch at least one non-chemistry edge; otherwise the graph
gets `BRIDGE_WITHOUT_PURPOSE` (warning).

**L4. Chemistry edges carry no organism context.** Biological edges inherit the
graph's `organism_scope`.

**L5. Mixtures use `COMPONENT` edges**, and each component's own record owns its
speciation and mechanism (Section 6).

**L6. No projection onto `MIM:<seven-digit-id>`.** A bridge is never projected onto the
`MIM:<seven-digit-id>` node and never exported as `same_as` or `exact_match`; has-part on
`MIM:<seven-digit-id>` stays reserved for `components`. As with a `skos:broadMatch` row
(#245), a bridge relates two distinct nodes and never makes them one.

### 7.4 Delegation (`SPECIATION`)

A salt, hydrate or stock solution may carry a `graph_kind: SPECIATION` graph:
the anchor plus bridges or `COMPONENT` edges to species or components that are
MIM records. The schema makes such a graph `NONMECHANISTIC`, and its
`scope_notes` names the records that hold the mechanism. The gate warns
`DELEGATION_TARGET_HAS_NO_MECHANISM` until a target record has a `MECHANISTIC`
graph explaining a role of the same name.

Delegation keeps the mechanistic count honest: a salt does not get a mechanism
of its own by restating its ion's. claw counts a `SPECIATION` graph as a graph
but not as mechanistic, and the derived links ledger
(`mappings/cross_mech_links.tsv`) adds `VIA_SPECIES_RECORD` rows, so a salt still
shows the sibling records reached through its species record.

### 7.5 Reading a failure

| Code | Severity | What to do |
|---|---|---|
| `IDENTITY_GATE`, `ANCHOR_MISMATCH` | error | Resolve the identity first (Section 3, the duplicate family or the placeholder), then add the graph. |
| `XREF_UNDECLARED` | error | Remove the xref, or make the entity a separate node joined by an edge. |
| `BRIDGE_GUARD_FAILED`, `STOICHIOMETRY_MISMATCH`, `CHARGE_IMBALANCE`, `COMPLEXATION_NEEDS_LITERATURE` | error | Re-check the record's identity under Section 3, or add literature. Never weaken the guard. |
| `RECIPROCAL_GROUNDING_MISMATCH` | error | The sibling does not state the relation for this grounding: bridge to the species it does ground, change the target, or drop the claim. |
| `RECIPROCAL_DIRECTION_MISMATCH`, `OBSOLETE_REPLACED`, `XREF_EQUIVALENT`, `SHARED_MEMBER`, `BRIDGE_WITHOUT_PURPOSE`, `DELEGATION_TARGET_HAS_NO_MECHANISM` | warning | Review. Establish direction with a database or literature basis; an `OBSOLETE_REPLACED` edge keeps the graph out of `MECHANISTIC`. |
| `GENERIC_SPECIALISATION` | info | None. |

The full list of gate codes, including evidence, snapshot and scope-gate
failures, is in `docs/CAUSAL_GRAPH_CONTRACT.md`.

---

## See also

- `scripts/validate_sssom_invariants.py` — the validator that enforces
  every rule named here.
- `mappings/ingredient_mappings.sssom.tsv` — the published SSSOM.
- `mappings/needs_curator_review.tsv` — triage queue for rejected rows.
- `docs/CURATION_GUIDE.md` — broader curation workflow (this file is
  scoped to mapping semantics specifically).
- `docs/stock_components.md` — typed ingredient/mixture partonomy contract.
- `docs/CAUSAL_GRAPH_CONTRACT.md` — causal graph shape, node types, predicates,
  evidence and cross-Mech links (Section 7 governs identity and bridges).
