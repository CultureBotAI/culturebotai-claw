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


@pytest.mark.parametrize(
    "values_block",
    ["      - 1\n      - \"a\"\n", "      - {a: 1}\n      - {b: 2}\n"],
    ids=["mixed-scalars", "mappings"],
)
def test_an_unorderable_permissible_values_list_still_raises_cleanly(
        monkeypatch, tmp_path, values_block):
    """#151: sorted() in the refusal message must not raise while building it.

    A list is a legitimate shape here -- `token in values` is correct for a
    mapping or a sequence -- so an unorderable one reached sorted() and escaped
    the VocabularyError contract as a TypeError.
    """
    schema = tmp_path / "src" / "mediaingredientmech" / "schema"
    schema.mkdir(parents=True)
    (schema / "mediaingredientmech.yaml").write_text(
        "enums:\n  IngredientTypeEnum:\n    permissible_values:\n" + values_block,
        encoding="utf-8")

    mod = _load(monkeypatch, tmp_path)

    with pytest.raises(mod.VocabularyError, match="without any of"):
        mod.medium_granularity_token()


# Shapes a schema file can take, well beyond what LinkML would emit. The point
# is not that any of these is likely; it is that the contract below holds
# without enumerating them one issue at a time -- #150 and #151 were each a
# single escaped shape, found separately, in a function whose whole purpose is
# to be trustworthy about a value it writes into another repository's corpus.
_HOSTILE_SCHEMAS = [
    "",
    "null\n",
    "- a\n- b\n",
    "just a string\n",
    "42\n",
    "enums:\n",
    "enums: null\n",
    "enums: []\n",
    "enums: text\n",
    "enums:\n  - a\n",
    "enums:\n  IngredientTypeEnum:\n",
    "enums:\n  IngredientTypeEnum: null\n",
    "enums:\n  IngredientTypeEnum: text\n",
    "enums:\n  IngredientTypeEnum:\n    - a\n",
    "enums:\n  IngredientTypeEnum:\n    permissible_values:\n",
    "enums:\n  IngredientTypeEnum:\n    permissible_values: null\n",
    "enums:\n  IngredientTypeEnum:\n    permissible_values: text\n",
    "enums:\n  IngredientTypeEnum:\n    permissible_values: []\n",
    "enums:\n  IngredientTypeEnum:\n    permissible_values: {}\n",
    "enums:\n  IngredientTypeEnum:\n    permissible_values:\n      - 1\n      - 'a'\n",
    "enums:\n  IngredientTypeEnum:\n    permissible_values:\n      - {a: 1}\n",
    "enums:\n  IngredientTypeEnum:\n    permissible_values:\n      OTHER: {}\n",
    "enums:\n  OtherEnum:\n    permissible_values:\n      NAMED_MEDIUM: {}\n",
    "enums:\n  IngredientTypeEnum:\n    permissible_values:\n      - NAMED_MEDIUM\n",
    "enums: [this is: not, a mapping\n",
]


@pytest.mark.parametrize("text", _HOSTILE_SCHEMAS, ids=range(len(_HOSTILE_SCHEMAS)))
def test_the_token_is_always_a_known_spelling_or_a_vocabulary_error(
        monkeypatch, tmp_path, text):
    """The whole contract, in one place.

    For a present MIM checkout the function must either return a spelling the
    target schema actually names, or raise VocabularyError. Anything else --
    AttributeError (#150), TypeError from the message itself (#151), or a
    plausible-looking guess -- is a value that could be written into MIM.
    """
    schema = tmp_path / "src" / "mediaingredientmech" / "schema"
    schema.mkdir(parents=True)
    (schema / "mediaingredientmech.yaml").write_text(text, encoding="utf-8")

    mod = _load(monkeypatch, tmp_path)

    try:
        token = mod.medium_granularity_token()
    except mod.VocabularyError:
        return
    assert token in mod._MEDIUM_GRANULARITY, (
        f"returned {token!r}, which is not a known medium spelling"
    )
    assert token in text, (
        f"returned {token!r}, which this schema does not name -- a guess"
    )


