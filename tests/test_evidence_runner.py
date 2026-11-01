"""Offline active-worktree and immutable-code boundary checks for #687."""

from __future__ import annotations

import json
import os
import py_compile
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "src/kg_microbe_governance/artifacts/scripts/run_shared_evidence_validator.py"


def git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false",
         "-C", str(root), *args],
        check=True, capture_output=True, text=True,
        env={k: v for k, v in os.environ.items() if not k.startswith("GIT_")},
    ).stdout.strip()


def init(root: Path, repository: str) -> None:
    root.mkdir()
    git(root, "init", "-b", "main")
    git(root, "config", "user.name", "Offline fixture")
    git(root, "config", "user.email", "fixture@example.invalid")
    git(root, "remote", "add", "origin", f"https://github.com/{repository}.git")


@pytest.fixture
def repositories(tmp_path):
    claw = tmp_path / "claw"
    init(claw, "CultureBotAI/culturebotai-claw")
    # Exercise the real manifest loader and RepositoryTarget, with only the
    # scientific validator replaced by an observable local dispatcher.
    for name in ["src/kg_microbe_fleet/__init__.py", "src/kg_microbe_fleet/fleet.yaml",
                 "plugins/repository_settings.py"]:
        destination = claw / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, destination)
    (claw / "plugins/__init__.py").write_text("")
    package = claw / "src/kg_microbe_evidence"
    package.mkdir()
    (package / "__init__.py").write_text("")
    (package / "__main__.py").write_text(
        "import json, os\nfrom pathlib import Path\n"
        "def main(argv):\n"
        "    root = Path(argv[argv.index('--root') + 1])\n"
        "    print(json.dumps({'argv': argv, 'payload': (root / 'payload.txt').read_text(),\n"
        "        'manifest': os.environ.get('KG_MICROBE_FLEET_MANIFEST')}))\n"
        "    return int(os.environ.get('EVIDENCE_FAKE_EXIT', '0'))\n"
    )
    git(claw, "add", ".")
    git(claw, "commit", "-m", "Pinned offline validator")
    pin = git(claw, "rev-parse", "HEAD")

    mech = tmp_path / "mech"
    init(mech, "CultureBotAI/MediaIngredientMech")
    (mech / "scripts").mkdir()
    shutil.copyfile(RUNNER, mech / "scripts/run_shared_evidence_validator.py")
    (mech / "scripts/.vendored_canon_ref").write_text(pin + "\n")
    (mech / "payload.txt").write_text("primary checkout")
    git(mech, "add", ".")
    git(mech, "commit", "-m", "Offline consumer")
    return claw, mech, pin


def invoke(claw, mech, *args, env=None):
    environment = dict(os.environ)
    environment.pop("CLAW_SRC", None)
    environment["CLAW_ROOT"] = str(claw)
    environment.update(env or {})
    return subprocess.run(
        [sys.executable, "-I", str(mech / "scripts/run_shared_evidence_validator.py"), *args],
        capture_output=True, text=True, env=environment, timeout=30,
    )


def test_runner_binds_active_worktree_not_primary_checkout(repositories, tmp_path):
    claw, primary, _ = repositories
    active = tmp_path / "active"
    git(primary, "worktree", "add", "--detach", str(active), "HEAD")
    (active / "payload.txt").write_text("active worktree")
    result = invoke(claw, active, "--strict", "--output-dir", "workspace/custom")
    assert result.returncode == 0, result.stderr
    observed = json.loads(result.stdout)
    assert observed["payload"] == "active worktree"
    assert observed["argv"] == ["--mech", "mediaingredientmech", "--root", str(active.resolve()),
                                "--strict", "--output-dir", "workspace/custom"]
    assert observed["manifest"] == str(claw / "src/kg_microbe_fleet/fleet.yaml")


@pytest.mark.parametrize("pin", ["main\n", "a" * 39, "A" * 40, "a" * 40 + "\nextra", "", "a" * 40 + "\n\n"])
def test_malformed_pin_never_reaches_shared_validator(repositories, pin):
    claw, mech, _ = repositories
    (mech / "scripts/.vendored_canon_ref").write_text(pin)
    result = invoke(claw, mech)
    assert result.returncode == 2 and "canonical pin" in result.stderr.lower()
    assert not result.stdout


def test_wrong_claw_revision_never_reaches_shared_validator(repositories):
    claw, mech, pin = repositories
    git(claw, "commit", "--allow-empty", "-m", "Different revision")
    assert git(claw, "rev-parse", "HEAD") != pin
    result = invoke(claw, mech)
    assert result.returncode == 2 and "HEAD does not match" in result.stderr
    assert not result.stdout


