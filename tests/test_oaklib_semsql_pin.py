"""The oaklib pin must keep `sqlite:obo:` off the retired semantic-sql S3 bucket (#345).

INCATools/semantic-sql removed public read from the raw S3 bucket
(semantic-sql#112). oaklib below 0.7.2 resolves `sqlite:obo:` selectors against
it; 0.7.2 moved the default to the CDN. This repo stayed on 0.6.23 — the last
pre-CDN release — long enough for the bucket to start answering 403, at which
point every `get_adapter("sqlite:obo:...")` in scripts/ was aimed at nothing,
and `build_mim_ingredient_sssom.py` was aiming there once per chunk.

The reversion is invisible until it is catastrophic. With `~/.data/oaklib/chebi.db`
already cached, every ChEBI lookup still succeeds on 0.6.23, so no test, gate or
error message distinguishes a correct pin from a reverted one — right up until a
cache miss. That includes the `label-correspondence` gate, which downloads
through this path.

These assert the floor, not the installed version: CI resolves from the lock
with `--frozen`, and a developer may legitimately be ahead.

Ported from MediaIngredientMech's guard of the same name.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# 0.7.2 introduced the CDN default, but declares `requires_python <3.14` while
# this project declares an unbounded `>=3.11`. 0.7.3 widened it to <3.15, so it
# is the lowest release installable across the range we claim to support.
#
# This constant is deliberately the DECLARED FLOOR, not the release that first
# carried the CDN. A constant set to 0.7.2 here would still accept a pyproject
# lowered to 0.7.2 and quietly undo the alignment.
MIN_OAKLIB = (0, 7, 3)

S3_HOST = "s3.amazonaws.com"


def _spec() -> str:
    data = tomllib.loads((REPO / "pyproject.toml").read_text())
    return next(d for d in data["project"]["dependencies"] if d.startswith("oaklib"))


def test_the_pin_floor_keeps_the_cdn_default():
    spec = _spec()
    match = re.search(r">=\s*(\d+)\.(\d+)\.(\d+)", spec)
    assert match, (
        f"no lower bound in {spec!r} — below 0.7.2, `sqlite:obo:` resolves against "
        "the raw S3 bucket semantic-sql retired"
    )
    assert tuple(int(g) for g in match.groups()) >= MIN_OAKLIB, (
        f"{spec!r} is below {'.'.join(map(str, MIN_OAKLIB))}; 0.7.2 carries the CDN "
        "default but is not installable on 3.14, which requires-python allows"
    )


def test_the_lockfile_agrees_with_the_floor():
    """A floor the lock does not satisfy is a floor in name only."""
    lock = (REPO / "uv.lock").read_text()
    match = re.search(r'name = "oaklib"\nversion = "(\d+)\.(\d+)\.(\d+)"', lock)
    assert match, "oaklib absent from uv.lock"
    assert tuple(int(g) for g in match.groups()) >= MIN_OAKLIB


def test_the_resolved_default_is_not_the_retired_bucket():
    """Pin the property, not a proxy for it.

    The two tests above track a version number, which is what we can control but
    not what we care about. This reads the constant oaklib will actually use, so
    it keeps working if upstream renames or re-defaults it again.
    """
    from oaklib.constants import SEMSQL_SQLITE_URL_BASE

    assert S3_HOST not in SEMSQL_SQLITE_URL_BASE, (
        f"oaklib resolves sqlite:obo: against {SEMSQL_SQLITE_URL_BASE}, the raw S3 "
        "bucket INCATools/semantic-sql retired (semantic-sql#112)"
    )
    assert SEMSQL_SQLITE_URL_BASE.startswith("https://"), SEMSQL_SQLITE_URL_BASE
