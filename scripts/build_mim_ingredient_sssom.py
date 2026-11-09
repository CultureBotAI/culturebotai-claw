"""
Build a diagnostic MIM → ingredient-ontology SSSOM candidate artifact set.

This candidate is not canonical promotion or scientific approval. Every
MediaIngredientMech record whose `ontology_mapping.ontology_id` starts
with a supported ingredient ontology prefix (CHEBI / FOODON; UBERON /
ENVO when populated) becomes one SSSOM row with:

  subject_id        MIM:<safe_stem>         -- stable per-YAML CURIE
  subject_label     preferred_term
  predicate_id      skos:exactMatch         -- default
                    skos:broadMatch         -- MIM is more specific; the object is
                                               the broader parent (SKOS reading,
                                               declared in the header; MIM#390)
                    skos:narrowMatch        -- MIM is less specific than the object
                    skos:closeMatch         -- SYMMETRIC (both defensible)
  object_id         <CHEBI|FOODON|...>:X
  object_label      canonical rdfs:label from OAK/OLS (fallback: MIM label)
  object_source     per-row ontology OWL URI (CHEBI/FOODON/... differ per row)
  mapping_justification  semapv:ManualMappingCuration | semapv:LexicalMatching
  source            MIM:<evidence>|MIM:curator=...|kgm:<sources>  (extension)
  mapping_date      latest valid curation-history calendar date (ISO)
  confidence        0.99 EXACT_MATCH / 0.9 CONSIDER_SPECIFIC / 0.8 SYMMETRIC
  comment           short human-readable rationale
  other             pipe-separated alternate labels (kg-microbe side, etc.),
                    plus `CAS:<rn>` on symmetric rows — kg-microbe turns these
                    into synonyms on the ontology entity, and from there KGX

Inputs (all read-only):
  MIM/data/ingredients/mapped/*.yaml
  kg-microbe/mappings/kgmicrobe_unified_entity_mappings.sssom.tsv.gz  (CHEBI-only)
  workspace/reports/kg_microbe_residual_p25_categorized.json   (optional)
      — enriches predicate / confidence for the 303 triaged CHEBI cases

Outputs:
  workspace/reports/mim_ingredient_mappings.sssom.tsv
      — working copy, regenerated on every run
      — validated with `sssom validate` before being written

The suppression sidecar and generation manifest travel with this working
copy. The legacy `publish-sssom` command refuses policy-marked candidates;
bounded canonical promotion belongs to a separate reviewed MIM workflow.
"""

from __future__ import annotations

import argparse
import builtins
import hashlib
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import date
from pathlib import Path
from types import ModuleType

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


def _producer_paths() -> tuple[Path, ...]:
    """Enumerate local producers before importing their executable modules."""
    paths = {
        Path(__file__).resolve(), REPO_ROOT / "scripts/kgm_unified_mappings.py",
        REPO_ROOT / "plugins/lock_manager.py",
    }
    for package in ("kg_microbe_utils", "kg_microbe_write", "kg_microbe_fleet"):
        paths.update((REPO_ROOT / "src" / package).rglob("*.py"))
    return tuple(sorted(paths))


def _producer_source_bytes() -> dict[Path, bytes]:
    """Bootstrap without importing the publication helper being bound."""
    result = {}
    for path in _producer_paths():
        if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
            raise ValueError(f"Producer source path is not a regular original file: {path}")
        result[path] = path.read_bytes()
    return result


# This is a process-local drift guard, not cryptographic code attestation.
# The supported CLI reads this entrypoint as source; an importing harness must
# likewise compile captured entrypoint bytes instead of trusting a stale pyc.
# Bind files/path membership before dependent imports, then check the same
# snapshot after imports and at generation/publication boundaries (#706).
_IMPORTED_PRODUCER_BYTES = _producer_source_bytes()


def _check_producer_bindings() -> None:
    current = _producer_source_bytes()
    if current.keys() != _IMPORTED_PRODUCER_BYTES.keys():
        raise ValueError("Producer path set changed after import snapshot")
    if current != _IMPORTED_PRODUCER_BYTES:
        raise ValueError("Producer source bytes changed after import snapshot")
    for name, module in tuple(sys.modules.items()):
        if name == "kgm_unified_mappings":
            expected = REPO_ROOT / "scripts/kgm_unified_mappings.py"
        elif any(name == prefix or name.startswith(prefix + ".") for prefix in (
                "kg_microbe_utils", "kg_microbe_write", "kg_microbe_fleet")):
            stem = REPO_ROOT / "src" / name.replace(".", "/")
            expected = stem / "__init__.py" if (stem / "__init__.py").is_file() else stem.with_suffix(".py")
        else:
            continue
        origin = getattr(module, "__file__", None)
        spec_origin = getattr(getattr(module, "__spec__", None), "origin", None)
        if (not origin or not spec_origin or expected not in current
                or Path(origin).resolve() != expected or Path(spec_origin).resolve() != expected):
            raise ValueError(f"Imported producer origin differs from declared source: {name}")


# Module level stays plain paths so importing this file never requires a
# checkout; `require_mech_roots` in main() is what verifies one (#176).
MIM_ROOT = Path(
    os.environ.get("MEDIAINGREDIENTMECH_ROOT", REPO_ROOT.parent / "MediaIngredientMech")
)
KGM_ROOT_PATH = Path(
    os.environ.get("KGMICROBE_ROOT", REPO_ROOT.parent / "kg-microbe")
)

# This fixed graph deliberately avoids both public sys.modules entries and
# timestamp-based .pyc reads. Existing harness modules are left untouched.
_PRODUCER_MODULE_PATHS = {
    "kgm_unified_mappings": REPO_ROOT / "scripts/kgm_unified_mappings.py",
    "claw_lock_manager": REPO_ROOT / "plugins/lock_manager.py",
    **{name: REPO_ROOT / "src" / filename for name, filename in {
        "kg_microbe_utils": "kg_microbe_utils/__init__.py",
        "kg_microbe_utils.owned_name_policy": "kg_microbe_utils/owned_name_policy.py",
        "kg_microbe_utils.sssom_artifacts": "kg_microbe_utils/sssom_artifacts.py",
        "kg_microbe_fleet": "kg_microbe_fleet/__init__.py",
        "kg_microbe_fleet.roots": "kg_microbe_fleet/roots.py",
        "kg_microbe_write": "kg_microbe_write/__init__.py",
        "kg_microbe_write.registry": "kg_microbe_write/registry.py",
        "kg_microbe_write.serialize": "kg_microbe_write/serialize.py",
        "kg_microbe_write.transaction": "kg_microbe_write/transaction.py",
    }.items()},
}
_PRODUCER_NAMESPACE = f"_mim_candidate_sources_{id(_IMPORTED_PRODUCER_BYTES):x}"
_PRODUCER_MODULES: dict[str, ModuleType] = {}
_STANDARD_IMPORT = builtins.__import__


def _source_import(name, globals=None, locals=None, fromlist=(), level=0):
    qualified = importlib.util.resolve_name("." * level + name, globals["__package__"]) if level else name
    qualified = qualified.removeprefix(_PRODUCER_NAMESPACE + ".")
    if qualified.split(".")[0] not in {"kgm_unified_mappings", "claw_lock_manager", "plugins",
                                       "kg_microbe_utils", "kg_microbe_write", "kg_microbe_fleet"}:
        return _STANDARD_IMPORT(name, globals, locals, fromlist, level)
    module = _load_producer(qualified)
    for member in fromlist:
        child = qualified + "." + member
        if child in _PRODUCER_MODULE_PATHS:
            setattr(module, member, _load_producer(child))
    return module if fromlist else _load_producer(qualified.split(".")[0])


def _load_producer(name: str) -> ModuleType:
    if name not in _PRODUCER_MODULE_PATHS:
        raise ImportError(f"Undeclared local producer dependency: {name}")
    if name in _PRODUCER_MODULES:
        return _PRODUCER_MODULES[name]
    path = _PRODUCER_MODULE_PATHS[name]
    private_name = _PRODUCER_NAMESPACE + "." + name
    spec = importlib.util.spec_from_file_location(private_name, path)
    if spec is None:
        raise ImportError(f"Cannot declare producer module: {name}")
    module = importlib.util.module_from_spec(spec)
    module.__dict__["__builtins__"] = {**vars(builtins), "__import__": _source_import}
    _PRODUCER_MODULES[name] = module
    sys.modules[private_name] = module  # dataclasses resolve their own qualified module
    exec(compile(_IMPORTED_PRODUCER_BYTES[path], str(path), "exec", dont_inherit=True), module.__dict__)
    if "." in name:
        parent, member = name.rsplit(".", 1)
        setattr(_load_producer(parent), member, module)
    return module


