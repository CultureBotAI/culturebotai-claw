#!/usr/bin/env python3
"""
CI-friendly validator for ``mappings/ingredient_mappings.sssom.tsv``.

Mirrors ``kg-microbe/mappings/validate_isolation_source_mappings.py``:
per-row stderr report, exit-2 on violation so CI blocks the merge.

Rules implemented (see ``MAPPING_SEMANTICS.md`` for the full contract):

* **Rule A** — auto-classifier token-overlap gate. For every row whose
  ``source`` column is "auto-classifier-only" (every pipe-separated tag
  is ``MIM:curator=...``), accept iff at least one of:

    * ``confidence`` >= 0.95
    * ``subject_label`` and ``object_label`` share at least one
      discriminating token (lowercase, length >= 2, stop-words removed —
      pattern reused verbatim from
      ``culturebotai-claw/scripts/foodon_pass.py:64-105``)
    * the subject's MIM YAML at ``data/ingredients/mapped/{slug}.yaml``
      carries an independent CAS-RN or PubChem CID xref (registry
      corroboration). Read lazily — only when the previous two tiers
      have failed — via a minimal regex parser to avoid a PyYAML
      dependency in CI.

* **Rule B1** — mandatory registry/identity row. For every distinct
  ``MIM:<slug>`` subject with at least one ``skos:narrowMatch`` or
  ``skos:broadMatch`` row, require that another row exists with the
  same subject and ``predicate_id == 'skos:exactMatch'`` and
  ``object_id`` matching ``^kgmicrobe\\.(ingredient|compound):<slug_lc>$``
  where ``<slug_lc>`` is the lowercased subject slug (the part after
  ``MIM:``). Reject every offending narrow/broad row. Closes the
  Codex-#558 round-3 hardening: without the registry row, a downstream
  consumer that walks the SSSOM by ``subject_label`` resolves the MIM
  child to its OBO parent (identity collapse).

  **Strict by default**: B1 contributes to exit-2 and the reject TSV
  on every run. The original warn-only stage shipped with PR #4 to
  let the validator land alongside the rest of Group B while the
  kg-microbe registry was being minted. The 162-subject backlog was
  cleared in the follow-up by extending the claw SSSOM builder
  (``culturebotai-claw/scripts/build_mim_ingredient_sssom.py``,
  ``_row_from_yaml``) to synthesize the registry row whenever any
  narrow/broad parent row is emitted. ``--lenient-b1`` is available
  as a diagnostic escape valve (downgrades B1 to warn-only) and the
  legacy ``--strict-b1`` opt-in flag is accepted as a no-op so
  existing tooling keeps working.

* **Rule B2** — at most one row per ``(subject_id, object_id)`` pair.
  Group all rows by tuple; any pair with > 1 row is a violation.
  Catches double-typed rows like ``(MIM:X exactMatch Y)`` +
  ``(MIM:X narrowMatch Y)``. Every row in a duplicated group is
  rejected.

* **Rule B3** — asymmetric child→parent only. For every
  ``(subject_id, object_id)`` pair appearing in any
  ``skos:narrowMatch`` (or ``skos:broadMatch``) row, verify no
  ``skos:exactMatch`` row exists for the same pair. Cross-row variant
  of B2 (catches the case where rows differ in trivia such as
  whitespace but share the same subject+object tuple).

* **Rule B5** — one local registry namespace. A subject may use
  ``kgmicrobe.ingredient:<slug>`` or ``kgmicrobe.compound:<slug>`` as
  its Rule B1 registry identity, but not both for the same lowercased
  MIM slug. The two namespaces distinguish prepared ingredients from
  compounds; emitting both asserts two local identities for one
  subject.

* **Rule C** — every published row names the source its object came from
  (non-empty ``object_source``).

* **Rule D** — a row whose ``object_id`` is the subject record's own
  ``identifier`` must be ``skos:exactMatch``. That row asserts identity;
  publishing it as ``closeMatch`` says a record is merely similar to itself.
  448 rows did (#438). ``mapping_quality`` grades the *ontology grounding* and
  must not reach this row's predicate.

* **Rule E** — a synonym entry typed ``REJECTED_LABEL`` is provenance-only.
  Its text must not appear in any published SSSOM ``other`` cell for that MIM
  subject. This keeps a reviewed false alias from returning through an
  enrichment rebuild.

* **Rule F** — every published row carries a `mapping_date` of the form
  ``YYYY-MM-DD``. The builder emits an empty cell when a record has no
  parseable ``curation_history`` timestamp (#542); nothing else in the repo or
  in ``sssom`` rejects that, so a dateless row would otherwise ship
  silently (#550).

* **Rule J** — non-resolving text such as ``Original amount: ...`` or bare
  parenthetical fragments is not published as SSSOM ``other`` synonyms. Those
  notes are not names a record answers to, and kg-microbe merges ``other`` into
  synonym sets.

* **Rule B4** — canonical ``object_label`` drift. For every row whose
  ``object_id`` prefix is in ``{CHEBI, FOODON, UBERON, ENVO, BTO,
  MICRO, PATO}``, look up the canonical label in the local sibling
  kg-microbe checkout at
  ``../kg-microbe/data/transformed/ontologies/{prefix_lc}_nodes.tsv``.
  If the file is absent (the typical case in CI — kg-microbe's
  ontology transforms are not checked into its repo), Rule B4 emits a
  single warning to stderr and skips entirely; it does NOT contribute
  to exit-2 in that case. If the file is present and ``object_label``
  matches neither the canonical name (column 3) nor any pipe-delimited
  exact-synonym (column 7), the row is rejected.

Rejected rows are written to ``mappings/needs_curator_review.tsv`` with
the same column shape as the source SSSOM plus a trailing
``reject_reason`` column. Workflow: fix the row in MIM (re-emit via the
claw builder) or leave it in the triage TSV; CI fails as long as a
violating row sits in ``ingredient_mappings.sssom.tsv``.

Exit codes:
  0 — every row passes Rules A, B1, B2, B3, B5, C, D, E, F, G, H, I, J, K, L, and
      (when its label source is present) B4.
  2 — at least one row failed Rule A, B1, B2, B3, B5, B4, C, D, E, F, G, H, I or
      J. (B1 contributes to exit-2 unless ``--lenient-b1`` is passed.)
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections.abc import Iterable, Iterator
from functools import cache, lru_cache
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
_SRC = REPO_ROOT / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from mediaingredientmech.synonym_policy import is_resolving_synonym_text  # noqa: E402

DEFAULT_SSSOM = REPO_ROOT / "mappings" / "ingredient_mappings.sssom.tsv"
DEFAULT_REJECT_TSV = REPO_ROOT / "mappings" / "needs_curator_review.tsv"
INGREDIENTS_DIR = REPO_ROOT / "data" / "ingredients" / "mapped"

# Local sibling kg-microbe checkout — Rule B4 reads canonical labels
# from <prefix>_nodes.tsv files here. Absent in CI; warn-and-skip then.
KGM_TRANSFORMS_DIR = REPO_ROOT.parent / "kg-microbe" / "data" / "transformed" / "ontologies"

AUTO_PIPELINE_TAGS = frozenset({
    "MIM:curator=auto_classify_ingredient_type",
    "MIM:curator=backfill_parent_terms",
})
CURATOR_TAG_PREFIX = "MIM:curator="
CONFIDENCE_TIER = 0.95

# Rule B1: predicates that trigger the registry-row requirement. The
# registry CURIE must match this regex (slug_lc filled in per-subject).
ASYMMETRIC_PREDICATES = frozenset({"skos:narrowMatch", "skos:broadMatch"})
_REGISTRY_OBJECT_RE = re.compile(r"^kgmicrobe\.(ingredient|compound):(.+)$")

# Rule B4: only these object_id prefixes are looked up against
# kg-microbe ontology transforms. Other prefixes (cas:, mesh:, NCIT,
# kgmicrobe.*) have no canonical label source local to this repo.
B4_PREFIXES = frozenset({"CHEBI", "FOODON", "UBERON", "ENVO", "BTO", "MICRO", "PATO"})


# ---------------------------------------------------------------------------
# Token-overlap heuristic — copied verbatim from
# culturebotai-claw/scripts/foodon_pass.py:64-105 to keep this validator
# stdlib-only. Any change there should be mirrored here.
# ---------------------------------------------------------------------------
_STOP_TOKENS = frozenset({
    "the", "a", "an", "of", "and", "or", "in", "on", "with",
    # Domain-stop words that appear in many media names but say nothing
    # specific (a match on these alone is too generic):
    "no", "nr", "type", "grade", "form", "powder", "solution",
    "extract", "broth", "infusion", "agar",
})


def _tokens(s: str) -> set[str]:
    """Lowercase tokens (alpha runs of length >= 2), minus stop words."""
    return {t for t in re.findall(r"[A-Za-z]{2,}", (s or "").lower())
            if t not in _STOP_TOKENS}


# ---------------------------------------------------------------------------
# Lazy MIM YAML chemistry lookup — minimal regex parser, no PyYAML.
# The validator only needs the truthiness of two flat scalar keys nested
# under the ``chemical_properties:`` block: ``cas_rn`` and ``pubchem_cid``
# (the schema name; the spec calls it ``pubchem`` — both spellings are
# accepted to be robust to either source).
# ---------------------------------------------------------------------------
_CHEM_BLOCK_RE = re.compile(
    r"^chemical_properties:\s*$(.*?)(?=^\S|\Z)",
    re.MULTILINE | re.DOTALL,
)
_SCALAR_RE = re.compile(r"^\s+(\w+):\s*(.+?)\s*$", re.MULTILINE)


# `curie.py::mim_curie_for_stem` escapes any character outside this set as
# `~HEX`. Inlined rather than imported to keep the validator stdlib-only; any
# change there must be mirrored here.
_STEM_UNSAFE_RE = re.compile(r"[^A-Za-z0-9_\-.]")


@lru_cache(maxsize=1)
def _subject_to_path() -> dict[str, Path]:
    """`MIM:<escaped stem>` -> the record file, built by escaping every stem.

    Built forwards, from the filenames, because the `~HEX` escape is
    variable-width (`f"~{ord(c):02X}"` — `02` is a *minimum*) and therefore
    ambiguous to decode: `~3911` is `chr(0x391) + "1"`, and nothing in the
    string says so. Encoding each real stem has no such ambiguity.

    This is why the naive `subject_id[4:]` it replaces was wrong: it looked for
    `~28R~29-lactate.yaml` when the file is `(R)-lactate.yaml`. All 19 escaped
    subjects in the published set resolved to nothing, which silently disabled
    Rule A's registry-corroboration tier for them and would have done the same
    to Rule D.
    """
    index: dict[str, Path] = {}
    for path in INGREDIENTS_DIR.glob("*.yaml"):
        escaped = _STEM_UNSAFE_RE.sub(lambda m: f"~{ord(m.group(0)):02X}", path.stem)
        index[f"MIM:{escaped}"] = path
    return index


def _yaml_path_for_subject(subject_id: str) -> Path:
    """Map ``MIM:<slug>`` -> ``data/ingredients/mapped/<slug>.yaml``.

    Returns the literal-stem path when the subject is not in the index, so
    callers keep their existing "missing file" behaviour rather than raising.
    """
    hit = _subject_to_path().get(subject_id)
    if hit is not None:
        return hit
    if not subject_id.startswith("MIM:"):
        return INGREDIENTS_DIR / f"{subject_id}.yaml"
    return INGREDIENTS_DIR / f"{subject_id[4:]}.yaml"


def has_registry_chemistry(subject_id: str) -> bool:
    """True iff the subject's YAML carries a non-empty ``cas_rn`` or
    ``pubchem_cid`` (a.k.a. ``pubchem``) under ``chemical_properties:``.

    Intentionally tolerant: returns False on missing-file / parse-error.
    """
    path = _yaml_path_for_subject(subject_id)
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return False
    block_match = _CHEM_BLOCK_RE.search(text)
    if not block_match:
        return False
    block = block_match.group(1)
    for key, value in _SCALAR_RE.findall(block):
        if key not in ("cas_rn", "pubchem_cid", "pubchem"):
            continue
        v = value.strip().strip('"').strip("'")
        if v and v.lower() not in ("null", "~", "none"):
            return True
    return False


# ---------------------------------------------------------------------------
# SSSOM I/O — handle the YAML-prelude header block by streaming until the
# first non-comment line, which is the column header.
# ---------------------------------------------------------------------------
def _read_sssom(path: Path) -> tuple[list[str], list[str], list[dict[str, str]]]:
    """Return (prelude_lines, fieldnames, rows). Prelude lines start with
    '#' and are preserved verbatim for round-trip writing."""
    prelude: list[str] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        header_line: str | None = None
        for line in f:
            if line.startswith("#"):
                prelude.append(line.rstrip("\n"))
                continue
            header_line = line.rstrip("\n")
            break
        if header_line is None:
            raise ValueError(f"{path}: no column header found")
        fieldnames = header_line.split("\t")
        reader = csv.DictReader(f, fieldnames=fieldnames, delimiter="\t")
        rows = [dict(r) for r in reader]
    return prelude, fieldnames, rows


def _write_reject_tsv(
    path: Path,
    prelude: list[str],
    fieldnames: list[str],
    rejects: list[tuple[dict[str, str], str]],
) -> None:
    """Write the rejects to ``needs_curator_review.tsv`` with the SSSOM
    prelude preserved and an extra trailing ``reject_reason`` column."""
    out_fields = list(fieldnames) + ["reject_reason"]
    with path.open("w", encoding="utf-8", newline="") as f:
        for line in prelude:
            f.write(line + "\n")
        writer = csv.DictWriter(
            f, fieldnames=out_fields, delimiter="\t", extrasaction="ignore",
            lineterminator="\n",
        )
        writer.writeheader()
        for row, reason in rejects:
            out = dict(row)
            out["reject_reason"] = reason
            writer.writerow(out)


# ---------------------------------------------------------------------------
# Rule A
# ---------------------------------------------------------------------------
def _is_auto_classifier_only(source: str) -> bool:
    """True iff every pipe-separated tag in ``source`` is a
    ``MIM:curator=...`` automation stamp AND at least one is one of the
    declared auto-pipeline tags. A non-curator tag (``MIM:CultureBotHT``,
    ``MIM:cbclaw_review_fix``, ``MIM:CultureMech``, ``MIM:manual review …``,
    etc.) means a human touched the row — accept."""
    tags = [t.strip() for t in (source or "").split("|") if t.strip()]
    if not tags:
        return False
    if not all(t.startswith(CURATOR_TAG_PREFIX) for t in tags):
        return False
    # at least one tag is a declared auto-classifier pipeline
    return any(t in AUTO_PIPELINE_TAGS for t in tags)


def _confidence(row: dict[str, str]) -> float:
    raw = (row.get("confidence") or "").strip()
    if not raw:
        return 0.0
    try:
        return float(raw)
    except ValueError:
        return 0.0


def evaluate_rule_a(rows: Iterable[dict[str, str]]) -> Iterator[tuple[int, dict[str, str], str]]:
    """Yield ``(row_number, row, reason)`` for every Rule A reject.
    Row numbers are 1-based, counting from the data row (header is row 0)."""
    for idx, row in enumerate(rows, start=1):
        source = row.get("source", "") or ""
        if not _is_auto_classifier_only(source):
            continue  # human-touched — accept

        # tier 1: high confidence
        if _confidence(row) >= CONFIDENCE_TIER:
            continue

        # tier 2: token-overlap on labels
        sl = _tokens(row.get("subject_label", ""))
        ol = _tokens(row.get("object_label", ""))
        if sl & ol:
            continue

        # tier 3: registry corroboration via subject YAML
        subject_id = (row.get("subject_id") or "").strip()
        if subject_id and has_registry_chemistry(subject_id):
            continue

        reason = (
            "auto-classifier row with confidence<0.95, zero token overlap "
            "between subject_label and object_label, and no CAS/PubChem "
            "corroboration in subject YAML"
        )
        yield idx, row, reason


# ---------------------------------------------------------------------------
# Rule B1 — mandatory registry/identity row
# ---------------------------------------------------------------------------
def _registry_slug_for(subject_id: str) -> str | None:
    """``MIM:Vermont_Soil`` -> ``vermont_soil``. None if not a MIM CURIE."""
    if not subject_id.startswith("MIM:"):
        return None
    return subject_id[4:].lower()


def _has_registry_row(rows: list[dict[str, str]], subject_id: str) -> bool:
    """True iff some row has ``subject_id == subject_id``,
    ``predicate_id == 'skos:exactMatch'``, and ``object_id`` matching
    ``^kgmicrobe\\.(ingredient|compound):<slug_lc>$`` for the subject's
    lowercased slug."""
    slug = _registry_slug_for(subject_id)
    if slug is None:
        return False
    for r in rows:
        if (r.get("subject_id") or "").strip() != subject_id:
            continue
        if (r.get("predicate_id") or "").strip() != "skos:exactMatch":
            continue
        m = _REGISTRY_OBJECT_RE.match((r.get("object_id") or "").strip())
        if m and m.group(2) == slug:
            return True
    return False


def _other_exact_match_targets(
    rows: list[dict[str, str]], subject_id: str
) -> list[str]:
    """Return every ``object_id`` that the subject is exactMatch'd to,
    excluding the kgmicrobe.* registry shape. Used by Rule B1's reject
    message so curators see at a glance whether the subject already has
    a CAS-RN / mesh / NCIT exactMatch and only the kg-microbe registry
    row is missing (vs. having no exactMatch row at all)."""
    out: list[str] = []
    for r in rows:
        if (r.get("subject_id") or "").strip() != subject_id:
            continue
        if (r.get("predicate_id") or "").strip() != "skos:exactMatch":
            continue
        oid = (r.get("object_id") or "").strip()
        if not oid:
            continue
        if _REGISTRY_OBJECT_RE.match(oid):
            continue
        out.append(oid)
    return out


def evaluate_rule_b1(
    rows: list[dict[str, str]],
) -> Iterator[tuple[int, dict[str, str], str]]:
    """Yield ``(row_number, row, reason)`` for every narrowMatch /
    broadMatch row whose subject lacks a matching registry row.

    A subject with N narrow/broad rows but no registry row produces N
    rejects (one per offending row), so curators see every row that
    needs to move out of the main TSV until the registry row is added.
    """
    # subject_id -> True if registry row exists; cached because we may
    # ask many times per subject.
    cache: dict[str, bool] = {}
    for idx, row in enumerate(rows, start=1):
        predicate = (row.get("predicate_id") or "").strip()
        if predicate not in ASYMMETRIC_PREDICATES:
            continue
        subject_id = (row.get("subject_id") or "").strip()
        if not subject_id.startswith("MIM:"):
            continue
        if subject_id not in cache:
            cache[subject_id] = _has_registry_row(rows, subject_id)
        if cache[subject_id]:
            continue
        slug = _registry_slug_for(subject_id) or "?"
        other_targets = _other_exact_match_targets(rows, subject_id)
        if other_targets:
            other_hint = (
                f" (subject has non-registry exactMatch row(s) to "
                f"{', '.join(other_targets)} — those are not the "
                f"kg-microbe registry CURIE Rule B1 requires)"
            )
        else:
            other_hint = " (subject has no exactMatch row at all)"
        reason = (
            f"Rule B1: missing registry row for {subject_id}. A "
            f"{predicate} row requires a sibling 'skos:exactMatch' row "
            f"with object_id matching kgmicrobe.(ingredient|compound):"
            f"{slug}.{other_hint} Mint the registry CURIE and re-emit "
            f"the SSSOM."
        )
        yield idx, row, reason


# ---------------------------------------------------------------------------
# Rule B2 — at most one row per (subject_id, object_id)
# ---------------------------------------------------------------------------
def evaluate_rule_b2(
    rows: list[dict[str, str]],
) -> Iterator[tuple[int, dict[str, str], str]]:
    """Yield every row that participates in a duplicated
    ``(subject_id, object_id)`` group. All rows in a group of size > 1
    are rejected — fixing one without checking the other lets the
    contradiction live on, so curators must look at every row."""
    groups: dict[tuple[str, str], list[tuple[int, dict[str, str]]]] = {}
    for idx, row in enumerate(rows, start=1):
        key = (
            (row.get("subject_id") or "").strip(),
            (row.get("object_id") or "").strip(),
        )
        groups.setdefault(key, []).append((idx, row))
    for (subj, obj), members in groups.items():
        if len(members) <= 1:
            continue
        predicates = sorted({
            (r.get("predicate_id") or "").strip() for _, r in members
        })
        for idx, row in members:
            reason = (
                f"Rule B2: duplicate (subject_id, object_id) pair "
                f"({subj}, {obj}) appears in {len(members)} rows under "
                f"predicate(s) {predicates}. At most one row per pair "
                f"is allowed; pick the correct predicate and remove the "
                f"others."
            )
            yield idx, row, reason


# ---------------------------------------------------------------------------
# Rule B3 — asymmetric child→parent disjoint from exactMatch
# ---------------------------------------------------------------------------
def evaluate_rule_b3(
    rows: list[dict[str, str]],
) -> Iterator[tuple[int, dict[str, str], str]]:
    """Yield every narrow/broad row whose ``(subject_id, object_id)``
    pair also appears under ``skos:exactMatch`` in some other row.
    B2 catches this when both rows live in the file with identical
    tuples; B3 is the cross-row variant where the rows might differ in
    columns other than subject_id/object_id."""
    exact_pairs: set[tuple[str, str]] = set()
    for row in rows:
        if (row.get("predicate_id") or "").strip() != "skos:exactMatch":
            continue
        exact_pairs.add((
            (row.get("subject_id") or "").strip(),
            (row.get("object_id") or "").strip(),
        ))
    for idx, row in enumerate(rows, start=1):
        predicate = (row.get("predicate_id") or "").strip()
        if predicate not in ASYMMETRIC_PREDICATES:
            continue
        key = (
            (row.get("subject_id") or "").strip(),
            (row.get("object_id") or "").strip(),
        )
        if key not in exact_pairs:
            continue
        reason = (
            f"Rule B3: ({key[0]}, {key[1]}) is asserted under both "
            f"{predicate} and skos:exactMatch — incompatible. The two "
            f"predicates are mutually exclusive for the same pair: "
            f"narrowMatch is parent/child, exactMatch is identity. "
            f"Pick one."
        )
        yield idx, row, reason


# ---------------------------------------------------------------------------
# Rule B5 — one local registry namespace
# ---------------------------------------------------------------------------
def evaluate_rule_b5(
    rows: list[dict[str, str]],
) -> Iterator[tuple[int, dict[str, str], str]]:
    """Reject subjects that exact-match both kg-microbe local namespaces."""
    registry: dict[tuple[str, str], dict[str, list[tuple[int, dict[str, str]]]]] = {}
    for idx, row in enumerate(rows, start=1):
        if (row.get("predicate_id") or "").strip() != "skos:exactMatch":
            continue
        subject_id = (row.get("subject_id") or "").strip()
        if not subject_id.startswith("MIM:"):
            continue
        match = _REGISTRY_OBJECT_RE.match((row.get("object_id") or "").strip())
        if match is None:
            continue
        namespace, slug = match.groups()
        registry.setdefault((subject_id, slug.casefold()), {}).setdefault(
            namespace,
            [],
        ).append((idx, row))

    for (subject_id, slug), by_namespace in registry.items():
        if not {"compound", "ingredient"} <= by_namespace.keys():
            continue
        object_ids = sorted({
            (row.get("object_id") or "").strip()
            for members in by_namespace.values()
            for _, row in members
        })
        for members in by_namespace.values():
            for idx, row in members:
                reason = (
                    f"Rule B5: {subject_id} exact-matches both local registry "
                    f"namespaces for slug {slug}: {', '.join(object_ids)}. "
                    f"kgmicrobe.ingredient and kgmicrobe.compound distinguish "
                    f"prepared ingredients from compounds; pick the namespace "
                    f"that matches the curated ingredient_type and remove the "
                    f"other identity row."
                )
                yield idx, row, reason


# ---------------------------------------------------------------------------
# Rule B4 — canonical object_label drift
# ---------------------------------------------------------------------------
def _load_ontology_labels(prefix: str) -> dict[str, tuple[str, set[str]]] | None:
    """Load ``../kg-microbe/data/transformed/ontologies/<prefix_lc>_nodes.tsv``
    into a dict ``{id: (canonical_name, {synonyms})}``. Return None if
    the file is absent. Raises on a parse error (the file is expected
    to have a header row with ``id``, ``name``, ``synonym`` columns)."""
    path = KGM_TRANSFORMS_DIR / f"{prefix.lower()}_nodes.tsv"
    if not path.is_file():
        return None
    out: dict[str, tuple[str, set[str]]] = {}
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        if reader.fieldnames is None:
            return out
        for row in reader:
            term_id = (row.get("id") or "").strip()
            if not term_id:
                continue
            name = (row.get("name") or "").strip()
            syn_raw = (row.get("synonym") or "").strip()
            synonyms = {
                s.strip() for s in syn_raw.split("|") if s.strip()
            } if syn_raw else set()
            out[term_id] = (name, synonyms)
    return out


def evaluate_rule_b4(
    rows: list[dict[str, str]],
    *,
    transforms_present: dict[str, bool] | None = None,
) -> Iterator[tuple[int, dict[str, str], str]]:
    """Yield rows whose ``object_label`` doesn't match the canonical
    name or any exact synonym in the local kg-microbe ontology
    transform. Skips rows whose object_id prefix isn't in
    ``B4_PREFIXES`` and skips entirely (yields nothing) for any
    prefix whose transform file is absent — caller has already emitted
    the warn-and-skip stderr line.

    ``transforms_present`` is an optional caller-supplied dict
    populated by load attempts so the caller can decide which prefixes
    to warn about. When None, this function loads transforms lazily
    and silently skips absent ones."""
    cache: dict[str, dict[str, tuple[str, set[str]]] | None] = {}
    for idx, row in enumerate(rows, start=1):
        object_id = (row.get("object_id") or "").strip()
        if ":" not in object_id:
            continue
        prefix = object_id.split(":", 1)[0]
        if prefix not in B4_PREFIXES:
            continue
        if prefix not in cache:
            cache[prefix] = _load_ontology_labels(prefix)
        labels = cache[prefix]
        if labels is None:
            continue  # warn-and-skip handled by caller
        if object_id not in labels:
            continue  # term not in transform — out of B4 scope
        canonical_name, synonyms = labels[object_id]
        if not canonical_name and not synonyms:
            # Term is in the transform but has no name and no synonyms
            # (e.g. an upper-level CHEBI placeholder). We have no
            # canonical label to compare against — skip to avoid false
            # positives.
            continue
        object_label = (row.get("object_label") or "").strip()
        if canonical_name and object_label == canonical_name:
            continue
        if object_label in synonyms:
            continue
        reason = (
            f"Rule B4: object_label '{object_label}' does not match "
            f"the canonical name '{canonical_name}' for {object_id} "
            f"and is not in the term's exact-synonym set. Use the "
            f"OBO-published label or a registered synonym."
        )
        yield idx, row, reason


def evaluate_rule_c(
    rows: Iterable[dict[str, str]]
) -> Iterator[tuple[int, dict[str, str], str]]:
    """Rule C — every published row names the source its object came from.

    `object_source` is how a consumer knows which ontology or registry to
    resolve `object_id` against. An empty cell publishes an identifier with no
    stated origin.

    This exists because the failure is silent by construction. The writers look
    the value up with `OBJECT_SOURCE.get(prefix, "")`, so an unlisted prefix
    does not raise — it emits an empty column and everything downstream keeps
    working. MICRO was absent from that table until #381, which meant any MICRO
    promotion through `promote_resolved_unmapped` (or the script that imports
    its table) would have published blank-sourced rows alongside the 51 correct
    `obo:micro.owl` rows already in the file. It never fired only because those
    rows happened to be written by a path carrying a local override.

    A missing prefix is a one-line fix; noticing it is the hard part. So assert
    the property rather than trusting the table to stay complete.
    """
    for row_num, row in enumerate(rows, start=1):
        if (row.get("object_source") or "").strip():
            continue
        yield (
            row_num,
            row,
            f"empty object_source for object_id "
            f"{row.get('object_id', '?')!r} — the writer's prefix table is "
            f"missing this prefix, so the row was published with no stated "
            f"origin (#381)",
        )


# ---------------------------------------------------------------------------
# Rule D — a row pointing at the record's own identifier must be exactMatch
# ---------------------------------------------------------------------------
_IDENTIFIER_RE = re.compile(r"^identifier:\s*(\S+)\s*$", re.MULTILINE)


@cache
def record_identifier(subject_id: str) -> str | None:
    """The `identifier:` of the subject's YAML, or None if unreadable.

    Deliberately a regex over the top-level key rather than a YAML parse:
    `identifier` is always a top-level scalar and this is asked once per row.
    Tolerant of a missing file, like `has_registry_chemistry` — a subject with
    no record is Rule B1 / #300 territory, not this rule's business.
    """
    try:
        text = _yaml_path_for_subject(subject_id).read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return None
    m = _IDENTIFIER_RE.search(text)
    return m.group(1).strip().strip('"').strip("'") if m else None



_MAPPING_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def evaluate_rule_f(
    rows: Iterable[dict[str, str]]
) -> Iterator[tuple[int, dict[str, str], str]]:
    """Rule F — every published row carries a real `mapping_date`.

    The builder derives this from the record's latest `curation_history`
    timestamp. When no entry has a parseable one it emits an empty cell and
    warns, which is deliberate: it used to fall back to the file's mtime, and
    since git does not preserve mtimes that stamped records with whenever the
    machine happened to clone (#542).

    Empty is the honest answer, but on its own it is not much better than the
    wrong one. Nothing else checks this column -- the shared contract does not
    mention it, and the `sssom` package accepts a blank cell, verified by
    blanking one on a real published row and running its JSON-schema validation
    clean. The builder's warning is a single line in a log that runs to
    hundreds, so a blank date would ship through every gate the repo has (#550).

    A row without a date cannot be ordered against its siblings or audited for
    staleness, and the record behind it is missing the `curation_history` event
    CLAUDE.md requires on every material change. That is a curation defect, so
    route it to the curator review file like any other reject.
    """
    for row_num, row in enumerate(rows, start=1):
        value = (row.get("mapping_date") or "").strip()
        if _MAPPING_DATE_RE.match(value):
            continue
        detail = "empty" if not value else f"{value!r}"
        yield (
            row_num,
            row,
            f"mapping_date is {detail} for subject "
            f"{row.get('subject_id', '?')!r} — the record has no parseable "
            f"curation_history timestamp, so the builder had no date to "
            f"publish (#550)",
        )


PREDICATE_SEMANTICS_KEY = "predicate_semantics"
SKOS_SEMANTICS = "skos"


def declared_predicate_semantics(prelude: Iterable[str]) -> str:
    """
    Return the set's top-level ``predicate_semantics`` declaration, or ``""``.

    Parsed the way kg-microbe's reader parses it, deliberately: a top-level key
    is ``# key: value`` with exactly one space after the ``#``. SSSOM headers
    are nested YAML, so a key of this name under some parent means something
    else, and a gate that accepted it would pass a file the consumer reads as
    legacy.

    :param prelude: The ``#`` header lines of the mapping set.
    :return: The declared value, or the empty string when absent.
    """
    for line in prelude:
        if not line.startswith("#"):
            continue
        body = line[1:].rstrip("\n")
        if body[:1] not in ("", " ") or body[1:2] == " ":
            continue
        stripped = body.strip()
        if stripped.startswith(f"{PREDICATE_SEMANTICS_KEY}:"):
            return stripped.split(":", 1)[1].strip().strip("\"'")
    return ""


def evaluate_rule_l(
    prelude: Iterable[str], rows: Iterable[dict[str, str]]
) -> Iterator[tuple[int, dict[str, str], str]]:
    """Rule L — the set declares that its asymmetric predicates follow SKOS.

    Since #390 a parent-anchoring row is ``skos:broadMatch``, which is what the
    spec says and the inverse of what MIM published before. kg-microbe reads
    the direction from one header line, ``# predicate_semantics: skos``, and
    treats its absence as the legacy inverted convention. So the declaration is
    load-bearing: strip that line from the flipped set and every parent edge
    inverts -- measured, 166 of 166, with ontology terms becoming children of
    MIM records.

    The rows and the declaration live in one file, which makes them atomic on
    publication, but nothing made them atomic on *rebuild*: a generator that
    wrote the new rows under an old header would produce exactly that inverted
    set, and every other rule would pass it.
    """
    declared = declared_predicate_semantics(prelude)
    if declared == SKOS_SEMANTICS:
        return
    asymmetric = sum(
        1 for row in rows if (row.get("predicate_id") or "").strip() in ASYMMETRIC_PREDICATES
    )
    yield (
        0,
        {},
        f"Rule L: the header does not declare `{PREDICATE_SEMANTICS_KEY}: "
        f"{SKOS_SEMANTICS}` at the top level (found {declared!r}). A consumer "
        f"treats absence as the legacy inverted convention and would read all "
        f"{asymmetric} asymmetric row(s) backwards. Add "
        f"`# {PREDICATE_SEMANTICS_KEY}: {SKOS_SEMANTICS}` to the header (#390).",
    )


def evaluate_rule_g(
    prelude: Iterable[str], rows: Iterable[dict[str, str]]
) -> Iterator[tuple[int, dict[str, str], str]]:
    """Rule G — the header's set version matches the newest row it describes.

    `mapping_set_version` is what an SSSOM consumer caches on: it decides
    whether the copy it holds is current. Nothing bumped it, so it was
    hand-edited and therefore wrong most of the time -- the header read
    2026-08-06 while two later commits had changed the rows underneath it
    (#301). A version that does not move is worse than no version, because a
    consumer reads it as "unchanged".

    Checking it against the clock would make the file un-reproducible, which is
    the defect kg-microbe fixed in its own artifact. So the anchor is the data:
    the header must equal the newest `mapping_date` in the set. That moves when
    and only when the mappings move.
    """
    dates = sorted(
        value
        for row in rows
        if _MAPPING_DATE_RE.match(value := (row.get("mapping_date") or "").strip())
    )
    if not dates:
        return
    newest = dates[-1]
    declared = {}
    for line in prelude:
        for field in ("mapping_set_version", "mapping_date"):
            marker = f"# {field}:"
            if line.startswith(marker):
                declared[field] = line[len(marker):].strip().strip('"')
    for field, value in sorted(declared.items()):
        if value != newest:
            yield (
                0,
                {"subject_id": f"(header {field})"},
                f"header {field} is {value!r} but the newest row mapping_date "
                f"is {newest!r} — a consumer caching on the version would not "
                f"see this set as changed (#301). Fix: just bump-sssom-header",
            )


def evaluate_rule_h(
    rows: Iterable[dict[str, str]]
) -> Iterator[tuple[int, dict[str, str], str]]:
    """Rule H — one published label belongs to one record.

    Two records publishing the same `subject_label` make the label ambiguous
    for anything that resolves by name, which is what CultureMech and the label
    index do (#504, #232). A record legitimately publishes several rows -- its
    ontology row plus its registry identity rows -- so the check is on distinct
    *subjects* sharing a label, never on row count.
    """
    by_label: dict[str, set[str]] = {}
    first_seen: dict[str, tuple[int, dict[str, str]]] = {}
    for row_num, row in enumerate(rows, start=1):
        label = (row.get("subject_label") or "").strip().lower()
        if not label:
            continue
        subject = (row.get("subject_id") or "").strip()
        by_label.setdefault(label, set()).add(subject)
        first_seen.setdefault(label, (row_num, row))
    for label, subjects in sorted(by_label.items()):
        if len(subjects) > 1:
            row_num, row = first_seen[label]
            yield (
                row_num,
                row,
                f"label {label!r} is published by {len(subjects)} distinct "
                f"subjects ({', '.join(sorted(subjects))}) — a name-based "
                f"consumer cannot tell which record is meant (#504)",
            )


def evaluate_rule_i(
    rows: Iterable[dict[str, str]]
) -> Iterator[tuple[int, dict[str, str], str]]:
    """Rule I — the `other` column does not repeat a synonym.

    kg-microbe merges `other` into the entity's synonym set, so a repeated
    token inflates every count taken over it and wastes a slot in the cap the
    builder applies (#529). Comparison is case-insensitive, because that is how
    the consumer indexes them.
    """
    for row_num, row in enumerate(rows, start=1):
        tokens = [t.strip() for t in (row.get("other") or "").split("|") if t.strip()]
        if not tokens:
            continue
        seen: set[str] = set()
        repeated = sorted({t for t in tokens if t.lower() in seen or seen.add(t.lower())})
        if repeated:
            yield (
                row_num,
                row,
                f"other repeats {', '.join(repr(r) for r in repeated)} for "
                f"subject {row.get('subject_id', '?')!r} — the consumer merges "
                f"this column into a synonym set (#529)",
            )


def evaluate_rule_j(
    rows: Iterable[dict[str, str]]
) -> Iterator[tuple[int, dict[str, str], str]]:
    """Rule J — the `other` column does not publish non-resolving text."""
    for row_num, row in enumerate(rows, start=1):
        tokens = [t.strip() for t in (row.get("other") or "").split("|") if t.strip()]
        non_resolving = sorted(
            {token for token in tokens if not is_resolving_synonym_text(token)},
            key=str.casefold,
        )
        if not non_resolving:
            continue
        yield (
            row_num,
            row,
            "Rule J: non-resolving curation text was published through "
            f"`other`: {non_resolving}. Remove it from the mapped record's "
            "synonyms; SSSOM `other` is merged into downstream synonym sets "
            "(#502/#610).",
        )


OTHER_BASELINE = REPO_ROOT / "mappings" / "other_cross_record_baseline.tsv"


@lru_cache(maxsize=1)
def _preferred_term_owners() -> dict[str, frozenset[str]]:
    """
    Map a casefolded ``preferred_term`` to the subjects that own it.

    Built from every active mapped-directory record rather than from the SSSOM's own
    ``subject_label`` values: a record whose label never appears as a subject
    label still owns its name, and keying on the published labels alone misses
    44% of the cross-record cases (64 of 115).

    A REJECTED record under mapped/ is a merge tombstone, and a merge moves the
    name to its target -- so ``MIM:Acetate`` carrying "Acetate (carbon source)"
    is the rightful holder, not a thief (#669). The name is therefore credited
    to the live record(s) named by its explicit ``representative``. Legacy
    tombstones without that field use their ``identifier`` instead. A reviewed
    merge may preserve the loser's former, incorrect identifier as provenance;
    that old identifier must not override the corrected representative (#721).

    Credited, not dropped. Dropping it -- the first version of this fix -- left
    the name with no owner at all, so *any* record could publish it unflagged:
    ``MIM:Feso4`` carrying a heptahydrate tombstone's name passed, where on
    ``main`` it was caught. And "REJECTED means merged" is an observed fact about
    the corpus, not an enforced invariant, so a REJECTED record with no live
    target keeps its own name rather than losing it. An explicit representative
    that does not resolve never falls back to a different identifier owner.
    """
    records: list[tuple[str, dict]] = []
    for subject_id, path in _subject_to_path().items():
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        records.append((subject_id, data))

    def _rejected(data: dict) -> bool:
        return str(data.get("mapping_status") or "").strip().upper() == "REJECTED"

    live_by_identifier: dict[str, set[str]] = {}
    for subject_id, data in records:
        identifier = str(data.get("identifier") or "").strip()
        if identifier and not _rejected(data):
            live_by_identifier.setdefault(identifier, set()).add(subject_id)

    owners: dict[str, set[str]] = {}
    for subject_id, data in records:
        term = str(data.get("preferred_term") or "").strip()
        if not term:
            continue
        if _rejected(data):
            target = data.get("representative") if "representative" in data else data.get("identifier")
            targets = live_by_identifier.get(str(target or "").strip())
            owners.setdefault(term.casefold(), set()).update(targets or {subject_id})
        else:
            owners.setdefault(term.casefold(), set()).add(subject_id)
    return {term: frozenset(ids) for term, ids in owners.items()}


@lru_cache(maxsize=1)
def _other_baseline() -> frozenset[tuple[str, str]]:
    """
    Return the ``(subject_id, casefolded token)`` pairs already known to Rule K.

    `other` is generated in claw, so clearing a violation means a rebuild there
    rather than an edit here. The baseline lets the rule block new contamination
    while the known set is triaged, the way
    ``mappings/duplicate_identifier_baseline.tsv`` does for identifiers.
    """
    if not OTHER_BASELINE.exists():
        return frozenset()
    with OTHER_BASELINE.open(encoding="utf-8", newline="") as handle:
        return frozenset(
            (row["subject_id"], row["token"].casefold())
            for row in csv.DictReader(handle, delimiter="\t")
            if row.get("subject_id") and row.get("token")
        )


def evaluate_rule_k(
    rows: Iterable[dict[str, str]]
) -> Iterator[tuple[int, dict[str, str], str]]:
    """Rule K — `other` does not publish a name another record owns.

    kg-microbe merges `other` into the ontology entity's synonym set, so a token
    there is a name the subject answers to. When that token is another record's
    ``preferred_term``, two records claim one name and the distinction between
    them stops existing downstream -- which is how a monohydrate ends up
    answering to the anhydrous compound's name (#669).

    Most of `other` is kg-microbe's synonyms for the *ontology term*, so when a
    hydrate family shares one CHEBI parent the parent's synonyms are merged into
    every member and each claims its siblings' names. That is the generator's
    behaviour, not a curation slip, which is why the known set is baselined
    rather than failed outright.
    """
    owners = _preferred_term_owners()
    baseline = _other_baseline()
    for row_num, row in enumerate(rows, start=1):
        subject_id = (row.get("subject_id") or "").strip()
        offenders: list[str] = []
        for token in (row.get("other") or "").split("|"):
            token = token.strip()
            if not token:
                continue
            folded = token.casefold()
            holder = owners.get(folded)
            if not holder or subject_id in holder:
                continue
            if (subject_id, folded) in baseline:
                continue
            offenders.append(f"{token!r} (owned by {sorted(holder)[0]})")
        if not offenders:
            continue
        yield (
            row_num,
            row,
            "Rule K: `other` publishes a name another record owns: "
            f"{sorted(offenders)}. kg-microbe merges `other` into the synonym "
            "set, so both records would answer to it. Rebuild the SSSOM in claw "
            "after fixing the record's synonyms, or add the pair to "
            "mappings/other_cross_record_baseline.tsv with a disposition (#669).",
        )


def evaluate_rule_d(
    rows: Iterable[dict[str, str]]
) -> Iterator[tuple[int, dict[str, str], str]]:
    """Rule D — the identity row asserts identity, so it must say exactMatch.

    Every mapped record emits exactly one row whose ``object_id`` **is** the
    record's own ``identifier``. A record whose ``identifier`` is
    ``CHEBI:17634`` asserts "I am CHEBI:17634"; publishing that as
    ``skos:closeMatch`` says the record is merely similar to itself.

    448 rows said exactly that (#438), and the same ``mapping_quality``
    produced both predicates: ``EXACT_MATCH`` split 1597/38, ``SYNONYM_MATCH``
    230/11, ``CLOSE_MATCH`` 93/22, ``CAS_RN_LOOKUP`` 1/39. Meanwhile all 142
    ``NARROW_MATCH`` identity rows were ``exactMatch`` — correctly, because the
    narrowness describes the *ontology parent*, not the record's identity with
    its own primary id. Exactly backwards from the 38.

    Mechanism: the builder hard-codes ``exactMatch`` on the dual-emission
    registry row, but when a record's ``identifier`` equals its ``ontology_id``
    there is no second row — the parent row *is* the identity row, and it took
    the quality-derived predicate. All 448 came from that path, none from
    dual-emission.

    So ``mapping_quality`` must not reach the identity row's predicate. It
    grades the *ontology grounding*; identity with one's own primary identifier
    is not graded, it is definitional.
    """
    for row_num, row in enumerate(rows, start=1):
        predicate = (row.get("predicate_id") or "").strip()
        if predicate == "skos:exactMatch":
            continue
        subject_id = (row.get("subject_id") or "").strip()
        object_id = (row.get("object_id") or "").strip()
        if not subject_id.startswith("MIM:") or not object_id:
            continue
        if record_identifier(subject_id) != object_id:
            continue
        yield (
            row_num,
            row,
            f"Rule D: {subject_id} is published as {predicate} to "
            f"{object_id}, which is its own `identifier`. A record is not "
            f"merely close to itself — the identity row must be "
            f"skos:exactMatch. mapping_quality grades the ontology grounding "
            f"and must not reach this row's predicate (#438).",
        )


# ---------------------------------------------------------------------------
# Rule E — reviewed non-identity labels cannot be published as synonyms
# ---------------------------------------------------------------------------
@cache
def rejected_labels(subject_id: str) -> dict[str, str]:
    """Return ``casefolded text -> curated spelling`` for one MIM subject.

    A missing or unreadable record yields no labels, matching Rule D's tolerant
    lookup behavior. Subject/file coverage is checked independently.
    """
    try:
        data = yaml.safe_load(
            _yaml_path_for_subject(subject_id).read_text(encoding="utf-8")
        ) or {}
    except (OSError, yaml.YAMLError):
        return {}
    out: dict[str, str] = {}
    for synonym in data.get("synonyms") or []:
        if not isinstance(synonym, dict):
            continue
        if (synonym.get("synonym_type") or "").strip().upper() != "REJECTED_LABEL":
            continue
        text = (synonym.get("synonym_text") or "").strip()
        if text:
            out[text.casefold()] = text
    return out


def evaluate_rule_e(
    rows: Iterable[dict[str, str]],
) -> Iterator[tuple[int, dict[str, str], str]]:
    """Yield rows that publish a curator-rejected label through ``other``."""
    for row_num, row in enumerate(rows, start=1):
        subject_id = (row.get("subject_id") or "").strip()
        rejected = rejected_labels(subject_id)
        if not rejected:
            continue
        published = {
            token.strip().casefold()
            for token in (row.get("other") or "").split("|")
            if token.strip()
        }
        leaked = sorted(rejected[key] for key in rejected.keys() & published)
        if not leaked:
            continue
        yield (
            row_num,
            row,
            "Rule E: provenance-only REJECTED_LABEL value(s) were published "
            f"through `other`: {leaked}. Remove them from the SSSOM and make "
            "the enrichment builder honor the curated rejection (#464/#470).",
        )


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "sssom_path",
        nargs="?",
        type=Path,
        default=DEFAULT_SSSOM,
        help=f"path to SSSOM TSV (default: {DEFAULT_SSSOM.relative_to(REPO_ROOT)})",
    )
    p.add_argument(
        "--reject-tsv",
        type=Path,
        default=DEFAULT_REJECT_TSV,
        help=(
            "where to write rejected rows "
            f"(default: {DEFAULT_REJECT_TSV.relative_to(REPO_ROOT)})"
        ),
    )
    # Rule B1 is strict-by-default: every narrow/broadMatch subject must
    # carry a kgmicrobe.{ingredient,compound}:<slug_lc> registry
    # exactMatch row, enforced by exit-2. The B1 backlog (162 missing
    # registry rows that motivated the warn-only stage) was cleared by
    # the claw builder change in `scripts/build_mim_ingredient_sssom.py`
    # (`_row_from_yaml` now synthesizes the registry row whenever a
    # narrow/broad parent row is emitted). Pass `--lenient-b1` to
    # downgrade B1 back to warn-only; intended only for one-off curator
    # bisecting (e.g. when triaging which subjects regress after a
    # claw-side schema change). CI runs without `--lenient-b1` so
    # regressions block the merge.
    p.add_argument(
        "--lenient-b1",
        action="store_true",
        help=(
            "Downgrade Rule B1 (mandatory kgmicrobe.{ingredient,compound}: "
            "registry row) from a hard reject to warn-only. Default is "
            "strict: B1 violations contribute to exit-2 and the reject "
            "TSV. The lenient mode is provided for diagnostic use only "
            "(e.g. while bisecting which subjects regressed) and should "
            "never be used in CI. See MAPPING_SEMANTICS.md Section 2 "
            "for the registry-row contract."
        ),
    )
    # Backwards-compatible alias: --strict-b1 was the opt-in flag during
    # the warn-only stage. Now that strict is the default it's a no-op,
    # but accepting it keeps existing tooling/scripts that pass it
    # working. We don't surface it in --help to discourage new callers.
    p.add_argument(
        "--strict-b1",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    args = p.parse_args(argv[1:])
    # `--strict-b1` is redundant once strict is the default, but pin
    # `strict_b1` so the rest of the function doesn't have to reason
    # about three states.
    args.strict_b1 = not args.lenient_b1

    if not args.sssom_path.is_file():
        print(f"ERROR: SSSOM file not found at {args.sssom_path}", file=sys.stderr)
        return 1

    prelude, fieldnames, rows = _read_sssom(args.sssom_path)

    # Aggregate rejects across rules. A row may fail multiple rules; we
    # keep one entry per (row_number, rule) so the curator sees every
    # contributing reason. Insertion order = rule order = stable output.
    all_rejects: list[tuple[int, dict[str, str], str]] = []
    rule_counts: dict[str, int] = {}

    def _collect(label: str, gen: Iterable[tuple[int, dict[str, str], str]]) -> None:
        new = list(gen)
        if new:
            rule_counts[label] = len(new)
            all_rejects.extend(new)

    _collect("Rule A", evaluate_rule_a(rows))
    if args.strict_b1:
        _collect("Rule B1", evaluate_rule_b1(rows))
    else:
        # Lenient (diagnostic) B1: emit per-row warnings to stderr but
        # do not contribute to exit-2 or the reject TSV. Triggered only
        # by --lenient-b1; CI runs strict.
        b1_findings = list(evaluate_rule_b1(rows))
        if b1_findings:
            print(
                f"WARNING: Rule B1 (lenient mode, --lenient-b1): "
                f"{len(b1_findings)} narrowMatch/broadMatch row(s) "
                f"belong to a MIM subject that lacks a "
                f"kgmicrobe.{{ingredient,compound}}:<slug_lc> registry "
                f"exactMatch row. Drop --lenient-b1 (the default) to "
                f"convert these to hard rejects. First five:",
                file=sys.stderr,
            )
            for row_num, row, _reason in b1_findings[:5]:
                print(
                    f"  row {row_num}: {row.get('subject_id','?')} "
                    f"-> {row.get('object_id','?')}",
                    file=sys.stderr,
                )
    _collect("Rule B2", evaluate_rule_b2(rows))
    _collect("Rule B3", evaluate_rule_b3(rows))
    _collect("Rule B5", evaluate_rule_b5(rows))

    # Rule B4: warn-and-skip if any in-use prefix's transform is absent.
    # We probe each B4 prefix that actually appears in the SSSOM so the
    # warning lists exactly the prefixes that would have been checked.
    in_use_prefixes: set[str] = set()
    for r in rows:
        oid = (r.get("object_id") or "").strip()
        if ":" in oid:
            p = oid.split(":", 1)[0]
            if p in B4_PREFIXES:
                in_use_prefixes.add(p)
    missing_prefixes = sorted(
        p for p in in_use_prefixes
        if not (KGM_TRANSFORMS_DIR / f"{p.lower()}_nodes.tsv").is_file()
    )
    if missing_prefixes:
        print(
            f"WARNING: Rule B4 skipped — kg-microbe ontology transforms "
            f"not found at {KGM_TRANSFORMS_DIR} for prefix(es): "
            f"{', '.join(missing_prefixes)}. To enable Rule B4 locally, "
            f"check out kg-microbe at the sibling path and run its "
            f"`just transform` recipe. (CI typically lacks these "
            f"transforms; the validator does not exit-2 on B4 alone in "
            f"that case.)",
            file=sys.stderr,
        )
    if missing_prefixes != sorted(in_use_prefixes):
        # At least one prefix has its transform — run B4 over the rows;
        # _load_ontology_labels returns None for the missing prefixes
        # and evaluate_rule_b4 silently skips them.
        _collect("Rule B4", evaluate_rule_b4(rows))

    _collect("Rule C", evaluate_rule_c(rows))
    _collect("Rule D", evaluate_rule_d(rows))
    _collect("Rule E", evaluate_rule_e(rows))
    _collect("Rule F", evaluate_rule_f(rows))
    _collect("Rule G", evaluate_rule_g(prelude, rows))
    _collect("Rule H", evaluate_rule_h(rows))
    _collect("Rule I", evaluate_rule_i(rows))
    _collect("Rule J", evaluate_rule_j(rows))
    _collect("Rule K", evaluate_rule_k(rows))
    _collect("Rule L", evaluate_rule_l(prelude, rows))

    args.reject_tsv.parent.mkdir(parents=True, exist_ok=True)
    _write_reject_tsv(
        args.reject_tsv,
        prelude,
        fieldnames,
        [(row, reason) for _, row, reason in all_rejects],
    )

    try:
        reject_display = args.reject_tsv.resolve().relative_to(REPO_ROOT)
    except ValueError:
        reject_display = args.reject_tsv

    if not all_rejects:
        b1_label = "B1" if args.strict_b1 else "B1(lenient)"
        rule_summary = f"Rules A, {b1_label}, B2, B3, B5, C, D, E, F, G, H, I, J, K, L"
        if "Rule B4" in rule_counts or not missing_prefixes:
            rule_summary += ", B4"
        print(
            f"OK: {args.sssom_path.name} passed {rule_summary}. "
            f"{reject_display} written with header only."
        )
        return 0

    rule_summary = ", ".join(
        f"{rule}: {count}" for rule, count in rule_counts.items()
    )
    print(
        f"FAIL: {len(all_rejects)} reject(s) in {args.sssom_path.name} "
        f"({rule_summary}).",
        file=sys.stderr,
    )
    for row_num, row, reason in all_rejects:
        subject = row.get("subject_label", "?")
        subject_id = row.get("subject_id", "?")
        object_id = row.get("object_id", "?")
        object_label = row.get("object_label", "?")
        print(
            f"  row {row_num}: {subject_id} '{subject}' "
            f"-> {object_id} '{object_label}' — {reason}",
            file=sys.stderr,
        )
    print(
        f"\nRejects written to {reject_display}. "
        "Fix the offending row(s) in MIM (re-emit via the claw builder, "
        "mint the missing registry CURIE for B1, dedupe pairs for B2/B3, "
        "resolve B5 local namespace conflicts, update object_label for B4, "
        "or remove rejected labels for E), or "
        "remove the row from the SSSOM. "
        "CI fails while a violating row remains in "
        "ingredient_mappings.sssom.tsv.",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
