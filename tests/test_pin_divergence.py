"""Which kind of pin disagreement, said out loud.

#267. The audit's contract is one shared pin, and this does not relax it: both
outcomes here are failures. What was missing is which failure.

A Mech cannot join at a pin that predates its own membership -- verified in
#267 by reading `vendored_artifacts.json` at the older ref, which does not know
the newcomer -- so "one Mech ahead, everyone else behind" is unavoidable during
an admission. Reporting it as drift sends someone looking for a mistake nobody
made, which is what happened in #257.
"""

from __future__ import annotations

import pytest

from kg_microbe_governance.pin_divergence import classify_pin_divergence

# A linear history: OLD -> MID -> NEW.
OLD, MID, NEW = "a" * 40, "b" * 40, "c" * 40
UNRELATED = "d" * 40
_ORDER = {OLD: 0, MID: 1, NEW: 2}


def linear(older: str, newer: str) -> bool:
    """Ancestry on that line; anything off it is unrelated in both directions."""
    if older not in _ORDER or newer not in _ORDER:
        return False
    return _ORDER[older] <= _ORDER[newer]


def test_one_shared_pin_is_converged():
    kind, message = classify_pin_divergence({"a": OLD, "b": OLD}, linear)

    assert kind == "converged"
    assert message == ""


def test_a_newcomer_ahead_of_the_fleet_is_a_rollout():
    """CellStructureMech's admission exactly: five at one ref, the newcomer at
    the commit that declared it."""
    pins = {"culturemech": OLD, "traitmech": OLD, "cellstructuremech": NEW}

    kind, message = classify_pin_divergence(pins, linear)

    assert kind == "rollout"
    assert "leads" in message
    assert "culturemech, traitmech" in message
    assert "cellstructuremech" not in message.split("Advance these")[1]


def test_pins_on_unrelated_commits_are_drift():
    """No candidate leads, so nobody can say which is right by ancestry."""
    kind, message = classify_pin_divergence({"a": OLD, "b": UNRELATED}, linear)

    assert kind == "drift"
    assert "pins differ" in message


def test_two_candidate_leaders_are_drift_not_a_rollout():
    """If two pins each descend from everything else, advancing "the rest" is
    ambiguous -- there is no single target."""

    def everything_descends(older: str, newer: str) -> bool:
        return True

    kind, _ = classify_pin_divergence({"a": OLD, "b": MID}, everything_descends)

    assert kind == "drift"


def test_a_three_step_rollout_names_only_the_ones_behind():
    """Partial rollouts are the normal mid-flight state: some advanced, some
    not. The message must name the ones still to move, not all of them."""
    pins = {"a": OLD, "b": MID, "c": NEW}

    kind, message = classify_pin_divergence(pins, linear)

    assert kind == "rollout"
    behind = message.split("Advance these to")[1]
    assert "a" in behind and "b" in behind


# --------------------------------------------------------------------------
# The wiring, so the classifier cannot end up unreachable (#284).

from pathlib import Path  # noqa: E402

AUDIT = Path(__file__).resolve().parents[1] / ".github/workflows/governance-fleet-audit.yaml"


def _pin_step() -> dict:
    import yaml

    workflow = yaml.safe_load(AUDIT.read_text(encoding="utf-8"))
    steps = [s for job in workflow["jobs"].values() for s in job.get("steps", [])]
    named = [s for s in steps if s.get("id") == "fleet-pin"]
    assert len(named) == 1, "expected exactly one fleet-pin step"
    return named[0]


def test_the_audit_classifies_rather_than_comparing_pins_itself():
    assert "classify_pin_divergence" in _pin_step()["run"]


def test_the_pin_step_reads_the_classifier_from_the_candidate_checkout():
    """fleet/trusted-claw is the PR base commit by design, so a function this
    PR adds does not exist there. Importing from it failed on the very PR that
    added it -- and always would have. Caught by CI, not by me."""
    run = _pin_step()["run"]

    assert "PYTHONPATH=control/src python -" in run, (
        "the classifier must come from the candidate checkout; trusted-claw is "
        "the PR base commit, so a function this PR adds is not there"
    )
    assert "uv run --project fleet/trusted-claw python -" not in run