_check_producer_bindings()
_KGM_PRODUCER = _load_producer("kgm_unified_mappings")
load_kgm_labels = _KGM_PRODUCER.load_kgm_labels
load_kgm_source_index = _KGM_PRODUCER.load_kgm_source_index
require_mech_roots = _load_producer("kg_microbe_fleet.roots").require_mech_roots
_POLICY_PRODUCER = _load_producer("kg_microbe_utils.owned_name_policy")
AliasCandidate = _POLICY_PRODUCER.AliasCandidate
Suppression = _POLICY_PRODUCER.Suppression
build_owner_index = _POLICY_PRODUCER.build_owner_index
filter_owned_aliases = _POLICY_PRODUCER.filter_owned_aliases
render_suppressed_aliases = _POLICY_PRODUCER.render_suppressed_aliases
_ARTIFACT_PRODUCER = _load_producer("kg_microbe_utils.sssom_artifacts")
POLICY_MARKER = _ARTIFACT_PRODUCER.POLICY_MARKER
artifact_paths = _ARTIFACT_PRODUCER.artifact_paths
capture_beforeimages = _ARTIFACT_PRODUCER.capture_beforeimages
checked_path = _ARTIFACT_PRODUCER.checked_path
publish_candidate_artifacts = _ARTIFACT_PRODUCER.publish_candidate_artifacts


def _snapshot_lock_manager(claw_root: Path):
    if checked_path(claw_root) != REPO_ROOT:
        raise ValueError("Native lock producer requested from another source root")
    return _load_producer("claw_lock_manager").LockManager


# Keep the native lock implementation, but obtain it from the same captured
# bytes and fresh fleet module, including its otherwise-lazy import path.
_ARTIFACT_PRODUCER._load_lock_manager = _snapshot_lock_manager
_check_producer_bindings()

OWNED_NAME_EVIDENCE = (
    "https://github.com/CultureBotAI/MediaIngredientMech/issues/669#issuecomment-6558035777",
    "https://github.com/CultureBotAI/culturebotai-claw/issues/701",
)

CLAW_ROOT = REPO_ROOT
MIM_ROOT = MIM_ROOT
KGM_ROOT = KGM_ROOT_PATH

MIM_INGREDIENTS_DIR = MIM_ROOT / "data" / "ingredients" / "mapped"
MIM_PUBLISHED_SSSOM = MIM_ROOT / "mappings" / "ingredient_mappings.sssom.tsv"
KGM_UNIFIED_TSV = KGM_ROOT / "mappings" / "kgmicrobe_unified_entity_mappings.sssom.tsv.gz"
REPORT_DIR = CLAW_ROOT / "workspace" / "reports"
RESIDUAL_JSON = REPORT_DIR / "kg_microbe_residual_p25_categorized.json"
OUT_TSV = REPORT_DIR / "mim_ingredient_mappings.sssom.tsv"

MAPPING_SET_ID = "https://w3id.org/sssom/mappings/culturebotai_mim_ingredient"
LICENSE = "https://creativecommons.org/publicdomain/zero/1.0/"
SSSOM_BIN = "sssom"

# Ontologies we emit mappings for. Add a new prefix here and to
# `_OBJECT_SOURCE_BY_PREFIX` (and plug a label loader into main()) to extend
# coverage.
SUPPORTED_OBJECT_PREFIXES: tuple[str, ...] = (
    "CHEBI:", "FOODON:", "UBERON:", "ENVO:", "NCIT:",
    "MICRO:", "mesh:", "BTO:",
    "kgmicrobe.compound:", "kgmicrobe.ingredient:", "cas:",
)
_OBJECT_SOURCE_BY_PREFIX: dict[str, str] = {
    "CHEBI:": "obo:chebi.owl",
    "FOODON:": "obo:foodon.owl",
    "UBERON:": "obo:uberon.owl",
    "ENVO:": "obo:envo.owl",
    "NCIT:": "obo:ncit.owl",
    "MICRO:": "obo:micro.owl",
    "mesh:": "registry:mesh",
    "BTO:": "obo:bto.owl",
    "kgmicrobe.compound:": "kgm:compound",
    "kgmicrobe.ingredient:": "kgm:ingredient",
    "cas:": "registry:cas",
}

# Matches MIM's kg_microbe_dict.POLLUTION_SYNONYM_THRESHOLD. Any kg-microbe
# entry above this is contaminated by the upstream row-merge bug (CHEBI:86254
# was observed at 50,686 in the 2026-04 dump; legitimate entries cap around
# 250). We drop kg-microbe-side synonyms for polluted CHEBIs — the mapping
# itself is still valid.
POLLUTION_SYNONYM_THRESHOLD = 500
# Additional defensive cap on the `other` column to keep SSSOM rows parseable
# by downstream tools (pandas default csv field limit is 128 KiB).
MAX_OTHER_ENTRIES = 50
# `mapping_quality` values that denote an exact identity. SYNONYM_MATCH belongs
# here: MIM's schema glosses it "Matches known synonym in ontology", which says
# how the term was located, not that the identity is approximate — CLOSE_MATCH
# is the value reserved for "semantically close but not exact".
EXACT_QUALITIES = {"EXACT_MATCH", "SYNONYM_MATCH"}
# Predicates for which kg-microbe merges `other` into the ontology entity's
# synonyms (`consolidate_chemical_mappings.py`). Asymmetric rows keep the
# ontology's own label instead, so anything added to their `other` is dropped.
SYMMETRIC_PREDICATES = {"skos:exactMatch", "skos:closeMatch"}

# MIM retains curator-rejected candidate labels on the record so their source
# and review decision are auditable.  They are deliberately not names the
# record answers to and must never be emitted through SSSOM ``other``.  Keep the
# comparison case-insensitive so an upstream spelling variant cannot recreate a
# reviewed rejection.
NON_PUBLISHABLE_MIM_SYNONYM_TYPES = {"REJECTED_LABEL"}
_CURATION_NOTE_MIM_SYNONYM_TEXT = re.compile(
    r"^\s*(?:role|properties|cross-references?|original amount)\s*:",
    re.IGNORECASE,
)
_BARE_PARENTHETICAL_MIM_SYNONYM_TEXT = re.compile(r"^\s*\([^)]*\)\s*$")

JUST_MANUAL = "semapv:ManualMappingCuration"
JUST_LEXICAL = "semapv:LexicalMatching"

_PREDICATE_BY_CATEGORY = {
    # Residual-P2.5 buckets → SKOS predicates.
    "CONSIDER_SPECIFIC": "skos:narrowMatch",  # kg-microbe's CHEBI is *narrower*
                                              # than the MIM generic, so this one
                                              # IS narrowMatch under SKOS and did
                                              # not move in MIM#390. Both branches
                                              # below clear `cat`, so it is
                                              # currently unreachable.
    "ENRICH_SYNONYM": "skos:exactMatch",
    "SYMMETRIC": "skos:closeMatch",
}
_CONFIDENCE_BY_CATEGORY = {
    "CONSIDER_SPECIFIC": "0.9",
    "ENRICH_SYNONYM": "0.95",
    "SYMMETRIC": "0.8",
}


def _mim_curie(source_file: str) -> str:
    """Stable local CURIE for a MIM ingredient YAML.

    `Ca_No32.yaml` → `MIM:Ca_No32`. Non-URL-safe characters are
    percent-style `~HEX`-encoded so the CURIE round-trips through SSSOM's
    prefix expansion."""
    stem = Path(source_file).stem
    safe = re.sub(
        r"[^A-Za-z0-9_\-.]",
        lambda m: f"~{ord(m.group(0)):02X}",
        stem,
    )
    return f"MIM:{safe}"


# Ontology prefixes that imply a chemically-defined SINGLE_INGREDIENT
# (-> kgmicrobe.compound:* registry namespace) when the parent term is
# in this list. Mirrors classify_ingredient_type.classify():
# CHEBI / NCIT / cas: / mesh: are pure-compound registries; FOODON /
# UBERON / ENVO / BTO / MICRO / kgmicrobe.ingredient: are
# complex/biological/anatomical -> kgmicrobe.ingredient:*.
_COMPOUND_PARENT_PREFIXES: frozenset[str] = frozenset({
    "CHEBI:", "NCIT:", "cas:", "mesh:", "kgmicrobe.compound:",
})
_INGREDIENT_PARENT_PREFIXES: frozenset[str] = frozenset({
    "FOODON:", "UBERON:", "ENVO:", "BTO:", "MICRO:",
    "kgmicrobe.ingredient:",
})


def _kgmicrobe_namespace_for(parent_obj_id: str) -> str:
    """Given the ontology parent CURIE that the MIM subject narrowMatches,
    decide which kgmicrobe registry namespace the synthesized B1
    registry row belongs in (`kgmicrobe.compound:` vs
    `kgmicrobe.ingredient:`).

    Mirrors classify_ingredient_type.classify(): chemistry registries
    (CHEBI, NCIT, cas:, mesh:) → compound; food / environmental /
    anatomical / tissue ontologies → ingredient. Falls back to
    `kgmicrobe.ingredient:` when the prefix is unrecognized — that's
    the safer default for "complex/uncertain"."""
    for pref in _COMPOUND_PARENT_PREFIXES:
        if parent_obj_id.startswith(pref):
            return "kgmicrobe.compound:"
    for pref in _INGREDIENT_PARENT_PREFIXES:
        if parent_obj_id.startswith(pref):
            return "kgmicrobe.ingredient:"
    return "kgmicrobe.ingredient:"


