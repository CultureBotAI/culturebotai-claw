"""Offline contract for claw's workflow scripts (`.claude/workflows/*.js`).

A workflow run spawns billed, non-deterministic agents, so nothing here makes
one. `tests/workflow_harness.mjs` runs a script against stubbed runtime hooks
with scripted agent responses and reports what the script did. That is enough
to check what the runtime requires of a script (a pure-literal `meta`, phases
that match, no clock or randomness), and what `dynamic-review.js` promises: a
stage whose agent returned nothing is never reported as a clean result (#529).

Node is required. Locally the module skips without it; in CI it fails, because
a gate that skips where it runs is not a gate.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".claude" / "workflows"
HARNESS = ROOT / "tests" / "workflow_harness.mjs"
SCRIPTS = sorted(WORKFLOWS.glob("*.js"))
DYNAMIC_REVIEW = WORKFLOWS / "dynamic-review.js"
NODE = shutil.which("node")


@pytest.fixture(scope="module", autouse=True)
def _node_available() -> None:
    if NODE is None:
        if os.environ.get("CI"):
            pytest.fail("node is not installed; the workflow-script contract cannot run")
        pytest.skip("node is not installed")


def _harness(*args: str) -> dict:
    assert NODE is not None
    completed = subprocess.run(
        [NODE, str(HARNESS), *args], capture_output=True, text=True, timeout=60, check=False
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def run(script: Path, scenario: dict) -> dict:
    return _harness("run", str(script), json.dumps(scenario))


def test_there_are_scripts_to_check() -> None:
    """Guards every parametrization below: an empty glob would pass silently."""
    assert DYNAMIC_REVIEW in SCRIPTS


# --------------------------------------------------------------------------
# What the runtime requires of every script
# --------------------------------------------------------------------------


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_meta_is_a_pure_literal_naming_the_file(script: Path) -> None:
    probe = _harness("meta", str(script))
    literal = re.sub(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"", "''", probe["literal"])
    assert "${" not in literal and "..." not in literal and "`" not in literal
    assert not re.search(r"[A-Za-z_$][\w$]*\s*\(", literal), "meta must not call anything"
    assert probe["meta"]["name"] == script.stem
    assert probe["meta"]["description"].strip()


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_declared_phases_are_exactly_the_phases_the_script_opens(script: Path) -> None:
    probe = _harness("meta", str(script))
    declared = [phase["title"] for phase in probe["meta"].get("phases", [])]
    assert set(declared) == set(probe["phaseCalls"])


FORBIDDEN = {
    "Date.now()": r"\bDate\.now\b",
    "Math.random()": r"\bMath\.random\b",
    "argument-less new Date()": r"\bnew\s+Date\s*\(\s*\)",
    "require()": r"\brequire\s*\(",
    "an import statement": r"^\s*import\s",
    "process": r"\bprocess\.",
    "setTimeout()": r"\bsetTimeout\s*\(",
    "fetch()": r"\bfetch\s*\(",
}


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
@pytest.mark.parametrize("name", FORBIDDEN)
def test_no_clock_randomness_or_host_access(script: Path, name: str) -> None:
    """The runtime replays a journal on resume, so a script must be deterministic,
    and it has no filesystem or network of its own."""
    assert not re.search(FORBIDDEN[name], script.read_text(encoding="utf-8"), re.M), (
        f"{script.name} uses {name}"
    )


# --------------------------------------------------------------------------
# dynamic-review.js: a failed stage is never a clean result (#529)
# --------------------------------------------------------------------------

SCOPE = {
    "nothingToReview": False,
    "repo": "/tmp/repo",
    "repoName": "repo",
    "ownerRepo": "CultureBotAI/example",
    "prNumber": 7,
    "headSha": "a" * 40,
    "diffCmd": "gh pr diff 7",
    "files": [{"path": "src/a.py", "lang": "python", "group": "src", "status": "M"}],
    "repoProfile": {"qcRecipes": ["test"], "schemaPath": None, "rootClass": None, "conventions": ["c"]},
    "dimensions": [{"key": "bugs", "guidance": "g"}, {"key": "conventions", "guidance": "g"}],
}


def _finding(title: str, dimension: str, severity: str) -> dict:
    return {"file": "src/a.py", "line": 3, "severity": severity, "dimension": dimension,
            "title": title, "rationale": "because", "suggestedFix": None}


RESPONSES = {
    "scope": SCOPE,
    "static-gate": {"ran": ["test"], "skipped": [], "failures": []},
    "review:bugs": {"findings": [_finding("Bug A", "bugs", "high")]},
    "review:conventions": {"findings": [_finding("Convention B", "conventions", "low")]},
    "verify:": {"refuted": False, "reason": "holds"},
    "synthesize": {"markdown": "# Review", "posted": False, "postedCount": 0,
                   "counts": {"critical": 0, "high": 1, "medium": 0, "low": 1, "gateFailures": 0}},
}
# scope, gate, two reviewers, one verifier per finding at standard depth, synthesis
NOMINAL_CALLS = 7


def review(**scenario) -> dict:
    scenario.setdefault("responses", RESPONSES)
    out = run(DYNAMIC_REVIEW, scenario)
    assert out["ok"], out.get("error") or out["unscripted"]
    return out


def test_a_nominal_review_is_complete_and_not_degraded() -> None:
    out = review()
    result = out["result"]
    assert len(out["calls"]) == NOMINAL_CALLS
    assert result["status"] == "complete" and result["degraded"] is False
    assert result["failedStages"] == []
    assert result["confirmedFindings"] == 2 and result["undecidedFindings"] == 0


def test_every_scripted_response_satisfies_the_schema_it_answers() -> None:
    """Fixtures that drift from the script's schemas would test a script that
    cannot exist; the runtime validates structured output against these."""
    for call in review()["calls"]:
        schema = call["schema"]
        jsonschema.validators.validator_for(schema).check_schema(schema)
        assert schema["type"] == "object"
        assert set(schema.get("required", [])) <= set(schema["properties"])
        response = next(v for k, v in sorted(RESPONSES.items(), key=lambda kv: -len(kv[0]))
                        if call["label"].startswith(k))
        jsonschema.validate(response, schema)


@pytest.mark.parametrize("index", range(NOMINAL_CALLS))
def test_any_agent_returning_nothing_marks_the_review_degraded(index: int) -> None:
    result = review(nullCalls=[index])["result"]
    assert result["degraded"] is True, f"agent #{index} failed and the review still reads clean"
    assert result["status"] != "complete"


def test_a_failed_scope_is_a_failure_not_nothing_to_review() -> None:
    failed = review(nullLabels=["scope"])["result"]
    empty = review(responses={**RESPONSES, "scope": {**SCOPE, "nothingToReview": True, "files": []}})["result"]
    assert failed["status"] == "failed" and failed["degraded"] is True
    assert "Nothing to review" not in failed["summary"]
    assert empty["status"] == "nothing-to-review" and empty["degraded"] is False


def test_a_gate_that_did_not_run_is_not_a_clean_gate() -> None:
    result = review(nullLabels=["static-gate"])["result"]
    assert result["gateStatus"] == "did-not-run"
    assert "static-gate" in result["failedStages"]


def test_a_finding_whose_verifiers_all_failed_is_unverified_not_confirmed() -> None:
    result = review(nullLabels=["verify:"])["result"]
    assert result["confirmedFindings"] == 0
    assert result["undecidedFindings"] == 2
    assert result["degraded"] is True


def test_quick_depth_findings_are_reported_unverified() -> None:
    out = review(args={"depth": "quick"})
    result = out["result"]
    assert not [c for c in out["calls"] if c["label"].startswith("verify:")]
    assert result["confirmedFindings"] == 0 and result["undecidedFindings"] == 2
    assert result["degraded"] is False, "quick depth skips verification on purpose"


def test_an_evenly_divided_vote_is_split_not_refuted() -> None:
    kept, refuted = {"refuted": False, "reason": "holds"}, {"refuted": True, "reason": "no"}
    responses = {**RESPONSES, "review:conventions": {"findings": []},
                 "verify:": {"sequence": [kept, refuted, refuted]}}
    # thorough depth asks three verifiers; the third returns nothing, leaving 1-1
    out = review(args={"depth": "thorough"}, responses=responses, nullCalls=[5])
    result = out["result"]
    assert result["confirmedFindings"] == 0 and result["refutedFindings"] == 0
    assert result["undecidedFindings"] == 1


def test_a_failed_synthesis_keeps_the_verified_findings() -> None:
    result = review(nullLabels=["synthesize"])["result"]
    assert "synthesize" in result["failedStages"]
    assert "Bug A" in result["report"] and "Convention B" in result["report"]


def test_caller_context_and_exclusions_reach_every_agent() -> None:
    out = review(args={"context": "CTX-MARKER pinned at 0123abc", "exclude": ["#507 EXCL-MARKER"]})
    for call in out["calls"]:
        assert "CTX-MARKER" in call["prompt"] and "EXCL-MARKER" in call["prompt"], call["label"]


def test_an_incomplete_review_is_never_posted() -> None:
    complete = review(args={"postComments": True})
    degraded = review(args={"postComments": True}, nullLabels=["review:bugs"])
    prompt = {out_id: next(c["prompt"] for c in out["calls"] if c["label"] == "synthesize")
              for out_id, out in (("complete", complete), ("degraded", degraded))}
    assert "THEN post to the PR" in prompt["complete"]
    assert "THEN post to the PR" not in prompt["degraded"]
    assert "Do NOT post anything" in prompt["degraded"]


def test_posting_instructions_do_not_depend_on_a_local_clone() -> None:
    """They named CultureMech/dismech/..., a gitignored checkout no other machine has."""
    assert "dismech" not in DYNAMIC_REVIEW.read_text(encoding="utf-8")
