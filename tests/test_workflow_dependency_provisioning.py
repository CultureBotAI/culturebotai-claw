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

The two governed queue controllers are narrow exceptions: every AST import,
including function-local imports, is checked against the standard library before
either canonical or consumer spelling is exempted. Dynamic loaders invalidate
the exemption. Other per-script import graphs are deliberately not modelled. `scripts/` imports
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

import ast
import re
import shlex
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_DIR = ROOT / ".github" / "workflows"

# Only PATH installs count for later bare Python commands. `uv pip install`
# targets the project environment; dry runs and --no-deps do not provision it.
_PIP_INSTALL = re.compile(
    r"^(?:(?:python3?\s+-m\s+)?pip3?)\s+install\b(?P<args>.*)$"
)
# Automatic project synchronization is the supported uv run path in this model.
_UV_RUN = re.compile(r"^uv\s+run\b(?![^\n]*--no-(?:project|sync)\b)")
# Ways this fleet's workflows invoke claw's own code.
_CLAW_CODE = re.compile(
    r"scripts/\w+\.py|-m\s+kg_microbe_\w+|\bkg-microbe-[a-z-]+\b|\bopenclaw-cli\b"
)


_STANDALONE_SOURCES = {
    spelling: Path("src/kg_microbe_governance/artifacts/scripts") / name
    for name in ("auto_merge_ready_prs.py", "verify_merge_integrity.py")
    for spelling in (f"scripts/{name}", f"src/kg_microbe_governance/artifacts/scripts/{name}")
}
# These stdlib facilities can import arbitrary code without an Import AST node.
# Fail closed on their presence rather than attempting dynamic dependency analysis.
_DYNAMIC_MODULES = {"builtins", "importlib", "runpy", "pkgutil"}
_DYNAMIC_NAMES = {"__import__", "__builtins__", "eval", "exec", "compile", "getattr", "globals", "locals"}
_DYNAMIC_ATTRIBUTES = {"__import__", "eval", "exec", "import_module", "exec_module", "load_module"}


