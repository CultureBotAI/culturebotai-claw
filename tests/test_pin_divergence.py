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

from kg_microbe_governance.fleet_audit import classify_pin_divergence

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


def test_the_pin_step_runs_under_the_trusted_project_interpreter():
    """It imports the governance package now. A bare `python` would raise
    ImportError at the moment the audit decides whether the fleet is
    converged -- caught before pushing, not after."""
    run = _pin_step()["run"]

    assert "uv run --project fleet/trusted-claw python -" in run