def _registry_slug_for_curie(mim_curie: str) -> str:
    """`MIM:Vermont_Soil` -> `vermont_soil` — lowercased subject slug
    used as the local part of the synthesized
    `kgmicrobe.{ingredient,compound}:<slug>` registry CURIE.

    Matches `validate_sssom_invariants._registry_slug_for`: the
    validator lowercases everything after `MIM:` and the regex
    expects an exact match against that string. We preserve the
    `~HEX` percent-encoding (already lowercase via the encoder)
    rather than trying to round-trip it back to original
    characters — the registry CURIE is opaque to consumers."""
    if not mim_curie.startswith("MIM:"):
        return mim_curie
    return mim_curie[4:].lower()


# How strong an identity claim each mapping predicate makes. Used to decide
# whether a `validation_method` stamp survives a predicate change (#126).
#
# The stamps are verdicts about the OBJECT -- `OAK+OLS:chebi|SYNONYM_ENRICH|...`,
# `none|UNKNOWN_TERM|...` -- so strengthening a relation cannot invalidate one:
# if the term resolved and its synonyms were enriched, that stays true when
# closeMatch becomes exactMatch. Weakening is different. Someone downgrading
# exactMatch to narrowMatch after a specificity review has changed their mind
# about the pair, and inheriting the old stamp would carry an endorsement they
# just withdrew, silently keeping the row out of the review queue.
#
# narrowMatch and broadMatch share a rank deliberately: they are directional
# subsumption rather than degrees of identity, so neither strengthens the
# other and a change between them resets.
PREDICATE_STRENGTH: dict[str, int] = {
    "skos:exactMatch": 3,
    "skos:closeMatch": 2,
    "skos:narrowMatch": 1,
    "skos:broadMatch": 1,
}

# A pair whose history holds more than one predicate cannot be compared, so it
# never carries. Does not occur in the corpus today (2885 rows, 2885 distinct
# subject+object pairs, none with two predicates) but the loader must not
# depend on that staying true.
_AMBIGUOUS = object()


def _is_nonresolving_mim_synonym_text(text: str) -> bool:
    """Return whether a text value is MIM provenance, not a synonym."""
    return bool(
        _CURATION_NOTE_MIM_SYNONYM_TEXT.match(text)
        or _BARE_PARENTHETICAL_MIM_SYNONYM_TEXT.match(text)
    )


def _is_publishable_mim_synonym(synonym: object) -> bool:
    """Return whether a MIM synonym row may enter SSSOM ``other``."""
    if not isinstance(synonym, dict):
        return False
    text = (synonym.get("synonym_text") or "").strip()
    if not text:
        return False
    synonym_type = (synonym.get("synonym_type") or "").strip().upper()
    if synonym_type in NON_PUBLISHABLE_MIM_SYNONYM_TYPES:
        return False
    return not _is_nonresolving_mim_synonym_text(text)


def _strengthens(old_predicate: str, new_predicate: str) -> bool:
    """Whether moving to `new_predicate` makes a strictly stronger claim.

    Unknown predicates never strengthen: a vocabulary this table does not
    describe is a reason to re-review, not to inherit a verdict.
    """
    old = PREDICATE_STRENGTH.get(old_predicate)
    new = PREDICATE_STRENGTH.get(new_predicate)
    if old is None or new is None:
        return False
    return new > old


def build_subject_object_index(
    prior_stamps: dict[tuple[str, str, str], str],
) -> dict[tuple[str, str], object]:
    """Index prior stamps by (subject, object), marking ambiguous pairs.

    A pair whose history holds more than one predicate cannot be compared for
    strength, so it is marked and never carries.
    """
    index: dict[tuple[str, str], object] = {}
    for (subject, predicate, obj), stamp in prior_stamps.items():
        key = (subject, obj)
        index[key] = _AMBIGUOUS if key in index else (stamp, predicate)
    return index


def replay_stamp(
    subject: str,
    predicate: str,
    obj: str,
    prior_stamps: dict[tuple[str, str, str], str],
    subject_object_index: dict[tuple[str, str], object],
) -> tuple[str | None, str]:
    """Decide this row's replayed stamp, and why.

    Returns `(stamp_or_None, outcome)` where outcome is one of `replayed` (the
    exact subject+predicate+object key hit), `carried` (the predicate changed
    but strengthened, so the object-level verdict still holds), `reset` (a
    prior stamp exists but the predicate weakened, went sideways, is
    unrecognised, or the pair is ambiguous), or `absent` (no prior stamp).
    """
    exact = prior_stamps.get((subject, predicate, obj))
    if exact:
        return exact, "replayed"

    prior = subject_object_index.get((subject, obj))
    if prior is None:
        return None, "absent"
    if prior is _AMBIGUOUS:
        return None, "reset"

    prior_stamp, prior_predicate = prior
    if _strengthens(prior_predicate, predicate):
        return prior_stamp, "carried"
    return None, "reset"


def apply_replayed_stamps(
    rows: list[dict],
    prior_stamps: dict[tuple[str, str, str], str],
) -> dict[str, int]:
    """Stamp `rows` in place from `prior_stamps`; return the outcome counts.

    Extracted so the wiring is exercised and not only the decision it delegates
    to: with the loop inline, breaking its assignment left the whole suite green
    while the build would have emitted every validation_method blank (#166).

    A row that already carries a stamp is left alone and not counted.
    """
    index = build_subject_object_index(prior_stamps)
    outcomes = {"replayed": 0, "carried": 0, "reset": 0, "absent": 0}
    for row in rows:
        if (row.get("validation_method") or "").strip():
            continue
        stamp, outcome = replay_stamp(
            row["subject_id"], row["predicate_id"], row["object_id"],
            prior_stamps, index,
        )
        outcomes[outcome] += 1
        if stamp:
            row["validation_method"] = stamp
    return outcomes


def _load_existing_validation_method(
    path: Path,
) -> dict[tuple[str, str, str], str]:
    """Return ``{(subject_id, predicate_id, object_id) → validation_method}``
    parsed from an existing SSSOM TSV at ``path``.

    Why this exists
    ---------------
    The downstream MIM curation pipeline (OAK+OLS audit, UNKNOWN_TERM triage,
    `sssom_synonym_enrich_review_*` passes) post-stamps the ``validation_method``
    extension column directly on the published TSV. Those stamps don't live
    in the source YAMLs — they're a property of the *emitted SSSOM row*
    keyed by (subject, predicate, object). A naive rebuild would emit
    column 13 empty and wipe ~2k OAK+OLS audit stamps.

    This loader reads the previous emission and returns a stamp index the
    writer can replay onto matching rows.

    Quietly returns ``{}`` if the file is missing or doesn't yet carry the
    column (first-ever build).
    """
    if not path.exists():
        return {}
    out: dict[tuple[str, str, str], str] = {}
    with path.open() as f:
        header: list[str] | None = None
        for line in f:
            if line.startswith("#"):
                continue
            parts = line.rstrip("\n").split("\t")
            if header is None:
                header = parts
                if "validation_method" not in header:
                    return {}
                continue
            row = dict(zip(header, parts))
            stamp = (row.get("validation_method") or "").strip()
            if not stamp:
                continue
            key = (
                (row.get("subject_id") or "").strip(),
                (row.get("predicate_id") or "").strip(),
                (row.get("object_id") or "").strip(),
            )
            if all(key):
                out[key] = stamp
    return out


def _warn_if_kgm_missing() -> bool:
    """kg-microbe enrichment is optional, but a silent skip is worse than a warning."""
    if KGM_UNIFIED_TSV.exists():
        return True
    print(
        f"WARNING: kg-microbe unified mapping not found ({KGM_UNIFIED_TSV}); "
        "building SSSOM with NO kg-microbe cross-reference enrichment. "
        "Regenerate it in kg-microbe with "
        "`poetry run python scripts/consolidate_chemical_mappings.py`.",
        file=sys.stderr,
    )
    return False


def _load_kgm_source_index() -> dict[str, str]:
    """CHEBI:X → pipe-separated kg-microbe `source` string."""
    if not _warn_if_kgm_missing():
        return {}
    return load_kgm_source_index(KGM_UNIFIED_TSV)


def _load_kgm_labels() -> dict[str, tuple[str, list[str]]]:
    """CHEBI:X → (canonical_name, [synonyms...]) from kg-microbe."""
    if not _warn_if_kgm_missing():
        return {}
    return load_kgm_labels(KGM_UNIFIED_TSV)


def _load_chebi_labels(chebi_ids: list[str], batch: int = 80) -> dict[str, str]:
    """CHEBI:X → rdfs:label from the local OAK sqlite. Batched so we
    don't pay cold-start overhead per term. Writes nothing if OAK isn't
    on PATH — the builder falls back to the MIM-stored ontology_label."""
    out: dict[str, str] = {}
    if not chebi_ids:
        return out
    try:
        for i in range(0, len(chebi_ids), batch):
            chunk = chebi_ids[i : i + batch]
            proc = subprocess.run(
                ["runoak", "-i", "sqlite:obo:chebi", "aliases"] + chunk,
                capture_output=True, text=True, timeout=300,
            )
            for line in proc.stdout.splitlines()[1:]:
                parts = line.split("\t")
                if len(parts) >= 3 and parts[1] == "rdfs:label":
                    out[parts[0]] = parts[2]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return out


