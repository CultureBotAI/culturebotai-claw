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

from collections.abc import Callable, Mapping


def classify_pin_divergence(
    pins: Mapping[str, str],
    is_ancestor: Callable[[str, str], bool],
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

    `is_ancestor` is injected rather than shelling out here so the rule can be
    exercised against constructed histories; a classifier that has only ever
    seen the fleet's real pins is one whose branches have never run.
    """
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