def _audited_stdlib_source(path: Path) -> bool:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeError):
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots = {alias.name.split(".", 1)[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom):
            if node.level or not node.module:
                return False
            roots = {node.module.split(".", 1)[0]}
        else:
            roots = set()
        if not roots <= sys.stdlib_module_names or roots & _DYNAMIC_MODULES:
            return False
        if isinstance(node, ast.Name) and node.id in _DYNAMIC_NAMES:
            return False
        if isinstance(node, ast.Attribute) and node.attr in _DYNAMIC_ATTRIBUTES:
            return False
    return True


def _requires_project(line: str) -> bool:
    """Remove only exact, source-audited standalone references from the scan.

    Assignments count too: workflows select a consumer or canonical path before
    invoking "$script". An unrelated script in that same shell command still
    requires project provisioning; this is never a whole-command exemption.
    """
    remaining = []
    for token in shlex.split(line):
        assignment = re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=(.*)", token)
        value = assignment.group(1) if assignment else token
        source = _STANDALONE_SOURCES.get(value)
        if source is not None and _audited_stdlib_source(ROOT / source):
            continue
        remaining.append(token)
    return bool(_CLAW_CODE.search(shlex.join(remaining)))


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
        yield from _shell_commands(pending + line)
        pending = ""
    if pending:
        yield from _shell_commands(pending)



def _shell_commands(line: str):
    """Keep quoted separators inside arguments; separate actual shell commands.

    This covers the simple command lists and `if` probes used by these workflows,
    rather than treating uv on one side of `;` as provisioning the other side.
    """
    assignment = re.fullmatch(
        r'[A-Za-z_][A-Za-z0-9_]*=(?P<quote>"?)\$\((?P<command>.*)\)(?P=quote)',
        line,
    )
    if assignment:
        yield from _shell_commands(assignment.group("command"))
        return
    lexer = shlex.shlex(line, posix=True, punctuation_chars=";&|")
    lexer.whitespace_split = True
    command: list[str] = []
    for token in [*lexer, ";"]:
        if token and set(token) <= set(";&|"):
            if command and command[0] in {"if", "then", "!"}:
                command = command[1:]
            if command:
                yield shlex.join(command)
            command = []
        else:
            command.append(token)


def _installs_the_project(argument: str) -> bool:
    """`.`, `./`, `'.'`, `.[dev]` all install the project and all it declares."""
    return argument.strip("'\"").rstrip("/").split("[", 1)[0] == "."


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
                arguments = shlex.split(install.group("args")) if install else []
                non_provisioning = {"--dry-run", "--no-deps", "--target", "-t", "--prefix", "--root", "--user", "--python"}
                suppressed = any(a.split("=", 1)[0] in non_provisioning for a in arguments)
                if install and not through_uv and not suppressed and not step.get("if") and not step.get("continue-on-error"):
                    for argument in arguments:
                        if argument.startswith("-"):
                            continue
                        if _installs_the_project(argument):
                            path_interpreter |= dependencies
                        else:
                            path_interpreter.add(_canonical(argument))
                if _requires_project(line):
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


@pytest.mark.parametrize("install", [
    "python -m pip install /",
    "python -m pip install [dev]",
    "uv pip install .",
    "python -m pip install --dry-run .",
    "python -m pip install --no-deps .",
    "python -m pip install --target=/tmp/elsewhere .",
    "echo pip install .",
])
def test_non_provisioning_installs_do_not_satisfy_bare_python(install):
    dependencies = {"pyyaml", "python-dotenv"}
    workflow = {"jobs": {"validate": {"steps": [
        {"run": install}, {"run": "python3 scripts/x.py"},
    ]}}}
    assert unprovisioned_claw_invocations(workflow, dependencies)


@pytest.mark.parametrize("separator", [";", "&&", "||"])
def test_uv_only_provisions_its_own_shell_command(separator):
    dependencies = {"pyyaml", "python-dotenv"}
    command = f"uv run echo ok {separator} python3 scripts/x.py"
    workflow = {"jobs": {"validate": {"steps": [{"run": command}]}}}
    assert unprovisioned_claw_invocations(workflow, dependencies) == [
        ("validate", "python3 scripts/x.py", ["python-dotenv", "pyyaml"])
    ]


def test_project_install_in_same_shell_list_does_provision_bare_python():
    workflow = {"jobs": {"validate": {"steps": [
        {"run": "python -m pip install . && python3 scripts/x.py"},
    ]}}}
    assert unprovisioned_claw_invocations(workflow, {"pyyaml", "python-dotenv"}) == []


def test_quoted_separator_and_if_probe_keep_uv_execution_intact():
    workflow = {"jobs": {"validate": {"steps": [
        {"run": 'if uv run python scripts/x.py --label "a;b"; then echo ok; fi'},
    ]}}}
    assert unprovisioned_claw_invocations(workflow, {"pyyaml", "python-dotenv"}) == []


def test_assignment_command_substitution_enters_uv_project_environment():
    workflow = {"jobs": {"prepare": {"steps": [
        {"run": 'matrix="$(uv run python -m kg_microbe_fleet matrix)"'},
    ]}}}
    assert unprovisioned_claw_invocations(workflow, {"pyyaml", "python-dotenv"}) == []


@pytest.mark.parametrize("script", ["auto_merge_ready_prs.py", "verify_merge_integrity.py"])
@pytest.mark.parametrize("prefix", ["scripts/", "src/kg_microbe_governance/artifacts/scripts/"])
def test_audited_queue_standalone_needs_no_project_dependencies(script, prefix):
    command = f"uv run --no-project python {prefix}{script} --help"
    workflow = {"jobs": {"queue": {"steps": [{"run": command}]}}}
    assert unprovisioned_claw_invocations(workflow, {"pyyaml", "python-dotenv"}) == []


@pytest.mark.parametrize("source", [
    "def later():\n    import third_party\n",
    "def later():\n    from . import sibling\n",
    "def later():\n    return __import__('third_party')\n",
    "import importlib as loader\ndef later():\n    return loader.import_module('third_party')\n",
    "from builtins import exec as execute\ndef later():\n    execute('import third_party')\n",
    "def later():\n    eval(\"__import__('third_party')\")\n",
])
def test_standalone_assignment_is_exempt_only_while_whole_source_is_stdlib(tmp_path, monkeypatch, source):
    path = tmp_path / "src/kg_microbe_governance/artifacts/scripts/auto_merge_ready_prs.py"
    path.parent.mkdir(parents=True)
    path.write_text("import json\n" + source)
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)
    workflow = {"jobs": {"queue": {"steps": [{"run": "script=scripts/auto_merge_ready_prs.py"}]}}}
    assert unprovisioned_claw_invocations(workflow, {"pyyaml"})
    path.write_text("import json\ndef later():\n    import pathlib\n")
    assert unprovisioned_claw_invocations(workflow, {"pyyaml"}) == []


def test_queue_standalone_does_not_exempt_other_claw_code_in_same_command():
    workflow = {"jobs": {"queue": {"steps": [{
        "run": "script=scripts/auto_merge_ready_prs.py python scripts/other.py",
    }]}}}
    assert unprovisioned_claw_invocations(workflow, {"pyyaml"})
