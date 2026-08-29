"""Per-Mech record serialization is verified, not copied (Phase 3 item 4).

CultureMech#141 measured the cost of getting this wrong: writing records back
at `width=120` re-wrapped every long string, so a two-field edit produced 47
added lines, 24 of them noise. The options here are declared only where they
were measured to round-trip that Mech's real corpus byte-for-byte.
"""

from __future__ import annotations

import os
import random
from pathlib import Path

import pytest
import yaml

from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_write import (
    SerializationUnavailable,
    dump_record,
    emit_options,
)

MANIFEST = load_fleet_manifest()
VERIFIED = sorted(
    key
    for key, mech in MANIFEST.mechs.items()
    if mech.serialization is not None and mech.serialization.verified
)
UNVERIFIED = sorted(set(MANIFEST.mechs) - set(VERIFIED))


def test_every_mech_declares_a_serialization_profile():
    """An absent profile is indistinguishable from an unverified one, and only
    the second is a recorded decision."""
    missing = [k for k, m in MANIFEST.mechs.items() if m.serialization is None]

    assert not missing, f"no serialization profile declared for: {missing}"


def test_both_outcomes_are_represented():
    """Guards the parametrized tests below: if every Mech landed in one bucket,
    half of them would silently exercise nothing."""
    assert VERIFIED, "no Mech has verified emit options"
    assert UNVERIFIED, "no Mech is recorded as unverified"


@pytest.mark.parametrize("key", VERIFIED)
def test_a_verified_profile_yields_usable_options(key):
    options = emit_options(key)

    assert options
    assert set(options) <= {
        "default_flow_style", "sort_keys", "allow_unicode", "width", "indent"
    }


@pytest.mark.parametrize("key", UNVERIFIED)
def test_an_unverified_profile_refuses_rather_than_guessing(key):
    """Reformatting someone else's corpus is worse than declining to write."""
    with pytest.raises(SerializationUnavailable, match="no verified emit options"):
        emit_options(key)


@pytest.mark.parametrize("key", UNVERIFIED)
def test_an_unverified_profile_records_why(key):
    profile = MANIFEST.mechs[key].serialization

    assert profile.reason.strip()
    assert not profile.options, "an unverified profile must carry no options"


def test_an_unknown_mech_is_refused():
    with pytest.raises(SerializationUnavailable, match="unknown Mech"):
        emit_options("nosuchmech")


def test_dump_record_uses_the_declared_options():
    record = {"identifier": "CHEBI:1", "note": "x" * 200}

    assert dump_record("mediaingredientmech", record) == yaml.safe_dump(
        record, **emit_options("mediaingredientmech")
    )


# --------------------------------------------------------------------------
# The measurement that makes the profile trustworthy
# --------------------------------------------------------------------------


def _records_for(key: str) -> list[Path]:
    mech = MANIFEST.mechs[key]
    root = os.environ.get(mech.environment_variable, "").strip()
    if not root or not Path(root).is_dir():
        return []
    return [p for glob in mech.record_globs for p in Path(root).glob(glob)]


@pytest.mark.parametrize("key", VERIFIED)
def test_a_verified_profile_round_trips_the_real_corpus(key):
    """The only check that proves the options are right.

    Skipped when the checkout is absent -- and the skip is honest, because a
    profile asserted without this measurement is exactly what #187 found in two
    other Mechs, where the declared options reproduce 0% of the corpus.
    """
    records = _records_for(key)
    if not records:
        pytest.skip(f"{MANIFEST.mechs[key].environment_variable} is not configured")

    random.seed(0)
    sample = random.sample(sorted(records), min(60, len(records)))
    options = emit_options(key)
    mismatched = []
    for path in sample:
        text = path.read_text(encoding="utf-8")
        document = yaml.safe_load(text)
        if document is None:
            continue
        if yaml.safe_dump(document, **options) != text:
            mismatched.append(path.name)

    assert not mismatched, (
        f"{key}: {len(mismatched)}/{len(sample)} records would be reformatted by "
        f"the declared options, e.g. {mismatched[:3]}"
    )


def test_the_claw_writers_use_the_shared_serializer_not_a_local_copy():
    """A local option set is how two Mechs ended up with options reproducing 0%
    of their own records (#187). claw's writers must not keep their own."""
    import importlib.util
    import sys

    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / "scripts"))
    spec = importlib.util.spec_from_file_location(
        "_classify_for_serialization", root / "scripts" / "classify_ingredient_type.py"
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    record = {"identifier": "CHEBI:1", "note": "y" * 300}

    assert module.dump_yaml(record) == dump_record("mediaingredientmech", record)


def test_no_claw_writer_hardcodes_yaml_emit_options():
    """A second option set anywhere is a second thing to keep in step."""
    root = Path(__file__).resolve().parents[1]
    offenders = []
    for path in sorted((root / "scripts").glob("*.py")):
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if "safe_dump" in stripped and (
                "default_flow_style" in stripped or "width=" in stripped
            ):
                offenders.append(f"{path.name}:{number}")

    assert not offenders, (
        "emit options are hardcoded; call kg_microbe_write.dump_record instead: "
        + ", ".join(offenders)
    )
