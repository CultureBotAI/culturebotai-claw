"""Which kind of pin disagreement the fleet is in.

Deliberately a module with **standard-library imports only**.

The audit's pin step runs before anything is installed, and it reads this from
the candidate checkout rather than the trusted one. That is not a weakening:
for a `pull_request` the workflow file itself is the candidate's, so the step's
logic was already candidate-controlled -- a PR that wanted to defeat the check
could simply delete the `raise`. What the trusted checkout protects is the
*audit and install code* a downstream pin selects, and this is neither.

Keeping it importable without a sync is what makes that possible: a heavier
module would need `uv sync` first, and the pin comparison happens before the
audit environment exists.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Mapping


def classify_pin_divergence(
    pins: Mapping[str, str],
    is_ancestor: Callable[[str, str], bool],
    unpinned: Collection[str] = (),
) -> tuple[str, str]:
    """Say which kind of pin disagreement this is, without excusing it.

    #267. The audit's contract is one shared pin and this does not relax it --
    both outcomes below are failures. What it adds is which failure, because
    two situations were being reported identically:

    * **rollout** -- one pin leads and every other is an ancestor of it. That
      is a Mech joining, or the fleet mid-advance: convergent, and the fix is
      to move the rest forward. A Mech cannot join at a pin predating its own
      membership, so this state is unavoidable during an admission, and
      reading it as drift sends someone looking for a mistake nobody made.
    * **drift** -- pins on unrelated commits, or more than one candidate
      leader. Someone has to decide which is right.

    `unpinned` names consumers that committed no pin at all. That is not a
    third kind of disagreement -- it is the *first* half of a rollout, and the
    only state a Mech can be in between claw declaring it a consumer and it
    vendoring, because it cannot pin a ref that does not yet name it. Before
    #309 it was not representable here: the audit read every pin with
    `check=True` and a consumer without one crashed the step with a
    CalledProcessError, so the first Mech to reach this state would have
    replaced the message this function exists to produce with a traceback.

    `is_ancestor` is injected rather than shelling out here so the rule can be
    exercised against constructed histories; a classifier that has only ever
    seen the fleet's real pins is one whose branches have never run.
    """
    kind, message = _classify_pinned(pins, is_ancestor)
    missing = sorted(unpinned)
    if not missing:
        return kind, message
    joined = ", ".join(missing)
    if kind == "converged":
        shared = next(iter(set(pins.values())), "")
        # Deliberately NOT "pin to the ref they all share". A consumer is
        # unpinned precisely because that ref does not declare it, so pinning
        # there asserts an artifact set that predates its membership -- the
        # bytes can be identical while the scoping is not. The target is the
        # commit that declared it, and everyone else advances to that (#314).
        others = (
            f"then advance the {len(pins)} consumer(s) now at {shared[:8]} to "
            f"the same commit" if shared else "which is the fleet's first pin"
        )
        return "rollout", (
            f"fleet rollout in progress, not drift: {joined} has no committed "
            f"claw pin yet, which is the state a Mech is in between claw "
            f"declaring it a consumer and it vendoring. Pin {joined} to the "
            f"claw commit that declares it, {others}"
        )
    return kind, f"{message}; also not yet pinned: {joined}"


def _classify_pinned(
    pins: Mapping[str, str],
    is_ancestor: Callable[[str, str], bool],
) -> tuple[str, str]:
    """The original rule, over consumers that actually committed a pin."""
    unique = set(pins.values())
    if len(unique) <= 1:
        return "converged", ""
    leaders = [
        candidate
        for candidate in sorted(unique)
        if all(is_ancestor(other, candidate) for other in unique)
    ]
    if len(leaders) == 1:
        leader = leaders[0]
        behind = sorted(key for key, pin in pins.items() if pin != leader)
        return "rollout", (
            f"fleet rollout in progress, not drift: {leader[:8]} leads and every "
            f"other pin is an ancestor of it. Advance these to {leader[:8]}: "
            f"{', '.join(behind)}"
        )
    return "drift", f"fleet claw pins differ: {dict(sorted(pins.items()))}"
