"""`mapping_date` must come from curation, never from the filesystem.

MediaIngredientMech#542: the builder used to fall back to a record's mtime when
`curation_history` yielded no parseable timestamp. Git does not preserve mtimes,
so that stamped records with whenever the machine cloned -- different per
checkout, meaningless as curation data, and published into an artifact whose
whole point is reproducibility.

It was not hypothetical. While the fallback was live it mis-stamped three rows
(`Sodium_glycerophosphate` among them, dated 2026-09-01 against a sole history
entry of 2026-08-31), and nothing caught it until a rebuild diff showed dates
moving *backward* -- the correction, not the defect.
"""

import importlib.util
import sys
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(_SCRIPTS))

_SPEC = importlib.util.spec_from_file_location(
    "build_mim_ingredient_sssom", _SCRIPTS / "build_mim_ingredient_sssom.py",
)
builder = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = builder
_SPEC.loader.exec_module(builder)


def _event(ts):
    return {"timestamp": ts, "action": "CORRECTED"}


def test_uses_the_latest_timestamp():
    """The published date is the newest curation, not the newest file write."""
    history = [_event("2026-01-05T10:00:00+00:00"), _event("2026-03-09T10:00:00+00:00")]
    assert builder._mapping_date(Path("irrelevant.yaml"), history) == "2026-03-09"


def test_out_of_order_history_still_yields_the_latest():
    """`history[-1]` and "most recent" coincide only while history stays sorted."""
    history = [_event("2026-03-09T10:00:00+00:00"), _event("2026-01-05T10:00:00+00:00")]
    assert builder._mapping_date(Path("irrelevant.yaml"), history) == "2026-03-09"


def test_unparseable_timestamps_are_ignored_not_guessed():
    """A malformed stamp must not promote a stale one, nor invent a date."""
    history = [_event("2026-02-02T00:00:00+00:00"), _event("not-a-date")]
    assert builder._mapping_date(Path("irrelevant.yaml"), history) == "2026-02-02"


def test_no_history_yields_empty_not_a_filesystem_date(tmp_path, capsys):
    """The whole point: no curation date means no date, and it says so.

    A real path is passed so that any reintroduced `path.stat()` fallback would
    succeed and return today -- making this test fail loudly rather than pass by
    accident on a missing file.
    """
    record = tmp_path / "Some_Record.yaml"
    record.write_text("identifier: CHEBI:1\n", encoding="utf-8")

    assert builder._mapping_date(record, []) == ""
    assert "Some_Record.yaml" in capsys.readouterr().out


def test_history_of_only_bad_timestamps_yields_empty(tmp_path):
    """Same contract when history exists but carries nothing usable."""
    record = tmp_path / "Another_Record.yaml"
    record.write_text("identifier: CHEBI:2\n", encoding="utf-8")

    assert builder._mapping_date(record, [_event(""), _event("soon")]) == ""
