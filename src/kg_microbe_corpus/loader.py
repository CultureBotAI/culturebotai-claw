"""Which YAML loader is safe to use on the machine running.

#233 and #263. `yaml.CSafeLoader` is roughly sixteen times faster than
`yaml.SafeLoader` -- 134 records/s against 2,129 on real trait records -- and on
claw's Linux CI it is broken in two ways at once, on a PyYAML 6.0.3 build with
`__with_libyaml__=True`:

    a valid document raises ConstructorError: could not determine a
    constructor for the tag None

    a parse error is raised with 'YAMLError' in its MRO, and
    isinstance(exc, yaml.YAMLError) is False -- a class named YAMLError that
    is not the one yaml.error.YAMLError names, so `except` misses it

macOS is sound, which is why this only ever appeared in CI.

Choosing the loader by `getattr(yaml, "CSafeLoader", yaml.SafeLoader)` -- which
is what two claw scripts did -- asks whether the name exists, not whether it
works. On Linux those scripts parsed nothing, and because they wrapped the load
in `except Exception` they reported zero changes rather than failing: a silent
wrong answer from a script that writes curated data.

So the question is answered by trying it, once, at import.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import yaml

__all__ = ["judge", "loader_is_sound", "safe_loader", "soundness"]

_VALID = "identifier: X:1\nlabel: a thing\nvalues:\n  - one\n  - two\n"
_INVALID = "identifier: [unclosed\n"


def judge(fast: Any | None) -> tuple[bool, str]:
    """Whether `fast` can stand in for SafeLoader, and why not.

    Takes the loader rather than reaching for `yaml.CSafeLoader`, so the rule
    can be exercised against loaders that fail each way. On a sound machine a
    rule that only ever sees a working loader is a rule whose failure paths have
    never run -- and this one exists precisely for a platform I cannot run.

    Both failure modes are checked, because either alone is disqualifying and
    the Linux build shows both. A parse that *succeeds* but disagrees is the
    dangerous one: it produces a wrong answer rather than an error.
    """
    if fast is None:
        return False, "this PyYAML build has no CSafeLoader"
    try:
        if yaml.load(_VALID, Loader=fast) != yaml.safe_load(_VALID):
            return False, "CSafeLoader disagrees with SafeLoader on a valid record"
    except Exception as exc:  # noqa: BLE001 - any failure disqualifies it
        return False, f"a valid record raised {type(exc).__qualname__}"
    try:
        yaml.load(_INVALID, Loader=fast)
    except yaml.YAMLError:
        return True, "sound"
    except Exception as exc:  # noqa: BLE001 - the second failure mode
        return False, (
            f"a parse error raised {type(exc).__module__}.{type(exc).__qualname__}, "
            f"which `except yaml.YAMLError` does not catch"
        )
    return False, "invalid YAML did not raise"


@lru_cache(maxsize=1)
def soundness() -> tuple[bool, str]:
    """`judge` applied to this build's CSafeLoader, computed once.

    Trying a parse on every call would cost more than the loader saves.
    """
    return judge(getattr(yaml, "CSafeLoader", None))


def loader_is_sound() -> bool:
    return soundness()[0]


def safe_loader() -> Any:
    """The fastest loader that behaves correctly here.

    Callers get libyaml's speed where it is trustworthy and PyYAML's Python
    loader where it is not, without having to know which machine they are on.
    """
    return yaml.CSafeLoader if loader_is_sound() else yaml.SafeLoader
