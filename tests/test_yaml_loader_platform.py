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
import warnings
from pathlib import Path

import pytest
import yaml

CSAFE = getattr(yaml, "CSafeLoader", None)

FACTS = (
    f"PyYAML {yaml.__version__}, with_libyaml={getattr(yaml, '__with_libyaml__', None)}, "
    f"{platform.system()} {platform.machine()}, python {platform.python_version()}"
)

VALID = "identifier: X:1\nlabel: a thing\nvalues:\n  - one\n  - two\n"
INVALID = "identifier: [unclosed\n"


def _soundness() -> tuple[bool, str]:
    """Whether libyaml's loader can be substituted for SafeLoader here."""
    if CSAFE is None:
        return False, "no CSafeLoader in this build"
    try:
        if yaml.load(VALID, Loader=CSAFE) != yaml.safe_load(VALID):
            return False, "CSafeLoader disagrees with SafeLoader on a valid record"
    except Exception as exc:  # noqa: BLE001 - any failure is unsoundness
        return False, f"a valid record raised {type(exc).__qualname__}"
    try:
        yaml.load(INVALID, Loader=CSAFE)
    except yaml.YAMLError:
        return True, "sound"
    except Exception as exc:  # noqa: BLE001 - the whole point
        mro = [c.__qualname__ for c in type(exc).__mro__]
        return False, (
            f"a parse error raised {type(exc).__module__}.{type(exc).__qualname__}, "
            f"which `except yaml.YAMLError` does not catch (MRO {mro})"
        )
    return False, "invalid YAML did not raise at all"


SOUND, WHY = _soundness()
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
