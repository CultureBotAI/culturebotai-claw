"""The shared source-queue contract, and the rule that was too strict.

Proved against the only two queues that exist: AntibioticMech wrote the pattern
and CellStructureMech adapted it. Both are well kept -- one finding between them,
and it is the spelling drift that argues for sharing the contract before five
more copies are made.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kg_microbe_fleet.roots import MechRootError, resolve_mech_root
from kg_microbe_source_queue import (
    CORE_COLUMNS,
    SourceQueueProfile,
    check_queue,
    summarise,
)

CLAW_ROOT = Path(__file__).resolve().parents[1]
HEADER = "\t".join(CORE_COLUMNS)


def row(**over: str) -> str:
    values = {
        "source_id": "s1",
        "name": "A source",
        "closes_gap": "records",
        "use": "REFERENCE",
        "redistribution": "CC0_OK",
        "access": "BULK",
        "priority": "1",
        "status": "CANDIDATE",
        "verified_on": "2026-08-31",
        "url": "https://example.test/",
        "rationale": "because",
    }
    values.update(over)
    return "\t".join(values[c] for c in CORE_COLUMNS)


def queue(tmp_path: Path, *rows: str, header: str = HEADER) -> Path:
    path = tmp_path / "source_queue.tsv"
    path.write_text(header + "\n" + "\n".join(rows) + "\n", encoding="utf-8")
    return path


def codes(findings) -> list[str]:
    return [f.code for f in findings]


def test_a_well_formed_queue_reports_nothing(tmp_path: Path):
    assert check_queue(queue(tmp_path, row())) == []


# -- the rule that was too strict -------------------------------------------


def test_a_candidate_may_intend_to_seed_before_its_licence_is_read(tmp_path: Path):
    """`use` on a candidate is an intention. "We would copy this if the licence
    allows" is the normal state before anyone has read the licence -- every SEED
    row with unverified terms in both real queues is CANDIDATE, EVALUATING or
    BLOCKED. Judging intent reported twelve correct rows as violations."""
    for status in ("CANDIDATE", "EVALUATING", "BLOCKED"):
        found = check_queue(
            queue(tmp_path, row(use="SEED", redistribution="UNVERIFIED", status=status,
                                verified_on=""))
        )
        assert found == [], status


def test_an_adopted_source_may_not_be_seeded_under_terms_that_forbid_it(tmp_path: Path):
    for terms in ("UNVERIFIED", "RESTRICTED", "NONCOMMERCIAL"):
        found = codes(
            check_queue(queue(tmp_path, row(use="SEED", redistribution=terms, status="ADOPTED")))
        )
        assert "SEED_UNDER_TERMS_THAT_FORBID_IT" in found, terms


# -- the adoption gate ------------------------------------------------------


def test_adopted_with_unverified_terms_is_the_failure_this_exists_for(tmp_path: Path):
    found = codes(
        check_queue(queue(tmp_path, row(status="ADOPTED", redistribution="UNVERIFIED")))
    )
    assert "ADOPTED_BUT_UNVERIFIED" in found


def test_adopted_without_a_verification_date_is_reported(tmp_path: Path):
    found = codes(check_queue(queue(tmp_path, row(status="ADOPTED", verified_on=""))))
    assert "ADOPTED_WITHOUT_A_DATE" in found


def test_a_repository_may_require_more_of_an_adopted_source(tmp_path: Path):
    """CellStructureMech requires a `script`, because a source nothing reads is
    not adopted."""
    header = HEADER + "\tscript"
    profile = SourceQueueProfile(extensions=("script",), required_when_adopted=("script",))
    empty = queue(tmp_path, row(status="ADOPTED") + "\t", header=header)
    assert "ADOPTED_WITHOUT_SCRIPT" in codes(check_queue(empty, profile))
    filled = queue(tmp_path, row(status="ADOPTED") + "\tscripts/fetch.py", header=header)
    assert check_queue(filled, profile) == []


# -- vocabularies -----------------------------------------------------------


def test_the_two_spellings_of_noncommercial_are_reported_as_one(tmp_path: Path):
    """AntibioticMech writes NON_COMMERCIAL and CellStructureMech NONCOMMERCIAL.
    Nothing catches it, both are plausible, and a reader comparing the queues
    cannot tell they mean the same thing. Reported as a spelling rather than an
    unknown value, so the message says what to change."""
    findings = check_queue(queue(tmp_path, row(redistribution="NON_COMMERCIAL")))
    assert codes(findings) == ["REDISTRIBUTION_SPELLING"]
    assert "NONCOMMERCIAL" in str(findings[0])


@pytest.mark.parametrize(
    ("column", "value"),
    [("status", "MAYBE"), ("redistribution", "FREE"), ("access", "SOMEHOW"), ("use", "STUFF")],
)
def test_a_value_outside_the_vocabulary_is_reported(tmp_path: Path, column, value):
    assert "UNKNOWN_VALUE" in codes(check_queue(queue(tmp_path, row(**{column: value}))))


def test_priority_is_one_to_five(tmp_path: Path):
    assert "BAD_PRIORITY" in codes(check_queue(queue(tmp_path, row(priority="9"))))
    assert check_queue(queue(tmp_path, row(priority="5"))) == []


def test_a_verification_date_must_be_a_date(tmp_path: Path):
    assert "BAD_VERIFIED_ON" in codes(check_queue(queue(tmp_path, row(verified_on="soon"))))


# -- shape ------------------------------------------------------------------


def test_the_core_is_what_both_queues_already_share():
    assert CORE_COLUMNS == (
        "source_id", "name", "closes_gap", "use", "redistribution", "access",
        "priority", "status", "verified_on", "url", "rationale",
    )


def test_a_missing_core_column_is_reported(tmp_path: Path):
    header = "\t".join(c for c in CORE_COLUMNS if c != "redistribution")
    text = "\t".join(
        v for c, v in zip(CORE_COLUMNS, row().split("\t")) if c != "redistribution"
    )
    assert "MISSING_CORE_COLUMN" in codes(check_queue(queue(tmp_path, text, header=header)))


def test_an_undeclared_column_is_reported(tmp_path: Path):
    header = HEADER + "\tstructures"
    path = queue(tmp_path, row() + "\t3", header=header)
    assert "UNDECLARED_COLUMN" in codes(check_queue(path))
    assert check_queue(path, SourceQueueProfile(extensions=("structures",))) == []


def test_a_repeated_source_id_is_reported(tmp_path: Path):
    assert "DUPLICATE_SOURCE_ID" in codes(check_queue(queue(tmp_path, row(), row())))


def test_a_row_without_a_source_id_is_reported(tmp_path: Path):
    assert "MISSING_SOURCE_ID" in codes(check_queue(queue(tmp_path, row(source_id=""))))


# -- against the two real queues --------------------------------------------

REAL = {
    "antibioticmech": (
        SourceQueueProfile(extensions=("structures",)),
        {"REDISTRIBUTION_SPELLING": 1},
    ),
    "cellstructuremech": (
        SourceQueueProfile(
            extensions=("taxon_link", "item_id", "script"),
            required_when_adopted=("script",),
        ),
        {},
    ),
}


@pytest.mark.parametrize(("mech", "spec"), sorted(REAL.items()))
def test_the_real_queues_report_exactly_what_was_measured(mech, spec):
    """One finding between two well-kept queues, and it is the spelling drift."""
    profile, expected = spec
    try:
        root = resolve_mech_root(mech, claw_root=CLAW_ROOT)
    except MechRootError as exc:
        # AntibioticMech is not a manifest member, so its root cannot resolve at
        # all -- the Tier 1.12 gap the Mech standard names, and the reason the
        # repository that *wrote* this pattern is the one whose queue cannot be
        # checked here. Tracked as CultureBotAI/AntibioticMech#29.
        pytest.skip(f"needs a {mech} checkout: {exc}")
    path = root / "curation/source_queue.tsv"
    if not path.is_file():
        pytest.skip(f"{mech} has no source queue here")
    assert summarise(check_queue(path, profile)) == expected
