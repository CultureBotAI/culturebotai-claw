"""The Mech standard's checkable claims, checked.

#278. The standard states counts as evidence -- "a count is evidence, not an
argument" is its own rule -- and nothing verified them. Two moved within a day
of being derived, because MediaIngredientMech gained two workflows and lost a
skill. Neither change was wrong; the document silently became wrong about them.

What is checkable offline is checked here. Two things are not, and saying which
matters more than the assertions:

* **Numerators that count files in another repository** -- "0 of 48 workflows",
  "14-27 skill files" -- need a checkout per Mech. #278 proposes skipping where
  one is absent. That is the shape #280 had to correct: a per-consumer case
  that skips without a checkout skips in every CI job, so the guard never runs.
  Whatever checks those belongs where the checkouts exist, escalating a missing
  root to a failure rather than a skip.
* **Judgements** -- "TraitMech's copy is the accurate one" -- are not counts and
  should stay prose.

So this covers the denominators, the declared scope, and the one Tier 1 claim
whose evidence lives in claw: membership.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from kg_microbe_fleet import load_fleet_manifest

ROOT = Path(__file__).resolve().parents[1]
STANDARD = ROOT / "docs/guides/MECH_STANDARD.md"

# Named in the document's own opening paragraph as what it was derived from.
# Written out rather than read from the manifest deliberately: the manifest now
# has six members, and the standard is a claim about the five it measured. If
# the derivation is ever widened, this list and the /5 denominators move
# together or the test fails -- which is the coupling #278 is about.
DERIVED_FROM = (
    "CultureMech",
    "MediaIngredientMech",
    "CommunityMech",
    "TraitMech",
    "ProteinTraitsMech",
)
EXCLUDED = ("AntibioticMech", "CellStructureMech")

# A bare N/M. Section references like "1.3/1.4" are not fractions, so a digit
# adjacent to a dot on either side disqualifies the match -- found by this
# guard's own first run, which read "so 1.3/1.4" as three-out-of-one.
_FRACTION = re.compile(r"(?<![\d.])(\d+)/(\d+)(?![\d.])")

# Counts deliberately taken over a set other than the derivation five, each
# with the reason. A ledger rather than a widened rule: the entry records that
# the number is unverified, where a permissive regex would just hide it.
OTHER_SCOPE: dict[str, str] = {
    "4/7": (
        "counts repositories that commit HTML, over the seven Mechs that "
        "existed when it was written. The document never names that set, and "
        "HabitatMech has since begun publishing, so both parts are unverified "
        "(#278)."
    ),
}


def _text() -> str:
    return STANDARD.read_text(encoding="utf-8")


def test_the_standard_names_the_mechs_it_was_derived_from():
    """A count over an unnamed set cannot be rechecked by anyone."""
    opening = _text().split("---", 1)[0]

    missing = [name for name in DERIVED_FROM if name not in opening]
    assert not missing, f"the derivation set is not named up front: {missing}"


def test_the_excluded_mechs_are_named_and_stay_excluded():
    """Letting the repositories under judgement vote would make it circular,
    and that exclusion is only honest while it is stated."""
    opening = _text().split("---", 1)[0]

    for name in EXCLUDED:
        assert name in opening, f"{name} is excluded but the document never says so"
    assert "exclude" in opening.lower()


def test_every_fraction_is_out_of_the_derivation_size():
    """`5/5` is the argument for a Tier 1 requirement. A denominator that does
    not match the set it was measured over makes the claim unreadable -- and
    when the fleet grew to six, `5/5` became ambiguous rather than wrong, which
    is worse: nothing looks broken."""
    size = len(DERIVED_FROM)
    wrong = []
    for line_number, line in enumerate(_text().splitlines(), start=1):
        for numerator, denominator in _FRACTION.findall(line):
            fraction = f"{numerator}/{denominator}"
            if int(denominator) != size:
                if fraction not in OTHER_SCOPE:
                    wrong.append(f"{line_number}: {fraction}")
            elif int(numerator) > int(denominator):
                wrong.append(f"{line_number}: {numerator}/{denominator} exceeds the set")
    assert not wrong, (
        f"every count is over the {size} Mechs the standard was derived from; "
        f"these are not: {wrong}"
    )


def test_the_document_states_how_to_read_a_count():
    body = _text()
    assert "`5/5` means" in body and "evidence, not an argument" in body


@pytest.mark.parametrize("display_name", DERIVED_FROM)
def test_tier_1_12_membership_holds_for_each_derivation_mech(display_name):
    """Tier 1.12 claims 5/5 for manifest membership and consumer registration.

    Unlike the file counts, this claim's evidence is in claw, so it can be
    checked rather than trusted. It is also the row the document itself calls
    the sharpest thing it has to say, after admitting a Mech turned main red.
    """
    manifest = load_fleet_manifest()
    key = display_name.lower()
    assert key in manifest.mechs, f"{display_name} is not a fleet manifest member"

    registry = json.loads(
        (ROOT / "src/kg_microbe_governance/vendored_artifacts.json").read_text(
            encoding="utf-8"
        )
    )
    assert key in registry["consumers"], (
        f"{display_name} is not a registered vendored consumer, so Tier 1.12's "
        f"count no longer holds"
    )


def test_the_standard_records_that_its_counts_rot():
    """The footer's re-check date is the one thing standing between a reader and
    a number nobody has looked at since it was written."""
    body = _text()
    assert re.search(r"re-?check", body, re.IGNORECASE), (
        "the standard no longer says its counts were re-checked, which is the "
        "only signal a reader has about their age (#278)"
    )


def test_every_other_scope_entry_is_still_in_the_document():
    """The ledger shrinks only. When a count is corrected or removed, this
    fails and the entry comes out, rather than a stale exemption outliving the
    claim it was written for."""
    body = _text()
    stale = [fraction for fraction in OTHER_SCOPE if fraction not in body]
    assert not stale, (
        f"these are exempted but no longer appear in the standard: {stale}"
    )
