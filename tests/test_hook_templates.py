"""Portability tests for installed coordination hook templates."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest


def _install_hooks(repository_root: Path, targets: list[Path]) -> subprocess.CompletedProcess:
    environment = os.environ.copy()
    environment.update(
        {
            "CULTUREMECH_ROOT": str(targets[0]),
            "MEDIAINGREDIENTMECH_ROOT": str(targets[1]),
            "COMMUNITYMECH_ROOT": str(targets[2]),
        }
    )
    return subprocess.run(
        ["bash", str(repository_root / "scripts" / "install_hooks.sh")],
        cwd=repository_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def test_hook_installer_replaces_paths_and_uses_workspace_status(tmp_path):
    repository_root = Path(__file__).parents[1]
    targets = [tmp_path / name for name in ("culturemech", "mim", "community")]
    for target in targets:
        target.mkdir()
    result = _install_hooks(repository_root, targets)

    assert result.returncode == 0, result.stderr
    post_edit = (targets[0] / ".claude" / "hooks" / "post-edit").read_text()
    assert "{{ORCHESTRATION_ROOT}}" not in post_edit
    assert 'WORKSPACE="${OPENCLAW_WORKSPACE:-workspace}"' in post_edit
    assert 'STATUS_DIR="$WORKSPACE/status"' in post_edit
    assert 'mkdir -p "$STATUS_DIR"' in post_edit


@pytest.mark.parametrize("hook_name", ["pre-edit", "pre-commit"])
def test_installed_pre_hooks_fail_closed_when_checker_errors(
    tmp_path: Path, hook_name: str
) -> None:
    repository_root = Path(__file__).parents[1]
    targets = [tmp_path / name for name in ("culturemech", "mim", "community")]
    for target in targets:
        target.mkdir()
    result = _install_hooks(repository_root, targets)
    assert result.returncode == 0, result.stderr

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_uv = fake_bin / "uv"
    fake_uv.write_text("#!/bin/sh\nexit 2\n", encoding="utf-8")
    fake_uv.chmod(0o755)
    environment = os.environ.copy()
    environment["PATH"] = f"{fake_bin}{os.pathsep}{environment['PATH']}"

    hook = targets[0] / ".claude" / "hooks" / hook_name
    hook_result = subprocess.run(
        [str(hook)],
        cwd=targets[0],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert hook_result.returncode != 0
    assert "Lock check failed" in hook_result.stdout


def test_hook_installer_shell_escapes_special_orchestration_path(tmp_path: Path) -> None:
    source_root = Path(__file__).parents[1]
    special_root = tmp_path / 'orchestration "quoted" \\ path'
    (special_root / "scripts").mkdir(parents=True)
    shutil.copy2(source_root / "scripts" / "install_hooks.sh", special_root / "scripts")
    shutil.copytree(source_root / "hook_templates", special_root / "hook_templates")
    targets = [tmp_path / name for name in ("culturemech", "mim", "community")]
    for target in targets:
        target.mkdir()

    result = _install_hooks(special_root, targets)
    assert result.returncode == 0, result.stderr

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        '#!/bin/sh\n[ "$3" = "$EXPECTED_ROOT" ] || exit 9\nexit 0\n',
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)
    environment = os.environ.copy()
    environment["EXPECTED_ROOT"] = str(special_root)
    environment["PATH"] = f"{fake_bin}{os.pathsep}{environment['PATH']}"
    hook = targets[0] / ".claude" / "hooks" / "pre-edit"

    syntax = subprocess.run(
        ["bash", "-n", str(hook)], capture_output=True, text=True, check=False
    )
    hook_result = subprocess.run(
        [str(hook)],
        cwd=targets[0],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert syntax.returncode == 0, syntax.stderr
    assert hook_result.returncode == 0, hook_result.stdout + hook_result.stderr
