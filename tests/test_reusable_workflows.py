"""Contracts a reusable workflow must hold before any Mech calls it.

#132 Phase 5 / #180. A `workflow_call` workflow is only executed by a caller,
so claw's own CI cannot run this one -- the canary is the first Mech to adopt
it, and until then the only thing claw can check is the file's shape. These
tests are therefore deliberately about structure, not behaviour, and they say
so rather than implying the workflow has been proven.

What they do catch is the class of defect that would break every caller at
once: an unpinned action, an input the callers rely on going missing, a
default that silently changes what a Mech runs.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "label-correspondence-reusable.yaml"

# yaml parses the bare `on:` key as the boolean True.
ON = True


@pytest.fixture(scope="module")
def workflow() -> dict:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def test_it_is_callable(workflow):
    assert "workflow_call" in workflow[ON], (
        "a reusable workflow is reached through workflow_call; without it every "
        "caller fails to resolve the reference"
    )


def test_the_inputs_callers_depend_on_exist(workflow):
    """Removing one breaks every Mech at once, and the failure surfaces in the
    caller's repository rather than here."""
    inputs = workflow[ON]["workflow_call"]["inputs"]
    assert set(inputs) >= {
        "python-version",
        "prepare-recipe",
        "drift-report-recipe",
        "enforce-recipe",
        "drift-report-path",
    }


def test_python_version_is_required_and_the_rest_are_not(workflow):
    """The Mechs run 3.10 to 3.12, so there is no defensible default -- guessing
    one would silently run a gate under the wrong interpreter. Everything else
    has a working default so a plain corpus needs three lines to adopt this."""
    inputs = workflow[ON]["workflow_call"]["inputs"]

    assert inputs["python-version"]["required"] is True
    assert "default" not in inputs["python-version"]
    for name, spec in inputs.items():
        if name == "python-version":
            continue
        assert spec.get("required") is False, name
        assert "default" in spec, name


def test_the_prepare_step_is_skipped_when_no_recipe_is_given(workflow):
    """A Mech whose corpus is already on disk passes nothing; `just ''` would
    fail the build for a step it never asked for."""
    steps = workflow["jobs"]["label-correspondence"]["steps"]
    prepare = next(s for s in steps if s.get("name", "").startswith("Build the product"))

    assert prepare["if"] == "inputs.prepare-recipe != ''"


def test_the_drift_report_is_uploaded_even_when_the_gate_fails(workflow):
    """The artifact is triage material. Uploading it only on success would
    withhold it from exactly the runs that need it -- the same shape as #164.

    Asserts the requirement rather than the literal condition. #299 added
    `&& inputs.report-when == 'always'`, which narrows *which mode* this step
    belongs to without weakening the guarantee inside that mode: `always()` is
    still what makes it survive a failing gate. Pinning the exact string would
    have failed on a change that keeps the property intact.
    """
    steps = workflow["jobs"]["label-correspondence"]["steps"]
    upload = next(s for s in steps if s.get("name") == "Upload drift report")

    assert upload["if"].startswith("always()"), (
        "the upload no longer survives a failing gate"
    )


def test_the_report_is_generated_before_the_gate_runs(workflow):
    """CultureMech generated it only on failure, which loses the passing-run
    baseline a reader compares a regression against."""
    names = [s.get("name", "") for s in workflow["jobs"]["label-correspondence"]["steps"]]

    assert names.index("Generate id-label drift report") < names.index(
        "Enforce id-label correspondence"
    )


@pytest.mark.parametrize(
    "step",
    [
        s
        for s in yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))["jobs"][
            "label-correspondence"
        ]["steps"]
        if "uses" in s
    ],
    ids=lambda s: s["uses"].split("@")[0],
)
def test_every_action_is_pinned_to_a_commit(step):
    """A tag is mutable. This workflow runs in five repositories, so a
    compromised or merely changed tag would move under all of them at once."""
    _, _, ref = step["uses"].partition("@")

    assert re.fullmatch(r"[0-9a-f]{40}", ref), (
        f"{step['uses']} is not pinned to a full commit SHA"
    )


def test_the_permissions_are_read_only(workflow):
    assert workflow["permissions"] == {"contents": "read"}


def test_the_file_says_it_is_unproven_until_a_mech_calls_it():
    """CLAUDE.md forbids describing an experimental path as implemented because
    a configuration file exists. A reusable workflow with no caller is exactly
    that, and the header has to say so."""
    header = WORKFLOW.read_text(encoding="utf-8").split("name:")[0]

    assert "only exercised by a caller" in header or "proves nothing" in header


def test_a_caller_can_keep_its_frozen_lockfile(workflow):
    """CultureMech and MediaIngredientMech run `uv sync --frozen`, which refuses
    to update the lockfile. Hard-coding a bare `uv sync` here would silently
    drop that hardening the moment either adopted this workflow -- they would
    have to choose between the shared gate and their own resolution guarantee.
    """
    inputs = workflow[True]["workflow_call"]["inputs"]
    assert "uv-sync-args" in inputs
    assert inputs["uv-sync-args"]["default"] == "", (
        "empty by default: TraitMech and CommunityMech run a plain uv sync, and "
        "a default of --frozen would change what they do on adoption"
    )

    steps = workflow["jobs"]["label-correspondence"]["steps"]
    install = next(s for s in steps if s.get("name") == "Install dependencies")
    assert install["run"] == "uv sync ${{ inputs.uv-sync-args }}"


