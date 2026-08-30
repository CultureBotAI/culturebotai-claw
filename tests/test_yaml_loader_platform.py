"""Whether libyaml's loader is sound here, asked on the machine that runs.

#233. Adopting `yaml.CSafeLoader` in `kg_microbe_corpus` is worth roughly 70
minutes on ProteinTraitsMech's 429,271 records -- 134 records/s becomes 2,129.
It passed the whole suite on macOS and failed 14 tests on Linux CI at the same
commit, and the cause was never found.

It is now. On claw's Linux runner, PyYAML 6.0.3 built `--with-libyaml`:

    >>> yaml.load("identifier: [unclosed", Loader=yaml.CSafeLoader)
    yaml.parser.ParserError: while parsing a flow sequence   (yaml/_yaml.pyx)
    >>> isinstance(exc, yaml.YAMLError)
    False
    >>> [c.__qualname__ for c in type(exc).__mro__]
    ['ParserError', 'MarkedYAMLError', 'YAMLError', 'Exception', ...]

The MRO contains a class *named* `YAMLError`, and it is not the one
`yaml.error.YAMLError` names. `except` matches by identity, so an error that
reads as a `YAMLError` in a traceback sails straight through
`except yaml.YAMLError`. That is #233's second symptom exactly. Its first --
valid records parsing to `None` -- shows up here as a `ConstructorError:
could not determine a constructor for the tag None` on a valid document, which
is the same two-module-instance problem seen from the constructor's end.

So this does not test that CSafeLoader is fine. It tests whether it is sound
*here*, records the answer, and holds the corpus reader to `yaml.safe_load` for
as long as it is not. Where CSafeLoader is sound the adoption tests run and
pass; where it is not they skip with the platform facts, and the test that
matters -- that nothing in `kg_microbe_corpus` uses it -- runs everywhere.
"""

from __future__ import annotations

import ast
import platform
import sys
import warnings
from pathlib import Path

import pytest
import yaml

from kg_microbe_corpus.loader import judge, loader_is_sound, safe_loader, soundness

CSAFE = getattr(yaml, "CSafeLoader", None)

FACTS = (
    f"PyYAML {yaml.__version__}, with_libyaml={getattr(yaml, '__with_libyaml__', None)}, "
    f"{platform.system()} {platform.machine()}, python {platform.python_version()}"
)

VALID = "identifier: X:1\nlabel: a thing\nvalues:\n  - one\n  - two\n"
INVALID = "identifier: [unclosed\n"


# One implementation, in the package rather than beside it: keeping a second
# copy here is the habit #132 Phase 7 exists to end.
SOUND, WHY = soundness()
needs_sound = pytest.mark.skipif(not SOUND, reason=f"{WHY}; {FACTS}")


# -- the property that holds everywhere -------------------------------------


def test_the_corpus_reader_does_not_use_libyaml():
    """The gate. `kg_microbe_corpus` reads corpora whose statistics feed reports
    people act on, so it stays on `yaml.safe_load` until CSafeLoader is sound on
    every platform the fleet runs -- which, as of this test, it is not on Linux.
    """
    module = Path(__file__).resolve().parents[1] / "src/kg_microbe_corpus/statistics.py"
    tree = ast.parse(module.read_text(encoding="utf-8"))
    # From the syntax tree, not the text: that module's docstring explains this
    # very decision and names CSafeLoader while not using it. Matching prose
    # would fail on a file that is doing exactly the right thing.
    names = {
        node.attr if isinstance(node, ast.Attribute) else node.id
        for node in ast.walk(tree)
        if isinstance(node, (ast.Attribute, ast.Name))
    }
    assert "CSafeLoader" not in names, (
        "kg_microbe_corpus adopted CSafeLoader; #233 requires it to be sound on "
        f"Linux first, and here it is: {WHY}"
    )
    assert "safe_load" in names


def test_this_platform_records_an_answer():
    """Neither outcome is a failure -- the point is that the answer is stated
    rather than assumed.

    An unsound platform emits a warning rather than only skipping, because a
    skip is invisible under `pytest -q`: the first version of this test passed
    green on Linux and said nothing about why, which is the same as not having
    asked. A warning appears in the run summary.
    """
    assert isinstance(SOUND, bool)
    assert WHY
    if not SOUND:
        warnings.warn(
            f"libyaml is not sound here, so CSafeLoader stays unadopted: "
            f"{WHY}. {FACTS}. See #233 and #263.",
            stacklevel=1,
        )


