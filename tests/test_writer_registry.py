"""The in-place corpus writers are declared, and the declaration stays honest.

Phase 3 items 2 and 5: every writer either uses the shared transaction or holds
a reviewed, time-bounded exception, and a new unmanaged writer cannot appear
silently.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest
import yaml

from kg_microbe_write import (
    REGISTRY_VERSION,
    RegistryError,
    calls_shared_record_writer,
    discover_corpus_writers,
    load_registry,
    overdue,
    parse_registry,
)

ROOT = Path(__file__).resolve().parents[1]


def test_the_registry_declares_exactly_the_writers_that_exist():
    """A script that starts calling write_yaml must be declared, and a script
    that stops must be removed -- both directions, or the registry drifts."""
    declared = set(load_registry())
    found = discover_corpus_writers(ROOT)

    assert found, "no corpus writers detected; this test would be vacuous"
    assert declared == found


def test_every_exception_is_reasoned_and_time_bounded():
    for entry in load_registry().values():
        if entry.status == "exception":
            assert entry.reason, entry.path
            assert entry.review_by is not None, entry.path


def test_no_exception_is_overdue():
    """An expired exception is an exception nobody renewed, which is the state
    a time-bounded exception exists to make visible."""
    stale = overdue(load_registry(), date.today())

    assert not stale, (
        "writer exceptions past their review date: "
        + ", ".join(f"{e.path} (due {e.review_by})" for e in stale)
    )


def test_every_declared_writer_file_exists():
    for path in load_registry():
        assert (ROOT / path).is_file(), path


def test_a_writer_using_the_transaction_is_not_registered_as_an_exception():
    """classify_ingredient_type moved to the transaction; if it were still
    listed as an exception the registry would understate the progress."""
    registry = load_registry()

    for path, entry in registry.items():
        source = (ROOT / path).read_text(encoding="utf-8")
        if "ValidatedWriteTransaction" in source:
            assert entry.status == "transaction", path


# --------------------------------------------------------------------------
# The detector
# --------------------------------------------------------------------------


def test_a_bare_call_without_the_shared_import_is_not_detected():
    """Calling something named write_yaml proves nothing on its own (#172)."""
    assert calls_shared_record_writer("write_yaml(path, record)\n") is False


@pytest.mark.parametrize(
    "definition",
    [
        "def write_yaml(path, record):",
        "def  write_yaml(path, record):",
        "def\twrite_yaml(path, record):",
        "async def write_yaml(path, record):",
        "    def write_yaml(self, path, record):",
    ],
)
def test_defining_the_helper_is_not_a_call(definition):
    """classify_ingredient_type defines write_yaml for its importers while
    using the transaction itself; defining it must not register it.

    #171: a fixed-width `(?<!def )` lookbehind matched exactly one space, so
    two spaces or a tab read as a call and would have registered a module that
    only defines the helper as a corpus writer.
    """
    assert calls_shared_record_writer(definition + "\n") is False


def test_a_call_below_a_definition_is_still_detected():
    """Removing definition lines must not hide a real call in the same file."""
    source = (
        "from classify_ingredient_type import write_yaml\n"
        "def write_yaml(path, record):\n    ...\n\nwrite_yaml(p, r)\n"
    )

    assert calls_shared_record_writer(source) is True


def test_a_mention_in_a_comment_is_not_a_call():
    assert calls_shared_record_writer("# write_yaml(path, record) is legacy\n") is False


def test_a_same_named_local_helper_is_not_the_shared_one():
    """#172: `recurate_deprecated_and_removed` defines its own
    `write_yaml(path, patches)` -- different signature, writes a patch file into
    claw's own workspace -- and was registered as an in-place MIM corpus writer.

    A fourth way to be wrong, alongside the report/cache/temp-file cases below:
    the call site looks identical, so only the import distinguishes them.
    """
    source = (
        "def write_yaml(path, patches):\n"
        "    path.write_text(yaml.safe_dump(patches))\n"
        "\n"
        "write_yaml(OUT_YAML, patches)\n"
    )

    assert calls_shared_record_writer(source) is False


def test_importing_and_calling_the_shared_helper_is_detected():
    source = (
        "from classify_ingredient_type import load_yaml, write_yaml\n"
        "write_yaml(path, record)\n"
    )

    assert calls_shared_record_writer(source) is True


def test_a_parenthesised_multi_name_import_is_detected():
    """These scripts import several names across lines; reading one line of the
    statement would miss the helper."""
    source = (
        "from classify_ingredient_type import (\n"
        "    load_yaml,\n"
        "    write_yaml,\n"
        "    append_curation_event,\n"
        ")\n"
        "write_yaml(path, record)\n"
    )

    assert calls_shared_record_writer(source) is True


def test_importing_without_calling_is_not_a_writer():
    source = "from classify_ingredient_type import write_yaml\nprint('unused')\n"

    assert calls_shared_record_writer(source) is False


def test_the_detector_does_not_flag_report_or_cache_writers():
    """A first version keyed on 'mentions a Mech root and writes something',
    which flagged a report generator, a PubMed cache, and a temp-file writer.
    Registering those would have asserted something false."""
    for source in (
        'MIM_ROOT = Path("x")\nOUT.write_text("report")\n',
        'CULTUREMECH_ROOT = Path("x")\ncache_path(pmid).write_text(body)\n',
        'MIM_ROOT = Path("x")\ntmp.write_text(json.dumps(payload))\n',
    ):
        assert calls_shared_record_writer(source) is False


# --------------------------------------------------------------------------
# Registry validation
# --------------------------------------------------------------------------


def _document(**overrides):
    entry = {
        "status": "exception",
        "targets": "MIM ingredient YAMLs",
        "reason": "not yet migrated",
        "review_by": date.today() + timedelta(days=180),
    }
    entry.update(overrides)
    return {"version": REGISTRY_VERSION, "writers": {"scripts/x.py": entry}}


def test_an_exception_without_a_review_date_is_refused():
    with pytest.raises(RegistryError, match="without a review_by"):
        parse_registry(_document(review_by=None))


def test_an_exception_without_a_reason_is_refused():
    with pytest.raises(RegistryError, match="without a reason"):
        parse_registry(_document(reason=""))


def test_a_transaction_writer_may_not_carry_a_review_date():
    with pytest.raises(RegistryError, match="needs no review_by"):
        parse_registry(_document(status="transaction", reason=""))


def test_an_unknown_status_is_refused():
    with pytest.raises(RegistryError, match="expected one of"):
        parse_registry(_document(status="probably-fine"))


def test_a_writer_without_targets_is_refused():
    with pytest.raises(RegistryError, match="must declare what it targets"):
        parse_registry(_document(targets="  "))


def test_an_unsupported_version_is_refused():
    document = _document()
    document["version"] = 999
    with pytest.raises(RegistryError, match="unsupported writer registry version"):
        parse_registry(document)


def test_an_empty_registry_is_refused():
    with pytest.raises(RegistryError, match="non-empty"):
        parse_registry({"version": REGISTRY_VERSION, "writers": {}})


def test_the_registry_ships_inside_the_package():
    """The registry must be packaged, not merely present in the source tree.

    An editable install hides a missing package-data declaration, so assert the
    declaration directly -- checking only that the file exists on disk would
    pass with the wheel silently omitting it, exactly as the fleet manifest
    could before Phase 0 moved it.
    """
    import tomllib

    registry_file = ROOT / "src" / "kg_microbe_write" / "writers.yaml"
    pyproject = tomllib.loads(
        (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    )
    package_data = pyproject["tool"]["setuptools"]["package-data"]

    assert registry_file.is_file(), "the registry must live inside the package"
    assert registry_file.name in package_data.get("kg_microbe_write", []), (
        "writers.yaml is not declared in package-data, so it would be absent "
        "from the wheel"
    )
    assert yaml.safe_load(
        registry_file.read_text(encoding="utf-8")
    )["version"] == REGISTRY_VERSION