def test_dirty_claw_code_never_reaches_shared_validator(repositories):
    claw, mech, _ = repositories
    (claw / "src/kg_microbe_evidence/__main__.py").write_text("raise AssertionError('unreviewed')\n")
    result = invoke(claw, mech)
    assert result.returncode == 2 and "tracked changes" in result.stderr
    assert not result.stdout


def test_wrong_consumer_origin_and_conflicting_push_identity_reject(repositories):
    claw, mech, _ = repositories
    git(mech, "remote", "set-url", "origin", "https://github.com/Other/NotAFleetMech")
    result = invoke(claw, mech)
    assert result.returncode == 2 and "unique declared Mech" in result.stderr
    git(mech, "remote", "set-url", "origin", "https://github.com/CultureBotAI/MediaIngredientMech")
    git(mech, "remote", "set-url", "--push", "origin", "https://github.com/Other/NotAFleetMech")
    result = invoke(claw, mech)
    assert result.returncode == 2 and "identities do not agree" in result.stderr


def test_wrong_claw_origin_rejects_without_disclosing_credentials(repositories):
    claw, mech, _ = repositories
    git(claw, "remote", "set-url", "origin", "https://private-secret@github.com/CultureBotAI/culturebotai-claw")
    result = invoke(claw, mech)
    assert result.returncode == 2 and "GitHub repository identity" in result.stderr
    assert "private-secret" not in result.stderr
    assert not result.stdout


def test_missing_explicit_claw_root_does_not_use_sibling_or_legacy_override(repositories):
    claw, mech, _ = repositories
    result = invoke(claw, mech, env={"CLAW_ROOT": "", "CLAW_SRC": str(claw / "src")})
    assert result.returncode == 2 and "Set CLAW_ROOT" in result.stderr
    assert not result.stdout


def test_source_symlink_pin_is_not_authority(repositories, tmp_path):
    claw, mech, pin = repositories
    elsewhere = tmp_path / "elsewhere-pin"
    elsewhere.write_text(pin + "\n")
    path = mech / "scripts/.vendored_canon_ref"
    path.unlink()
    path.symlink_to(elsewhere)
    result = invoke(claw, mech)
    assert result.returncode == 2 and "non-symlink" in result.stderr


def test_manifest_override_cannot_replace_pinned_scope(repositories, tmp_path):
    claw, mech, _ = repositories
    unrelated = tmp_path / "unrelated.yaml"
    unrelated.write_text("invalid: unrelated\n")
    result = invoke(claw, mech, env={"KG_MICROBE_FLEET_MANIFEST": str(unrelated)})
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["manifest"] == str(claw / "src/kg_microbe_fleet/fleet.yaml")


def test_shared_validation_failure_propagates(repositories):
    claw, mech, _ = repositories
    result = invoke(claw, mech, "--strict", env={"EVIDENCE_FAKE_EXIT": "2"})
    assert result.returncode == 2
    assert "--strict" in json.loads(result.stdout)["argv"]


def test_cli_cannot_redirect_consumer_root_or_identity(repositories):
    claw, mech, _ = repositories
    result = invoke(claw, mech, "--root", str(claw))
    assert result.returncode == 2 and "unrecognized arguments" in result.stderr
    assert not result.stdout


