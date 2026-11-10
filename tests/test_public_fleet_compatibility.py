"""Real workflow shell, exact legacy bytes, and full public coverage guards."""

import copy
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from kg_microbe_governance import automatic_private_audit as auto
from kg_microbe_merge_queue import workflow_errors

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/public_fleet_legacy_adapter"
WORKFLOW = ROOT / ".github/workflows/governance-fleet-audit.yaml"
KNOWN = {
    "automatic_fleet_component.py": "93e666029922aa4fa2f902922ae0aa54c28da41c618a2c33af173c65907e0252",
    "automatic_private_audit_cli.py": "26376fcb7cac5ec84f40cd9529c53881e9c9a4ea256d57609a27fda858159ab5",
    "private_scaleup_audit.py": "bab998c0f194e87cf6b510123c671dc45ccc830ccc5526c05aa636df200bffc7",
}


def steps():
    workflow = yaml.safe_load(WORKFLOW.read_text())
    selector = next(s for s in workflow["jobs"]["fleet-audit"]["steps"] if s.get("id") == "automatic")
    final = workflow["jobs"]["verified-fleet"]["steps"][-1]
    return selector, final


def setup(tmp_path, *, adapter="known", protected=False, candidate=False):
    original = json.loads((ROOT / auto.MANIFEST_PATH).read_bytes())
    for root, private in (("control", candidate), ("fleet/trusted-claw", protected)):
        document = copy.deepcopy(original)
        document["consumers"].pop("scaleupmech", None)
        if private:
            document["consumers"]["scaleupmech"] = {
                "github": "CultureBotAI/ScaleupMech", "package_path": "src/scaleupmech",
            }
        target = tmp_path / root / auto.MANIFEST_PATH
        target.parent.mkdir(parents=True)
        target.write_text(json.dumps(document))
    trusted = tmp_path / "fleet/trusted-claw/src/kg_microbe_governance"
    if adapter != "absent":
        for name, digest in KNOWN.items():
            raw = (FIXTURES / (name + ".txt")).read_bytes()
            assert hashlib.sha256(raw).hexdigest() == digest
            (trusted / name).write_bytes(raw)
        if adapter != "known":
            with (trusted / adapter).open("ab") as stream:
                stream.write(b"\n# changed protected bytes\n")
    binaries = tmp_path / "bin"
    binaries.mkdir()
    uv = binaries / "uv"
    # Execute the actual extracted stdin shell program in a fresh interpreter;
    # only environment installation and the terminal verifier are stubbed.
    uv.write_text(
        f"#!{sys.executable}\n"
        "import pathlib, sys\n"
        f"sys.path.insert(0, {str(ROOT / 'src')!r})\n"
        "if '-m' in sys.argv:\n"
        "    pathlib.Path('automatic-verifier-called').write_text('called')\n"
        "else:\n"
        "    exec(compile(sys.stdin.read(), '<workflow-stdin>', 'exec'))\n"
    )
    uv.chmod(0o755)
    return {"PATH": str(binaries) + os.pathsep + os.defpath,
            "GITHUB_WORKSPACE": str(tmp_path), "GITHUB_OUTPUT": str(tmp_path / "output"),
            "CANDIDATE_SHA": "a" * 40}


def shell(step, root, env):
    return subprocess.run(["bash", "-c", step["run"]], cwd=root, env=env,
                          capture_output=True, text=True, timeout=20)


@pytest.mark.parametrize("protected,candidate", [(False, False), (True, False), (False, True), (True, True)])
def test_exact_old_adapter_and_both_manifest_obligations(tmp_path, protected, candidate):
    env = setup(tmp_path, protected=protected, candidate=candidate)
    selector, final = steps()
    assert shell(selector, tmp_path, env).returncode == 0
    expected = protected or candidate
    assert (tmp_path / "output").read_text() == f"available={str(expected).lower()}\n"
    env["AUTOMATIC_AVAILABLE"] = str(expected).lower()
    assert shell(final, tmp_path, env).returncode == 0
    assert (tmp_path / "automatic-verifier-called").exists() is expected
    env["AUTOMATIC_AVAILABLE"] = str(not expected).lower()
    assert shell(final, tmp_path, env).returncode != 0


@pytest.mark.parametrize("changed", list(KNOWN))
def test_unknown_or_repaired_protected_bytes_never_take_compatibility(tmp_path, changed):
    env = setup(tmp_path, adapter=changed)
    selector, final = steps()
    assert shell(selector, tmp_path, env).returncode == 0
    assert (tmp_path / "output").read_text() == "available=true\n"
    env["AUTOMATIC_AVAILABLE"] = "false"
    assert shell(final, tmp_path, env).returncode != 0
    assert not (tmp_path / "automatic-verifier-called").exists()


@pytest.mark.parametrize("protected,candidate", [(False, False), (True, False), (False, True), (True, True)])
def test_historical_adapter_absence_only_allows_public_only(tmp_path, protected, candidate):
    env = setup(tmp_path, adapter="absent", protected=protected, candidate=candidate)
    selector, final = steps()
    expected = not (protected or candidate)
    assert (shell(selector, tmp_path, env).returncode == 0) is expected
    env["AUTOMATIC_AVAILABLE"] = "false"
    assert (shell(final, tmp_path, env).returncode == 0) is expected
    assert not (tmp_path / "automatic-verifier-called").exists()