def test_a_consumer_with_no_pin_at_all_is_a_rollout_not_a_crash():
    """#309, AntibioticMech's admission. Between claw declaring a consumer and
    that Mech vendoring, it has committed no pin file -- it cannot pin a ref
    that does not yet name it. The audit used to read every pin with
    `check=True`, so this state raised CalledProcessError and the operator saw
    a traceback instead of the message #267 exists to give."""
    pins = {"culturemech": OLD, "traitmech": OLD}

    kind, message = classify_pin_divergence(pins, linear, ["antibioticmech"])

    assert kind == "rollout"
    assert "antibioticmech" in message
    assert "no committed claw pin yet" in message
    assert OLD[:8] in message


def test_an_unpinned_consumer_does_not_hide_real_drift():
    """The distinction that matters: unpinned is the benign half of a rollout,
    but it must not downgrade a genuine disagreement among the pins that exist.
    Both facts are reported."""
    pins = {"culturemech": OLD, "traitmech": UNRELATED}

    kind, message = classify_pin_divergence(pins, linear, ["antibioticmech"])

    assert kind == "drift"
    assert "antibioticmech" in message
    assert "differ" in message


def test_the_first_consumer_of_all_has_nothing_to_pin_to():
    """No pinned consumer to name a target, so the message must not offer a
    truncated empty string as the ref to advance to."""
    kind, message = classify_pin_divergence({}, linear, ["antibioticmech"])

    assert kind == "rollout"
    assert "the fleet's first pin" in message
    assert "advance the 0 consumer" not in message


def test_no_unpinned_consumers_leaves_the_original_rule_untouched():
    """The default keeps every existing caller and outcome identical."""
    pins = {"culturemech": OLD, "cellstructuremech": NEW}

    assert classify_pin_divergence(pins, linear) == classify_pin_divergence(
        pins, linear, []
    )


def test_the_pin_step_hands_the_unpinned_consumers_to_the_classifier():
    """The classifier can only report what the step passes it. Asserted on the
    call itself rather than on the word appearing somewhere in the step, since
    the step also explains the case in a comment -- a substring match would
    pass on the explanation alone."""
    run = _pin_step()["run"]

    assert "classify_pin_divergence(pins, is_ancestor, unpinned)" in run


def test_the_pin_step_does_not_read_a_missing_pin_with_check_true():
    """A consumer that has not vendored yet has no pin file. `git show` on it
    exits nonzero, so reading it with check=True raises before the classifier
    is reached. The step must test existence first."""
    run = _pin_step()["run"]
    probe = 'cat-file", "-e", f"HEAD:{pin_path}"'

    assert probe in run, "the step must probe for the pin before reading it"
    assert run.index(probe) < run.index('"show", f"HEAD:{pin_path}"')


@pytest.mark.parametrize(
    "pins,unpinned",
    [
        ({"a": OLD, "b": NEW}, []),
        ({"a": OLD, "b": UNRELATED}, []),
        ({"a": OLD, "b": OLD}, ["c"]),
        ({"a": OLD, "b": UNRELATED}, ["c"]),
        ({}, ["c"]),
    ],
)
def test_no_message_ends_with_a_period(pins, unpinned):
    """The audit appends ". Pins: {...}" to whatever this returns, so a message
    ending in a period renders as "that.. Pins:". Asserted here rather than
    patched at the call site because logic in a workflow cannot be tested."""
    _kind, message = classify_pin_divergence(pins, linear, unpinned)

    assert not message.endswith("."), message


def test_the_rollout_message_does_not_send_a_newcomer_to_the_shared_ref():
    """#314. The advice matters more than the classification. A consumer is
    unpinned because the ref the others share does not declare it -- pinning
    there asserts an artifact set predating its membership, which is a trap I
    have already fallen into once: identical artifact bytes, different scoping.
    The target is the commit that declared it."""
    pins = {"culturemech": OLD, "traitmech": OLD}

    _kind, message = classify_pin_divergence(pins, linear, ["antibioticmech"])

    assert "claw commit that declares it" in message
    assert f"so pin antibioticmech to {OLD[:8]}" not in message
    assert "advance" in message
