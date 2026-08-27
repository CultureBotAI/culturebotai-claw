"""The medium-granularity token is read from MIM's schema, not hardcoded.

`classify_ingredient_type.py --apply` WRITES `ingredient_type` back into MIM
records. MediaIngredientMech#222 renames `DEFINED_MEDIUM` to `NAMED_MEDIUM`, so
a literal in this repo would guarantee a window where claw writes a token the
target schema rejects -- and that window exists in whichever order the two PRs
land, so no sequencing closes it. These pin the property that does.
"""

import importlib.util
import sys
import textwrap
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "classify_ingredient_type.py"


def _load(monkeypatch, mim_root: Path):
    """Import a fresh copy of the module bound to `mim_root`.

    MIM_ROOT is resolved at import time, so each case needs its own module
    object rather than a reload of a shared one.
    """
    monkeypatch.setenv("MEDIAINGREDIENTMECH_ROOT", str(mim_root))
    spec = importlib.util.spec_from_file_location("_classify_under_test", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _write_schema(root: Path, medium_token: str) -> Path:
    schema = root / "src" / "mediaingredientmech" / "schema"
    schema.mkdir(parents=True, exist_ok=True)
    (schema / "mediaingredientmech.yaml").write_text(textwrap.dedent(f"""\
        id: https://example.org/test
        name: test
        enums:
          IngredientTypeEnum:
            permissible_values:
              SINGLE_INGREDIENT:
                description: pure compound
              {medium_token}:
                description: a whole named medium
              UNDEFINED_MIXTURE:
                description: complex mixture
              STOCK_SOLUTION:
                description: premixed
        """), encoding="utf-8")
    return root


@pytest.mark.parametrize("token", ["DEFINED_MEDIUM", "NAMED_MEDIUM"])
def test_the_token_follows_the_target_schema(monkeypatch, tmp_path, token):
    """Pre- and post-rename corpora each get the spelling they accept."""
    mod = _load(monkeypatch, _write_schema(tmp_path, token))

    assert mod.medium_granularity_token() == token


def test_the_new_spelling_wins_when_the_schema_offers_both(monkeypatch, tmp_path):
    """A deprecation period that keeps both values must not pin claw to the old
    one, or the contract step of #222 could never remove it."""
    schema = tmp_path / "src" / "mediaingredientmech" / "schema"
    schema.mkdir(parents=True)
    (schema / "mediaingredientmech.yaml").write_text(textwrap.dedent("""\
        enums:
          IngredientTypeEnum:
            permissible_values:
              DEFINED_MEDIUM:
                description: deprecated spelling
              NAMED_MEDIUM:
                description: current spelling
        """), encoding="utf-8")

    mod = _load(monkeypatch, tmp_path)

    assert mod.medium_granularity_token() == "NAMED_MEDIUM"


def test_a_missing_mim_checkout_does_not_break_import(monkeypatch, tmp_path):
    """Five other scripts import this module for its regexes alone; none of
    them should start requiring a MIM checkout to be present."""
    mod = _load(monkeypatch, tmp_path / "nonexistent")

    assert mod.medium_granularity_token() == "DEFINED_MEDIUM"


def test_an_unparseable_schema_falls_back_rather_than_raising(monkeypatch, tmp_path):
    schema = tmp_path / "src" / "mediaingredientmech" / "schema"
    schema.mkdir(parents=True)
    (schema / "mediaingredientmech.yaml").write_text(
        "enums: [this is: not, a mapping", encoding="utf-8")

    mod = _load(monkeypatch, tmp_path)

    assert mod.medium_granularity_token() == "DEFINED_MEDIUM"


def test_classify_emits_the_schema_token_not_a_literal(monkeypatch, tmp_path):
    """The end-to-end property: a record classified as a medium carries the
    spelling the target corpus uses."""
    mod = _load(monkeypatch, _write_schema(tmp_path, "NAMED_MEDIUM"))
    record = {"preferred_term": "R2A agar", "identifier": "UNMAPPED_0001"}

    value, rationale = mod.classify(record)

    assert value == "NAMED_MEDIUM"
    assert "medium pattern" in rationale


def test_no_module_in_claw_hardcodes_the_medium_token():
    """A second literal would drift from the schema exactly the way
    report_hydrate_grounding.py's regex copy drifted from hydrate_guard.py."""
    offenders = []
    for path in (REPO_ROOT / "scripts").rglob("*.py"):
        for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1):
            if '"DEFINED_MEDIUM"' in line or "'DEFINED_MEDIUM'" in line:
                if "_MEDIUM_GRANULARITY" in line:
                    continue  # the one deliberate candidate tuple
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}")

    assert not offenders, (
        "hardcoded medium token; call medium_granularity_token() instead: "
        + ", ".join(offenders))