@pytest.mark.parametrize("root", ["control", "fleet/trusted-claw"])
@pytest.mark.parametrize("raw", [None, b"{}", b"not json", b'{"consumers":{},"consumers":{}}'])
def test_missing_or_malformed_either_manifest_never_selects_compatibility(tmp_path, root, raw):
    env = setup(tmp_path)
    path = tmp_path / root / auto.MANIFEST_PATH
    if raw is None:
        path.unlink()
    else:
        path.write_bytes(raw)
    selector, final = steps()
    assert shell(selector, tmp_path, env).returncode != 0
    env["AUTOMATIC_AVAILABLE"] = "false"
    assert shell(final, tmp_path, env).returncode != 0


@pytest.mark.parametrize("root", ["control", "fleet/trusted-claw"])
@pytest.mark.parametrize("identity", ["CultureBotAI/ScaleupMech", "culturebotai/scaleupmech"])
def test_reserved_identity_alias_is_not_a_public_only_manifest(tmp_path, root, identity):
    env = setup(tmp_path)
    path = tmp_path / root / auto.MANIFEST_PATH
    document = json.loads(path.read_bytes())
    document["consumers"]["aliasedmech"] = {"github": identity, "package_path": "src/aliasedmech"}
    path.write_text(json.dumps(document))
    selector, final = steps()
    assert shell(selector, tmp_path, env).returncode != 0
    env["AUTOMATIC_AVAILABLE"] = "false"
    assert shell(final, tmp_path, env).returncode != 0
    assert not (tmp_path / "automatic-verifier-called").exists()


@pytest.mark.parametrize("root", ["control", "fleet/trusted-claw"])
def test_reserved_key_requires_exact_supported_identity(tmp_path, root):
    env = setup(tmp_path)
    path = tmp_path / root / auto.MANIFEST_PATH
    document = json.loads(path.read_bytes())
    document["consumers"]["scaleupmech"] = {"github": "CultureBotAI/OtherMech", "package_path": "src/scaleupmech"}
    path.write_text(json.dumps(document))
    selector, final = steps()
    assert shell(selector, tmp_path, env).returncode != 0
    env["AUTOMATIC_AVAILABLE"] = "false"
    assert shell(final, tmp_path, env).returncode != 0


def test_complete_legacy_audits_and_required_aggregate_are_preserved():
    raw = (FIXTURES / "governance-fleet-audit.yaml.txt").read_bytes()
    assert hashlib.sha256(raw).hexdigest() == "79f2a9e91f8910e28242ffd940dacd330246b4a792fec190ed3fc49d27582bae"
    old = yaml.safe_load(raw)
    current = yaml.safe_load(WORKFLOW.read_text())
    assert current["jobs"]["candidate-contracts"] == old["jobs"]["candidate-contracts"]
    old_public = old["jobs"]["fleet-audit"]
    public = current["jobs"]["fleet-audit"]
    assert {k: v for k, v in public.items() if k != "steps"} == {k: v for k, v in old_public.items() if k != "steps"}
    old_steps = {s.get("name"): s for s in old_public["steps"]}
    current_steps = {s.get("name"): s for s in public["steps"]}
    assert current_steps.keys() == old_steps.keys()
    for name, step in old_steps.items():
        if step.get("id") != "automatic":
            assert current_steps[name] == step, name
    assert current["jobs"]["verified-fleet"]["steps"][:-1] == old["jobs"]["verified-fleet"]["steps"][:-1]
    for key in ("needs", "if", "name", "permissions"):
        assert current["jobs"]["verified-fleet"][key] == old["jobs"]["verified-fleet"][key]
    assert workflow_errors(WORKFLOW.read_text(), ["fleet-audit"]) == []


def test_selector_and_finalizer_compute_identical_mode():
    selector, final = steps()
    selector_code = selector["run"].split("<<'PYCODE'\n")[1].split("\nPYCODE")[0]
    final_code = final["run"].split("<<'PYCODE'\n")[1].split("\nPYCODE")[0]
    assert selector_code.split('with Path(os.environ["GITHUB_OUTPUT"])')[0] == final_code.split('if os.environ.get("AUTOMATIC_AVAILABLE")')[0]


@pytest.mark.parametrize("candidate,public", [
    ("success", "success"), ("failure", "success"), ("success", "failure"),
    ("success", "skipped"), ("skipped", "success"), ("cancelled", "success"),
    ("success", "cancelled"),
])
def test_aggregate_refuses_every_unsuccessful_dependency(tmp_path, candidate, public):
    workflow = yaml.safe_load(WORKFLOW.read_text())
    guard = workflow["jobs"]["verified-fleet"]["steps"][0]
    result = shell(guard, tmp_path, {"PATH": os.defpath, "CANDIDATE_RESULT": candidate, "PUBLIC_RESULT": public})
    assert (result.returncode == 0) is (candidate == public == "success")