def _load_ols_labels(
    term_ids: list[str],
    ontology: str,
    iri_prefix: str,
) -> dict[str, str]:
    """Fetch rdfs:label via EBI OLS4 REST for ontologies without a local
    OAK sqlite (e.g. FOODON). `ontology` is the OLS ontology slug
    (\"foodon\"); `iri_prefix` is the OBO IRI stem (
    \"http://purl.obolibrary.org/obo/FOODON_\").

    Non-fatal — on any network error we return whatever we've resolved so
    far; the builder falls back to the MIM-stored ontology_label."""
    out: dict[str, str] = {}
    if not term_ids:
        return out
    try:
        import urllib.parse
        import urllib.request
    except ImportError:
        return out
    base = f"https://www.ebi.ac.uk/ols4/api/ontologies/{ontology}/terms"
    for curie in term_ids:
        try:
            local = curie.split(":", 1)[1]
        except IndexError:
            continue
        iri = iri_prefix + local
        double_encoded = urllib.parse.quote(urllib.parse.quote(iri, safe=""), safe="")
        url = f"{base}/{double_encoded}"
        try:
            with urllib.request.urlopen(url, timeout=10) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except Exception:
            continue
        label = (payload.get("label") or "").strip()
        if label:
            out[curie] = label
    return out


def _load_residual_categorization() -> dict[str, dict]:
    """source_file → residual-P2.5 decision, for predicate upgrading."""
    if not RESIDUAL_JSON.exists():
        return {}
    data = json.loads(RESIDUAL_JSON.read_text())
    return {d["source_file"]: d for d in data.get("decisions", [])}


def _last_curator(history: list[dict]) -> str:
    if not history:
        return ""
    return (history[-1].get("curator") or "").strip()


def _mapping_date(path: Path, history: list[dict]) -> str:
    """Latest valid ASCII curation-history date; empty for native Rule F.

    Takes the calendar maximum over valid date prefixes, not `history[-1]`. The
    two coincide only while history stays append-ordered, and the published date
    should not depend on that holding.

    There is deliberately no filesystem fallback. Git does not preserve mtimes,
    so a record reaching one would be stamped with whenever the machine happened
    to clone -- a value that differs per checkout and means nothing, published
    into an artifact that is supposed to be reproducible. While such a fallback
    was in place it silently mis-stamped three rows, and only a backward-moving
    date in a rebuild diff exposed them (MediaIngredientMech#542).

    Invalid history entries are reported and ignored; they cannot outrank a
    valid entry through Unicode or lexical ordering. A record with none remains
    dateless for MIM's Rule F curator report. The writer can emit that diagnostic
    row if other rows supply a header date; an entirely dateless set is refused.
    """
    dates = []
    for event in history or []:
        value = str(event.get("timestamp") or "")
        match = re.match(r"^([0-9]{4}-[0-9]{2}-[0-9]{2})(?:[Tt ]|$)", value)
        parsed = _parse_mapping_date(match.group(1)) if match else None
        if parsed is not None:
            dates.append(parsed)
        else:
            print(f"  WARNING: ignoring invalid curation_history date in {path.name}: {value!r}")
    if dates:
        return max(dates).isoformat()
    print(
        f"  WARNING: no valid curation_history date in {path.name}; "
        "keeping an empty mapping_date for native Rule F review "
        "(the writer refuses a set with no dated rows; #686)"
    )
    return ""


def _cas_token(data: dict) -> str:
    """`CAS:<rn>` for the substance a lab would actually order, or "".

    Prefers `supplied_form[].cas_rn` over `chemical_properties.cas_rn`: the
    latter describes the substance the record *denotes*, the former the
    material that is physically ordered and delivered, and where MIM records
    both it is because they differ (MIM #398).

    Prefixed rather than bare — `9004-32-4` alone is indistinguishable from a
    catalogue code or a concentration in a synonym search.
    """
    for sf in data.get("supplied_form") or []:
        rn = (sf or {}).get("cas_rn")
        if rn and str(rn).strip():
            return f"CAS:{str(rn).strip()}"
    rn = (data.get("chemical_properties") or {}).get("cas_rn")
    return f"CAS:{str(rn).strip()}" if rn and str(rn).strip() else ""


def _pipe(labels: list[str], drop: set[str], max_entries: int | None = None) -> str:
    out: list[str] = []
    seen: set[str] = set()
    for a in labels:
        a = (a or "").strip()
        if not a:
            continue
        key = a.lower()
        if key in drop or key in seen:
            continue
        seen.add(key)
        out.append(a)
        if max_entries is not None and len(out) >= max_entries:
            break
    return "|".join(out)


def _join_sources(mim_ev: list[str], last_curator: str, kgm_src: str) -> str:
    parts: list[str] = [f"MIM:{s}" for s in mim_ev if s]
    if last_curator:
        parts.append(f"MIM:curator={last_curator}")
    for s in filter(None, (p.strip() for p in kgm_src.split("|"))):
        parts.append(f"kgm:{s}")
    return "|".join(parts)


def _read_mapped_records(directory: Path, snapshot: dict[Path, bytes | None] | None = None) -> dict[Path, dict]:
    """Parse the complete direct mapped-directory population, including ignored files."""
    paths = sorted(directory.glob("*.yaml"))
    contents = capture_beforeimages(paths) if snapshot is None else snapshot
    records = {}
    subjects = set()
    for path in paths:
        content = contents[checked_path(path)]
        if content is None:
            raise ValueError(f"Mapped record disappeared: {path}")
        data = yaml.safe_load(content)
        if not isinstance(data, dict):
            raise ValueError(f"Mapped record is not a mapping: {path}")
        subject = _mim_curie(path.name)
        if subject in subjects:
            raise ValueError(f"Duplicate escaped MIM subject: {subject}")
        subjects.add(subject)
        records[path] = data
    return records


def _revision(root: Path) -> str | None:
    result = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"],
                            capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else None


def _digest(content: bytes | None) -> str | None:
    return hashlib.sha256(content).hexdigest() if content is not None else None


