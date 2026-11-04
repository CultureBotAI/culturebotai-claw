# Quote-against-source evidence validation

The `evidence_reference_validation` capability separates a populated evidence
field from a quotation matched against a retained source. Every Mech declares
an explicit status in `src/kg_microbe_fleet/fleet.yaml`; disabled and
not-applicable declarations require a reason. Three Mechs enable it:
MediaIngredientMech (MIM), the bounded canary, and CellStructureMech and
HabitatMech, adopted in the
[#729](https://github.com/CultureBotAI/culturebotai-claw/issues/729) rollout.
The other eleven are disabled, each with a measured reason that names what its
adoption needs. No Mech is assumed inapplicable merely because most of its
records originated in a database.

## Contract and limits

An enabled profile must name a repository-relative `cache_dir`. Optional
`reference_fields`, `snippet_fields` and `evidence_fields` map native fields to
the shared validator. MIM uses `references_cache`, references
`[pmid, doi, reference]`, quotes `[snippet, excerpt, supporting_text]`, and
evidence containers `[evidence]`. Field mappings are explicit selectors, not
permission to reinterpret an explanation or database assertion as a quotation.

Optional `evidence_paths` limits the gate to specific evidence containers using
dotted fields and `[]` for list members. When omitted, all occurrences of the
declared evidence-field names are in scope; this broad mode requires a reviewed
native schema mapping. MIM deliberately preserves its existing gate's scope:

```yaml
evidence_paths:
  - ontology_mapping.evidence
  - role_assignments[].evidence
  - cellular_role_assignments[].evidence
```

These are the exact selectors used by the old gate at Claw revision
`a5d562962c75a2ad9efd8160b548df5944315422`. The two role names are legacy slots,
absent from MIM's current schema and committed records. They do not certify
the current role facets. On the inspected MIM main
`4625afd492b6cf43e3b499d1425d2453d490009d`, a complete archive scan found 2,953
records and 3,290 ontology-mapping evidence rows, of which 31 had a nonempty
quote-like field. This is a shape inventory, not a quote-validation result.

Broader native evidence remains explicitly unmeasured by this bounded gate:

| Native container | Immediate evidence entries in that snapshot | Reason for separate review |
|---|---:|---|
| `nutritional_roles[].evidence` | 752 | `RoleCitation` permits reference text/URLs and an excerpt or quote. |
| `physicochemical_roles[].evidence` | 272 | Same native `RoleCitation` distinction. |
| `cellular_metabolic_roles[].evidence` | 17 | Same native `RoleCitation` distinction. |
| `discussions[].evidence` | 32 | Discussion evidence and nested argument evidence need a reviewed source adapter. |
| `culturemech_reference.evidence` | 2 scalar values | The schema defines explanatory prose, not a quotation assertion. |

The inventory above counts immediate containers, not all nested evidence.
Reports identify other evidence-container locations and shapes as outside the
declared selectors; they do not assign quote verdicts to those native types.
Causal-edge evidence is also outside MIM's declared selectors, so graph
coverage must report it as unmeasured. Expanding any selector requires review
of its native semantics and source/cache support.

The source adapters read a retained markdown abstract for the cited PMID
(`PMID_<n>.md`, header `# PMID:<n>`) or DOI (`DOI_<percent-encoded lowercase
DOI>.md`, header `# DOI:<doi>`). DOIs are case-insensitive. The `doi:` form, the
bare `10.<registrant>/<suffix>` form and resolver URLs (`doi.org`,
`www.doi.org` or `dx.doi.org`, with or without a scheme) of one DOI read one
cache. Only a resolver URL's path is the DOI -- its `#fragment` and `?query` are
not -- and only that path is percent-decoded, because a URL encodes the DOI
while `%` is a legal DOI character. A citation that carries a PMID is checked
against the PMID alone, exactly as before DOI support; DOI values beside it are
not read.
The adapter checks source identity and matches normalized quote text inside the
abstract body; title, authors and other metadata are not quote evidence. It
performs no fetch, provider call or corpus repair. Citations that are neither a
PMID nor a DOI, absent quotes, and unavailable or invalid cached sources remain
unverified; a populated citation alone cannot become a successful quote
validation. Every report states how many in-scope items carry quote text in a
configured quote slot, whatever their verdict, because a pass covers only those
([#729](https://github.com/CultureBotAI/culturebotai-claw/issues/729)).

### Adding caches

`kg-microbe-evidence-fetch --mech <mech>` is the separate, explicit command that
adds caches; the gate never runs it. It plans from the gate's own
`MISSING_CACHE` results, so it fetches exactly what the declared selectors cite,
and it is a dry run unless `--apply` is given. Before any request, both modes
check that the cache destination is a writable directory, and every dry run
checks the repository-lock setup that `--apply` takes (the locks directory, its
hierarchy guard, the global lock and the Mech's lock path), so a dry run fails
wherever
`--apply` would, before anything is fetched or written. A lock another process
holds at that moment is reported only by `--apply`. An efetch reply other than a
`PubmedArticleSet` without an `ERROR` element stops the run as a provider
failure; it is never read as sources not found. `--json` may name a file outside
the Mech checkout or under its `workspace/`, never a cache, record or ledger. `--limit N` makes a canary:
when both PMIDs and DOIs are pending it covers at least one DOI, so `--limit 2`
exercises both lookup paths. `--apply` holds the Mech's repository lock. It
calls NCBI E-utilities anonymously, with no e-mail address or tool registration;
`NCBI_API_KEY` only raises the rate limit and is never printed. A DOI's abstract
is accepted only from a single PubMed record that itself lists that DOI. It
never rewrites an existing cache, writes each file atomically, and writes
nothing for a record without an abstract, which therefore stays `MISSING_CACHE`.
Each file records its PubMed URL and retrieval date. A cache records what
PubMed returned; it does not clear the text's redistribution rights, which
remain each Mech's source policy.

### Known findings

A profile may declare `known_findings`, a repository-relative TSV with the
columns `record`, `reference`, `verdict`, `quote_sha256` and `issue`. It lets a
Mech adopt the gate with an existing backlog without pretending the backlog is
validated:

- A current finding listed there is reported and counted apart, never as
  validated, and does not block. Each entry names the GitHub issue that owns
  its repair, and excuses exactly one occurrence: a copy of a recorded failing
  quote blocks until it is recorded too.
- A finding that is not listed blocks as before, so new or edited quotes are
  checked from the day the gate is adopted.
- The key holds the quote's hash and not the item's position. Reordering a
  record keeps an entry; editing the quote makes it stale.
- An entry whose finding no longer occurs is stale and blocks until removed, so
  the ledger can only shrink by repair. A record that could not be read is
  never the reason an entry is called stale, and the run fails on the read
  error.
- Only quote and citation findings can be recorded (`MISSING_REFERENCE`,
  `MISSING_CACHE`, `UNSUPPORTED_REFERENCE`, `SNIPPET_NOT_IN_SOURCE`).
  `INVALID_EVIDENCE` and `INVALID_CACHE` are broken input and must be fixed.
  A `MISSING_REFERENCE` entry has an empty `reference`, because the finding is
  that there is none; every other entry names its citation.

`kg-microbe-evidence --record-known-findings --issue <url>` plans the ledger
from the current findings (keep, add, drop stale) and writes it only with
`--apply`, reading, planning and writing under one hold of the Mech's
repository lock. Its dry run checks the ledger directory and the lock setup the
same way. A dry run that would leave a
current finding without an owner exits 1, and `--apply` then refuses (exit 2);
a row the writer cannot write fails the dry run too.

A cached substring match does not prove that a source supports the scientific
claim, establish the source's redistribution rights, or replace human review.
Curators still assess entailment, context, source quality and rights. Graph
coverage therefore reports evidence-field presence separately from measured
quote validation; disabled capabilities do not silently become validated or
failures. This distinction implements the concern tracked in
[#687](https://github.com/CultureBotAI/culturebotai-claw/issues/687), with
[#333](https://github.com/CultureBotAI/culturebotai-claw/issues/333) and
[#352](https://github.com/CultureBotAI/culturebotai-claw/issues/352) as context.

## The MIM canary

The 2026-10-31 committed-main audit selected MIM because its existing strict
`qc-evidence` gate already validated cached PMID snippets and
[passed on the inspected main](https://github.com/CultureBotAI/MediaIngredientMech/actions/runs/41250979368/job/124684245425).
Its profile keeps that gate's bounded selectors, described above. The runner
and CI workflow it proved are the canonical vendored artifacts every adopter
receives. The workflow resolves the Claw revision from the consumer's
`scripts/.vendored_canon_ref` pin; it must not carry an independent hard-coded
Claw revision.

## Rollout

Every Mech was measured read-only on 2026-11-04 (UTC) with this validator,
broad candidate profiles, and abstracts fetched into a scratch cache outside
every repository. The scripts are under `scripts/adhoc/`
(`survey_evidence_shapes.py`, `measure_quote_gate.py`,
`classify_quote_mismatches.py`, `measure_culturemech_layers.py`,
`classify_traitmech_citations.py`); the results are on
[#729](https://github.com/CultureBotAI/culturebotai-claw/issues/729).

CellStructureMech and HabitatMech adopt the gate. Every one of their `evidence`
slots holds an `EvidenceItem` or `SupportingReference` whose schema defines
`snippet` as a verbatim quote, so their profiles select every slot. Each commits
the abstracts its quotes cite, and keeps a known-findings ledger whose entries
name one issue in that Mech that owns their repair. HabitatMech's habitat
records are generated from its curation sources, whose evidence they carry
unchanged, so a repair goes into the curation source and is regenerated.

The gate reads the manifest's `record_globs`, so they must name a Mech's
authoritative records. CultureMech's name its derived merged layer, which is
stale on evidence (91 quotes against 38,580 in the authoritative normalized
corpus, almost all citing web or database sources), so CultureMech is not
adopted ([#774](https://github.com/CultureBotAI/culturebotai-claw/issues/774),
[#779](https://github.com/CultureBotAI/culturebotai-claw/issues/779)).

The other eleven stay disabled, and each manifest reason records the
measurement and what adoption needs:

- A source adapter for texts beyond the abstract: CommunityMech, whose failing
  quotes mostly occur in its tracked PMID text caches (full texts and abstract
  exports), and PathwayMech, most of whose failing quotes cite the full text by
  `source_locator`.
- An adapter for native excerpt caches: DUFMech binds each quote to a full-text
  excerpt with `cache_path` and `cache_sha256`.
- A source adapter for web or database citations: ProteinTraitsMech,
  AntibioticMech, NaturalProductMech and CultureMech, whose quoted items mostly
  cite such sources.
- TraitMech, whose quotes mostly cite DOIs: measure those first, then add
  supplement, full-text and database-assertion adapters for the rest.
- Nothing to check yet: TaxonMech, CMMMech and AIMech carry no quoted evidence.
  TaxonMech's evidence class already allows a verbatim snippet, CMMMech's needs
  a quote slot, and AIMech's gated concept records carry no evidence at all.
  Neither CMMMech nor AIMech carries the citation on the evidence item:
  CMMMech's `source_ref` and AIMech's curated `source_id` are keys into a
  per-record source list. So each also needs a PMID or DOI on the item or a
  reviewed adapter for that reference join
  ([#790](https://github.com/CultureBotAI/culturebotai-claw/issues/790)).

### How the rollout release lands

The single-MIM canary ran as a bounded release lane that froze the evidence
capability and the governance manifest; see
`docs/guides/VENDORED_GOVERNANCE.md`. The rollout release retires that lane and
returns the fleet to the coordinated contract of one shared pin:

1. The release enables the adopters, extends the runner and workflow to them,
   lists them in `INCOMPLETE_CONSUMERS` until they vendor, and removes the
   lane's declaration and audit. From its merge until every Mech re-pins,
   `fleet-audit` reports a rollout in progress. Until the first Mech re-pins,
   that message names MIM's canary commit as the commit to advance to; the
   target is the release commit
   ([#775](https://github.com/CultureBotAI/culturebotai-claw/issues/775)).
2. Every Mech re-pins to the release commit with `kg-microbe-governance sync`.
   Before fanning out, run `kg-microbe-governance pin-coupling` once per
   outgoing pin: MIM leaves the canary commit `16fd7c94`, the other thirteen
   the baseline `a5d56296`. It reports every file that names the outgoing pin,
   but only a copy the Mech's own checks compare changes. For this release
   that is NaturalProductMech's `scripts/.vendored_manifest.json`, which must
   equal claw's manifest at the pin, so its re-pin re-snapshots it
   ([#791](https://github.com/CultureBotAI/culturebotai-claw/issues/791)).
   Dated review and research records, provenance and commit permalinks that
   name the old pin are history and stay unchanged
   ([#795](https://github.com/CultureBotAI/culturebotai-claw/issues/795)).
   The adopters' PRs also commit their fetched caches and ledger. They also add
   `scripts/run_shared_evidence_validator.py` to `[tool.ruff] extend-exclude`
   beside their other claw-governed scripts, since their required `qc` lint
   rejects it at 110 columns
   ([#788](https://github.com/CultureBotAI/culturebotai-claw/issues/788)).
   Their `qc-evidence` job must pass on the PR and in the merge group.
3. A final claw PR removes the adopters from `INCOMPLETE_CONSUMERS` and
   removes the lane's now-unreachable workflow steps. Until that PR lands,
   `fleet-audit` stays red even after every Mech has re-pinned: once an
   adopter vendors the runner and workflow, the audit's completeness check
   reports that adopter's `INCOMPLETE_CONSUMERS` entry as stale.

`qc-evidence` stays advisory in the adopters after the rollout. A merge-queue
policy mapping alone changes nothing on GitHub; only a reviewed
`kg-microbe-merge-queue plan` and `apply` writes a ruleset
([#792](https://github.com/CultureBotAI/culturebotai-claw/issues/792)). And the
queue checker accepts an auxiliary checkout only at a literal commit, while the
governed workflow checks claw out at the committed pin. So mapping the job
would block every queue plan for that Mech, as it already blocks MIM's
([#793](https://github.com/CultureBotAI/culturebotai-claw/issues/793)). Once the
checker accepts a pin-derived claw checkout, map the job and apply the plan.

To roll the release back, roll forward.

- Do not revert it. Until the final PR lands, a revert restores the lane's
  declaration while its selection steps are still in the workflow. The
  restored audit then fails every pull request, including one that would
  remove the declaration again
  ([#784](https://github.com/CultureBotAI/culturebotai-claw/issues/784)).
- Do not re-pin the fleet to an older commit either. `fleet-audit` requires
  the manifest at the shared pin to equal the one claw's base installs, so
  every claw pull request would fail, including one that restores the old
  manifest ([#789](https://github.com/CultureBotAI/culturebotai-claw/issues/789)).
- Instead:
  1. Bring every Mech to the release commit.
  2. Merge a reviewed claw PR that restores the previous evidence profiles and
     manifest without the lane declaration. If the final PR has not landed, it
     also removes the adopters' `INCOMPLETE_CONSUMERS` entries.
  3. Re-pin every Mech to that commit. `sync` never deletes, so each adopter's
     re-pin also deletes the `qc-evidence` workflow and runner, whose job would
     fail under the restored profile. If that job is required by then,
     un-require it with a reviewed merge-queue plan and apply first
     ([#794](https://github.com/CultureBotAI/culturebotai-claw/issues/794)).

### Adopting another Mech

1. Reconcile the Mech's native evidence model, aliases and open work. Check
   that its `record_globs` name its authoritative records. Map only slots whose
   schema defines a verbatim quote, and review an adapter for anything else:
   local reference joins, full text, database assertions.
2. Against an isolated Mech worktree, run `kg-microbe-evidence-fetch` (a dry
   run, then a `--limit 2` canary, then `--apply`) and the gate,
   `kg-microbe-evidence`. Both read the profile from claw's manifest and
   refuse, with exit 2, a Mech whose capability is not enabled. Run them from a
   claw worktree on a branch that enables the candidate profile, or call the
   library functions behind them, as `scripts/adhoc/prepare_evidence_adoption.py`
   did for the [#729](https://github.com/CultureBotAI/culturebotai-claw/issues/729)
   rollout. Classify the residual findings, file one issue that owns their
   repair, and record them with `--record-known-findings`. A cached abstract
   does not clear redistribution rights; follow the Mech's source policy before
   committing caches.
3. Adopt through a coordinated re-pin as above. A Mech that lints its scripts
   excludes the vendored runner, as it does its other claw-governed files.
   Making `qc-evidence` required waits for the merge-queue checker to accept
   the governed workflow
   ([#793](https://github.com/CultureBotAI/culturebotai-claw/issues/793)).
   After that, map the job in the merge-queue policy and apply a reviewed
   `kg-microbe-merge-queue plan`.
