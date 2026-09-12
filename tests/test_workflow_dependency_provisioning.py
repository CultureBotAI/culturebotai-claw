"""A workflow step that runs claw's code must get claw's declared dependencies.

`cross-repo-validation.yaml` provisioned its runner with a hand-typed
`pip install pyyaml jinja2 matplotlib`. That list is a second, unversioned copy
of `[project].dependencies`, and on 2026-09-08 the two diverged: #372 added
`from dotenv import dotenv_values` to `src/kg_microbe_fleet/roots.py`,
python-dotenv was already declared in `pyproject.toml` and was not in the typed
list, and every run from then on died in the first step with
`ModuleNotFoundError: No module named 'dotenv'` before reading one record
(#376).

The property is not "the file says uv". It is that each line running claw code
reaches an interpreter that has already been given everything `pyproject.toml`
declares, and there are exactly two ways to arrive there: `uv run`, which
executes inside the project environment, or a `pip install .` that put the
project on the interpreter found on PATH. Naming individual distributions is
neither, which is why `uv sync` followed by a bare `python3 scripts/x.py` fails
this test -- as it would fail on a runner, the sync having populated an
environment that line never enters.

`uv run --no-project` is the one spelling that looks like the first and behaves
like neither: it deliberately declines the project's dependencies. The fleet
already uses it, in the vendored pr-shepherd workflow, so the flag is excluded
rather than assumed absent.

Per-script import graphs are deliberately not modelled. `scripts/` imports
`kg_microbe_fleet`, which imports whatever it needs today; pinning a subset per
script would recreate the hand list one level down. Two spellings are also
outside the model because nothing here uses them: `uv pip install <name>`,
which names distributions into the project environment, and a `uses:` step that
provisions through a composite action.

id-label-canon.yaml is NOT exempted and does not need to be: it runs the
vendored governance artifacts, which are dependency-light by design and are not
matched as claw code here.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github" / "workflows"

# `pip install ...` up to the first shell separator, however python invokes it.
_PIP_INSTALL = re.compile(r"\bpip3?\s+install\b(?P<args>[^\n;&|]*)")
# `uv run` executes inside the project environment -- unless told not to.
_UV_RUN = re.compile(r"\buv\s+run\b(?![^\n]*--no-project\b)")
# Ways this fleet's workflows invoke claw's own code.
_CLAW_CODE = re.compile(
    r"scripts/\w+\.py|-m\s+kg_microbe_\w+|\bkg-microbe-[a-z-]+\b|\bopenclaw-cli\b"
)


def _canonical(name: str) -> str:
    """PEP 503 normalisation, so `PyYAML` and `pyyaml` are one distribution."""
    return re.sub(r"[-_.]+", "-", name).lower()


def declared_dependencies() -> set[str]:
    document = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return {
        _canonical(re.split(r"[<>=!~\[; ]", spec.strip(), maxsplit=1)[0])
        for spec in document["project"]["dependencies"]
    }


def _command_lines(run: str):
    """Shell lines with comments dropped and `\\` continuations joined."""
    pending = ""
    for raw in run.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith("\\"):
            pending += line[:-1] + " "
            continue
        yield pending + line
        pending = ""
    if pending:
        yield pending


def _installs_the_project(argument: str) -> bool:
    """`.`, `./`, `'.'`, `.[dev]` all install the project and all it declares."""
    return argument.strip("'\"").rstrip("/").split("[", 1)[0] in {".", ""}


def unprovisioned_claw_invocations(
    workflow: dict, dependencies: set[str]
) -> list[tuple[str, str, list[str]]]:
    """Every claw invocation whose interpreter lacks a declared dependency."""
    findings: list[tuple[str, str, list[str]]] = []
    for job_name, job in workflow.get("jobs", {}).items():
        path_interpreter: set[str] = set()
        for step in job.get("steps", []) or []:
            run = step.get("run")
            if not run:
                continue
            for line in _command_lines(run):
                through_uv = bool(_UV_RUN.search(line))
                install = _PIP_INSTALL.search(line)
                if install and not through_uv:
                    for argument in install.group("args").split():
                        if argument.startswith("-"):
                            continue
                        if _installs_the_project(argument):
                            path_interpreter |= dependencies
                        else:
                            path_interpreter.add(_canonical(argument))
                if _CLAW_CODE.search(line):
                    available = dependencies if through_uv else path_interpreter
                    missing = sorted(dependencies - available)
                    if missing:
                        findings.append((job_name, line, missing))
    return findings


def _workflows() -> dict[str, dict]:
    return {
        path.name: yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in sorted(WORKFLOW_DIR.glob("*.y*ml"))
    }


def test_the_dependency_that_broke_the_nightly_run_is_a_declared_dependency():
    """Non-vacuity: the set this test compares against must contain the package
    whose absence caused #376, or the comparison proves nothing."""
    dependencies = declared_dependencies()

    assert "python-dotenv" in dependencies
    assert len(dependencies) > 3, "fewer deps than the hand list had; check the parse"


