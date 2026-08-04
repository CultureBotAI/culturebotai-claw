#!/usr/bin/env /opt/homebrew/bin/python3.13
"""
Unified ingredient-import pipeline. See
.claude/skills/ingredient-mapping/SKILL.md for the full architecture.

Source loaders (--source <X>) yield Candidate dicts. The resolver
cascade tries each tier in order until a match is found. Every
candidate ends up in MIM somewhere — MAPPED with CHEBI/NCIT/cas: or
UNMAPPED_NNNN. No row is dropped.

Usage:
    python scripts/import_ingredients.py --source culturebotht --apply
    python scripts/import_ingredients.py --source kgm-unmapped --apply
    python scripts/import_ingredients.py --source mim-queue --apply --accept-medium
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

import yaml

# ---------- paths ----------

WORKSPACE = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/culturebotai-claw/workspace"
)
# Overridable so an import can target a git worktree instead of the primary
# checkout. Without this the hardcoded path writes into whatever branch the main
# MediaIngredientMech checkout happens to have out — which, when the onboarding
# work lives on a worktree branch, is the wrong one and is invisible until the
# records show up in someone else's diff.
MIM_INGREDIENTS = Path(
    os.environ.get(
        "MIM_INGREDIENTS_DIR",
        "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/"
        "MediaIngredientMech/data/ingredients",
    )
)
MAPPED_DIR = MIM_INGREDIENTS / "mapped"
UNMAPPED_DIR = MIM_INGREDIENTS / "unmapped"

CULTUREBOT_ROOT = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CultureBotHT/CultureBotHT"
)
KGM_ROOT = Path("/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/kg-microbe")
CULTUREMECH_ROOT = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CultureMech"
)
COMMUNITYMECH_ROOT = Path(
    "/Users/marcin/Documents/VIMSS/ontology/KG-Hub/KG-Microbe/CommunityMech/CommunityMech"
)

OLS_CAS_CACHE = WORKSPACE / "cache/ols_cas_cache.json"
PUBCHEM_CACHE = WORKSPACE / "cache/pubchem_cas_chebi.json"
OAK_CAS_INDEX = WORKSPACE / "cache/cas_to_chebi.json"

OLS_SEARCH = "https://www.ebi.ac.uk/ols4/api/search"

PANEL_COLUMNS = (
    "Hans80Anti", "Hans80metals", "FEBA_carbon",
    "FEBA_nitrogen", "FEBA_stress", "All_star",
)

TIMESTAMP = datetime.now(timezone.utc).isoformat()

sys.path.insert(0, str(Path(__file__).parent))
from apply_mim_chebi_fixes import _slug as slugify  # noqa: E402


# ---------- candidate model ----------

@dataclasses.dataclass
class Candidate:
    name: str
    cas: str = ""
    source_id: str = ""
    preset_id: str = ""    # already-resolved ontology CURIE; bypasses OLS/OAK
    preset_label: str = "" # ontology label that came with the preset_id
    synonyms: list[str] = dataclasses.field(default_factory=list)
    panels: list[str] = dataclasses.field(default_factory=list)
    media_uses: list[str] = dataclasses.field(default_factory=list)
    raw: dict = dataclasses.field(default_factory=dict)


@dataclasses.dataclass
class ResolveResult:
    primary: str = ""              # CHEBI:N / NCIT:N / cas:N / UNMAPPED_NNNN / ""
    label: str = ""                # ontology label (when applicable)
    method: str = "no-match"       # which resolver tier hit
    confidence: str = "NONE"       # HIGH / MEDIUM / LOW / NONE / FALLBACK_REGISTRY / UNMAPPED


# ---------- caches ----------

def _load_json_cache(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            pass
    return {}


def _save_json_cache(path: Path, cache: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, indent=2))


# ---------- MIM existing index ----------

def build_mim_index() -> tuple[set[str], dict[str, str], dict[str, str], set[str]]:
    """Return (labels lowercased, CAS→file, CHEBI→file, slugs lowercased)."""
    labels: set[str] = set()
    by_cas: dict[str, str] = {}
    by_chebi: dict[str, str] = {}
    slugs: set[str] = set()
    for d in (MAPPED_DIR, UNMAPPED_DIR):
        for p in d.glob("*.yaml"):
            try:
                doc = yaml.safe_load(p.read_text())
            except Exception:
                continue
            if not isinstance(doc, dict):
                continue
            labels.add((doc.get("preferred_term") or "").lower().strip())
            for s in doc.get("synonyms") or []:
                if isinstance(s, dict):
                    t = (s.get("synonym_text") or "").lower().strip()
                    if t:
                        labels.add(t)
            cas = ((doc.get("chemical_properties") or {}).get("cas_rn") or "").strip()
            if cas:
                by_cas.setdefault(cas, p.name)
            chebi = ((doc.get("ontology_mapping") or {}).get("ontology_id") or "").strip()
            if chebi.startswith(("CHEBI:", "NCIT:", "cas:")):
                by_chebi.setdefault(chebi, p.name)
            slugs.add(p.stem.lower())
    labels.discard("")
    return labels, by_cas, by_chebi, slugs


def next_unmapped_id() -> int:
    max_id = 0
    for p in UNMAPPED_DIR.glob("*.yaml"):
        try:
            text = p.read_text()
        except Exception:
            continue
        m = re.search(r"identifier:\s*UNMAPPED_(\d+)", text)
        if m:
            n = int(m.group(1))
            if n > max_id:
                max_id = n
    return max_id + 1


# ---------- resolver tiers ----------

def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower().strip())


def ols_search_by_name(term: str, ontology: str, cache: dict) -> dict | None:
    """Return HIGH-confidence hit (label-exact or synonym-exact) or None."""
    key = f"name::{ontology}::{term}"
    if key in cache:
        return cache[key]
    params = urllib.parse.urlencode({
        "q": term, "ontology": ontology, "rows": 5,
        "exact": "false", "type": "class",
    })
    try:
        with urllib.request.urlopen(f"{OLS_SEARCH}?{params}", timeout=15) as r:
            j = json.loads(r.read())
    except Exception as e:
        cache[key] = {"error": str(e)}
        return None
    n = _norm(term)
    expected_prefix = ontology.upper() + ":"
    for d in j.get("response", {}).get("docs", []):
        if d.get("is_obsolete"):
            continue
        curie = d.get("obo_id") or d.get("short_form", "").replace("_", ":")
        if not curie or not curie.upper().startswith(expected_prefix):
            continue
        if _norm(d.get("label", "")) == n:
            cache[key] = {"chebi": curie, "label": d.get("label", ""),
                          "match": "label-exact"}
            return cache[key]
        if n in {_norm(s) for s in (d.get("synonym") or [])}:
            cache[key] = {"chebi": curie, "label": d.get("label", ""),
                          "match": "synonym-exact"}
            return cache[key]
    cache[key] = None
    return None


def oak_cas_lookup(cas: str, oak_index: dict) -> str | None:
    """Local CHEBI sqlite CAS-xref lookup."""
    return oak_index.get(cas)


def pubchem_cas_to_chebi(cas: str, cache: dict) -> str | None:
    """Resolve CAS via PubChem CID→synonyms (looks for CHEBI: prefix)."""
    if cas in cache:
        return cache[cas]
    try:
        cid_url = (f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/xref/"
                   f"RegistryID/{cas}/cids/JSON")
        with urllib.request.urlopen(cid_url, timeout=15) as r:
            j = json.loads(r.read())
        cids = j.get("InformationList", {}).get("Information", [])
        if not cids:
            cache[cas] = None
            return None
        cid = cids[0].get("CID", [None])[0]
        if not cid:
            cache[cas] = None
            return None
        syn_url = (f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/"
                   f"{cid}/synonyms/JSON")
        with urllib.request.urlopen(syn_url, timeout=15) as r:
            sj = json.loads(r.read())
        syns = sj.get("InformationList", {}).get("Information", [])
        if not syns:
            cache[cas] = None
            return None
        for s in syns[0].get("Synonym", []):
            m = re.match(r"^CHEBI:(\d+)$", s.strip())
            if m:
                chebi = f"CHEBI:{m.group(1)}"
                cache[cas] = chebi
                return chebi
    except Exception:
        pass
    cache[cas] = None
    return None


class Resolver:
    """Tries each tier in priority order; returns first match."""

    def __init__(self, ols_cache: dict, oak_index: dict, pubchem_cache: dict,
                 use_pubchem: bool = True, accept_medium: bool = False):
        self.ols_cache = ols_cache
        self.oak_index = oak_index
        self.pubchem_cache = pubchem_cache
        self.use_pubchem = use_pubchem
        self.accept_medium = accept_medium

    def resolve(self, c: Candidate) -> ResolveResult:
        # Tier 0: source has a pre-set authoritative ontology ID
        # (e.g. kg-microbe metatraits chemical_mappings already
        # carries a CHEBI/FOODON/ENVO/NCIT object_id).
        if c.preset_id and c.preset_id.startswith(
            ("CHEBI:", "FOODON:", "UBERON:", "ENVO:", "NCIT:")
        ):
            return ResolveResult(c.preset_id, c.preset_label or c.name,
                                 "source-preset", "HIGH")

        # Tier 2: OLS exact label/synonym in CHEBI
        hit = ols_search_by_name(c.name, "chebi", self.ols_cache)
        if hit and "chebi" in hit:
            return ResolveResult(hit["chebi"], hit.get("label", ""),
                                 f"ols-{hit['match']}-chebi", "HIGH")

        # Tier 4: OAK CHEBI CAS-xref
        if c.cas:
            chebi = oak_cas_lookup(c.cas, self.oak_index)
            if chebi:
                return ResolveResult(chebi, "", "oak-cas-xref", "HIGH")

        # Tier 5: PubChem CID→CHEBI synonym
        if c.cas and self.use_pubchem and self.accept_medium:
            chebi = pubchem_cas_to_chebi(c.cas, self.pubchem_cache)
            if chebi:
                return ResolveResult(chebi, "", "pubchem-cid-synonym", "MEDIUM")

        # Tier 6: NCIT exact match
        hit = ols_search_by_name(c.name, "ncit", self.ols_cache)
        if hit and hit.get("chebi", "").startswith("NCIT:"):
            return ResolveResult(hit["chebi"], hit.get("label", ""),
                                 f"ols-{hit['match']}-ncit", "HIGH")

        # Tier 7: CAS fallback
        if c.cas:
            return ResolveResult(f"cas:{c.cas}", c.name, "cas-fallback",
                                 "FALLBACK_REGISTRY")

        # Tier 8: UNMAPPED
        return ResolveResult("", c.name, "unmapped", "UNMAPPED")


# ---------- YAML emitter ----------

def emit_mapped_yaml(path: Path, c: Candidate, r: ResolveResult,
                     source_name: str) -> tuple[bool, str]:
    if path.exists():
        return False, "yaml exists"
    primary = r.primary
    label = r.label or c.name
    notes = (
        f"Imported from {source_name} via {r.method}. "
        f"source_id={c.source_id or '—'}; "
    )
    if c.panels:
        notes += f"FEBA/Hans80 panels: {', '.join(c.panels)}. "
    if c.media_uses:
        notes += (
            f"Used in {len(c.media_uses)} CultureBot media; samples: "
            f"{', '.join(c.media_uses[:3])}{'…' if len(c.media_uses) > 3 else ''}. "
        )
    extra_synonyms = [
        {"synonym_text": s, "synonym_type": "EXACT_SYNONYM",
         "source": source_name}
        for s in c.synonyms if s.strip().lower() != c.name.lower()
    ]
    ontology_source = {
        "CHEBI:": "CHEBI",
        "NCIT:": "NCIT",
        "cas:": "CAS",
        "kgmicrobe.compound:": "kgmicrobe.compound",
    }
    src = next((v for k, v in ontology_source.items() if primary.startswith(k)),
               "registry")
    mapping_quality = "FALLBACK_REGISTRY" if r.confidence == "FALLBACK_REGISTRY" \
        else "EXACT_MATCH" if r.confidence == "HIGH" else "LEXICAL_MATCH"
    doc = {
        "identifier": primary,
        "preferred_term": c.name,
        "ontology_mapping": {
            "ontology_id": primary,
            "ontology_label": label,
            "ontology_source": src,
            "mapping_quality": mapping_quality,
            "evidence": [
                {
                    "evidence_type": ("DATABASE_MATCH" if r.method.startswith(("oak", "ols-cas", "cas-"))
                                     else "LEXICAL_MATCH"),
                    "source": source_name,
                    "notes": notes,
                }
            ],
        },
        "synonyms": extra_synonyms,
        "mapping_status": "MAPPED",
        "occurrence_statistics": {
            "total_occurrences": len(c.media_uses),
            "media_count": len(c.media_uses),
        },
        "curation_history": [
            {
                "timestamp": TIMESTAMP,
                "curator": f"audit_import_ingredients[{source_name}]",
                "action": "CREATED_FROM_INGREDIENT_IMPORT",
                "changes": notes,
                "new_status": "MAPPED",
                "llm_assisted": False,
            }
        ],
    }
    if c.cas:
        doc["chemical_properties"] = {
            "cas_rn": c.cas,
            "data_source": source_name,
            "retrieval_date": TIMESTAMP,
        }
    path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
    return True, f"created {path.name} → {primary} ({r.method})"


def emit_unmapped_yaml(path: Path, c: Candidate, identifier: str,
                       source_name: str) -> tuple[bool, str]:
    if path.exists():
        return False, "yaml exists"
    notes = (
        f"Imported from {source_name} (source_id={c.source_id or '—'}); "
        f"no CAS-RN or CHEBI/NCIT match. Curator review needed."
    )
    if c.media_uses:
        notes += (f" Used in {len(c.media_uses)} CultureBot media; samples: "
                  f"{', '.join(c.media_uses[:3])}.")
    doc = {
        "identifier": identifier,
        "preferred_term": c.name,
        "synonyms": [
            {"synonym_text": s, "synonym_type": "RAW_TEXT", "source": source_name}
            for s in (c.synonyms or [c.name])
        ],
        "mapping_status": "UNMAPPED",
        "occurrence_statistics": {
            "total_occurrences": len(c.media_uses),
            "media_count": len(c.media_uses),
        },
        "curation_history": [
            {
                "timestamp": TIMESTAMP,
                "curator": f"audit_import_ingredients[{source_name}]",
                "action": "CREATED_AS_UNMAPPED",
                "changes": notes,
                "new_status": "UNMAPPED",
                "llm_assisted": False,
            }
        ],
        "notes": notes,
    }
    path.write_text(yaml.safe_dump(doc, sort_keys=False, allow_unicode=True))
    return True, f"created {path.name} (UNMAPPED)"


# ---------- source loaders ----------

def src_kgm_unmapped() -> Iterable[Candidate]:
    src = KGM_ROOT / "docs/metatraits/unmapped_compounds.tsv"
    if not src.exists():
        return
    with src.open() as f:
        for r in csv.DictReader(f, delimiter="\t"):
            label = (r.get("label_token") or "").strip()
            if not label:
                continue
            # Title-case (e.g. "aburamycin a" → "Aburamycin A")
            parts = label.split()
            name = " ".join(p[0].upper() + p[1:] if len(p) > 1 else p.upper()
                            for p in parts)
            yield Candidate(
                name=name, cas="",
                source_id=r.get("placeholder_id", ""),
                raw=r,
            )


# Source columns whose labels are chemicals/ingredients. The file's own
# `category` tag is NOT usable for this: only 73 of 5,224 rows are tagged
# biolink:ChemicalEntity, while ~1,023 chemicals sit in rows tagged
# biolink:PhenotypicQuality because they came from metabolite-utilization and
# antibiotic assays. Classify by provenance column, not by the category guess.
_MICRODECODER_INGREDIENT_COLUMNS = (
    "BacDive_Metabolite_utilization",
    "BacDive_Metabolite_production",
    "BacDive_Antibiotic_sensitivity",
    "BacDive_Antibiotic_resistance",
    "bergey:substrates",
    "bergey:major_end_products",
    "bergey:minor_end_products",
    "literature:substrates",
)

# Labels that survive the column filter but are not ingredients: bare numbers,
# units, and assay non-answers.
_MICRODECODER_NOISE = {
    "not reported", "not determined", "n/a", "na", "none", "unknown",
    "%", "%(w/v)", "+", "-", "+/-", "positive", "negative",
}


def src_microbedecoder() -> Iterable[Candidate]:
    """kg-microbe microbedecoder labels that its transform could not map.

    Distinct from `kgm-unmapped`, which reads docs/metatraits/unmapped_compounds.tsv
    (122 compound rows). This is the broader microbedecoder dump: 5,224 rows of
    which only the ingredient-bearing columns above are in MIM's scope — the rest
    are phenotype measurements, isolation-category context and metabolic
    pathways, which belong to TraitMech, not here.
    """
    src = KGM_ROOT / "data/transformed/microbedecoder/unmapped_labels.tsv"
    if not src.exists():
        return
    with src.open() as f:
        for r in csv.DictReader(f, delimiter="\t"):
            columns = r.get("source_columns") or ""
            if not any(c in columns for c in _MICRODECODER_INGREDIENT_COLUMNS):
                continue
            label = (r.get("label") or "").strip()
            if not label or label.lower() in _MICRODECODER_NOISE:
                continue
            # Bare numerics and measurement fragments ("1", "3.5", "0.5%").
            if label.replace(".", "", 1).replace("%", "").strip().isdigit():
                continue
            parts = label.split()
            name = " ".join(
                p[0].upper() + p[1:] if len(p) > 1 else p.upper() for p in parts
            )
            yield Candidate(
                name=name, cas="",
                source_id=r.get("placeholder_curie", ""),
                raw=r,
            )


def src_culturebotht() -> Iterable[Candidate]:
    compounds_csv = CULTUREBOT_ROOT / "data/raw/google_sheets/compounds_to_cas.csv"
    media_json = CULTUREBOT_ROOT / "data/consolidated/consolidated_media.json"
    # Build media-usage index first.
    ing_to_media: dict[str, list[str]] = defaultdict(list)
    media_cas: dict[str, str] = {}
    if media_json.exists():
        data = json.loads(media_json.read_text())
        for medium_name, m in data.items():
            for ing in m.get("ingredients", []):
                n = (ing.get("name") or "").strip()
                if not n:
                    continue
                ing_to_media[n].append(medium_name)
                if ing.get("cas_number") and n not in media_cas:
                    media_cas[n] = ing["cas_number"].strip()
    # Compound master pass.
    seen: set[str] = set()
    if compounds_csv.exists():
        with compounds_csv.open() as f:
            for r in csv.DictReader(f):
                name = (r.get("Compound") or "").strip()
                cas = (r.get("CAS") or "").strip()
                # Sanitize multi-CAS values: take first.
                if cas and (" " in cas or "/" in cas):
                    cas = cas.split("/")[0].split()[0].strip()
                if not name:
                    continue
                seen.add(name.lower())
                panels = [p for p in PANEL_COLUMNS if (r.get(p) or "").strip()]
                synonyms = [s.strip() for s in
                            (r.get("Synonyms") or "").split(";") if s.strip()]
                yield Candidate(
                    name=name, cas=cas,
                    source_id="culturebotht.compound:" + name.replace(" ", "_"),
                    synonyms=synonyms,
                    panels=panels,
                    media_uses=ing_to_media.get(name, []),
                    raw=r,
                )
    # Media-only pass — names not in compound master.
    for n, media_uses in ing_to_media.items():
        if n.lower() in seen:
            continue
        cas = media_cas.get(n, "")
        if cas and (" " in cas or "/" in cas):
            cas = cas.split("/")[0].split()[0].strip()
        yield Candidate(
            name=n, cas=cas,
            source_id="culturebotht.media:" + n.replace(" ", "_"),
            media_uses=media_uses,
        )


def src_mim_queue() -> Iterable[Candidate]:
    src = WORKSPACE / "reports/mim_curation_queue.tsv"
    if not src.exists():
        return
    with src.open() as f:
        for r in csv.DictReader(f, delimiter="\t"):
            if (r.get("already_in_mim") or "no").strip() == "yes":
                continue
            name = (r.get("preferred_term") or "").strip()
            if not name:
                continue
            yield Candidate(
                name=name, cas="",
                source_id=r.get("source_id", ""),
                raw=r,
            )


def src_kgm_metatraits() -> Iterable[Candidate]:
    """kg-microbe's out-of-SSSOM chemical mappings:
       kg_microbe/transform_utils/metatraits/mappings/{chemical_mappings,
       special_chemical_mappings}.tsv. Each row already carries an
       authoritative ontology ID, so the resolver's preset tier accepts
       it directly.
    """
    base = (KGM_ROOT / "kg_microbe/transform_utils/metatraits/mappings")
    seen: set[str] = set()  # dedupe by name (these files have repeats)

    chem_path = base / "chemical_mappings.tsv"
    if chem_path.exists():
        with chem_path.open() as f:
            header = f.readline().rstrip("\n").split("\t")
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) < len(header):
                    parts += [""] * (len(header) - len(parts))
                row = dict(zip(header, parts))
                raw = (row.get("subject_label") or "").strip()
                # "produces: ethanol" → "ethanol"
                name = raw.split(":", 1)[-1].strip() if ":" in raw else raw
                if not name or name.lower() in seen:
                    continue
                obj = (row.get("object_id") or "").strip()
                if not obj:
                    continue
                seen.add(name.lower())
                yield Candidate(
                    name=name.capitalize() if name.islower() else name,
                    preset_id=obj,
                    preset_label=(row.get("object_label") or "").strip(),
                    source_id=f"kgm.metatraits.chemical:{name.replace(' ', '_')}",
                )

    sp_path = base / "special_chemical_mappings.tsv"
    if sp_path.exists():
        with sp_path.open() as f:
            header = f.readline().rstrip("\n").split("\t")
            for line in f:
                parts = line.rstrip("\n").split("\t")
                if len(parts) < len(header):
                    parts += [""] * (len(header) - len(parts))
                row = dict(zip(header, parts))
                name = (row.get("chemical_name") or "").strip()
                if not name or name.lower() in seen:
                    continue
                obj = (row.get("ontology_id") or "").strip()
                if not obj:
                    continue
                seen.add(name.lower())
                yield Candidate(
                    name=name.capitalize() if name.islower() else name,
                    preset_id=obj,
                    preset_label=(row.get("ontology_name") or "").strip(),
                    source_id=f"kgm.metatraits.special:{name.replace(' ', '_')}",
                )


def src_culturemech_pending() -> Iterable[Candidate]:
    """CultureMech ingredients flagged as 'NEW - Not in MediaIngredientMech'
    in the migration tracking TSV. Each row already carries an authoritative
    CHEBI ID + label, so the resolver's preset tier accepts it directly."""
    p = (CULTUREMECH_ROOT / "data/import_tracking"
         / "new_solution_ingredients_vs_mediaingredientmech.tsv")
    if not p.exists():
        return
    with p.open() as f:
        for r in csv.DictReader(f, delimiter="\t"):
            status = (r.get("MediaIngredientMech Status") or "").strip()
            if "NEW" not in status and "Not in" not in status:
                continue
            name = (r.get("Preferred Term") or "").strip()
            if not name:
                continue
            chebi = (r.get("CHEBI ID") or "").strip()
            yield Candidate(
                name=name,
                preset_id=chebi if chebi.startswith("CHEBI:") else "",
                preset_label=(r.get("CHEBI Label") or "").strip(),
                source_id=f"culturemech.solution_ingredient:{name.replace(' ', '_')}",
                raw=dict(r),
            )


