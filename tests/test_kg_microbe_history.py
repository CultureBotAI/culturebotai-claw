"""Tests for the append-only curation-history layer.

Written after a second-pass review of #25 found defects that unit-level reasoning
alone had missed. CultureMech learned the same lesson in its own #107: a script
that writes YAML needs at least one test that validates its output against the
schema, because unit tests cannot catch a wrong slot name.

So `test_scaffolded_record_validates_against_schema` is the load-bearing one; the
rest pin the specific defects from #29/#30/#31 so they cannot come back.
"""

from __future__ import annotations

import shutil
import sys
from importlib.resources import files
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))
SCHEMA = files("kg_microbe_governance").joinpath("artifacts/schema/history.yaml")

from kg_microbe_history.__main__ import _default_schema_path, main  # noqa: E402
from kg_microbe_history.scaffold import (  # noqa: E402
    KIND_DIRS,
    _slug_token,
    build_record,
    new_history_path,
    write_record,
)


def _new(tmp_path: Path, *args: str) -> int:
    return main(["new", "--history-root", str(tmp_path / "history"), *args])


def _only_record(tmp_path: Path) -> Path:
    found = list((tmp_path / "history").rglob("*.yaml"))
    assert len(found) == 1, f"expected exactly one record, got {found}"
    return found[0]


# --------------------------------------------------------------------------
# The load-bearing test: emitted YAML must satisfy the real schema.
# --------------------------------------------------------------------------


def test_default_schema_is_the_packaged_governance_artifact() -> None:
    assert Path(_default_schema_path()).resolve() == Path(str(SCHEMA)).resolve()


@pytest.mark.skipif(shutil.which("linkml-validate") is None, reason="linkml not installed")
def test_scaffolded_record_validates_against_schema(tmp_path: Path) -> None:
    assert _new(tmp_path, "--kind", "record", "--slug", "demo", "--target-root", "data",
                "--summary", "s", "--details", "real details") == 0
    assert main(["validate", str(tmp_path / "history")]) == 0


def test_code_enums_match_schema() -> None:
    """A permissible value drifting between code and schema is silent otherwise."""
    from kg_microbe_history import scaffold as s

    enums = yaml.safe_load(SCHEMA.read_text())["enums"]
    assert set(KIND_DIRS) == set(enums["HistoryTargetKindEnum"]["permissible_values"])
    assert set(s.EVENT_TYPES) == set(enums["HistoryEventTypeEnum"]["permissible_values"])
    assert set(s.OUTCOMES) == set(enums["HistoryOutcomeEnum"]["permissible_values"])
    assert set(s.ACTOR_TYPES) == set(enums["HistoryActorTypeEnum"]["permissible_values"])


# --------------------------------------------------------------------------
# #29 — the enforcement model
# --------------------------------------------------------------------------


def test_todo_placeholder_is_rejected_by_validate(tmp_path: Path) -> None:
    """The whole point of the gate: a scaffolded-but-unfilled record must fail."""
    assert _new(tmp_path, "--kind", "record", "--slug", "demo", "--target-root", "data",
                "--summary", "no details supplied") == 0
    rc = main(["validate", str(tmp_path / "history"), "--structural-only"])
    assert rc == 1


def test_filled_details_passes(tmp_path: Path) -> None:
    assert _new(tmp_path, "--kind", "record", "--slug", "demo", "--target-root", "data",
                "--summary", "s", "--details", "what actually happened") == 0
    assert main(["validate", str(tmp_path / "history"), "--structural-only"]) == 0


# --------------------------------------------------------------------------
# #30 — path and slug derivation
# --------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["mapping", "report", "infrastructure", "other"])
def test_non_yaml_kinds_require_explicit_path(tmp_path: Path, kind: str) -> None:
    """Records are append-only, so a guessed .yaml extension is permanently wrong."""
    assert _new(tmp_path, "--kind", kind, "--slug", "x", "--summary", "s",
                "--details", "d") == 2


def test_dot_only_slug_is_rejected() -> None:
    with pytest.raises(ValueError):
        _slug_token("..")
    with pytest.raises(ValueError):
        _slug_token(".")


def test_slug_cannot_escape_kind_directory(tmp_path: Path) -> None:
    rc = _new(tmp_path, "--kind", "record", "--slug", "..", "--target-root", "data",
              "--summary", "s", "--details", "d")
    assert rc == 2
    assert not list((tmp_path / "history").rglob("*.yaml"))


def test_multi_suffix_target_yields_same_dir_as_slug(tmp_path: Path) -> None:
    """foo.sssom.tsv must not file under 'foo.sssom' while --slug foo files under 'foo'."""
    a, _, _ = new_history_path(tmp_path, "mapping", "foo", "claude-code")
    assert a.parent.name == "foo"
    assert _new(tmp_path, "--kind", "mapping", "--path", "mappings/foo.sssom.tsv",
                "--summary", "s", "--details", "d") == 0
    assert _only_record(tmp_path).parent.name == "foo"