# -- what adoption would require, run only where it could work --------------


@needs_sound
def test_the_two_loaders_agree_on_a_valid_record():
    assert yaml.load(VALID, Loader=CSAFE) == yaml.safe_load(VALID)


@needs_sound
def test_an_empty_document_is_none_for_both():
    assert yaml.safe_load("") is None
    assert yaml.load("", Loader=CSAFE) is None


@needs_sound
def test_a_parse_error_is_the_yaml_error_this_package_catches():
    """Not merely *a* YAMLError -- the class this package's except clauses name.
    A build where those are two objects is exactly what breaks on Linux."""
    with pytest.raises(yaml.YAMLError):
        yaml.load(INVALID, Loader=CSAFE)


@needs_sound
def test_repeated_loads_do_not_degrade():
    for _ in range(200):
        assert yaml.load(VALID, Loader=CSAFE) is not None


# -- the loader helper (#263) -----------------------------------------------


def test_the_helper_picks_a_loader_that_actually_works():
    """`getattr(yaml, "CSafeLoader", yaml.SafeLoader)` asks whether the name
    exists, not whether it works -- and on Linux it exists and does not. Two
    claw scripts chose it that way, and because they wrapped the load in
    `except Exception` they reported zero changes instead of failing: a silent
    wrong answer from scripts that write curated data."""
    chosen = safe_loader()
    assert chosen is (yaml.CSafeLoader if SOUND else yaml.SafeLoader)
    # Whatever was chosen must round-trip a valid record and raise catchably.
    assert yaml.load(VALID, Loader=chosen) == yaml.safe_load(VALID)
    with pytest.raises(yaml.YAMLError):
        yaml.load(INVALID, Loader=chosen)


def test_the_helper_agrees_with_its_own_verdict():
    assert loader_is_sound() is SOUND


def test_the_verdict_is_computed_once():
    """Trying a parse on every call would cost more than the loader saves."""
    soundness.cache_clear()
    first = soundness()
    assert soundness() is first
    assert soundness.cache_info().hits >= 1


def test_no_claw_script_chooses_a_loader_by_name():
    """The bug this fixes, kept fixed. A script that reaches for CSafeLoader
    directly has not asked whether it works here."""
    offenders = []
    for path in sorted(Path(__file__).resolve().parents[1].glob("scripts/*.py")):
        source = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(source)
        names = {
            node.attr if isinstance(node, ast.Attribute) else node.id
            for node in ast.walk(tree)
            if isinstance(node, (ast.Attribute, ast.Name))
        }
        strings = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        # Strings as well as names: the shape being outlawed is
        # `getattr(yaml, "CSafeLoader", ...)`, where the loader is named by a
        # string constant and no Name or Attribute node mentions it at all.
        if {"CSafeLoader", "CLoader"} & (names | strings):
            offenders.append(path.name)
    assert not offenders, (
        f"{offenders} choose a YAML loader by name; use "
        f"kg_microbe_corpus.loader.safe_loader(), which tries it first (#263)"
    )


@pytest.mark.parametrize(
    ("loader", "expected"),
    [
        (None, "no CSafeLoader"),
        ("disagrees", "disagrees with SafeLoader"),
        ("raises-on-valid", "a valid record raised"),
        ("uncatchable", "does not catch"),
        ("never-raises", "did not raise"),
    ],
)
def test_the_rule_rejects_each_way_a_loader_can_be_unsound(loader, expected):
    """The failure paths, run on a machine where the real loader works.

    Every one of these is a mutation that survived when the rule was only ever
    applied to this build's CSafeLoader -- on macOS it is sound, so removing a
    check changed nothing observable. The rule has to be given a broken loader
    to show that it notices.
    """

    class Disagrees(yaml.SafeLoader):
        pass

    class NotAYAMLError(Exception):
        pass

    def _construct_wrong(self, node):
        return {"wrong": True}

    Disagrees.add_constructor("tag:yaml.org,2002:map", _construct_wrong)

    class RaisesOnValid(yaml.SafeLoader):
        def get_single_data(self):
            raise RuntimeError("boom")

    class Uncatchable(yaml.SafeLoader):
        """Sound on a valid record, and raises something uncatchable on a bad
        one -- which is exactly the Linux build's second failure mode, and why
        the rule cannot stop at "does it parse"."""

        def get_single_data(self):
            try:
                return super().get_single_data()
            except yaml.YAMLError as exc:
                raise NotAYAMLError(str(exc)) from None

    class NeverRaises(yaml.SafeLoader):
        def get_single_data(self):
            return yaml.safe_load(VALID)

    chosen = {
        None: None,
        "disagrees": Disagrees,
        "raises-on-valid": RaisesOnValid,
        "uncatchable": Uncatchable,
        "never-raises": NeverRaises,
    }[loader]
    sound, why = judge(chosen)
    assert sound is False
    assert expected in why, why