def src_communitymech_unmapped() -> Iterable[Candidate]:
    """CommunityMech ingredients with status=unmapped in the
    per-community ingredient_mapping report. Names repeat across
    communities — dedupe on normalized name."""
    p = COMMUNITYMECH_ROOT / "reports" / "ingredient_mapping.csv"
    if not p.exists():
        return
    seen: set[str] = set()
    with p.open() as f:
        for r in csv.DictReader(f):
            if (r.get("status") or "").strip() != "unmapped":
                continue
            name = (r.get("ingredient_name") or "").strip()
            if not name:
                continue
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            yield Candidate(
                name=name,
                source_id=f"communitymech.ingredient:{name.replace(' ', '_')}",
                raw=dict(r),
            )


_SOURCES: dict[str, Callable[[], Iterable[Candidate]]] = {
    "kgm-unmapped": src_kgm_unmapped,
    "microbedecoder": src_microbedecoder,
    "kgm-metatraits": src_kgm_metatraits,
    "culturebotht": src_culturebotht,
    "mim-queue": src_mim_queue,
    "culturemech-pending": src_culturemech_pending,
    "communitymech-unmapped": src_communitymech_unmapped,
}


# ---------- driver ----------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", required=True, choices=list(_SOURCES))
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--no-pubchem", action="store_true",
                    help="Skip PubChem fallback (faster, less coverage).")
    ap.add_argument("--accept-medium", action="store_true",
                    help="Auto-create MIM YAMLs for MEDIUM-confidence "
                         "PubChem-resolved hits (default: queue them).")
    ap.add_argument("--max", type=int, default=None,
                    help="Stop after N candidates (for testing).")
    args = ap.parse_args()

    print(f"[1/5] Indexing existing MIM")
    labels, by_cas, by_chebi, slugs = build_mim_index()
    print(f"      {len(labels)} labels, {len(by_cas)} CAS, {len(by_chebi)} primary IDs, "
          f"{len(slugs)} slugs")

    print(f"[2/5] Loading caches")
    ols_cache = _load_json_cache(OLS_CAS_CACHE)
    pubchem_cache = _load_json_cache(PUBCHEM_CACHE)
    oak_index = _load_json_cache(OAK_CAS_INDEX)
    print(f"      OLS:{len(ols_cache)} OAK:{len(oak_index)} PubChem:{len(pubchem_cache)}")

    resolver = Resolver(ols_cache, oak_index, pubchem_cache,
                        use_pubchem=not args.no_pubchem,
                        accept_medium=args.accept_medium)

    print(f"[3/5] Streaming candidates from --source {args.source}")
    counts = defaultdict(int)
    method_counts = defaultdict(int)
    minted_slugs: set[str] = set()
    next_id = next_unmapped_id()
    sample_records = []

    start = time.time()
    for i, c in enumerate(_SOURCES[args.source]()):
        if args.max and i >= args.max:
            break
        # Skip if name or CAS already in MIM.
        if c.name.lower() in labels:
            counts["skipped_already_in_mim"] += 1
            continue
        if c.cas and c.cas in by_cas:
            counts["skipped_already_in_mim"] += 1
            continue
        # Slug collision guard.
        slug = slugify(c.name)
        if slug.lower() in slugs or slug.lower() in minted_slugs:
            counts["skipped_slug_collision"] += 1
            continue
        result = resolver.resolve(c)
        method_counts[result.method] += 1

        if result.confidence in ("HIGH", "FALLBACK_REGISTRY") or \
                (result.confidence == "MEDIUM" and args.accept_medium):
            # Check primary collision (CHEBI/NCIT/cas: already in MIM).
            if result.primary in by_chebi:
                counts["chebi_collision"] += 1
                continue
            path = MAPPED_DIR / f"{slug}.yaml"
            if args.apply:
                ok, _ = emit_mapped_yaml(path, c, result, args.source)
                if ok:
                    counts["mapped_created"] += 1
                    by_chebi[result.primary] = path.name
                    if c.cas:
                        by_cas[c.cas] = path.name
                    labels.add(c.name.lower())
                    slugs.add(slug.lower())
                    minted_slugs.add(slug.lower())
            else:
                counts["mapped_created"] += 1
                minted_slugs.add(slug.lower())
            sample_records.append({
                "name": c.name, "primary": result.primary,
                "method": result.method, "confidence": result.confidence,
            })
        else:
            # UNMAPPED bucket — always reachable since fallback tiers cover all.
            # Special case for kgm-unmapped: keep kgmicrobe.compound: as primary.
            if args.source == "kgm-unmapped" and c.source_id.startswith("kgmicrobe.compound:"):
                # Mint a MAPPED record with the kgmicrobe.compound: primary.
                path = MAPPED_DIR / f"{slug}.yaml"
                placeholder_result = ResolveResult(
                    primary=c.source_id, label=c.name,
                    method="kgm-placeholder", confidence="HIGH",
                )
                if args.apply:
                    ok, _ = emit_mapped_yaml(path, c, placeholder_result, args.source)
                    if ok:
                        counts["mapped_created"] += 1
                        by_chebi[c.source_id] = path.name
                        labels.add(c.name.lower())
                        slugs.add(slug.lower())
                        minted_slugs.add(slug.lower())
                else:
                    counts["mapped_created"] += 1
                    minted_slugs.add(slug.lower())
                continue
            # Default: UNMAPPED_NNNN
            path = UNMAPPED_DIR / f"{slug}.yaml"
            identifier = f"UNMAPPED_{next_id:04d}"
            if args.apply:
                ok, _ = emit_unmapped_yaml(path, c, identifier, args.source)
                if ok:
                    counts["unmapped_created"] += 1
                    next_id += 1
                    labels.add(c.name.lower())
                    slugs.add(slug.lower())
                    minted_slugs.add(slug.lower())
            else:
                counts["unmapped_created"] += 1
                next_id += 1
                minted_slugs.add(slug.lower())

        if (i + 1) % 100 == 0:
            elapsed = time.time() - start
            print(f"  {i+1} candidates in {elapsed:.0f}s "
                  f"(mapped={counts['mapped_created']}, "
                  f"unmapped={counts['unmapped_created']})", flush=True)
            _save_json_cache(OLS_CAS_CACHE, ols_cache)
            _save_json_cache(PUBCHEM_CACHE, pubchem_cache)

    _save_json_cache(OLS_CAS_CACHE, ols_cache)
    _save_json_cache(PUBCHEM_CACHE, pubchem_cache)

    print(f"\n[4/5] Outcome ({'APPLY' if args.apply else 'DRY-RUN'}):")
    for k, v in counts.items():
        print(f"  {k}: {v}")
    print(f"\n  Resolver methods:")
    for k, v in sorted(method_counts.items(), key=lambda x: -x[1]):
        print(f"    {k}: {v}")

    # Summary markdown
    summary_md = WORKSPACE / f"reports/import_summary_{args.source}.md"
    summary_md.parent.mkdir(parents=True, exist_ok=True)
    out = [
        f"# Ingredient Import — {args.source}\n",
        f"**Mode:** {'APPLY' if args.apply else 'DRY-RUN'}  \n",
        f"**Timestamp:** {TIMESTAMP}\n\n",
        "## Outcome\n\n| Outcome | Count |\n|---|---:|\n",
    ]
    for k, v in counts.items():
        out.append(f"| {k} | {v} |\n")
    out.append("\n## Resolver method breakdown\n\n| Method | Count |\n|---|---:|\n")
    for k, v in sorted(method_counts.items(), key=lambda x: -x[1]):
        out.append(f"| {k} | {v} |\n")
    if sample_records:
        out.append("\n## Sample mapped records (first 25)\n\n")
        out.append("| Name | Primary | Method | Confidence |\n|---|---|---|---|\n")
        for r in sample_records[:25]:
            out.append(f"| {r['name']} | `{r['primary']}` | {r['method']} | {r['confidence']} |\n")
    summary_md.write_text("".join(out))
    print(f"\n[5/5] Summary: {summary_md}")


if __name__ == "__main__":
    main()