def test_pinned_source_ignores_timestamp_valid_stale_bytecode(repositories):
    """#689: -I/-B still read a same-size/mtime cache unless redirected."""
    claw, mech, _ = repositories
    baseline = invoke(claw, mech, "--strict", env={"EVIDENCE_FAKE_EXIT": "2"})
    assert baseline.returncode == 2 and '"argv"' in baseline.stdout
    source = claw / "src/kg_microbe_evidence/__main__.py"
    original, stat = source.read_bytes(), source.stat()
    stale = b"def main(argv):\n    print('UNPINNED STALE BYTECODE RAN')\n    return 0\n"
    stale += b"#" * (len(original) - len(stale))
    assert len(stale) == len(original)
    source.write_bytes(stale)
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    cache = source.parent / "__pycache__" / f"{source.stem}.{sys.implementation.cache_tag}.pyc"
    py_compile.compile(str(source), cfile=str(cache), doraise=True)
    source.write_bytes(original)
    os.utime(source, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    assert git(claw, "status", "--porcelain", "--untracked-files=no") == ""
    replay = invoke(claw, mech, "--strict", env={"EVIDENCE_FAKE_EXIT": "2"})
    assert replay.returncode == 2 and '"argv"' in replay.stdout
    assert "UNPINNED" not in replay.stdout + replay.stderr
    assert cache.is_file(), "the user's existing cache must be preserved"


@pytest.mark.parametrize("ignored", [False, True])
@pytest.mark.parametrize("relative", ["src/yaml.py", "yaml.py", "yaml/__init__.py", "plugins/shadow.py"])
def test_importable_shadow_is_rejected_including_ignored_files(repositories, ignored, relative):
    claw, mech, _ = repositories
    shadow = claw / relative
    shadow.parent.mkdir(parents=True, exist_ok=True)
    shadow.write_text("raise AssertionError('UNPINNED SHADOW EXECUTED')\n")
    if ignored:
        (claw / ".git/info/exclude").write_text(relative + "\n")
        assert git(claw, "check-ignore", relative) == relative
        assert relative not in git(claw, "ls-files", "--others", "--exclude-standard")
    assert git(claw, "status", "--porcelain", "--untracked-files=no") == ""
    result = invoke(claw, mech, "--strict")
    assert result.returncode == 2 and "untracked or ignored importable code" in result.stderr
    assert "UNPINNED" not in result.stdout + result.stderr


def test_preloaded_shared_module_cannot_substitute_for_pinned_source(repositories):
    claw, mech, _ = repositories
    code = (
        "import importlib.util, sys, types\nfrom pathlib import Path\n"
        "spec = importlib.util.spec_from_file_location('runner', sys.argv[1])\n"
        "module = importlib.util.module_from_spec(spec)\nspec.loader.exec_module(module)\n"
        "fake = types.ModuleType('kg_microbe_evidence.__main__')\n"
        "fake.main = lambda argv: 0\n"
        "sys.modules['kg_microbe_evidence.__main__'] = fake\n"
        "raise SystemExit(module.main(['--strict'], root=Path(sys.argv[2]), "
        "environment={'CLAW_ROOT': sys.argv[3]}))\n"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", code, str(RUNNER), str(mech), str(claw)],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 2 and "Preloaded Claw modules" in result.stderr
    assert not result.stdout


@pytest.mark.parametrize("flag", ["skip-worktree", "assume-unchanged"])
@pytest.mark.parametrize("relative", ["src/kg_microbe_evidence/__main__.py", "src/kg_microbe_fleet/fleet.yaml"])
def test_index_flags_cannot_hide_source_or_resource_drift(repositories, flag, relative):
    """#694: status is clean but imported bytes must still equal Git HEAD."""
    claw, mech, _ = repositories
    baseline = invoke(claw, mech, "--strict", env={"EVIDENCE_FAKE_EXIT": "2"})
    assert baseline.returncode == 2 and '"argv"' in baseline.stdout
    git(claw, "update-index", "--" + flag, relative)
    target = claw / relative
    if relative.endswith(".py"):
        target.write_text("def main(argv):\n    print('UNPINNED HIDDEN SOURCE RAN')\n    return 0\n")
    else:
        target.write_text(target.read_text() + "\n# hidden resource drift\n")
    changed = target.read_bytes()
    flags = git(claw, "ls-files", "-v", "--", relative)
    assert git(claw, "status", "--porcelain", "--untracked-files=no") == ""
    result = invoke(claw, mech, "--strict", env={"EVIDENCE_FAKE_EXIT": "2"})
    assert result.returncode == 2 and "source or resource differs from HEAD" in result.stderr
    assert not result.stdout
    assert target.read_bytes() == changed
    assert git(claw, "ls-files", "-v", "--", relative) == flags


@pytest.mark.parametrize("replacement", ["symlink", "directory", "mode"])
def test_hidden_import_path_must_be_regular_and_keep_committed_mode(repositories, tmp_path, replacement):
    claw, mech, _ = repositories
    relative = "src/kg_microbe_evidence/__main__.py"
    target = claw / relative
    original = target.read_bytes()
    git(claw, "update-index", "--skip-worktree", relative)
    if replacement == "symlink":
        outside = tmp_path / "outside.py"
        outside.write_bytes(original)
        target.unlink()
        target.symlink_to(outside)
    elif replacement == "directory":
        target.unlink()
        target.mkdir()
    else:
        git(claw, "config", "core.fileMode", "false")
        target.chmod(0o755)
    assert git(claw, "status", "--porcelain", "--untracked-files=no") == ""
    result = invoke(claw, mech)
    assert result.returncode == 2
    assert "Pinned Claw import" in result.stderr and not result.stdout
