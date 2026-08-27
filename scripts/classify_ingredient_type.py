#!/usr/bin/env /opt/homebrew/bin/python3.13
"""Auto-populate the `ingredient_type` slot on every MIM ingredient YAML.

The schema's `IngredientTypeEnum` (mediaingredientmech.yaml) already
distinguishes chemically-defined vs complex, but as of this commit
0/2,349 records have it set. This script walks all YAMLs and assigns
a default value based on:

  1. The ontology source of the primary identifier
  2. Name-based hints (presence of words like "extract", "peptone")
  3. A small override list for known-complex CHEBI terms

The classifier is conservative: when uncertain, it leaves the slot
unset rather than guessing. Records resolved to UNMAPPED_NNNN slugs
always remain unset (curator decides).

Vocabulary (existing schema):
  SINGLE_INGREDIENT — pure compound (defined; CHEBI/NCIT/cas:)
  UNDEFINED_MIXTURE — yeast extract / peptone / soil extract
  NAMED_MEDIUM      — full media recipe (DEFINED_MEDIUM pre-#222)
  STOCK_SOLUTION    — pre-mixed defined components

Usage:
  python3 scripts/classify_ingredient_type.py             # dry-run
  python3 scripts/classify_ingredient_type.py --apply     # write YAMLs
  python3 scripts/classify_ingredient_type.py --override  # also overwrite
                                                          # already-set values
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import re
import sys
from functools import lru_cache
from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
MIM_ROOT = Path(os.environ.get(
    "MEDIAINGREDIENTMECH_ROOT",
    REPO_ROOT.parent / "MediaIngredientMech",
))
INGREDIENTS = MIM_ROOT / "data" / "ingredients"
SCHEMA = MIM_ROOT / "src" / "mediaingredientmech" / "schema" / "mediaingredientmech.yaml"

# The spelling MIM's schema uses today; MediaIngredientMech#479 renamed
# DEFINED_MEDIUM to NAMED_MEDIUM for #222.
CANONICAL_MEDIUM_GRANULARITY = "NAMED_MEDIUM"

# Candidates for "this record is a whole named medium", newest spelling first.
# The retired spelling stays in the *lookup* so a pre-rename MIM checkout still
# gets a token its own schema accepts. It is no longer an answer of last
# resort: nothing returns it unless that checkout's schema names it (#147).
_MEDIUM_GRANULARITY = (CANONICAL_MEDIUM_GRANULARITY, "DEFINED_MEDIUM")


class VocabularyError(RuntimeError):
    """A MIM checkout is present but its ingredient-type vocabulary is unreadable."""


@lru_cache(maxsize=1)
def medium_granularity_token() -> str:
    """The IngredientTypeEnum value meaning "a whole named medium".

    Read from MIM's schema rather than written as a literal. This script
    WRITES ingredient_type back into MIM records under --apply, so a hardcoded
    token guaranteed a window during MediaIngredientMech#222 -- which renamed
    DEFINED_MEDIUM to NAMED_MEDIUM -- where claw wrote a value the target
    schema rejects. That window existed in whichever order the two repos
    landed, so no sequencing of the two PRs closed it; reading the target's own
    vocabulary does.

    Two cases that the pre-#147 fallback collapsed into one are now distinct:

    * **No MIM at all.** Nothing to classify and nothing to write, so there is
      no wrong answer to give. Returns the canonical spelling, because several
      scripts import this module for its regexes alone and must not start
      requiring a checkout.
    * **MIM present, vocabulary undeterminable.** Raises. The vocabulary is
      right there and merely unreadable, and this script is about to write a
      token into someone else's corpus -- a partial checkout used to get a
      quiet wrong answer instead of a loud one.
    """
    if not MIM_ROOT.is_dir():
        return CANONICAL_MEDIUM_GRANULARITY

    try:
        text = SCHEMA.read_text(encoding="utf-8")
    except OSError as exc:
        raise VocabularyError(
            f"MIM checkout {MIM_ROOT} exists but its schema could not be read "
            f"({SCHEMA}): {exc}. Refusing to guess the ingredient_type "
            f"vocabulary; complete the checkout or unset "
            f"MEDIAINGREDIENTMECH_ROOT."
        ) from exc

    try:
        schema = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise VocabularyError(
            f"MIM schema {SCHEMA} is not valid YAML: {exc}. Refusing to guess "
            f"the ingredient_type vocabulary."
        ) from exc

    if not isinstance(schema, dict):
        raise VocabularyError(
            f"MIM schema {SCHEMA} is not a YAML mapping (parsed as "
            f"{type(schema).__name__}). Refusing to guess the ingredient_type "
            f"vocabulary."
        )

    # Every level is isinstance-guarded, not just `or {}`-guarded: a truthy
    # non-mapping (`enums: [a, b]`) passes `or {}` untouched and then raises
    # AttributeError, which escapes the VocabularyError contract this function
    # advertises and reaches the caller as a traceback (#150).
    enums = schema.get("enums")
    enum = enums.get("IngredientTypeEnum") if isinstance(enums, dict) else None
    values = enum.get("permissible_values") if isinstance(enum, dict) else None
    if not isinstance(values, (dict, list)):
        values = {}
    for token in _MEDIUM_GRANULARITY:
        if token in values:
            return token

    # map(str, ...) because `values` may be a list (`token in values` is right
    # for either shape) and an unorderable one makes sorted() raise while this
    # error is being built -- a second failure on the failure path (#151).
    raise VocabularyError(
        f"MIM schema {SCHEMA} defines IngredientTypeEnum without any of "
        f"{list(_MEDIUM_GRANULARITY)}; it names "
        f"{sorted(map(str, values)) if values else 'no permissible values'}. The "
        f"medium-granularity value was renamed again, or this is not the "
        f"ingredient schema -- update _MEDIUM_GRANULARITY rather than letting "
        f"a stale spelling be written into the corpus."
    )

OUT_DIR = REPO_ROOT / "workspace" / "reports"
OUT_TSV = OUT_DIR / "ingredient_type_classification.tsv"
OUT_MD = OUT_DIR / "ingredient_type_classification.md"

# Whole-word patterns that strongly indicate a complex (UNDEFINED_MIXTURE)
# ingredient. Matched with word boundaries so "malt extract" hits but
# "maltose" / "isomaltose" / "maltodextrin" do not.
_COMPLEX_HINTS = (
    r"extracts?", r"hydrolysates?", r"hydrolyzates?",
    r"peptone", r"tryptone", r"casamino",
    r"yeast", r"casein", r"milk", r"meat", r"beef",
    r"soybean", r"tomato",
    r"soil", r"seawater", r"sea\s+water", r"sediment", r"compost",
    r"manure", r"sludge", r"fish\s+meal",
    r"broth", r"infusion",
    # "malt" only when followed by space (malt extract), not maltose
    r"malt(?=\s)",
    # "fish" only as standalone, not in "fishlike"
    r"fish(?=[\s-]|$)",
    # "soy" only as standalone, not in "soybean" — covered above
    r"soy(?=[\s-]|$)",
)

# Whole-word patterns for stock solutions / pre-mixes.
_SOLUTION_HINTS = (
    r"stock\s+(?:solution|mix)?",
    r"trace\s+metal", r"trace\s+element",
    r"vitamin\s+solution",
    r"mineral\s+solution",
    r"buffer\s+solution", r"\w+\s+buffer$",
    r"premix", r"mix\s+solution",
    r"salts?\s+solution", r"amino\s+acid\s+mix",
)

# Whole-word patterns for complete medium recipes.
_MEDIUM_HINTS = (
    r"agar\s+medium", r"broth\s+medium", r"marine\s+agar",
    r"lb\s+broth", r"\br2a\b", r"\btsa\b", r"\bmedium\b\s+no",
)


def _compile(patterns: tuple[str, ...]) -> "re.Pattern":
    return re.compile(r"(?<![A-Za-z])(?:" + "|".join(patterns) + r")(?![A-Za-z])",
                      re.IGNORECASE)


_COMPLEX_RE = _compile(_COMPLEX_HINTS)
_SOLUTION_RE = _compile(_SOLUTION_HINTS)
_MEDIUM_RE = _compile(_MEDIUM_HINTS)

# Known-complex CHEBI terms (override the "CHEBI → SINGLE" default).
# Keep small; expand as curators identify problematic auto-classifications.
_CHEBI_COMPLEX_OVERRIDES = {
    # CHEBI sometimes has terms for biological extracts / mixtures
    # under the "biological role" tree. Add IDs here as they're found.
}


def classify(record: dict) -> tuple[str, str]:
    """Returns (ingredient_type_or_empty, rationale)."""
    ident = (record.get("identifier") or "").strip()
    name = (record.get("preferred_term") or "").strip()
    om = record.get("ontology_mapping") or {}
    onto_id = (om.get("ontology_id") or ident).strip()
    prefix = onto_id.split(":", 1)[0] if ":" in onto_id else ""

    # 0. UNMAPPED_* placeholders — fall through to name-pattern
    # heuristics (no ontology to default from). The pattern matches
    # below typically catch the obvious cases (yeast extract, peptone,
    # buffer solution, etc.); the residual stays unset → curator
    # decides.
    if not ident:
        return "", "no identifier; curator review needed"

    # 1. Hard rule: a populated molecular_formula / SMILES / InChI means
    # the substance is chemically defined — this trumps name hints (so
    # "Fish-sperm DNA" with a CHEBI formula is SINGLE_INGREDIENT, not
    # UNDEFINED_MIXTURE just because the name contains "Fish").
    cp = record.get("chemical_properties") or {}
    formula = (cp.get("molecular_formula") or "").strip()
    smiles = (cp.get("smiles") or "").strip()
    inchi = (cp.get("inchi") or "").strip()
    if formula or smiles or inchi:
        which = "molecular_formula" if formula else (
            "smiles" if smiles else "inchi")
        return "SINGLE_INGREDIENT", f"chemical structure populated ({which})"

    # 2. Name-based hints (word-boundary matched)
    m = _COMPLEX_RE.search(name)
    if m:
        return "UNDEFINED_MIXTURE", f"name matches complex pattern {m.group(0)!r}"
    m = _SOLUTION_RE.search(name)
    if m:
        return "STOCK_SOLUTION", f"name matches solution pattern {m.group(0)!r}"
    m = _MEDIUM_RE.search(name)
    if m:
        return (medium_granularity_token(),
                f"name matches medium pattern {m.group(0)!r}")

    # 2. Ontology-source defaults
    if prefix == "CHEBI":
        if onto_id in _CHEBI_COMPLEX_OVERRIDES:
            return "UNDEFINED_MIXTURE", f"CHEBI override list ({onto_id})"
        return "SINGLE_INGREDIENT", "CHEBI primary"
    if prefix == "NCIT":
        return "SINGLE_INGREDIENT", "NCIT primary (pharmaceutical)"
    if prefix == "cas":
        return "SINGLE_INGREDIENT", "cas: primary (defined chemical)"
    if prefix == "FOODON":
        return "UNDEFINED_MIXTURE", "FOODON primary (food/biological)"
    if prefix == "ENVO":
        return "UNDEFINED_MIXTURE", "ENVO primary (environmental)"
    if prefix == "UBERON":
        return "UNDEFINED_MIXTURE", "UBERON primary (anatomical)"
    if prefix == "kgmicrobe.compound":
        # Mostly secondary metabolites / antibiotics — defined but
        # without a real ontology yet
        return "SINGLE_INGREDIENT", "kgmicrobe.compound placeholder (defined)"

    return "", f"unrecognized prefix {prefix!r}"


def load_yaml(path: Path) -> dict | None:
    try:
        with open(path) as f:
            y = yaml.safe_load(f)
        return y if isinstance(y, dict) else None
    except Exception:
        return None


def write_yaml(path: Path, record: dict) -> None:
    with open(path, "w") as f:
        yaml.safe_dump(record, f, default_flow_style=False,
                       allow_unicode=True, sort_keys=False)


def append_curation_event(record: dict, action: str, changes: str) -> None:
    history = record.setdefault("curation_history", [])
    history.append({
        "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "curator": "auto_classify_ingredient_type",
        "action": action,
        "changes": changes,
        "llm_assisted": False,
    })


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="write YAMLs (default: dry-run)")
    ap.add_argument("--override", action="store_true",
                    help="overwrite ingredient_type even if already set")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[tuple[str, str, str, str, str]] = []
    counts: dict[str, int] = {}
    n_total = n_already = n_set = n_skip = 0

    for path in sorted(INGREDIENTS.rglob("*.yaml")):
        record = load_yaml(path)
        if not record or not record.get("identifier"):
            continue
        n_total += 1
        rel = str(path.relative_to(MIM_ROOT))
        existing = record.get("ingredient_type")
        new_type, rationale = classify(record)

        if existing and not args.override:
            n_already += 1
            rows.append((rel, record.get("identifier", ""),
                         existing, "(already set)", rationale))
            counts[existing] = counts.get(existing, 0) + 1
            continue

        if not new_type:
            n_skip += 1
            rows.append((rel, record.get("identifier", ""),
                         "", "(unset; needs curator)", rationale))
            counts["(unset)"] = counts.get("(unset)", 0) + 1
            continue

        rows.append((rel, record.get("identifier", ""),
                     new_type, "auto", rationale))
        counts[new_type] = counts.get(new_type, 0) + 1

        if args.apply:
            record["ingredient_type"] = new_type
            append_curation_event(
                record, "AUTO_CLASSIFY_INGREDIENT_TYPE",
                f"set ingredient_type={new_type} ({rationale})")
            write_yaml(path, record)
            n_set += 1

    # Emit reports
    import csv
    with open(OUT_TSV, "w", newline="") as f:
        w = csv.writer(f, delimiter="\t")
        w.writerow(["yaml_path", "identifier", "ingredient_type",
                    "source", "rationale"])
        w.writerows(rows)

    md = ["# Ingredient type classification\n"]
    md.append(f"Total records: **{n_total}**")
    md.append(f"Mode: **{'APPLY' if args.apply else 'DRY-RUN'}**")
    if args.apply:
        md.append(f"Records written: **{n_set}**")
    else:
        md.append(f"Records that would be written: **{sum(1 for r in rows if r[3]=='auto')}**")
    md.append(f"Records already set (preserved): **{n_already}**")
    md.append(f"Records skipped (no rule fit): **{n_skip}**\n")
    md.append("\n## Distribution\n")
    md.append("| ingredient_type | count |")
    md.append("|---|---:|")
    for k in sorted(counts):
        md.append(f"| `{k}` | {counts[k]} |")
    with open(OUT_MD, "w") as f:
        f.write("\n".join(md))

    print(f"Total: {n_total}")
    if args.apply:
        print(f"  Set: {n_set}")
    else:
        print(f"  Would set: {sum(1 for r in rows if r[3]=='auto')}")
    print(f"  Already set: {n_already}")
    print(f"  Skipped: {n_skip}")
    print()
    print("Distribution:")
    for k, v in sorted(counts.items(), key=lambda x: -x[1]):
        print(f"  {k:25s} {v}")
    print(f"\nReports: {OUT_TSV.relative_to(REPO_ROOT)}")
    print(f"         {OUT_MD.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    # A VocabularyError means a MIM checkout is present but its ingredient-type
    # vocabulary could not be determined (#147). Report it as an error rather
    # than a traceback, and exit nonzero so a caller can gate on it.
    try:
        sys.exit(main())
    except VocabularyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)
