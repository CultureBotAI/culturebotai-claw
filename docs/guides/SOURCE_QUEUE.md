# The data-source queue

`curation/source_queue.tsv` is a Mech's ranked list of the data sources its
corpus draws on or might adopt, with each source's licence verified before
anything is copied. AntibioticMech wrote the pattern; CellStructureMech adapted
it. This guide separates the part every Mech should share from the part each
Mech has to write itself, so the next five adoptions do not each re-derive it.

The shared half is enforced: `kg-microbe-source-queue check --mech <name>`.

## What is shared

### The columns

Eleven, present in both existing queues:

| column | what it holds |
|---|---|
| `source_id` | stable slug, unique in the file |
| `name` | human name |
| `closes_gap` | *which* corpus gap this source fills |
| `use` | `SEED` · `CURATE_ONLY` · `REFERENCE` · `LINK_ONLY` |
| `redistribution` | `CC0_OK` · `ATTRIBUTION` · `SHARE_ALIKE` · `NONCOMMERCIAL` · `RESTRICTED` · `UNVERIFIED` |
| `access` | `BULK` · `API` · `BOTH` · `MANUAL` · `UNVERIFIED` |
| `priority` | 1–5 |
| `status` | `CANDIDATE` · `EVALUATING` · `ADOPTED` · `BLOCKED` · `REJECTED` |
| `verified_on` | ISO date the licence page was read |
| `url` | the source |
| `rationale` | the evidence, in this corpus's terms |

Spell `NONCOMMERCIAL` without the underscore. Both spellings are in use today,
which is the drift that motivated sharing this; the checker reports the other
one and says what to change.

Add columns your corpus needs and declare them in the manifest —
CellStructureMech adds `taxon_link`, `item_id`, `script`; AntibioticMech adds
`structures`. Neither should have to carry the other's.

### The ranking rule

Rank by **what the corpus cannot currently assert**, not by how well known the
source is:

1. **Does it close a stated gap?** A source that supplies records, or fields
   that are currently empty, outranks one that thickens a full column. "6 of our
   6 test records would gain a component list" is an answer; "thousands of
   entries" is not.
2. **Can we redistribute it?** A hard gate, not a tiebreaker. `SEED` — copying
   content into the repository — needs `CC0_OK`, `ATTRIBUTION` or `SHARE_ALIKE`.
   `NONCOMMERCIAL` is `LINK_ONLY` at best. `RESTRICTED` is `CURATE_ONLY`: cite,
   never copy. `UNVERIFIED` cannot be adopted at all.
3. **Does every item carry a citable identifier?** A source that joins only by
   name is a curation project, not an extraction.
4. **Bulk or API over manual.** A per-item manual pull cannot become `ADOPTED`,
   because nothing can read it offline.
5. **Effort, last.**

Two sources closing the same gap: adopt one, measure what it added, then decide
about the second.

### The adoption gate

`ADOPTED` claims the pipeline actually reads this source under terms someone
checked. It requires a verified `redistribution`, a `verified_on` date, and
whatever else the repository declares — CellStructureMech requires a `script`,
because a source nothing reads is not adopted.

Editing a row to say `ADOPTED` without that work makes the check fail, which is
intended.

**A candidate may say `use: SEED` while `redistribution` is still `UNVERIFIED`.**
That is the normal state before anyone has read the licence, and it is not a
finding. An earlier version of the checker judged intent and reported twelve
correct rows across the two real queues.

### Verifying

`redistribution` starts `UNVERIFIED` and is checked against **the source's own
licence page** — not a summary, not another database's claim, not memory. Record
the date. A licence that cannot be reached is a result too: record the URLs tried
and what blocked them.

## What is yours

Do not copy these from another Mech; they are wrong for your corpus by
construction.

- **The gap list.** Which fields your records leave empty, and how many records
  you have against how many you want. This is what step 1 ranks against, and it
  is why AntibioticMech and CellStructureMech rank the same source differently.
- **The licence tensions.** A CC0 repository hosting CC BY images has a real
  problem; one that only cites sources does not. Judge candidates against your
  repository's own distribution terms.
- **The known traps.** Identifiers that look valid and do not resolve, retired
  APIs still documented elsewhere, a rendering presented as a micrograph, a site
  that resolves but refuses connections. Each Mech accumulates its own; they earn
  their place in the skill by having cost someone time.
- **The rows.** Obviously — but worth saying, because the rows *are* the work.

## Adopting

1. Create `curation/source_queue.tsv` with the eleven columns plus yours.
2. Fill it with real candidates, ranked by gap.
3. Declare `source_queue: enabled` in `fleet.yaml` with `queue_path`, any
   `extensions`, and any `required_when_adopted`.
4. Wire `just source-queue` to `kg-microbe-source-queue check`.
5. Write `.claude/skills/source-queue/SKILL.md` — the shared parts can be
   referenced from here; the sections above under "What is yours" cannot.