# --------------------------------------------------------------------------
# #299: report-when preserves a recorded per-Mech cost decision.

REUSABLE = ROOT / ".github/workflows/label-correspondence-reusable.yaml"


def _reusable() -> dict:
    import yaml

    document = yaml.safe_load(REUSABLE.read_text(encoding="utf-8"))
    # PyYAML parses the bare `on:` key as the boolean True.
    return document[True] if True in document else document["on"]


def _reusable_steps() -> list[dict]:
    import yaml

    document = yaml.safe_load(REUSABLE.read_text(encoding="utf-8"))
    return document["jobs"]["label-correspondence"]["steps"]


def test_report_when_defaults_to_always():
    """TraitMech and MediaIngredientMech report unconditionally today. A
    default of `failure` would silently take their passing-run baseline away."""
    inputs = _reusable()["workflow_call"]["inputs"]

    assert inputs["report-when"]["default"] == "always"
    assert inputs["report-when"]["required"] is False


def test_both_orderings_exist_because_a_condition_cannot_reorder_steps():
    """`always` reports before the gate; `failure` reports after it. That is a
    difference in order, not in condition, so the workflow carries both and
    skips one. A single guarded step could not express it."""
    names = [step.get("name", "") for step in _reusable_steps()]

    before = names.index("Generate id-label drift report")
    gate = names.index("Enforce id-label correspondence")
    after = names.index("Generate id-label drift report (on failure)")

    assert before < gate < after


def test_each_report_path_is_guarded_by_the_mode_it_belongs_to():
    """Without the mode guard, `failure` mode would still pay the second
    validator pass on every green run -- the ~6 minutes #299 is about -- while
    appearing to have adopted the cheaper behaviour."""
    steps = {step.get("name", ""): step for step in _reusable_steps()}

    assert steps["Generate id-label drift report"]["if"] == (
        "inputs.report-when == 'always'"
    )
    assert "inputs.report-when == 'always'" in steps["Upload drift report"]["if"]

    on_failure = steps["Generate id-label drift report (on failure)"]["if"]
    assert "failure()" in on_failure and "inputs.report-when == 'failure'" in on_failure


def test_the_failure_upload_cannot_run_on_a_green_run():
    """`always()` on this one would upload a report the failure path never
    generated, and report success doing it."""
    steps = {step.get("name", ""): step for step in _reusable_steps()}

    condition = steps["Upload drift report (on failure)"]["if"]

    assert condition.startswith("failure()")
    assert "always()" not in condition


# --------------------------------------------------------------------------
# #302: a fixed cache key freezes the ontology snapshot forever.

def test_the_oak_cache_key_rotates():
    """CommunityMech#707: with a fixed key the post-step reports "Cache hit
    occurred on the primary key ..., not saving cache" in every run, so
    whatever was stored first can never be replaced. A gate that resolves terms
    through OAK then answers from a snapshot nobody can refresh."""
    steps = {step.get("name", ""): step for step in _reusable_steps()}

    assert "Ontology cache stamp" in steps, "nothing rotates the key"
    key = steps["Cache OAK ontologies"]["with"]["key"]

    assert "oak-cache-stamp" in key, f"the cache key does not rotate: {key}"


def test_the_cache_falls_back_to_the_previous_period():
    """Rotation without a prefix restore-key would miss on the first run of
    every month and re-download every ontology."""
    cache = {s.get("name", ""): s for s in _reusable_steps()}["Cache OAK ontologies"]

    restore = [line.strip() for line in cache["with"]["restore-keys"].splitlines() if line.strip()]

    assert restore, "no restore-key: every month starts cold"
    assert restore[0].startswith("oaklib-${{ runner.os }}-")


def test_no_restore_key_can_defeat_the_manual_bust():
    """Found verifying #302 by hand, against my own first version.

    restore-keys are tried in order. A broader `oaklib-<os>-` fallback looks
    like a harmless extra safety net and is not: bumping oak-cache-key to v2
    misses `oaklib-<os>-v2-` and then matches the v1 entry it was bumped to
    escape, so the bust silently does nothing.

    Every restore-key must therefore carry the bust. The earlier test asserted
    only that the *first* one did, which is the adjacent question.
    """
    cache = {s.get("name", ""): s for s in _reusable_steps()}["Cache OAK ontologies"]

    restore = [line.strip() for line in cache["with"]["restore-keys"].splitlines() if line.strip()]

    bustless = [key for key in restore if "inputs.oak-cache-key" not in key]
    assert not bustless, (
        f"these restore-keys would match a cache the bust was meant to "
        f"discard: {bustless}"
    )


def test_the_manual_bust_still_works():
    """`oak-cache-key` becomes a component rather than the whole key, so
    bumping it must still discard a poisoned cache -- which means it has to
    appear in the primary key AND in the narrower restore-key, or a bumped
    value would restore the very entry it was bumped to escape."""
    cache = {s.get("name", ""): s for s in _reusable_steps()}["Cache OAK ontologies"]

    assert "inputs.oak-cache-key" in cache["with"]["key"]
    narrower = [
        line.strip()
        for line in cache["with"]["restore-keys"].splitlines()
        if line.strip()
    ][0]
    assert "inputs.oak-cache-key" in narrower, (
        "the first restore-key must include the bust, or bumping it restores "
        "the cache it was bumped to escape"
    )