def _row_from_yaml(
    path: Path,
    residual: dict[str, dict],
    kgm_sources: dict[str, str],
    kgm_labels: dict[str, tuple[str, list[str]]],
    canonical_labels: dict[str, str],
    *,
    record: dict | None = None,
    owners: dict[str, frozenset[str]] | None = None,
    suppressions: list[Suppression] | None = None,
) -> list[dict]:
    """Returns a list of SSSOM rows for one MIM YAML.

    Most records yield exactly one row. Records whose primary
    `identifier` is a registry/custom CURIE (`cas:`, `kgmicrobe.compound:`,
    `kgmicrobe.ingredient:`) AND whose `ontology_mapping.ontology_id`
    points to a *different* ontology parent (typically backfilled by
    `backfill_parent_terms.py`) emit TWO rows so downstream consumers
    keep both joins:

      Row A (parent):   subject → ontology parent  (skos:broadMatch)
      Row B (registry): subject → identifier       (skos:exactMatch)

    Returns [] for records with no supported ontology_id prefix.
    """
    # Direct callers receive the same complete-directory policy as main().
    # main supplies its once-parsed snapshot, avoiding a second corpus read.
    if record is None or owners is None:
        records = _read_mapped_records(path.parent)
        if record is None:
            record = records[path]
        if owners is None:
            owners = build_owner_index({_mim_curie(p.name): d for p, d in records.items()})
    data = record

    def owned_tokens(text: str, surface: str, reference: str) -> list[AliasCandidate]:
        return [AliasCandidate(token, surface, (reference,), OWNED_NAME_EVIDENCE)
                for token in text.split("|") if token.strip()]

    def keep_owned(candidates: list[AliasCandidate]) -> list[str]:
        kept, events = filter_owned_aliases(_mim_curie(path.name), candidates, owners)
        if suppressions is not None:
            suppressions.extend(events)
        return [candidate.text for candidate in kept]

    # A curator-rejected record must not appear in the canonical mapping
    # set, even though it can still live under data/ingredients/mapped/
    # and carry an ontology_mapping.ontology_id. MIM's reconcile_sssom.py
    # qc gate treats data/curated/mapped_ingredients.yaml as the source of
    # truth and flags such rows as ORPHANs; honor the curated status here
    # so rejected mappings never leak in (issue #16).
    if (data.get("mapping_status") or "").strip().upper() == "REJECTED":
        return []

    ont = data.get("ontology_mapping") or {}
    obj_id = (ont.get("ontology_id") or "").strip()
    if not any(obj_id.startswith(p) for p in SUPPORTED_OBJECT_PREFIXES):
        return []
    is_chebi = obj_id.startswith("CHEBI:")

    preferred = (data.get("preferred_term") or "").strip()
    ont_label = (ont.get("ontology_label") or "").strip()
    quality = (ont.get("mapping_quality") or "").strip().upper()
    evidence = [
        (e.get("source") or "").strip()
        for e in (ont.get("evidence") or [])
        if (e.get("source") or "").strip()
    ]
    history = data.get("curation_history") or []

    # Default: exact match at high confidence
    predicate = "skos:exactMatch"
    justification = (
        JUST_LEXICAL
        if quality in {"EXACT_MATCH", "LEXICAL_MATCH", ""}
        else JUST_MANUAL
    )
    confidence = "0.99" if quality in EXACT_QUALITIES else "0.9"
    # Non-exact quality (e.g. CLOSE_MATCH used by FOODON peptones) earns a
    # closeMatch predicate by default so downstream consumers don't treat them
    # as identity mappings.
    #
    # SYNONYM_MATCH is NOT one of those. MIM's schema defines it as "Matches
    # known synonym in ontology" — a statement about how the match was FOUND,
    # not about whether the identity holds — while CLOSE_MATCH is the value
    # that means "Semantically close but not exact". Treating them alike
    # demoted 227 published exactMatch rows to closeMatch on rebuild, among
    # them `nitrous oxide` -> CHEBI:17045 `dinitrogen oxide`, `Escin` ->
    # CHEBI:2500 `Aescin` and `Disodium oxalate` -> CHEBI:132764 `sodium
    # oxalate`: same substance, reached through the ontology's own synonym
    # list. See MediaIngredientMech#409.
    if quality and quality not in EXACT_QUALITIES:
        predicate = "skos:closeMatch"
    # NARROW_MATCH (typically minted kgmicrobe.ingredient:* primaries)
    # asserts the MIM term is narrower than the parent ontology term, so the
    # parent is the BROADER concept and the row is skos:broadMatch --
    # `A skos:broadMatch B` asserts B is broader than A. This emitted
    # skos:narrowMatch until MediaIngredientMech#390, which is the inverse
    # relation (a sub-property of skos:narrower). The set declares
    # `predicate_semantics: skos` in its header so consumers read it that way;
    # kg-microbe treats absence as the legacy convention (kg-microbe#822).
    if quality == "NARROW_MATCH":
        predicate = "skos:broadMatch"
    comment = ""

    # Residual-P2.5 override: the generator ran a specificity / symmetry
    # analysis for 303 records; use its decision when available. This is
    # where broad/narrow/closeMatch predicates come from. CHEBI-only — the
    # residual pipeline wasn't run for FOODON/UBERON/ENVO.
    src_file = path.name
    if is_chebi and src_file in residual:
        dec = residual[src_file]
        cat = dec.get("category")
        if cat == "CONSIDER_SPECIFIC":
            # The YAML `ontology_id` is MIM's curated source of truth for
            # the object. A CONSIDER_SPECIFIC decision proposes swapping it
            # to kg-microbe's more-specific CHEBI — but a curator may have
            # deliberately kept the generic term (a choice recorded in the
            # YAML / on the published SSSOM, and never back-propagated to
            # this gitignored cache). So the cache may *annotate* but must
            # never *override* the curated object: honor the decision only
            # when the YAML already holds the proposed term; otherwise
            # suppress it so the curated mapping wins and predicate/
            # confidence fall through to the YAML-quality default.
            #
            # This is the self-maintaining successor to the per-file
            # stale-entry list in prune_residual_for_chebi_fixes.py: no
            # hand-maintained list can drift out of date, because the
            # authority is always the current YAML. (Historical context:
            # the token-overlap gate this replaces still swapped whenever
            # labels shared a token — which is exactly how curator-rejected
            # swaps like Xylose→aldehydo-D-xylose kept coming back on
            # rebuild. See Codex review #558 / PR #2.)
            kgm_chebi = (dec.get("kg_microbe_chebi") or "").strip()
            kgm_label = (dec.get("kg_microbe_label") or "").strip()
            if kgm_chebi.startswith("CHEBI:") and obj_id == kgm_chebi:
                # Curator already adopted the specific term in the YAML.
                # Annotate only — keep the label and record the rationale
                # as a comment, but leave predicate/confidence to the
                # YAML's mapping_quality. The cache annotates, never
                # overrides (issue #14): forcing narrowMatch/0.9 here would
                # silently downgrade a curator's EXACT_MATCH.
                ont_label = kgm_label or ont_label
                comment = f"CONSIDER_SPECIFIC: {dec.get('rationale', '')}"
                cat = None
            else:
                if kgm_chebi.startswith("CHEBI:"):
                    print(
                        f"  suppressed CONSIDER_SPECIFIC swap for {src_file}: "
                        f"kept curated YAML object {obj_id} over cache target "
                        f"{kgm_chebi}",
                        file=sys.stderr)
                cat = None  # object + predicate come from the YAML
        if cat is not None:
            predicate = _PREDICATE_BY_CATEGORY.get(cat, predicate)
            confidence = _CONFIDENCE_BY_CATEGORY.get(cat, confidence)
            justification = JUST_MANUAL if cat == "CONSIDER_SPECIFIC" else JUST_LEXICAL
            comment = f"{cat}: {dec.get('rationale', '')}"

    # Identity row: when the object IS the record's own `identifier`, this row
    # asserts "MIM:X is X" and nothing above may weaken it. Last, so it also
    # overrides the residual-P2.5 category.
    #
    # The dual-emission block below already hard-codes exactMatch for the
    # registry row it synthesises — but that block only fires when the
    # identifier DIFFERS from the ontology_id. When they are equal there is no
    # second row: this parent row is the identity row, and it was taking the
    # quality-derived predicate instead. That published 448 rows saying a
    # record is merely `closeMatch` to itself, with the same mapping_quality
    # yielding both predicates (EXACT_MATCH split 1597/38, CAS_RN_LOOKUP 1/39)
    # while all 142 NARROW_MATCH identity rows were correctly exactMatch.
    # See MediaIngredientMech#438 and its Rule D.
    #
    # mapping_quality grades the *ontology grounding*. Identity with one's own
    # primary identifier is not graded; it is definitional.
    #
    # Predicate only. `confidence` is deliberately left alone: raising it would
    # move 45 further rows that are not what #438 is about, and the identity
    # row's confidence is a separate question.
    if (data.get("identifier") or "").strip() == obj_id:
        predicate = "skos:exactMatch"
        # ...and the residual-P2.5 rationale goes with it. Those comments argue
        # for a specificity or symmetry *difference* — "MIM is the more
        # specific side ('D-glucose' vs 'glucose')", "kg-microbe adds salt/
        # hydrate qualifier ('hexahydrate')" — so leaving one on a row that now
        # says exactMatch publishes a row contradicting its own comment. 51 did
        # after the predicate half of MediaIngredientMech#438 landed.
        #
        # They were also wrong on their own terms: the triage compared MIM's
        # term against a kg-microbe *source label* and then attached the verdict
        # to the MIM→ontology row. `MIM:D-glucose → CHEBI:17634` has object
        # label 'D-glucose'; the cited contrast is with plain 'glucose'
        # (CHEBI:17234), a different term. Retiring them loses nothing true.
        if comment.startswith("SYMMETRIC:"):
            comment = ""

    # Prefer the ontology's canonical rdfs:label for object_label (SSSOM
    # best practice). Fall back to MIM's stored ontology_label if the
    # label loader didn't resolve. The old label names the OBJECT, so it
    # can become a subject synonym only when the final row asserts identity.
    canonical_label = canonical_labels.get(obj_id, "")
    mim_stored_label = ont_label
    if canonical_label:
        ont_label = canonical_label

    # kg-microbe cross-source data is CHEBI-only.
    kgm_name, kgm_syns = kgm_labels.get(obj_id, ("", [])) if is_chebi else ("", [])
    kgm_src = kgm_sources.get(obj_id, "") if is_chebi else ""
    mim_synonym_rows = [
        s for s in (data.get("synonyms") or [])
        if isinstance(s, dict) and (s.get("synonym_text") or "").strip()
    ]
    rejected_labels = {
        token.strip().casefold()
        for s in mim_synonym_rows
        if (s.get("synonym_type") or "").strip().upper()
        in NON_PUBLISHABLE_MIM_SYNONYM_TYPES
        for token in (s.get("synonym_text") or "").split("|")
    }
    # `other` carries alternate surface forms that downstream consumers can
    # adopt as synonyms. Non-exact target aliases do not name this subject
    # (#680): a KG exact alias of the parent remains a parent alias. Preserve
    # subject-owned YAML synonyms on every predicate. For exactMatch, retain
    # the existing order: stored target label → KG name → KG synonyms → YAML.
    # Drop the chosen
    # object_label and the preferred_term so we don't duplicate what's in
    # the dedicated columns.
    drop = {(preferred or "").lower(), (ont_label or "").lower(), ""}
    candidate_alts: list[AliasCandidate] = []
    if predicate == "skos:exactMatch":
        candidate_alts.extend(owned_tokens(
            mim_stored_label, "mim.ontology_label", f"{path}#ontology_mapping.ontology_label"))
        candidate_alts.extend(owned_tokens(
            kgm_name, "kgmicrobe.canonical_name", f"{KGM_UNIFIED_TSV}#object_id={obj_id}"))
        for synonym in kgm_syns:
            candidate_alts.extend(owned_tokens(
                synonym, "kgmicrobe.synonym", f"{KGM_UNIFIED_TSV}#object_id={obj_id}"))
    for index, synonym in enumerate(data.get("synonyms") or []):
        if isinstance(synonym, dict) and _is_publishable_mim_synonym(synonym):
            candidate_alts.extend(owned_tokens(
                synonym.get("synonym_text") or "", "mim.synonym",
                f"{path}#synonyms[{index}]"))
    # Filter MIM RAW_TEXT entries that encode roles/properties — those are
    # not chemical synonyms.
    candidate_alts = [
        a for a in candidate_alts
        if a.text.strip().casefold() not in rejected_labels
        and not _is_nonresolving_mim_synonym_text(a.text)
    ]
    other = _pipe(keep_owned(candidate_alts), drop=drop, max_entries=MAX_OTHER_ENTRIES)

    # The CAS-RN travels in `other` so it lands in KGX as a synonym: the KG
    # node optimises for how it *reads*, while the number you actually order
    # by stays findable (MIM #398/#403). Symmetric rows only — kg-microbe
    # merges `other` into the ontology entity for exactMatch/closeMatch and
    # ignores it otherwise, so a CAS on an asymmetric row would both vanish
    # and, if it didn't, wrongly imply the broader parent is purchasable
    # under the child's number.
    #
    # Appended AFTER the cap on purpose. `_pipe` truncates by breaking at
    # MAX_OTHER_ENTRIES, so a CAS placed in `candidate_alts` would be the
    # first thing dropped on crowded rows — and the crowded rows are the
    # MnSO4 hydrate family, i.e. exactly the ones a lab orders by number.
    # One ~15-char token cannot threaten the 128 KiB field limit the cap
    # defends against.
    cas_token = _cas_token(data)
    # CAS is appended after the ordinary alias cap and also appears on direct
    # and B1 registry rows. Filter that shared token before any of those paths.
    cas_candidates = [candidate for candidate in owned_tokens(
        cas_token, "mim.cas", f"{path}#chemical_properties.cas_rn-or-cross_references")
        if candidate.text.strip().casefold() not in rejected_labels]
    cas_token = _pipe(keep_owned(cas_candidates), drop=set())
    if cas_token and predicate in SYMMETRIC_PREDICATES:
        if cas_token.lower() not in {p.strip().lower() for p in other.split("|")}:
            other = f"{other}|{cas_token}" if other else cas_token

    # Per-row object_source — SSSOM supports per-row override when the
    # mapping_set mixes ontologies.
    prefix = next(p for p in SUPPORTED_OBJECT_PREFIXES if obj_id.startswith(p))
    object_source = _OBJECT_SOURCE_BY_PREFIX.get(prefix, "")

    parent_row = {
        "subject_id": _mim_curie(src_file),
        "subject_label": preferred,
        "predicate_id": predicate,
        "object_id": obj_id,
        "object_label": ont_label,
        "object_source": object_source,
        "mapping_justification": justification,
        "source": _join_sources(evidence, _last_curator(history), kgm_src),
        "mapping_date": _mapping_date(path, history),
        "confidence": confidence,
        "comment": comment,
        "other": other,
        # Populated by scripts/review_sssom_synonyms.py on the next review
        # pass — left blank here so every fresh build signals "needs
        # re-review". Format: "{authorities}|{verdict}|{date}", e.g.
        # "OAK+OLS:chebi|CONFIRMED|2026-04-18".
        "validation_method": "",
    }

    # Dual-emission: when the MIM record's `identifier` is a custom
    # registry CURIE (cas:, kgmicrobe.compound:, kgmicrobe.ingredient:)
    # AND the ontology_mapping points to a *different* parent term,
    # emit a second row preserving the registry-form identity. This
    # protects downstream joins on the registry CURIE that the
    # parent-class primary would otherwise displace.
    primary_id = (data.get("identifier") or "").strip()
    rows = [parent_row]
    if (primary_id and primary_id != obj_id and any(
            primary_id.startswith(p) for p in (
                "cas:", "kgmicrobe.compound:", "kgmicrobe.ingredient:"))):
        primary_prefix = next(
            (p for p in SUPPORTED_OBJECT_PREFIXES
             if primary_id.startswith(p)), "")
        if primary_prefix:
            rows.append({
                "subject_id": parent_row["subject_id"],
                "subject_label": preferred,
                "predicate_id": "skos:exactMatch",
                "object_id": primary_id,
                "object_label": preferred,  # registry CURIE: label is the MIM term
                "object_source": _OBJECT_SOURCE_BY_PREFIX.get(
                    primary_prefix, ""),
                "mapping_justification": JUST_MANUAL,
                "source": parent_row["source"],
                "mapping_date": parent_row["mapping_date"],
                "confidence": "0.99",
                "comment": (f"Registry/identity row preserving "
                            f"{primary_id} alongside parent {obj_id}."),
                # These minted registry nodes carry no ontology synonyms of
                # their own, so the CAS is the only orderable handle they get.
                "other": cas_token,
                "validation_method": "",
            })

    # B1 backfill: every subject whose parent row is asymmetric
    # (narrowMatch / broadMatch) is required by Rule B1 to also carry a
    # `kgmicrobe.{ingredient,compound}:<slug_lc>` registry exactMatch
    # row. The dual-emission block above already covers the cases where
    # `identifier:` is `kgmicrobe.{ingredient,compound}:<slug>`. For the
    # 162 narrowMatch subjects whose `identifier:` is `cas:` / `mesh:` /
    # `NCIT:` / a same-as-parent CHEBI, we synthesize the missing
    # registry row here. A curated local identity determines its namespace,
    # including when its slug differs from the subject or uses mixed case
    # (#684, #685). Only nonlocal primaries use the parent-prefix fallback:
    # chemistry registries -> compound, complex/biological -> ingredient.
    # Slug is the lowercased subject slug — matches Rule B1's
    # `subject_id[4:].lower()` regex anchor exactly.
    if parent_row["predicate_id"] in ("skos:narrowMatch", "skos:broadMatch"):
        slug_lc = _registry_slug_for_curie(parent_row["subject_id"])
        kgm_namespace = next(
            (prefix for prefix in ("kgmicrobe.ingredient:", "kgmicrobe.compound:")
             if primary_id.startswith(prefix)),
            None,
        )
        if kgm_namespace is None:
            kgm_namespace = _kgmicrobe_namespace_for(obj_id)
        kgm_curie = f"{kgm_namespace}{slug_lc}"
        # Skip if the dual-emission block (or some prior row in `rows`)
        # already satisfies B1 in either namespace. The curated identity
        # takes precedence over the parent-prefix fallback; adding the other
        # namespace would assert a competing identity and fail B5 (#679).
        # Keep this exact: a mixed-case primary slug still needs a lowercase
        # subject handle for B1, emitted in the same namespace as that primary.
        registry_ids = {
            f"kgmicrobe.ingredient:{slug_lc}", f"kgmicrobe.compound:{slug_lc}",
        }
        already_emitted = any(
            r["subject_id"] == parent_row["subject_id"]
            and r["object_id"] in registry_ids
            and r["predicate_id"] == "skos:exactMatch"
            for r in rows
        )
        if not already_emitted:
            rows.append({
                "subject_id": parent_row["subject_id"],
                "subject_label": preferred,
                "predicate_id": "skos:exactMatch",
                "object_id": kgm_curie,
                "object_label": preferred,
                "object_source": _OBJECT_SOURCE_BY_PREFIX.get(kgm_namespace, ""),
                "mapping_justification": JUST_MANUAL,
                "source": parent_row["source"],
                "mapping_date": parent_row["mapping_date"],
                "confidence": "0.99",
                # The predicate word comes from the parent row itself. It was
                # a literal "narrowMatch", which went stale on 128 published
                # rows the moment the parent predicate moved (MIM#390).
                "comment": (f"Registry/identity row (Rule B1) for "
                            f"{parent_row['predicate_id'].split(':', 1)[-1]} "
                            f"subject; kg-microbe primary id "
                            f"{kgm_curie} alongside parent {obj_id}."),
                # The parent row is asymmetric, so this registry row is the
                # only place the subject's CAS can reach a KG synonym.
                "other": cas_token,
                "validation_method": "",
            })
    return rows


