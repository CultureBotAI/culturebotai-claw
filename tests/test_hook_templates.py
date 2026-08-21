"""Portability tests for installed coordination hook templates."""

import os
import subprocess
from pathlib import Path


def test_hook_installer_replaces_paths_and_uses_workspace_status(tmp_path):
    repository_root = Path(__file__).parents[1]
    targets = [tmp_path / name for name in ("culturemech", "mim", "community")]
    for target in targets:
        target.mkdir()
    environment = os.environ.copy()
    environment.update(
        {
            "CULTUREMECH_ROOT": str(targets[0]),
            "MEDIAINGREDIENTMECH_ROOT": str(targets[1]),
            "COMMUNITYMECH_ROOT": str(targets[2]),
        }
    )

    result = subprocess.run(
        ["bash", str(repository_root / "scripts" / "install_hooks.sh")],
        cwd=repository_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    post_edit = (targets[0] / ".claude" / "hooks" / "post-edit").read_text()
    assert "{{ORCHESTRATION_ROOT}}" not in post_edit
    assert 'WORKSPACE="${OPENCLAW_WORKSPACE:-workspace}"' in post_edit
    assert 'STATUS_DIR="$WORKSPACE/status"' in post_edit
    assert 'mkdir -p "$STATUS_DIR"' in post_edit
