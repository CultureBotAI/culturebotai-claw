"""Execute the canonical spoke drift checker against a hermetic curl stub.

These tests pin the timeout design from #89 and make this repository execute
the script logic it vendors (#91), without network access.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "shared" / "spoke" / "scripts" / "check_vendored_sync.sh"
SAME_PATHS = (
    "tests/test_provider_triage_contract.py",
    "scripts/validate_id_label_correspondence.py",
    "scripts/chem_formula.py",
    "tests/test_id_label_empty_adapter.py",
    "tests/test_id_label_unknown_prefix.py",
    "tests/test_id_label_plausibility.py",
)
MAPPED_PATHS = (
    ("src/fixture/schema/mech_shared.yaml", "src/culturemech/schema/mech_shared.yaml"),
    ("src/fixture/schema/history.yaml", "src/culturemech/schema/history.yaml"),
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _fixture(tmp_path: Path) -> tuple[Path, dict[str, str], Path]:
    root = tmp_path / "spoke"
    remote = tmp_path / "canonical"
    ref = "a" * 40
    _write(root / "scripts/.vendored_canon_ref", ref + "\n")
    for rel in SAME_PATHS:
        _write(root / rel, f"same:{rel}\n")
        _write(remote / rel, f"same:{rel}\n")
    checker = SCRIPT.read_text()
    _write(root / "scripts/check_vendored_sync.sh", checker)
    _write(remote / "scripts/check_vendored_sync.sh", checker)
    for local, hub in MAPPED_PATHS:
        _write(root / local, f"mapped:{hub}\n")
        _write(remote / hub, f"mapped:{hub}\n")

    bin_dir = tmp_path / "bin"
    curl = bin_dir / "curl"
    _write(
        curl,
        f"""#!{sys.executable}
import json
import os
import shutil
import sys
from pathlib import Path

args = sys.argv[1:]
with Path(os.environ["CURL_LOG"]).open("a") as stream:
    stream.write(json.dumps(args) + "\\n")
if os.environ.get("CURL_FAIL"):
    raise SystemExit(28)
output = Path(args[args.index("-o") + 1])
url = next(arg for arg in args if arg.startswith("https://"))
prefix = "/{ref}/"
relative = url.split(prefix, 1)[1]
shutil.copyfile(Path(os.environ["CANON_FIXTURES"]) / relative, output)
""",
    )
    curl.chmod(0o755)
    log = tmp_path / "curl.jsonl"
    env = {
        **os.environ,
        "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
        "CANON_FIXTURES": str(remote),
        "CURL_LOG": str(log),
        "GITHUB_REPOSITORY": "CultureBotAI/proteintraitsmech",
    }
    return root, env, log


def _calls(log: Path) -> list[list[str]]:
    return [json.loads(line) for line in log.read_text().splitlines()]


def test_all_fetches_are_bounded_and_never_retry_internally(tmp_path: Path) -> None:
    root, env, log = _fixture(tmp_path)
    result = subprocess.run(
        ["bash", str(SCRIPT)], cwd=root, env=env, text=True, capture_output=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "OK: all 9 vendored files match" in result.stdout
    calls = _calls(log)
    assert len(calls) == 9
    for args in calls:
        assert args[args.index("--max-time") + 1] == "10"
        assert not any(arg == "--retry" or arg.startswith("--retry-") for arg in args)


def test_curl_failure_is_reported_for_the_calling_workflow_to_retry(tmp_path: Path) -> None:
    root, env, log = _fixture(tmp_path)
    env["CURL_FAIL"] = "1"
    result = subprocess.run(
        ["bash", str(SCRIPT)], cwd=root, env=env, text=True, capture_output=True
    )
    assert result.returncode == 1
    assert "ERROR: could not fetch" in result.stdout
    assert "To resolve:" in result.stdout
    calls = _calls(log)
    assert len(calls) == 9
    assert all("--max-time" in args for args in calls)