def test_the_rule_accepts_a_loader_that_behaves():
    sound, why = judge(yaml.SafeLoader)
    assert sound is True and why == "sound"


def test_the_helper_falls_back_when_the_verdict_is_unsound(monkeypatch):
    """On a sound machine `safe_loader()` returning CSafeLoader unconditionally
    is indistinguishable from the correct code, so the fallback has to be forced
    to be tested at all. It is the only branch that runs on Linux."""
    from kg_microbe_corpus import loader as module

    monkeypatch.setattr(module, "loader_is_sound", lambda: False)
    assert module.safe_loader() is yaml.SafeLoader

    monkeypatch.setattr(module, "loader_is_sound", lambda: True)
    assert module.safe_loader() is yaml.CSafeLoader


def test_which_modules_hold_a_second_copy_of_yaml_error(record_property):
    """#233's remaining question: `yaml/error.py` is executed twice on Linux CI,
    producing two `YAMLError` objects that both report `__module__ ==
    "yaml.error"`. This asks which `sys.modules` keys hold them.

    If a second key exists, its name says what re-imported the file -- and if
    that is something claw depends on, the fix is claw's rather than PyYAML's.
    Records rather than asserts: on a machine with one copy there is nothing to
    report, and the absence is itself the answer.
    """
    same_file = {
        name: getattr(module, "__file__", None)
        for name, module in list(sys.modules.items())
        if getattr(module, "__file__", None)
        and Path(module.__file__).name == "error.py"
        and "yaml" in Path(module.__file__).parts
    }
    record_property("modules whose file is yaml/error.py", str(same_file))

    classes = {}
    for name, module in list(sys.modules.items()):
        candidate = getattr(module, "YAMLError", None)
        if isinstance(candidate, type) and candidate.__qualname__ == "YAMLError":
            classes.setdefault(f"{id(candidate):x}", []).append(name)
    record_property("distinct YAMLError objects", str(classes))
    warnings.warn(
        f"yaml.error copies: {same_file}; YAMLError objects: {classes}", stacklevel=1
    )
    # One object is the only sound state; more than one is #233.
    assert len(classes) >= 1


def test_the_error_classes_are_one_object(record_property):
    """#233's root cause, asked directly.

    The hypothesis: PyYAML's `yaml/__init__.py` re-exports `yaml.error`, and the
    compiled `_yaml` extension carries its own error classes. If the extension
    was built against a different PyYAML than the one imported, there are two
    `YAMLError` objects with the same name, and `except` -- which matches by
    identity -- misses the compiled one.

    This does not assert; it records. On a sound machine the identity holds and
    there is nothing to see. On Linux CI the properties are the evidence, and
    they say whether the two classes are genuinely distinct objects or whether
    something else is going on.
    """
    facts = {
        "yaml.__file__": getattr(yaml, "__file__", "?"),
        "yaml.error.YAMLError": f"{id(yaml.error.YAMLError):x}",
        "yaml.YAMLError is yaml.error.YAMLError": yaml.YAMLError is yaml.error.YAMLError,
    }
    if CSAFE is not None:
        try:
            yaml.load(INVALID, Loader=CSAFE)
        except BaseException as exc:  # noqa: BLE001 - the class is the subject
            raised = type(exc)
            same_name = [c for c in raised.__mro__ if c.__qualname__ == "YAMLError"]
            facts["raised"] = f"{raised.__module__}.{raised.__qualname__}"
            facts["raised module file"] = getattr(
                __import__(raised.__module__, fromlist=["_"]), "__file__", "?"
            )
            facts["YAMLError in its MRO"] = (
                f"{id(same_name[0]):x} from {same_name[0].__module__}"
                if same_name
                else "none"
            )
            facts["is the same object"] = bool(
                same_name and same_name[0] is yaml.error.YAMLError
            )
    for key, value in facts.items():
        record_property(key, str(value))
    # Surfaced where a green run can still be read.
    warnings.warn("libyaml identity: " + "; ".join(f"{k}={v}" for k, v in facts.items()), stacklevel=1)
    assert facts["yaml.YAMLError is yaml.error.YAMLError"] is True
