"""Every declared vendored consumer must actually carry what it declares.

#257. Adding `cellstructuremech` to `vendored_artifacts.json`'s `consumers`
turned claw's `main` red, and nothing caught it until after the merge: the CI
fleet audit clones each consumer and reads its committed pin, so it can only
fail once the declaration has landed.

The trap is sharper than "declare before vendoring". Admitting a consumer can
*require* rescoping an artifact -- `test_provider_triage_contract.py` had to
stop applying to "all" before a Mech with no research provider could join -- and
that rescoping advances claw's canonical ref, which invalidates every existing
consumer's pin. So admitting a Mech is a fleet-wide re-pin, not a
single-repository adoption, and the audit requires all pins to be identical.

This asks the cheap half offline: does each consumer's `origin/main` track every
artifact the manifest says applies to it? Read from git rather than the working
tree, because a checkout sits on whatever branch its owner is using -- the same
correction #256 made for capability reasons.

**Where this runs.** Needing a checkout per consumer made every per-consumer
case skip wherever there are none, which is every CI job: `tests.yaml` sets no
roots, and the governance audit ran four named test files that did not include
this one. So the guard written to catch #257 before a merge had never once
executed its failure path anywhere (#209, #216).

The governance audit already clones every consumer to `fleet/<key>`, so it now
runs this file with those roots and with FLEET_CONSUMER_ROOTS_REQUIRED set.
That variable is what makes the difference between a guard and a decoration:
with it, a consumer whose root will not resolve is a failure rather than a
silent skip, so the audit cannot pass by checking nothing.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Mapping
from pathlib import Path

import pytest

from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_fleet.roots import MechRootError, resolve_mech_root

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = json.loads(
    (ROOT / "src/kg_microbe_governance/vendored_artifacts.json").read_text(
        encoding="utf-8"
    )
)

# Consumers known to be mid-adoption, with the reason. A ledger rather than a
# skip: it fails in both directions, so the list can only shrink. When a
# repository finishes vendoring, this test says so and the entry comes out.
INCOMPLETE_CONSUMERS: dict[str, str] = {
    # Empty, and that is the point: entries leave this list because the test
    # below fails when a repository becomes complete. CellStructureMech left it
    # when CultureBotAI/CellStructureMech#53 merged, and CultureMech,
    # MediaIngredientMech and ProteinTraitsMech left it when they vendored
    # scripts/deep_research_contract.py (#270).
}


def _applicable(consumer: str) -> list[str]:
    """Every artifact target the manifest says this consumer owes."""
    package_path = MANIFEST["consumers"][consumer]["package_path"]
    targets = []
    for artifact in MANIFEST["artifacts"]:
        scope = artifact.get("consumers")
        if scope == "all" or (isinstance(scope, list) and consumer in scope):
            targets.append(artifact["target"].replace("{package_path}", package_path))
    return targets


def _tracked_on_main(root: Path, relative: str) -> bool:
    return (
        subprocess.run(
            ["git", "-C", str(root), "cat-file", "-e", f"origin/main:{relative}"],
            capture_output=True,
        ).returncode
        == 0
    )


ROOTS_REQUIRED_VAR = "FLEET_CONSUMER_ROOTS_REQUIRED"


def roots_are_required(environ: Mapping[str, str] | None = None) -> bool:
    """Whether an unresolvable consumer root is a failure rather than a skip.

    Set wherever the caller has arranged the checkouts -- the governance audit
    clones all six. Anywhere else, a developer without roots still gets the
    offline assertions and skips the rest.
    """
    env = os.environ if environ is None else environ
    return (env.get(ROOTS_REQUIRED_VAR) or "").strip().lower() in {"1", "true", "yes"}


def _unavailable(consumer: str, reason: str) -> None:
    """Skip, or fail if this environment promised the roots would be there."""
    if roots_are_required(None):
        pytest.fail(
            f"{ROOTS_REQUIRED_VAR} is set, so every declared consumer must be "
            f"resolvable, but {consumer} is not: {reason}. This check exists to "
            f"stop the audit passing while silently examining nothing."
        )
    pytest.skip(f"needs a {consumer} checkout: {reason}")


def _missing(consumer: str) -> list[str]:
    try:
        root = resolve_mech_root(consumer, claw_root=ROOT)
    except MechRootError as exc:
        _unavailable(consumer, str(exc))
    if (
        subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--verify", "--quiet", "origin/main"],
            capture_output=True,
        ).returncode
        != 0
    ):
        _unavailable(consumer, "no origin/main to read")
    return [t for t in _applicable(consumer) if not _tracked_on_main(root, t)]


CONSUMERS = sorted(MANIFEST["consumers"])


def test_the_manifest_declares_the_consumers_the_fleet_expects():
    """Offline, so it runs everywhere. Names the set rather than counting it."""
    assert CONSUMERS == [
        "cellstructuremech",
        "communitymech",
        "culturemech",
        "mediaingredientmech",
        "proteintraitsmech",
        "traitmech",
    ]


def bad_scopes(manifest: dict) -> list[str]:
    """Artifacts whose `consumers` names something that is not a consumer.

    Extracted so the rule can be exercised against a manifest that breaks it.
    Asserting it only against the shipped manifest is a guard that has never run
    its failure path, and would not run it until the day it mattered (#216).
    """
    known = set(manifest["consumers"])
    problems = []
    for artifact in manifest["artifacts"]:
        scope = artifact.get("consumers")
        if scope == "all":
            continue
        if not isinstance(scope, list) or not scope:
            problems.append(f"{artifact['id']}: scope is not a non-empty list")
            continue
        unknown = sorted(set(scope) - known)
        if unknown:
            problems.append(f"{artifact['id']}: unknown consumers {unknown}")
    return problems


def test_every_artifact_scopes_itself_to_known_consumers():
    """A typo in an artifact's `consumers` list silently exempts every
    repository from it, which reads exactly like a deliberate narrowing."""
    assert bad_scopes(MANIFEST) == []


@pytest.mark.parametrize(
    ("scope", "expected"),
    [
        (["culturemech", "cellstructuremesh"], "unknown consumers ['cellstructuremesh']"),
        ([], "scope is not a non-empty list"),
        ("some", "scope is not a non-empty list"),
        (["culturemech"], None),
        ("all", None),
    ],
    ids=["typo", "empty", "wrong-type", "valid-subset", "all"],
)
def test_the_scope_rule_catches_what_it_is_for(scope, expected):
    manifest = {
        "consumers": {name: {} for name in CONSUMERS},
        "artifacts": [{"id": "probe", "consumers": scope}],
    }
    problems = bad_scopes(manifest)
    if expected is None:
        assert problems == []
    else:
        assert len(problems) == 1 and expected in problems[0]


@pytest.mark.parametrize("consumer", CONSUMERS)
def test_a_declared_consumer_carries_every_artifact_that_applies_to_it(consumer):
    missing = _missing(consumer)
    if consumer in INCOMPLETE_CONSUMERS:
        pytest.skip(f"{consumer} is a known-incomplete consumer")
    assert not missing, (
        f"{consumer} is declared a vendored consumer but its origin/main does "
        f"not track {len(missing)} artifact(s) that apply to it: {missing}. "
        f"Either it has not finished vendoring -- in which case claw declared "
        f"the consumer too early -- or the artifact should not apply to it."
    )


@pytest.mark.parametrize("consumer", sorted(INCOMPLETE_CONSUMERS))
def test_a_known_incomplete_consumer_is_still_incomplete(consumer):
    """The other direction, so the ledger can only shrink. When the repository
    finishes vendoring, this fails and the entry comes out -- rather than a
    stale exemption quietly outliving the problem it was written for."""
    missing = _missing(consumer)
    assert missing, (
        f"{consumer} now tracks every artifact that applies to it, so remove it "
        f"from INCOMPLETE_CONSUMERS ({INCOMPLETE_CONSUMERS[consumer]})"
    )


def test_each_consumers_env_var_is_the_name_the_audit_derives():
    """The governance audit exports one root per consumer with a shell
    uppercase of the manifest key:

        var="$(printf '%s' "$key" | tr '[:lower:]' '[:upper:]')_ROOT"

    which is a second, silent definition of a name the manifest already states.
    If a future Mech's `environment_variable` does not follow that pattern, the
    audit exports a name nothing reads. FLEET_CONSUMER_ROOTS_REQUIRED makes that
    loud rather than silent, but a failing audit is a poor way to learn it --
    so the coupling is asserted here, where the fix is obvious.
    """
    manifest = load_fleet_manifest()
    mismatched = {
        key: manifest.mechs[key].environment_variable
        for key in CONSUMERS
        if manifest.mechs[key].environment_variable != f"{key.upper()}_ROOT"
    }
    assert not mismatched, (
        "the audit derives <KEY>_ROOT by uppercasing the manifest key, but "
        f"these declare something else: {mismatched}. Either rename them or "
        "make the workflow read environment_variable from the manifest."
    )
