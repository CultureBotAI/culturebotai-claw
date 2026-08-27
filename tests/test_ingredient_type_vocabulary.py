"""The medium-granularity token is read from MIM's schema, not hardcoded.

`classify_ingredient_type.py --apply` WRITES `ingredient_type` back into MIM
records. MediaIngredientMech#222 renamed `DEFINED_MEDIUM` to `NAMED_MEDIUM`
(MediaIngredientMech#479, merged), so a literal in this repo would have
guaranteed a window where claw writes a token the target schema rejects -- and
that window existed in whichever order the two PRs landed, so no sequencing
closed it. These pin the property that does.

Since #147 they also pin the distinction the original fallback collapsed: "no
MIM at all" is answerable without a schema, "MIM present but its vocabulary is
unreadable" is not, and only the first gets a default.
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
    them should start requiring a MIM checkout to be present.

    With no MIM there is nothing to classify and nothing to write, so the
    default cannot be written anywhere -- it just has to exist. It is the
    CURRENT spelling: before #147 this returned `DEFINED_MEDIUM`, which
    MediaIngredientMech#479 has since retired.
    """
    mod = _load(monkeypatch, tmp_path / "nonexistent")

    assert mod.medium_granularity_token() == "NAMED_MEDIUM"
    assert mod.medium_granularity_token() == mod.CANONICAL_MEDIUM_GRANULARITY


def test_an_unparseable_schema_raises_rather_than_guessing(monkeypatch, tmp_path):
    """#147: a partial checkout used to get a quiet wrong answer.

    MIM is present, so records exist to write; the vocabulary is right there
    and merely unreadable. Guessing writes a token into someone else's corpus
    on the strength of a parse failure.
    """
    schema = tmp_path / "src" / "mediaingredientmech" / "schema"
    schema.mkdir(parents=True)
    (schema / "mediaingredientmech.yaml").write_text(
        "enums: [this is: not, a mapping", encoding="utf-8")

    mod = _load(monkeypatch, tmp_path)

    with pytest.raises(mod.VocabularyError, match="not valid YAML"):
        mod.medium_granularity_token()


def test_a_present_checkout_with_no_schema_file_raises(monkeypatch, tmp_path):
    """The exact exposure #147 names: MIM present, schema absent."""
    (tmp_path / "data" / "ingredients").mkdir(parents=True)

    mod = _load(monkeypatch, tmp_path)

    with pytest.raises(mod.VocabularyError, match="could not be read"):
        mod.medium_granularity_token()


def test_a_schema_naming_no_known_medium_token_raises(monkeypatch, tmp_path):
    """A future rename must fail loudly, not silently reuse a retired spelling.

    This is the failure the old `return _MEDIUM_GRANULARITY[-1]` tail hid: the
    enum had been renamed out from under claw and the script carried on
    writing the previous value.
    """
    mod = _load(monkeypatch, _write_schema(tmp_path, "RENAMED_AGAIN_MEDIUM"))

    with pytest.raises(mod.VocabularyError, match="RENAMED_AGAIN_MEDIUM"):
        mod.medium_granularity_token()


def test_a_non_mapping_schema_raises(monkeypatch, tmp_path):
    schema = tmp_path / "src" / "mediaingredientmech" / "schema"
    schema.mkdir(parents=True)
    (schema / "mediaingredientmech.yaml").write_text(
        "- just\n- a\n- list\n", encoding="utf-8")

    mod = _load(monkeypatch, tmp_path)

    with pytest.raises(mod.VocabularyError, match="not a YAML mapping"):
        mod.medium_granularity_token()


def test_the_retired_spelling_stays_in_the_lookup(monkeypatch, tmp_path):
    """It must still be readable, so a pre-rename checkout gets a token its own
    schema accepts. That is the one case where it is still the right answer."""
    mod = _load(monkeypatch, _write_schema(tmp_path, "DEFINED_MEDIUM"))

    assert "DEFINED_MEDIUM" in mod._MEDIUM_GRANULARITY
    assert mod.medium_granularity_token() == "DEFINED_MEDIUM"


def test_the_retired_spelling_is_never_an_answer_of_last_resort(monkeypatch, tmp_path):
    """#147's core complaint: the tuple kept `DEFINED_MEDIUM` reachable as the
    default for every caller without a readable MIM checkout.

    No input may produce it now except a schema that actually names it -- which
    `test_the_retired_spelling_stays_in_the_lookup` covers. Here: the two
    schema-less paths must not.
    """
    absent = _load(monkeypatch, tmp_path / "absent")
    assert absent.medium_granularity_token() == "NAMED_MEDIUM"

    (tmp_path / "present").mkdir()
    partial = _load(monkeypatch, tmp_path / "present")
    with pytest.raises(partial.VocabularyError):
        partial.medium_granularity_token()


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
    report_hydrate_grounding.py's regex copy drifted from hydrate_guard.py.

    Covers src/ as well as scripts/ (#148): nothing in src/ references the
    token today, so scoping the guard to scripts/ would have read as "this is
    checked" to anyone later adding ingredient-type handling there.
    """
    offenders = []
    roots = [REPO_ROOT / "scripts", REPO_ROOT / "src"]
    for path in (p for root in roots for p in root.rglob("*.py")):
        for lineno, line in enumerate(
                path.read_text(encoding="utf-8").splitlines(), start=1):
            if '"DEFINED_MEDIUM"' in line or "'DEFINED_MEDIUM'" in line:
                if "_MEDIUM_GRANULARITY" in line:
                    continue  # the one deliberate candidate tuple
                offenders.append(f"{path.relative_to(REPO_ROOT)}:{lineno}")

    assert not offenders, (
        "hardcoded medium token; call medium_granularity_token() instead: "
        + ", ".join(offenders))


@pytest.mark.parametrize(
    "enums_block",
    ["enums:\n  - a\n  - b\n", "enums: just-a-string\n",
     "enums:\n  IngredientTypeEnum:\n    - not\n    - a mapping\n",
     "enums:\n  IngredientTypeEnum:\n    permissible_values: nope\n"],
    ids=["enums-list", "enums-string", "enum-list", "values-string"],
)
def test_a_structurally_wrong_enums_block_raises_vocabulary_error(
        monkeypatch, tmp_path, enums_block):
    """#150: `or {}` does nothing for a truthy non-mapping.

    These parse as valid YAML, so they reach the lookup and used to raise
    AttributeError -- which the entry points do not catch, so a malformed
    schema printed a traceback instead of the clean refusal every other
    unreadable-vocabulary case gets.
    """
    schema = tmp_path / "src" / "mediaingredientmech" / "schema"
    schema.mkdir(parents=True)
    (schema / "mediaingredientmech.yaml").write_text(enums_block, encoding="utf-8")

    mod = _load(monkeypatch, tmp_path)

    with pytest.raises(mod.VocabularyError):
        mod.medium_granularity_token()
