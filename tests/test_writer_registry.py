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


def test_every_unmigrated_writer_is_declared():
    """The detector finds scripts still using the shared, non-atomic helper.

    Those are the UNMIGRATED writers, so the detected set must be a subset of
    the registry -- not equal to it. Once a writer moves to the transaction it
    stops importing the helper and drops out of detection while staying
    declared, which is the whole point of the migration.
    """
    declared = set(load_registry())
    found = discover_corpus_writers(ROOT)

    unregistered = found - declared
    assert not unregistered, (
        f"scripts use the shared non-atomic write helper but are not in the "
        f"registry: {sorted(unregistered)}"
    )


def test_a_detected_writer_is_never_marked_as_migrated():
    """A script still importing the helper cannot be using the transaction."""
    registry = load_registry()
    found = discover_corpus_writers(ROOT)

    for path in found:
        assert registry[path].status == "exception", (
            f"{path} still uses the shared write helper but is registered as "
            f"having moved to the transaction"
        )


def test_a_migrated_writer_no_longer_uses_the_shared_helper():
    """The converse: `transaction` status must be earned, not asserted."""
    found = discover_corpus_writers(ROOT)

    for path, entry in load_registry().items():
        if entry.uses_transaction:
            assert path not in found, (
                f"{path} claims to use the transaction while still importing "
                f"and calling the shared write helper"
            )


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


def test_a_writer_importing_the_transaction_is_registered_as_migrated():
    """If a converted writer were still listed as an exception the registry
    would understate the progress and keep a stale review date alive."""
    for path, entry in load_registry().items():
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


def test_a_call_below_other_definitions_is_still_detected():
    """A call is a call wherever it sits in the file.

    This previously used a source that ALSO redefined `write_yaml`, and
    asserted True. The AST detector says False there, and it is right: a
    module-level `def write_yaml` rebinds the name, so the call below it goes
    to the local function, not the shared helper. That case is now
    `test_a_module_that_shadows_the_import_is_not_a_caller`; this one keeps the
    original intent with a source that does not shadow.
    """
    source = (
        "from classify_ingredient_type import write_yaml\n"
        "def helper(path, record):\n    ...\n\nwrite_yaml(p, r)\n"
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


# --------------------------------------------------------------------------
# Phase 3 item 3: AST detection, generalizing the strongest Mech writer audit
# --------------------------------------------------------------------------


def test_an_aliased_import_is_still_the_shared_helper():
    """`import write_yaml as _w` then `_w(...)` reads nothing like a call to the
    shared helper. Text matching cannot follow the rename; a parser can."""
    source = (
        "from classify_ingredient_type import write_yaml as _w\n"
        "_w(path, record)\n"
    )

    assert calls_shared_record_writer(source) is True


def test_a_module_that_shadows_the_import_is_not_a_caller():
    """Importing then redefining the same name rebinds it; the calls that
    follow are to the local function, not the shared helper."""
    source = (
        "from classify_ingredient_type import write_yaml\n"
        "def write_yaml(path, patches):\n"
        "    path.write_text(patches)\n"
        "write_yaml(OUT, patches)\n"
    )

    assert calls_shared_record_writer(source) is False


def test_unparseable_source_is_not_reported_as_a_writer():
    """A syntax error is a broken file, not a corpus writer; claiming otherwise
    would put a nonsense entry in the registry."""
    assert calls_shared_record_writer("def broken(:\n") is False


@pytest.mark.parametrize(
    "definition",
    [
        "def write_yaml(path, record):",
        "def  write_yaml(path, record):",
        "def\twrite_yaml(path, record):",
        "async def write_yaml(path, record):",
    ],
)
def test_spacing_in_a_definition_is_irrelevant_to_a_parser(definition):
    """#171 was a fixed-width lookbehind matching exactly one space. An AST has
    no notion of the whitespace between `def` and the name."""
    source = f"from classify_ingredient_type import write_yaml\n{definition}\n    ...\n"

    assert calls_shared_record_writer(source) is False


def test_a_call_in_a_nested_function_is_still_a_call():
    source = (
        "from classify_ingredient_type import write_yaml\n"
        "def outer():\n"
        "    def inner():\n"
        "        write_yaml(path, record)\n"
        "    return inner\n"
    )

    assert calls_shared_record_writer(source) is True


# --------------------------------------------------------------------------
# #185: both import forms reach the same function
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "source",
    [
        "import classify_ingredient_type as m\nm.write_yaml(p, r)\n",
        "import classify_ingredient_type\nclassify_ingredient_type.write_yaml(p, r)\n",
    ],
    ids=["aliased-module", "plain-module"],
)
def test_a_module_attribute_call_reaches_the_shared_helper(source):
    """#185: only the from-import form was understood, so a detector meant to
    be unevadable could be evaded by writing ordinary Python."""
    assert calls_shared_record_writer(source) is True


def test_importing_the_module_without_calling_the_writer_is_not_a_writer():
    """Non-vacuity: the module import alone must not register."""
    source = "import classify_ingredient_type as m\nm.load_yaml(path)\n"

    assert calls_shared_record_writer(source) is False


def test_an_indirect_binding_is_a_stated_limit_not_a_silent_one():
    """`f = write_yaml; f(...)` is NOT detected, and the docstring says so.

    Following a value through arbitrary rebinding is dataflow analysis rather
    than a parse. The test exists so the boundary is recorded and anyone
    changing it sees the intent.
    """
    source = (
        "from classify_ingredient_type import write_yaml\n"
        "f = write_yaml\n"
        "f(path, record)\n"
    )

    assert calls_shared_record_writer(source) is False
    assert "dataflow analysis" in calls_shared_record_writer.__doc__