HEADER_YAML = f"""\
# curie_map:
#   CHEBI: "http://purl.obolibrary.org/obo/CHEBI_"
#   FOODON: "http://purl.obolibrary.org/obo/FOODON_"
#   UBERON: "http://purl.obolibrary.org/obo/UBERON_"
#   ENVO: "http://purl.obolibrary.org/obo/ENVO_"
#   NCIT: "http://purl.obolibrary.org/obo/NCIT_"
#   MICRO: "http://purl.obolibrary.org/obo/MICRO_"
#   mesh: "http://id.nlm.nih.gov/mesh/"
#   BTO: "http://purl.obolibrary.org/obo/BTO_"
#   kgmicrobe.compound: "https://w3id.org/kg-microbe/compound/"
#   kgmicrobe.ingredient: "https://w3id.org/kg-microbe/ingredient/"
#   cas: "https://commonchemistry.cas.org/detail?cas_rn="
#   registry: "https://w3id.org/kg-microbe/registry/"
#   MIM: "https://github.com/CultureBotAI/MediaIngredientMech/blob/main/data/ingredients/mapped/"
#   obo: "http://purl.obolibrary.org/obo/"
#   kgm: "https://w3id.org/kg-microbe/"
#   semapv: "https://w3id.org/semapv/vocab/"
#   skos: "http://www.w3.org/2004/02/skos/core#"
#   orcid: "https://orcid.org/"
#   cbclaw: "https://github.com/culturebotai/culturebotai-claw/blob/main/"
# license: "{LICENSE}"
# mapping_set_id: "{MAPPING_SET_ID}"
# mapping_set_version: "{{version}}"
# mapping_set_description: "Canonical MediaIngredientMech → ingredient-ontology mappings (CHEBI + FOODON; UBERON/ENVO when populated). One row per mapped MIM ingredient record. Per-row object_source distinguishes ontologies. Predicate is skos:exactMatch by default; narrowMatch/broadMatch/closeMatch where residual-P2.5 triage found a specificity or symmetry difference, or where mapping_quality != EXACT_MATCH. The `source` extension column records the upstream origin (MIM evidence + kg-microbe source pipeline, CHEBI only). {POLICY_MARKER}."
# mapping_date: "{{version}}"
# predicate_semantics: skos
# creator_id:
#   - "orcid:0000-0001-8175-045X"
# subject_source: "MIM:ingredients"
# extension_definitions:
#   - slot_name: source
#     property: "cbclaw:provenance-source"
#     type_hint: "xsd:string"
#   - slot_name: validation_method
#     property: "cbclaw:validation-method"
#     type_hint: "xsd:string"
"""

