"""The public dashboard's safe rendering boundary and browser-independent logic."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from kg_microbe_site import check_site

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site" / "progress"


def test_progress_page_contract(tmp_path: Path) -> None:
    """Resolve deployment-relative assets at the built root, not source paths."""
    shutil.copytree(SITE, tmp_path / "site")
    # Runtime data is supplied by the publisher, not a checked-in fake snapshot.
    data = tmp_path / "site" / "data"
    data.mkdir(exist_ok=True)
    (data / "progress.json").write_text("{}\n")
    findings = check_site(tmp_path / "site")
    assert findings == [], [(finding.code, finding.detail) for finding in findings]


def test_progress_presentation_contract() -> None:
    node = shutil.which("node")
    if not node:
        if os.environ.get("CI"):
            pytest.fail("Node is required to check the progress dashboard in CI")
        pytest.skip("Node is not installed")
    subprocess.run(
        [node, str(ROOT / "tests" / "progress_site_harness.mjs"), str(SITE / "model.mjs")],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def test_progress_dynamic_content_has_no_html_interpolation() -> None:
    script = (SITE / "app.mjs").read_text()
    assert "innerHTML" not in script
    assert "outerHTML" not in script
    assert "insertAdjacentHTML" not in script
    assert "textContent" in script
    assert 'new URL("data/progress.json", import.meta.url)' in script
