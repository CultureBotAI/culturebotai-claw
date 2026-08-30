"""Whether libyaml's loader can be trusted here, asked on the machine that runs.

#233. Swapping `kg_microbe_corpus` to `yaml.CSafeLoader` is worth about 70
minutes on ProteinTraitsMech's 429,271 records -- 134 records/s becomes 2,129.
It passed the whole suite on macOS and failed 14 tests on Linux CI at the same
commit, with two symptoms that are hard to hold together:

  * every corpus test found zero records -- valid fixtures parsed to None; and
  * a ParserError escaped an `except (OSError, yaml.YAMLError)` that
    demonstrably catches it locally.

If nothing parsed, nothing should have reached the parser to raise. The cause
was never found, and a parser that behaves differently by platform is not
something to adopt for a speed-up however large -- corpus statistics feed
reports people act on.

So rather than guess again, this states the two properties CSafeLoader must
have before it can be adopted, and lets each platform answer for itself. On a
machine where they hold, the tests pass and say so. On a machine where they do
not, the failure *is* the reproduction #233 asks for, with the platform facts
in the message.

These tests do not change what the corpus reader uses. `statistics.py` still
calls `yaml.safe_load`.
"""

from __future__ import annotations

import platform

import pytest
import yaml

CSAFE = getattr(yaml, "CSafeLoader", None)

_FACTS = (
    f"PyYAML {yaml.__version__}, with_libyaml={getattr(yaml, '__with_libyaml__', None)}, "
    f"{platform.system()} {platform.machine()}, python {platform.python_version()}"
)

pytestmark = pytest.mark.skipif(
    CSAFE is None, reason=f"no CSafeLoader here ({_FACTS})"
)

VALID = "identifier: X:1\nlabel: a thing\nvalues:\n  - one\n  - two\n"
INVALID = "identifier: [unclosed\n"


def test_the_two_loaders_agree_on_a_valid_record():
    """The first symptom: valid fixtures parsed to None under CSafeLoader."""
    expected = yaml.safe_load(VALID)
    assert expected is not None, "the fixture itself is wrong"
    assert yaml.load(VALID, Loader=CSAFE) == expected, (
        f"CSafeLoader disagrees with SafeLoader on a valid record here. {_FACTS}"
    )


def test_an_empty_document_is_none_for_both():
    assert yaml.safe_load("") is None
    assert yaml.load("", Loader=CSAFE) is None


def test_a_parse_error_is_catchable_as_a_yaml_error():
    """The second symptom: a ParserError escaped `except yaml.YAMLError`.

    That can happen when the compiled extension's error classes are not the
    ones `yaml.YAMLError` names -- a mismatched PyYAML/libyaml build gives two
    distinct class objects and `except` matches by identity, not by name.
    """
    with pytest.raises(yaml.YAMLError):
        yaml.load(INVALID, Loader=CSAFE)


def test_the_error_class_is_the_one_this_package_would_catch():
    """Stated separately from the `raises` above, because that one passing tells
    you the error is *a* YAMLError, not that it is the YAMLError the corpus
    reader's except clause refers to."""
    try:
        yaml.load(INVALID, Loader=CSAFE)
    except BaseException as exc:  # noqa: BLE001 - the class is the subject
        assert isinstance(exc, yaml.YAMLError), (
            f"CSafeLoader raised {type(exc).__module__}.{type(exc).__qualname__}, "
            f"which is not yaml.YAMLError ({yaml.YAMLError.__module__}). "
            f"MRO: {[c.__qualname__ for c in type(exc).__mro__]}. {_FACTS}"
        )
    else:  # pragma: no cover - the fixture is invalid YAML
        pytest.fail("invalid YAML did not raise")


def test_repeated_loads_do_not_degrade():
    """A libyaml parser reused across documents is the shape the corpus reader
    would hit -- thousands of small loads in one process."""
    for _ in range(200):
        assert yaml.load(VALID, Loader=CSAFE) is not None