COLUMNS = [
    "subject_id",
    "subject_label",
    "predicate_id",
    "object_id",
    "object_label",
    "object_source",
    "mapping_justification",
    "source",
    "mapping_date",
    "confidence",
    "comment",
    "other",
    "validation_method",
]


def _parse_mapping_date(value: object) -> date | None:
    """Parse a real ASCII ISO date, without normalizing invalid provenance."""
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _mapping_set_version(rows: list[dict]) -> str:
    """Bind header dates to emitted curation dates (MIM Rule G, #681).

    Preserve empty row dates for MIM's documented Rule F review path. Derive
    the header only from valid dated rows, never the clock. If no header can
    be derived, or nonempty dates are malformed, report every affected subject
    before opening the output (#686).
    """
    if not rows:
        raise ValueError("Cannot derive mapping_date from an empty mapping set")
    dates = []
    dateless = set()
    invalid = set()
    for row in rows:
        value = row.get("mapping_date", "")
        subject = str(row.get("subject_id", "<missing subject_id>"))
        if value == "":
            dateless.add(subject)
        elif (parsed := _parse_mapping_date(value)) is not None:
            dates.append(parsed)
        else:
            invalid.add(f"{subject}: {value!r}")
    if invalid:
        detail = "; ".join(sorted(invalid))
        raise ValueError(f"Invalid mapping_date values (all offenders): {detail}")
    if not dates:
        detail = ", ".join(sorted(dateless))
        raise ValueError(f"Cannot derive mapping_date: all subjects are dateless: {detail}")
    return max(dates).isoformat()


def _write_sssom(rows: list[dict], out_path: Path) -> None:
    version = _mapping_set_version(rows)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    header = HEADER_YAML.format(version=version)
    with out_path.open("w") as f:
        f.write(header)
        f.write("\t".join(COLUMNS) + "\n")
        for r in rows:
            f.write("\t".join(str(r.get(c, "")) for c in COLUMNS) + "\n")


def _sssom_validate(path: Path) -> list[str]:
    """Run `sssom validate` and collect hard errors (ignores informational
    `No attr for ...` warnings that sssom-py emits for declared extensions)."""
    try:
        proc = subprocess.run(
            [
                SSSOM_BIN, "validate",
                "-V", "JsonSchema",
                "-V", "PrefixMapCompleteness",
                "-V", "StrictCurieFormat",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=180,
        )
    except FileNotFoundError:
        return ["sssom CLI not on PATH; skipping validation"]
    combined = (proc.stdout or "") + "\n" + (proc.stderr or "")
    markers = ("is not well-formed", "is not a valid URI or CURIE", "must be supplied")
    errors = [ln.strip() for ln in combined.splitlines() if any(m in ln for m in markers)]
    if proc.returncode:
        errors.insert(0, f"sssom validate exited {proc.returncode}: {combined.strip()[:1000]}")
    return errors


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=OUT_TSV)
    ap.add_argument("--suppressed-aliases-output", type=Path)
    ap.add_argument("--generation-manifest-output", type=Path)
    ap.add_argument("--no-validate", action="store_true", help="skip external sssom validation (ownership and publication guards still run)")
    ap.add_argument(
        "--no-preserve-validation",
        action="store_true",
        help="don't replay validation_method stamps from the existing "
             "SSSOM (default: re-stamp matching rows so the OAK+OLS "
             "audit pass isn't clobbered).",
    )
    ap.add_argument(
        "--prior-stamps-from",
        type=Path,
        action="append",
        default=None,
        help="explicit path to read prior validation_method stamps from. "
             "May be passed multiple times; sources are merged (later "
             "wins on conflict). Defaults to both the workspace working "
             "copy (--output) AND the published MIM SSSOM, so audit "
             "stamps survive even when the workspace copy is empty "
             "(the typical pre-`just publish-sssom` state on a fresh "
             "checkout).",
    )
    args = ap.parse_args()
    _check_producer_bindings()
    require_mech_roots("mediaingredientmech", claw_root=REPO_ROOT)


    paths = artifact_paths(args.output, args.suppressed_aliases_output,
                           args.generation_manifest_output)
    args.output = paths[0]
    before = capture_beforeimages(paths)
    stamp_sources = ([] if args.no_preserve_validation else
                     [checked_path(p) for p in (args.prior_stamps_from or
                                             [args.output, MIM_PUBLISHED_SSSOM])])
    yamls = tuple(sorted(MIM_INGREDIENTS_DIR.glob("*.yaml")))
    producers = _producer_paths()
    inputs = set(yamls) | set(producers) | set(stamp_sources) | {
        RESIDUAL_JSON, KGM_UNIFIED_TSV, MIM_PUBLISHED_SSSOM,
    }
    snapshot = capture_beforeimages(inputs)
    # The working copy is an allowed stamp input, never a loophole for writing
    # the published canonical input or an ingredient/code/source path.
    working_copy_input = args.output in stamp_sources
    immutable = {p: b for p, b in snapshot.items() if p != args.output}
    protected = {checked_path(p) for p in (set(yamls) | set(producers) | {
        RESIDUAL_JSON, KGM_UNIFIED_TSV, MIM_PUBLISHED_SSSOM,
    })}
    if args.output in protected:
        raise ValueError("Candidate output overlaps a protected source input")
    if working_copy_input and snapshot[args.output] != before[args.output]:
        raise ValueError("Working-copy stamp beforeimage changed during capture")
    records = _read_mapped_records(MIM_INGREDIENTS_DIR, snapshot)
    owners = build_owner_index({_mim_curie(p.name): data for p, data in records.items()})

    def check_inputs():
        _check_producer_bindings()
        if tuple(sorted(MIM_INGREDIENTS_DIR.glob("*.yaml"))) != yamls:
            raise ValueError("Mapped-record path set changed during generation")
        if _producer_paths() != producers:
            raise ValueError("Producer path set changed during generation")
        if capture_beforeimages(immutable) != immutable:
            raise ValueError("Source input bytes changed during generation")

    check_inputs()
    with tempfile.TemporaryDirectory(prefix="mim-owned-name-") as temporary:
        stage = Path(temporary)
        frozen_paths = {}
        for index, source in enumerate(sorted(snapshot)):
            content = snapshot[source]
            if content is not None:
                frozen = stage / f"input-{index}{source.suffix}"
                frozen.write_bytes(content)
                frozen_paths[source] = frozen
        residual_bytes = snapshot[checked_path(RESIDUAL_JSON)]
        residual = ({d["source_file"]: d for d in json.loads(residual_bytes).get("decisions", [])}
                    if residual_bytes is not None else {})
        kgm_frozen = frozen_paths.get(checked_path(KGM_UNIFIED_TSV))
        kgm_sources = load_kgm_source_index(kgm_frozen) if kgm_frozen else {}
        kgm_labels = load_kgm_labels(kgm_frozen) if kgm_frozen else {}
        if kgm_frozen is None:
            _warn_if_kgm_missing()
        _build_candidate(args, paths, before, stamp_sources, snapshot, frozen_paths,
                         records, owners, residual, kgm_sources, kgm_labels,
                         stage, check_inputs, working_copy_input)


