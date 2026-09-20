"""What an automated alarm may say, and what it must be able to say it with.

`cross-repo-validation.yaml` opens an issue when the nightly job fails, and its
body was a constant. Both of its sentences were wrong for every failure it ever
reported: it named a MIM snippet mismatch as the likely cause of runs that had
died importing python-dotenv before reading a record, and it pointed at
artifacts that every failing run had skipped uploading. #376 was read against
that sentence for four days (#449).

Three couplings are checked here, because each one is a way for an alarm to be
worse than no alarm:

* a script that calls `github.rest.<namespace>` needs the matching scope. The
  workflow's `permissions:` block is enumerated, and an enumerated block sets
  every unlisted scope to `none`, so a call added without its scope fails at the
  moment it is needed and never before;
* a call the alarm does not depend on must not be able to stop it. Naming the
  failed step is a nicety; opening the issue is the point, so the lookup belongs
  inside `try`/`catch`. A misleading issue is bad, and silence is worse;
* the body has to carry something the run measured, and must not assert a cause.

The third is two assertions because only one half is mechanically decidable.
"The body says only what this run established" is not checkable, so what is
pinned instead is the specific regression -- a speculating phrase -- plus the
structural half: a value assigned inside the `try` must reach the body.

Brace matching for the `try` spans is naive about braces inside strings. Every
literal in these scripts is balanced, and an unbalanced one reports the call as
uncovered, which is a red test rather than a silent pass.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github" / "workflows"

GITHUB_SCRIPT = "actions/github-script"

_REST_CALL = re.compile(r"github\.rest\.(?P<namespace>\w+)\.(?P<method>\w+)")
# github-script namespace -> the `permissions:` key that grants it.
_SCOPE = {
    "actions": "actions",
    "checks": "checks",
    "git": "contents",
    "issues": "issues",
    "pulls": "pull-requests",
    "repos": "contents",
}
_WRITES = re.compile(r"^(?:create|update|delete|add|remove|set|merge|replace|lock)")
# A body that speculates reads as a diagnosis. This is the #449 regression.
_SPECULATION = re.compile(
    r"\b(?:likely cause|probably|presumably|most likely|usually caused by)\b",
    re.IGNORECASE,
)
# What the alarm SAYS, as opposed to what its comments explain: string and
# template literals, with escapes honoured so an escaped backtick inside a
# template does not end it early.
_LITERAL = re.compile(
    r"`(?:[^`\\]|\\.)*`|\"(?:[^\"\\\n]|\\.)*\"|'(?:[^'\\\n]|\\.)*'"
)
_OPENS_AN_ISSUE = re.compile(r"github\.rest\.issues\.(?:create|createComment)\b")
_INTERPOLATION = re.compile(r"\$\{(?P<name>[A-Za-z_]\w*)")
# `(?![=>])` excludes both `==` and the parameter of a bare arrow function:
# `step => step` assigns nothing, and counting it would let the alarm report
# a name it never measured -- the #286 vacuity, inside a test written to
# prevent one.
_ASSIGNMENT = re.compile(r"(?:^|[;{\s])(?P<name>[A-Za-z_]\w*)\s*=(?![=>])")


def _workflows() -> dict[str, dict]:
    return {
        path.name: yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in sorted(WORKFLOW_DIR.glob("*.y*ml"))
    }


def _script_steps() -> list[tuple[str, str, str, dict]]:
    """(workflow, step name, script, effective permissions) per github-script step."""
    steps = []
    for name, workflow in _workflows().items():
        top = workflow.get("permissions")
        for job in (workflow.get("jobs") or {}).values():
            permissions = job.get("permissions", top)
            for step in job.get("steps") or []:
                if GITHUB_SCRIPT not in str(step.get("uses", "")):
                    continue
                script = (step.get("with") or {}).get("script")
                if script:
                    steps.append((name, step.get("name", "?"), script, permissions))
    return steps


def _granted(permissions, scope: str) -> str:
    """The level a `permissions:` value grants for one scope."""
    if permissions == "write-all":
        return "write"
    if permissions == "read-all":
        return "read"
    if isinstance(permissions, dict):
        return str(permissions.get(scope, "none"))
    return "none"


def required_scopes(script: str) -> set[tuple[str, str]]:
    """(scope, level) every `github.rest` call in this script needs."""
    needed = set()
    for call in _REST_CALL.finditer(script):
        scope = _SCOPE.get(call.group("namespace"))
        if scope is None:  # an unmapped namespace is reported, not assumed safe
            scope = call.group("namespace")
        level = "write" if _WRITES.match(call.group("method")) else "read"
        needed.add((scope, level))
    return needed


def try_spans(script: str) -> list[tuple[int, int]]:
    """Character spans of every `try { ... }` that is followed by a `catch`."""
    spans = []
    for match in re.finditer(r"\btry\s*\{", script):
        depth = 0
        index = match.end() - 1
        while index < len(script):
            if script[index] == "{":
                depth += 1
            elif script[index] == "}":
                depth -= 1
                if depth == 0:
                    break
            index += 1
        else:
            continue
        if re.match(r"\s*catch\b", script[index + 1 : index + 40]):
            spans.append((match.start(), index))
    return spans


def calls_outside_try(script: str, namespaces: set[str]) -> list[str]:
    """Calls into `namespaces` that nothing catches."""
    spans = try_spans(script)
    loose = []
    for call in _REST_CALL.finditer(script):
        if call.group("namespace") not in namespaces:
            continue
        if not any(start <= call.start() <= end for start, end in spans):
            loose.append(call.group(0))
    return loose


def measured_names(script: str) -> set[str]:
    """Names the `try` assigned: what the script knows only because it ran."""
    return {
        match.group("name")
        for start, end in try_spans(script)
        for match in _ASSIGNMENT.finditer(script[start:end])
    }


def reported_names(script: str) -> set[str]:
    """Names interpolated into the text written after the last `try`."""
    spans = try_spans(script)
    after = script[max(end for _, end in spans) :] if spans else script
    return {match.group("name") for match in _INTERPOLATION.finditer(after)}


def _alarms() -> list[tuple[str, str, str, dict]]:
    return [row for row in _script_steps() if _OPENS_AN_ISSUE.search(row[2])]


def test_the_workflows_actually_contain_an_alarm_that_calls_a_scoped_api():
    """Non-vacuity: every assertion below is empty if no such step exists."""
    alarms = _alarms()

    assert alarms, "no github-script step opens an issue; these tests prove nothing"
    assert ("cross-repo-validation.yaml", "actions", "read") in {
        (workflow, scope, level)
        for workflow, _, script, _ in alarms
        for scope, level in required_scopes(script)
    }


def test_every_github_script_call_has_the_permission_it_needs():
    """An enumerated `permissions:` block sets every unlisted scope to none, so a
    call added without its scope fails only on the run that needed it."""
    ungranted = [
        f"{workflow} [{step}]: github.rest needs {scope}:{level}, "
        f"permissions grant {_granted(permissions, scope)}"
        for workflow, step, script, permissions in _script_steps()
        for scope, level in sorted(required_scopes(script))
        if not (
            _granted(permissions, scope) == "write"
            or (_granted(permissions, scope) == "read" and level == "read")
        )
    ]

    assert not ungranted, "\n".join(ungranted)


def test_an_alarm_is_not_stopped_by_a_call_it_does_not_depend_on():
    """#449: naming the failed step is a nicety; opening the issue is the point.
    An uncaught lookup turns a misleading issue into no issue at all."""
    loose = {
        f"{workflow} [{step}]": calls_outside_try(script, set(_SCOPE) - {"issues"})
        for workflow, step, script, _ in _alarms()
    }
    reported = {where: calls for where, calls in loose.items() if calls}

    assert not reported, f"uncaught non-essential calls in an alarm: {reported}"


def spoken_text(script: str) -> str:
    """Only the literals. A comment may quote the sentence this test forbids."""
    return " ".join(match.group(0) for match in _LITERAL.finditer(script))


def test_an_alarm_does_not_assert_a_cause_it_has_not_measured():
    """#449: the body asserted a MIM snippet mismatch for runs that died on an
    import. A constant guess is indistinguishable from a diagnosis."""
    speaks = {
        f"{workflow} [{step}]": spoken_text(script)
        for workflow, step, script, _ in _alarms()
    }
    mute = [where for where, text in speaks.items() if not text.strip()]
    speculating = [
        f"{where}: {_SPECULATION.search(text).group(0)!r}"
        for where, text in speaks.items()
        if _SPECULATION.search(text)
    ]

    assert not mute, f"no literals parsed out of {mute}; the scan is vacuous"
    assert not speculating, "\n".join(speculating)


def test_an_alarm_reports_something_the_run_measured():
    """The structural half: a value the `try` assigned must reach the text that
    is written after it, or the body is a constant however it is worded."""
    silent = []
    for workflow, step, script, _ in _alarms():
        if not try_spans(script):
            silent.append(f"{workflow} [{step}]: no try/catch, nothing is measured")
            continue
        measured = measured_names(script)
        reported = reported_names(script)
        if not measured & reported:
            silent.append(f"{workflow} [{step}]: measured {sorted(measured)}, "
                          f"reported {sorted(reported)}")

    assert not silent, "\n".join(silent)


def test_an_arrow_parameter_is_not_mistaken_for_something_measured():
    """A name the script never assigned must not enter the measured set, or the
    test above passes on a body that reports nothing the run established."""
    # `step` here is an arrow parameter preceded by a space, which is the
    # position a name-then-`=` pattern mistakes for an assignment. An arrow
    # inside a call -- `map(step => ...)` -- sits after `(` and is excluded by
    # accident, so a fixture built from that spelling would pass either way.
    script = (
        "try {\n"
        "  const listing = await github.rest.actions.listJobsForWorkflowRun();\n"
        "  const label = step => step.name;\n"
        "  listing.jobs.map(label);\n"
        "} catch (error) { }\n"
        "const body = `${step}`;\n"
    )

    assert measured_names(script) == {"listing", "label"}
    assert reported_names(script) == {"step"}
    assert not measured_names(script) & reported_names(script)