# --------------------------------------------------------------------------
# #156: an unreadable vocabulary must not leave a partially written corpus
# --------------------------------------------------------------------------


def _corpus(root: Path) -> Path:
    """Two records: a plain chemical that sorts first, and a medium.

    Order matters. The chemical does not need the medium token, so it is
    classified and written before anything asks for the vocabulary; the medium
    is what triggers the lookup. That ordering is the bug.
    """
    ingredients = root / "data" / "ingredients"
    ingredients.mkdir(parents=True)
    (ingredients / "aaa_nacl.yaml").write_text(
        "identifier: CHEBI:26710\npreferred_term: sodium chloride\n", encoding="utf-8"
    )
    (ingredients / "zzz_r2a.yaml").write_text(
        "identifier: UNMAPPED_0001\npreferred_term: R2A agar\n", encoding="utf-8"
    )
    return ingredients


def test_apply_writes_nothing_when_the_vocabulary_is_unreadable(
    monkeypatch, tmp_path, capsys
):
    """#156: --apply wrote per record while the token resolved lazily.

    A present-but-unreadable schema wrote every record classified before the
    first medium-pattern one, then aborted -- leaving an unknown subset of
    another repository's corpus modified, with no recovery path in the output.
    """
    ingredients = _corpus(tmp_path)
    mod = _load(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "argv", ["classify_ingredient_type.py", "--apply"])

    with pytest.raises(mod.VocabularyError):
        mod.main()

    for path in sorted(ingredients.glob("*.yaml")):
        assert "ingredient_type" not in path.read_text(encoding="utf-8"), (
            f"{path.name} was written before the vocabulary was known"
        )


def test_the_vocabulary_is_resolved_before_the_corpus_is_walked(
    monkeypatch, tmp_path
):
    """Pins the ordering rather than only its visible effect.

    Asserting "nothing was written" passes for the wrong reason if the walk
    never reaches a writable record; this fails if the lookup moves back after
    the first `write_yaml`.
    """
    _corpus(tmp_path)
    mod = _load(monkeypatch, tmp_path)
    calls: list[str] = []
    monkeypatch.setattr(mod, "write_yaml", lambda *a, **k: calls.append("write"))
    monkeypatch.setattr(
        mod,
        "medium_granularity_token",
        lambda: calls.append("vocabulary") or "NAMED_MEDIUM",
    )
    monkeypatch.setattr(sys, "argv", ["classify_ingredient_type.py", "--apply"])

    mod.main()

    assert calls, "nothing happened; the test would pass vacuously"
    assert calls[0] == "vocabulary", (
        f"the corpus was touched before the vocabulary was resolved: {calls[:3]}"
    )


def test_a_healthy_checkout_still_applies_the_schema_spelling(
    monkeypatch, tmp_path, capsys
):
    """The preflight must not break the working path."""
    ingredients = _corpus(tmp_path)
    _write_schema(tmp_path, "NAMED_MEDIUM")
    mod = _load(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "argv", ["classify_ingredient_type.py", "--apply"])

    assert mod.main() == 0

    written = (ingredients / "zzz_r2a.yaml").read_text(encoding="utf-8")
    assert "ingredient_type: NAMED_MEDIUM" in written


def test_an_empty_corpus_with_a_broken_schema_now_fails_rather_than_passing(
    monkeypatch, tmp_path
):
    """Removes the hidden dependence on corpus contents.

    Whether a broken schema was noticed at all used to depend on whether the
    corpus happened to contain a medium-pattern record; an empty one exited 0.
    """
    (tmp_path / "data" / "ingredients").mkdir(parents=True)
    mod = _load(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "argv", ["classify_ingredient_type.py"])

    with pytest.raises(mod.VocabularyError):
        mod.main()