def _build_candidate(args, paths, before, stamp_sources, snapshot, frozen_paths,
                     records, owners, residual, kgm_sources, kgm_labels,
                     stage, check_inputs, working_copy_input):
    yamls = tuple(records)
    print(f"Scanning {len(yamls)} MIM ingredient YAMLs...", file=sys.stderr)
    # Group target term IDs by prefix so we can dispatch the right label
    # loader (OAK sqlite for CHEBI, OLS4 REST for FOODON, etc.). The
    # residual-P2.5 override can swap CHEBI to kg-microbe's more-specific
    # one, so include both sides when collecting CHEBIs.
    needed_by_prefix: dict[str, set[str]] = {p: set() for p in SUPPORTED_OBJECT_PREFIXES}
    for p in yamls:
        data = records[p]
        cid = ((data.get("ontology_mapping") or {}).get("ontology_id") or "").strip()
        for pref in SUPPORTED_OBJECT_PREFIXES:
            if cid.startswith(pref):
                needed_by_prefix[pref].add(cid)
                break
        dec = residual.get(p.name)
        if dec and (dec.get("kg_microbe_chebi") or "").startswith("CHEBI:"):
            needed_by_prefix["CHEBI:"].add(dec["kg_microbe_chebi"])

    canonical_labels: dict[str, str] = {}
    for pref, ids in needed_by_prefix.items():
        if not ids:
            continue
        ids_sorted = sorted(ids)
        if pref == "CHEBI:":
            print(f"Fetching rdfs:labels for {len(ids_sorted)} CHEBI ids from OAK...", file=sys.stderr)
            resolved = _load_chebi_labels(ids_sorted)
            if not resolved:
                print("  (OAK unavailable — falling back to MIM-stored ontology_label)", file=sys.stderr)
            else:
                print(f"  resolved {len(resolved)} / {len(ids_sorted)}", file=sys.stderr)
            canonical_labels.update(resolved)
        elif pref in ("FOODON:", "UBERON:", "ENVO:"):
            ontology = pref.rstrip(":").lower()
            iri_prefix = f"http://purl.obolibrary.org/obo/{pref.rstrip(':')}_"
            print(f"Fetching rdfs:labels for {len(ids_sorted)} {pref.rstrip(':')} ids from OLS4...", file=sys.stderr)
            resolved = _load_ols_labels(
                ids_sorted,
                ontology=ontology,
                iri_prefix=iri_prefix,
            )
            print(f"  resolved {len(resolved)} / {len(ids_sorted)}", file=sys.stderr)
            canonical_labels.update(resolved)
        else:
            print(f"  (no label loader for {pref}; falling back to MIM-stored labels)", file=sys.stderr)

    rows: list[dict] = []
    suppressions: list[Suppression] = []
    skipped_unsupported = 0
    for p in yamls:
        record_rows = _row_from_yaml(
            p, residual, kgm_sources, kgm_labels, canonical_labels,
            record=records[p], owners=owners, suppressions=suppressions)
        if not record_rows:
            skipped_unsupported += 1
            continue
        rows.extend(record_rows)

    # Dedup: registry-CURIE / parent dual emission means a single
    # subject can legitimately have multiple object rows. Dedup on
    # (subject_id, object_id) so we don't collapse the parent +
    # registry pair, but still drop accidental duplicates from
    # residual-redirect overlap.
    uniq: dict[tuple[str, str], dict] = {}
    for r in rows:
        uniq[(r["subject_id"], r["object_id"])] = r
    final = list(uniq.values())

    # Replay validation_method stamps from prior SSSOM emissions so a
    # downstream OAK+OLS audit pass isn't wiped on every rebuild. Only
    # rows whose (subject, predicate, object) triple matches an existing
    # row receive a stamp; newly-emitted rows stay blank.
    #
    # Sources merged (later wins on conflict):
    #   1. ``args.output`` — workspace working copy. Often empty in
    #      practice (cleaned between runs) but preserves stamps an
    #      iterative dev loop has produced in this run.
    #   2. ``MIM_PUBLISHED_SSSOM`` — the live published MIM TSV. This
    #      is where audit/QC stamps actually accumulate; reading from
    #      it ensures `just publish-sssom` from a clean workspace
    #      doesn't clobber audit history.
    # Pass ``--prior-stamps-from PATH`` (repeatable) to override.
    if not args.no_preserve_validation:
        prior_stamps: dict[tuple[str, str, str], str] = {}
        per_source: list[tuple[Path, int]] = []
        for src in stamp_sources:
            frozen = frozen_paths.get(src)
            loaded = _load_existing_validation_method(frozen) if frozen else {}
            per_source.append((src, len(loaded)))
            prior_stamps.update(loaded)  # later source overrides earlier
        # Fall back to (subject, object) when the predicate has changed since
        # the stamp was written. The stamps record verdicts about the *object*
        # -- `OAK+OLS:chebi|SYNONYM_ENRICH|...`, `none|UNKNOWN_TERM|...` -- so
        # a predicate correction does not invalidate them, and this loader
        # exists precisely so a rebuild does not wipe review state. Correcting
        # 448 identity rows to exactMatch (MediaIngredientMech#438) would
        # otherwise have silently dropped 389 stamps as collateral.
        #
        # Counted separately and reported: a carry-over across a predicate
        # change is a weaker claim than an exact-key replay, and a reviewer
        # who endorsed the old predicate should be able to see how many.
        #
        # The carry-over is restricted to STRENGTHENING changes (#126). It was
        # unconditional, which meant a genuine curation decision to weaken a
        # relation -- exactMatch to narrowMatch after a specificity review --
        # inherited the endorsement it was meant to withdraw and stayed out of
        # the review queue.
        outcomes = apply_replayed_stamps(final, prior_stamps)
        replayed = outcomes["replayed"]
        carried = outcomes["carried"]
        reset = outcomes["reset"]
        if prior_stamps:
            srcs = ", ".join(f"{p.name}={n}" for p, n in per_source if n)
            print(
                f"Replayed {replayed} validation_method stamps "
                f"(prior sources: {srcs}; {len(prior_stamps)} unique)",
                file=sys.stderr,
            )
            if carried:
                print(
                    f"  ...plus {carried} carried across a STRENGTHENED "
                    f"predicate (matched on subject+object; the object-level "
                    f"verdict still holds)",
                    file=sys.stderr,
                )
            if reset:
                print(
                    f"  ...and {reset} NOT carried because the predicate "
                    f"weakened or is unrecognised; those rows re-enter the "
                    f"review queue unstamped",
                    file=sys.stderr,
                )

    staged = stage / "candidate.sssom.tsv"
    _write_sssom(final, staged)
    proposed = staged.read_bytes()
    if not args.no_validate:
        errors = _sssom_validate(staged)
        if errors:
            raise ValueError("SSSOM validation FAILED: " + "; ".join(errors[:20]))
    if staged.read_bytes() != proposed:
        raise ValueError("Staged SSSOM changed during validation")
    sidecar = render_suppressed_aliases(suppressions)
    check_inputs()
    result = publish_candidate_artifacts(
        args.output, proposed, sidecar,
        {
            "scope": "diagnostic candidate; not canonical promotion or scientific approval",
            "external_sssom_validation": "skipped_explicitly" if args.no_validate else "passed",
            "prior_stamp_sources": [str(p) for p in stamp_sources],
            "source_inputs": [{"path": str(p), "sha256": _digest(content)}
                              for p, content in sorted(snapshot.items())],
            "producer_import_snapshot": {str(p): _digest(content)
                                         for p, content in _IMPORTED_PRODUCER_BYTES.items()},
            "producer_binding_scope": "source entrypoint plus captured local dependency graph; "
                                      "trusted caller/interpreter, not cryptographic runtime attestation",
            "mapped_record_paths": [str(p) for p in yamls],
            "source_revisions": {"claw": _revision(REPO_ROOT), "mim": _revision(MIM_ROOT),
                                 "kg_microbe": _revision(KGM_ROOT)},
            "canonical_label_resolution": dict(sorted(canonical_labels.items())),
            "policy_evidence": list(OWNED_NAME_EVIDENCE),
            "emitted_rows": len(final),
        }, check_inputs, input_paths=snapshot,
        expected_before=before, claw_root=REPO_ROOT,
        working_copy_stamp_input=working_copy_input,
        sidecar_output=paths[1], manifest_output=paths[2],
    )
    print(f"Published {len(final)} diagnostic rows to {args.output} ({result['status']})",
          file=sys.stderr)
    print(
        f"  (skipped {skipped_unsupported} MIM records without a supported ontology_id "
        f"prefix: {', '.join(SUPPORTED_OBJECT_PREFIXES)})",
        file=sys.stderr,
    )

    # Predicate breakdown so we can see at a glance how many rows got
    # upgraded beyond skos:exactMatch by the residual pass.
    pred_counts: dict[str, int] = {}
    for r in final:
        pred_counts[r["predicate_id"]] = pred_counts.get(r["predicate_id"], 0) + 1
    print("Predicate breakdown:", file=sys.stderr)
    for p, n in sorted(pred_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {p:24s} {n}", file=sys.stderr)

    # Per-prefix row counts (CHEBI vs FOODON vs ...).
    pref_counts: dict[str, int] = {}
    for r in final:
        for pref in SUPPORTED_OBJECT_PREFIXES:
            if r["object_id"].startswith(pref):
                pref_counts[pref] = pref_counts.get(pref, 0) + 1
                break
    print("Object-prefix breakdown:", file=sys.stderr)
    for pref, n in sorted(pref_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {pref:10s} {n}", file=sys.stderr)



if __name__ == "__main__":
    main()
