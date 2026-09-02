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
    """Whether `relative` is a file on the consumer's origin/main.

    Deliberately `ls-tree` rather than `cat-file -e origin/main:<path>`. The
    audit clones consumers with `--filter=blob:none`, so asking cat-file about
    a blob makes git lazily fetch it over the network -- 0.487s against 0.017s
    per artifact here, and roughly 45s across the fleet. Worse than slow: a
    transient network failure then returns non-zero and is reported as a
    missing artifact, a false red indistinguishable from the real thing this
    guard exists to catch. ls-tree reads trees, which a blobless clone already
    has, so the answer is local and the blob is never downloaded -- and the
    question was only ever whether the path is tracked, not what is in it.

    Checks the object type too: a directory at the artifact's path is not the
    file the manifest asked for.
    """
    result = subprocess.run(
        [
            "git", "-C", str(root), "ls-tree", "-z", "--format=%(objecttype)",
            "origin/main", "--", relative,
        ],
        capture_output=True,
        check=True,
    )
    return result.stdout.replace(b"\0", b"").strip() == b"blob"


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
        "antibioticmech",
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


@pytest.mark.parametrize(
    ("value", "required"),
    [
        ("1", True), ("true", True), ("TRUE", True), ("Yes", True), (" 1 ", True),
        ("0", False), ("false", False), ("no", False), ("", False), ("  ", False),
    ],
    ids=lambda v: repr(v),
)
def test_the_switch_reads_the_values_the_audit_can_set(value, required):
    """#284. This function decides whether the guard fails or skips, and was
    the only new logic in #280 with no test. If it ever returned False while
    the audit set the variable, every per-consumer case would go back to
    skipping and the step would pass having examined nothing -- the state the
    PR exists to end, restored silently.
    """
    assert roots_are_required({ROOTS_REQUIRED_VAR: value}) is required


def test_an_unset_variable_does_not_require_roots():
    """A developer without checkouts still gets the offline assertions."""
    assert roots_are_required({}) is False


def test_the_switch_reads_the_mapping_it_is_given(monkeypatch):
    """The `environ` parameter exists so the rule can be driven without
    touching the process environment -- the injection shape `resolve_mech_root`
    uses. Untested, the parameter's reason for existing is unverified.
    """
    monkeypatch.setenv(ROOTS_REQUIRED_VAR, "1")

    assert roots_are_required({}) is False, "the injected mapping was ignored"
    assert roots_are_required() is True


# --------------------------------------------------------------------------
# #284: the wiring, so deleting the step cannot quietly return the guard to
# running nowhere. Reads the workflow the way test_id_label_workflow.py does.

AUDIT_WORKFLOW = ROOT / ".github/workflows/governance-fleet-audit.yaml"


def _completeness_step() -> dict:
    """The audit step that runs this file, parsed rather than grepped.

    The first version of these three tests asserted substrings against the
    whole file. All three passed while the step was broken: deleting the env
    entry left the variable's name in the comment above it, and deleting the
    export loop left `fleet/$key` in an unrelated --target-root line further
    up. Two guards that could not fail, written to guard against guards that
    cannot fail. Parsing makes the assertions land on the step itself.
    """
    import yaml

    workflow = yaml.safe_load(AUDIT_WORKFLOW.read_text(encoding="utf-8"))
    steps = [step for job in workflow["jobs"].values() for step in job.get("steps", [])]
    named = [s for s in steps if Path(__file__).name in (s.get("run") or "")]
    assert len(named) == 1, (
        f"expected exactly one audit step running {Path(__file__).name}, "
        f"found {len(named)} -- the guard runs nowhere again (#280, #284)"
    )
    return named[0]


def test_the_audit_still_runs_this_file():
    assert _completeness_step()["run"].strip()


def test_the_audit_arms_the_switch_on_that_step():
    """On the step, not merely somewhere in the file: the variable's name also
    appears in the comment explaining it, which is what let the first version
    of this test pass with the env entry deleted."""
    step = _completeness_step()

    assert (step.get("env") or {}).get(ROOTS_REQUIRED_VAR) in ("1", 1, "true", "yes"), (
        f"{ROOTS_REQUIRED_VAR} is not set on the step that runs this file, so a "
        f"consumer whose root fails to resolve is skipped and the step passes "
        f"having checked nothing"
    )


def test_the_audit_exports_a_root_per_consumer_on_that_step():
    """Also on the step. `fleet/$key` appears in an earlier --target-root line,
    which made the whole-file version of this assertion unfalsifiable."""
    run = _completeness_step()["run"]

    assert "_ROOT" in run, "the step no longer derives a <KEY>_ROOT name"
    assert "fleet/$key" in run, (
        "the step no longer points each root at the consumer's clone"
    )
    assert "export" in run, "the derived names are never exported"