def test_the_cross_repo_workflow_actually_invokes_claw_code():
    """Non-vacuity: renaming the scripts past `_CLAW_CODE` would empty the check."""
    workflow = _workflows()["cross-repo-validation.yaml"]
    invocations = [
        line
        for job in workflow["jobs"].values()
        for step in job["steps"]
        if step.get("run")
        for line in _command_lines(step["run"])
        if _CLAW_CODE.search(line)
    ]

    assert len(invocations) >= 3, invocations


def test_every_workflow_step_running_claw_code_has_claws_declared_dependencies():
    """#376: a hand-typed install list drifted from `pyproject.toml`."""
    dependencies = declared_dependencies()
    findings = {
        name: unprovisioned_claw_invocations(workflow, dependencies)
        for name, workflow in _workflows().items()
    }
    reported = {name: rows for name, rows in findings.items() if rows}

    assert not reported, "\n".join(
        f"{name} [{job}]: `{line}` runs claw code without {missing}"
        for name, rows in reported.items()
        for job, line, missing in rows
    )


def test_a_hand_listed_install_is_distinguished_from_a_project_install():
    """The two sides of the distinction, on inputs that differ only there."""
    dependencies = {"pyyaml", "python-dotenv"}

    def workflow(*commands: str) -> dict:
        steps = "".join(f"      - run: {command}\n" for command in commands)
        return yaml.safe_load(f"jobs:\n  validate:\n    steps:\n{steps}")

    script = "scripts/validate_evidence_references.py"
    hand_listed = workflow("python -m pip install pyyaml", f"python3 {script}")
    project_installed = workflow("python -m pip install .", f"python3 {script}")
    project_with_extras = workflow("python -m pip install '.[dev]'", f"python3 {script}")
    synced_but_outside_the_venv = workflow("uv sync", f"python3 {script}")
    synced_and_entered = workflow("uv sync", f"uv run python {script}")

    assert unprovisioned_claw_invocations(hand_listed, dependencies) == [
        ("validate", f"python3 {script}", ["python-dotenv"])
    ]
    assert unprovisioned_claw_invocations(synced_but_outside_the_venv, dependencies)
    assert unprovisioned_claw_invocations(project_installed, dependencies) == []
    assert unprovisioned_claw_invocations(project_with_extras, dependencies) == []
    assert unprovisioned_claw_invocations(synced_and_entered, dependencies) == []


def test_uv_run_no_project_is_not_a_provisioned_interpreter():
    """`--no-project` is the one spelling that reads as `uv run` and declines
    the project's dependencies; the fleet uses it in the vendored shepherd."""
    dependencies = {"pyyaml", "python-dotenv"}

    def workflow(command: str) -> dict:
        return yaml.safe_load(
            f"jobs:\n  validate:\n    steps:\n      - run: {command}\n"
        )

    declined = workflow("uv run --no-project --with pyyaml python scripts/x.py")
    accepted = workflow("uv run python scripts/x.py")

    assert unprovisioned_claw_invocations(declined, dependencies) == [
        ("validate", "uv run --no-project --with pyyaml python scripts/x.py",
         ["python-dotenv", "pyyaml"])
    ]
    assert unprovisioned_claw_invocations(accepted, dependencies) == []