def test_recorded_slug_matches_its_directory(tmp_path: Path) -> None:
    assert _new(tmp_path, "--kind", "record", "--slug", "Foo Bar/baz",
                "--target-root", "data", "--summary", "s", "--details", "d") == 0
    record = _only_record(tmp_path)
    assert yaml.safe_load(record.read_text())["target"]["slug"] == record.parent.name


def test_target_root_and_path_are_mutually_exclusive(tmp_path: Path) -> None:
    assert _new(tmp_path, "--kind", "record", "--slug", "x", "--target-root", "a",
                "--path", "b/c.yaml", "--summary", "s", "--details", "d") == 2


@pytest.mark.parametrize("bad", ["../../../evil.yaml", "/etc/passwd"])
def test_path_must_be_repo_relative(tmp_path: Path, bad: str) -> None:
    assert _new(tmp_path, "--kind", "record", "--slug", "ok", "--path", bad,
                "--summary", "s", "--details", "d") == 2


# --------------------------------------------------------------------------
# #31 — validator robustness
# --------------------------------------------------------------------------


@pytest.mark.parametrize("body", [
    "events:\n- just-a-scalar\n",                       # events entry not a mapping
    "events:\n- {type: EDIT, outcome: changed, summary: s, details: 42}\n",  # non-str
    "session: a-scalar\nevents:\n- {type: EDIT, outcome: changed, summary: s, details: d}\n",
])
def test_malformed_record_reports_rather_than_crashing(tmp_path: Path, body: str) -> None:
    """One bad record used to abort the scan, losing results for every good one."""
    good = tmp_path / "history" / "records" / "g"
    good.mkdir(parents=True)
    assert _new(tmp_path, "--kind", "record", "--slug", "good", "--target-root", "data",
                "--summary", "s", "--details", "fine") == 0

    bad_dir = tmp_path / "history" / "records" / "bad"
    bad_dir.mkdir(parents=True, exist_ok=True)
    (bad_dir / "r.yaml").write_text(
        'history_version: 1\ntarget: {kind: record, path: a.yaml}\n'
        'session: {id: i, timestamp: "2026-07-31T00:00:00Z", actors: [{type: human, name: n}]}\n'
        + body
    )
    assert main(["validate", str(tmp_path / "history"), "--structural-only"]) == 1


def test_yml_extension_is_not_skipped(tmp_path: Path) -> None:
    d = tmp_path / "history" / "records" / "x"
    d.mkdir(parents=True)
    (d / "r.yml").write_text("just: a-mapping\n")
    assert main(["validate", str(tmp_path / "history"), "--structural-only"]) == 1


def test_validate_missing_target_is_clean_error(tmp_path: Path) -> None:
    assert main(["validate", str(tmp_path / "nope"), "--structural-only"]) == 2


def test_missing_schema_error_names_packaged_authority(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    history = tmp_path / "history"
    history.mkdir()
    missing = tmp_path / "missing-history.yaml"

    assert main(["validate", str(history), "--schema", str(missing)]) == 2

    error = capsys.readouterr().err
    assert "kg_microbe_governance/artifacts/schema/history.yaml" in error


def test_build_record_rejects_unknown_kind() -> None:
    with pytest.raises(ValueError):
        build_record(kind="nonsense", slug="s", target_path="a.yaml", session_id="i",
                     timestamp="2026-07-31T00:00:00Z", summary="s", details="d")


def test_write_record_refuses_to_clobber(tmp_path: Path) -> None:
    p = tmp_path / "r.yaml"
    write_record(p, {"a": 1})
    with pytest.raises(FileExistsError):
        write_record(p, {"a": 2})
    assert yaml.safe_load(p.read_text()) == {"a": 1}


def test_write_record_leaves_no_temp_files(tmp_path: Path) -> None:
    p = tmp_path / "r.yaml"
    write_record(p, {"a": 1})
    write_record(p, {"a": 2}, force=True)
    assert yaml.safe_load(p.read_text()) == {"a": 2}
    assert [q.name for q in tmp_path.iterdir()] == ["r.yaml"]


def test_details_round_trips_through_yaml(tmp_path: Path) -> None:
    """Literal-block dumping must not corrupt whitespace-sensitive prose."""
    details = "line one \n\ttabbed\n  indented\nends\n"
    assert _new(tmp_path, "--kind", "record", "--slug", "rt", "--target-root", "data",
                "--summary", "s", "--details", details) == 0
    loaded = yaml.safe_load(_only_record(tmp_path).read_text())
    assert loaded["events"][0]["details"] == details


def test_session_id_equals_filename_stem(tmp_path: Path) -> None:
    """The schema promises this; it is how a record is located from its id."""
    assert _new(tmp_path, "--kind", "record", "--slug", "demo", "--target-root", "data",
                "--summary", "s", "--details", "d") == 0
    record = _only_record(tmp_path)
    assert yaml.safe_load(record.read_text())["session"]["id"] == record.stem
