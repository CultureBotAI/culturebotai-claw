"""Exercise the workflow's candidate admission lane with offline Git repos.

A PR's newly declared member is absent from the trusted-base clone list. The
mandatory candidate completeness check must provide that root without changing
the deployed-fleet audit or allowing a failed clone to become a skipped test.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

WORKFLOW = (
    Path(__file__).resolve().parents[1]
    / ".github/workflows/governance-fleet-audit.yaml"
)


def _steps() -> list[dict]:
    return yaml.safe_load(WORKFLOW.read_text())["jobs"]["fleet-audit"]["steps"]


def _candidate_step() -> dict:
    return next(
        step for step in _steps()
        if "test_vendored_consumer_completeness.py" in step.get("run", "")
    )


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], check=True, capture_output=True, text=True
    ).stdout.strip()


def _source(path: Path) -> None:
    path.mkdir()
    _git("init", "-b", "main", str(path))
    (path / "governed.txt").write_text("committed governance fixture\n")
    _git("-C", str(path), "add", "governed.txt")
    _git(
        "-C", str(path), "-c", "user.name=Test", "-c", "user.email=test@example.org",
        "-c", "commit.gpgsign=false", "commit", "-m", "fixture",
    )


@pytest.fixture
def admission(tmp_path: Path) -> tuple[Path, dict[str, str]]:
    fleet = tmp_path / "fleet"
    fleet.mkdir()
    sources = tmp_path / "sources"
    sources.mkdir()
    urls = {}
    for key in ("existing", "newcomer"):
        source = sources / key
        _source(source)
        urls[f"https://github.com/Example/{key}.git"] = str(source)

    existing = fleet / "existing"
    _git("clone", str(sources / "existing"), str(existing))
    _git(
        "-C", str(existing), "remote", "set-url", "origin",
        "https://github.com/Example/existing.git",
    )
    (fleet / "governance-consumers.tsv").write_text(
        "existing\tExample/existing\tsrc/existing\tscripts/.vendored_canon_ref\n"
        "retired\tExample/retired\tsrc/retired\tscripts/.vendored_canon_ref\n"
    )

    package = tmp_path / "candidate-package"
    package.mkdir()
    (package / "kg_microbe_governance.py").write_text(
        "import os\n"
        "from types import SimpleNamespace as Row\n"
        "def load_governance_manifest():\n"
        "    if os.environ.get('INVALID_CANDIDATE'):\n"
        "        raise ValueError('invalid candidate manifest')\n"
        "    return Row(pin_path='scripts/.vendored_canon_ref', consumers={\n"
        "        key: Row(key=key, github='Example/' + key, package_path='src/' + key)\n"
        "        for key in ('existing', 'newcomer')\n"
        "    })\n"
    )
    binaries = tmp_path / "bin"
    binaries.mkdir()
    uv = binaries / "uv"
    uv.write_text(
        f"#!{sys.executable}\n"
        "import json, os, sys\n"
        "from pathlib import Path\n"
        "if sys.argv[-1] == '-':\n"
        "    sys.path.insert(0, os.environ['CANDIDATE_PACKAGE'])\n"
        "    exec(sys.stdin.read())\n"
        "else:\n"
        "    assert sys.argv[-1].endswith('test_vendored_consumer_completeness.py')\n"
        "    assert os.environ['FLEET_CONSUMER_ROOTS_REQUIRED'] == '1'\n"
        "    Path('checked-roots.json').write_text(json.dumps({\n"
        "        key: value for key, value in os.environ.items() if key.endswith('_ROOT')\n"
        "    }))\n"
    )
    git = binaries / "git"
    git.write_text(
        f"#!{sys.executable}\n"
        "import json, os, subprocess, sys\n"
        "from pathlib import Path\n"
        "args = sys.argv[1:]\n"
        "real_git = os.environ['REAL_GIT']\n"
        "if args[0] == 'clone':\n"
        "    if os.environ.get('FAIL_CLONE'):\n"
        "        sys.exit(7)\n"
        "    url, target = args[-2:]\n"
        "    with Path('clones.jsonl').open('a') as stream:\n"
        "        stream.write(json.dumps(args) + '\\n')\n"
        "    args[-2] = json.loads(os.environ['LOCAL_REPOSITORIES'])[url]\n"
        "    subprocess.run([real_git, *args], check=True)\n"
        "    args = ['-C', target, 'remote', 'set-url', 'origin', url]\n"
        "sys.exit(subprocess.run([real_git, *args]).returncode)\n"
    )
    uv.chmod(0o755)
    git.chmod(0o755)
    env = dict(os.environ)
    env.update({
        "PATH": f"{binaries}{os.pathsep}{env['PATH']}",
        "GITHUB_WORKSPACE": str(tmp_path),
        "CANDIDATE_PACKAGE": str(package),
        "REAL_GIT": shutil.which("git") or "git",
        "LOCAL_REPOSITORIES": json.dumps(urls),
        "FLEET_CONSUMER_ROOTS_REQUIRED": str(_candidate_step()["env"][
            "FLEET_CONSUMER_ROOTS_REQUIRED"
        ]),
    })
    return tmp_path, env


def _run(admission: tuple[Path, dict[str, str]]) -> subprocess.CompletedProcess[str]:
    root, env = admission
    return subprocess.run(
        ["bash", "-c", _candidate_step()["run"]], cwd=root, env=env,
        check=False, capture_output=True, text=True, timeout=30,
    )


def test_candidate_addition_is_cloned_and_checked_without_changing_trusted_scope(admission):
    root, _env = admission
    trusted = (root / "fleet/governance-consumers.tsv").read_bytes()
    result = _run(admission)
    assert result.returncode == 0, result.stderr
    roots = json.loads((root / "checked-roots.json").read_text())
    for key in ("existing", "newcomer"):
        target = root / "fleet" / key
        assert roots[f"{key.upper()}_ROOT"] == str(target)
        assert _git("-C", str(target), "ls-tree", "--name-only", "origin/main") == (
            "governed.txt"
        )
    assert "RETIRED_ROOT" not in roots
    assert (root / "fleet/governance-consumers.tsv").read_bytes() == trusted
    clones = [json.loads(line) for line in (root / "clones.jsonl").read_text().splitlines()]
    assert len(clones) == 1
    assert clones[0][-2] == "https://github.com/Example/newcomer.git"
    assert "--no-checkout" in clones[0]


@pytest.mark.parametrize("failure", ["INVALID_CANDIDATE", "FAIL_CLONE", "wrong_origin"])
def test_candidate_preconditions_fail_before_mandatory_completeness(admission, failure):
    root, env = admission
    if failure == "wrong_origin":
        _git(
            "-C", str(root / "fleet/existing"), "remote", "set-url", "origin",
            "https://github.com/Example/wrong.git",
        )
    else:
        env[failure] = "1"
    result = _run(admission)
    assert result.returncode != 0
    assert not (root / "checked-roots.json").exists()
    assert not (root / "fleet/newcomer").exists()


def test_candidate_roots_are_prepared_after_authority_validation():
    steps = _steps()
    validation = next(
        index for index, step in enumerate(steps)
        if step.get("name") == "Validate candidate authority contract"
    )
    assert validation < steps.index(_candidate_step())
    assert "--project control" in _candidate_step()["run"]
