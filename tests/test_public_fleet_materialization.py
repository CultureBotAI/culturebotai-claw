"""Real, offline Git materialization with the production no-lazy-fetch guard."""

import hashlib
import subprocess
from dataclasses import replace

import pytest

from kg_microbe_governance import automatic_fleet_component as component
from kg_microbe_governance import private_scaleup_audit as manual
from kg_microbe_governance.artifacts.scripts.check_vendored_sync import (
    Artifact,
    Consumer,
    GovernanceManifest,
    _git_environment,
)


def fixture_git(root, *arguments):
    return subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", *arguments],
        cwd=root,
        env=_git_environment(),
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout.strip()


@pytest.fixture
def local_public_remote(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    fixture_git(source, "init", "--template=", "--initial-branch=main")
    payloads = {
        "scripts/.vendored_canon_ref": b"a" * 40 + b"\n",
        "scripts/payload.py": b"# reviewed protected payload\n",
        "src/publicmech/candidate.txt": b"candidate lane payload\n",
        "corpus/unrequested.txt": b"unrelated scientific fixture\n",
    }
    for name, raw in payloads.items():
        path = source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    fixture_git(source, "add", ".")
    fixture_git(
        source, "-c", "user.name=Offline fixture", "-c",
        "user.email=fixture@example.invalid", "commit", "-m", "offline fixture",
    )
    head = fixture_git(source, "rev-parse", "HEAD")
    remote = tmp_path / "remote.git"
    fixture_git(tmp_path, "clone", "--bare", str(source), str(remote))
    # The server really supports filters. Reintroducing blob:none must fail,
    # rather than passing because a local clone silently ignored the filter.
    fixture_git(remote, "config", "uploadpack.allowFilter", "true")
    consumer = Consumer("publicmech", "CultureBotAI/PublicMech", "src/publicmech")
    protected_artifact = Artifact(
        "protected", "canonical/payload.py", "scripts/payload.py", (),
        hashlib.sha256(payloads["scripts/payload.py"]).hexdigest(), 0o644,
    )
    candidate_artifact = Artifact(
        "candidate", "canonical/candidate.txt", "{package_path}/candidate.txt", (),
        hashlib.sha256(payloads["src/publicmech/candidate.txt"]).hexdigest(), 0o644,
    )
    protected = GovernanceManifest(
        "CultureBotAI/culturebotai-claw", "scripts/.vendored_canon_ref",
        {consumer.key: consumer}, (protected_artifact,),
    )
    candidate = replace(protected, artifacts=(protected_artifact, candidate_artifact))
    return remote, head, payloads, {"protected": protected, "candidate": candidate}


def install_local_transport(monkeypatch, remote, *, metadata_change=None, force_filtered=False):
    """Inject only metadata and one exact clone URL; every Git command is real."""
    metadata_calls, commands = [], []

    class Metadata:
        def __init__(self, allowed):
            assert allowed == {"CultureBotAI/PublicMech"}

        def get(self, name):
            assert name == "CultureBotAI/PublicMech"
            metadata_calls.append(name)
            return {
                "full_name": name, "private": False, "default_branch": "main",
                **(metadata_change or {}),
            }

    original_git = component.git
    original_run = subprocess.run

    def route(root, *arguments):
        if arguments[0] == "clone":
            assert arguments[-2] == "https://github.com/CultureBotAI/PublicMech.git"
            arguments = (*arguments[:-2], remote.as_uri(), arguments[-1])
            if force_filtered:
                # Negative-only fixture: a promisor clone has missing objects.
                # A reachable source must not allow implicit hydration to pass.
                arguments = (
                    "clone", "--filter=blob:none",
                    *(arg for arg in arguments[1:] if not arg.startswith("--filter=")),
                )
        return original_git(root, *arguments)

    def observed_run(command, *arguments, **kwargs):
        assert command[0] == "git"
        assert kwargs["env"]["GIT_NO_LAZY_FETCH"] == "1"
        assert kwargs["env"]["GIT_NO_REPLACE_OBJECTS"] == "1"
        commands.append(tuple(command))
        return original_run(command, *arguments, **kwargs)

    monkeypatch.setattr(component, "PublicRepositoryMetadata", Metadata)
    monkeypatch.setattr(component, "git", route)
    monkeypatch.setattr(component.subprocess, "run", observed_run)
    return metadata_calls, commands


def test_real_public_clone_materializes_both_lanes_without_lazy_fetch(
    tmp_path, monkeypatch, local_public_remote,
):
    remote, head, payloads, values = local_public_remote
    metadata, commands = install_local_transport(monkeypatch, remote)
    roots = component.clone_public(None, tmp_path / "clones", values)
    target = roots["publicmech"]
    assert set(roots) == {"publicmech"}
    assert metadata == ["CultureBotAI/PublicMech"]
    assert sum("clone" in command for command in commands) == 1
    assert component.git(target, "rev-parse", "HEAD") == head
    assert component.git(target, "rev-parse", "refs/remotes/origin/main") == head
    for name, raw in payloads.items():
        if name.startswith("corpus/"):
            assert not (target / name).exists()
        else:
            assert (target / name).read_bytes() == raw
            blob = component.git(target, "rev-parse", "HEAD:" + name)
            expected = hashlib.sha1(
                b"blob " + str(len(raw)).encode() + b"\0" + raw
            ).hexdigest()
            assert blob == expected
    assert component.git(target, "status", "--porcelain=v1", "--untracked-files=all") == ""


@pytest.mark.parametrize(
    "metadata_change",
    [{"private": True}, {"full_name": "Other/Repository"}, {"default_branch": "other"}],
)
def test_unverified_public_metadata_never_starts_git(
    tmp_path, monkeypatch, local_public_remote, metadata_change,
):
    remote, _, _, values = local_public_remote
    _, commands = install_local_transport(
        monkeypatch, remote, metadata_change=metadata_change,
    )
    with pytest.raises(manual.AuditError, match="source_unverified"):
        component.clone_public(None, tmp_path / "refused", values)
    assert commands == []


def test_existing_clone_workspace_is_preserved(
    tmp_path, monkeypatch, local_public_remote,
):
    remote, _, _, values = local_public_remote
    metadata, commands = install_local_transport(monkeypatch, remote)
    workspace = tmp_path / "owned"
    workspace.mkdir()
    retained = workspace / "evidence.txt"
    retained.write_bytes(b"unique evidence")
    with pytest.raises(FileExistsError):
        component.clone_public(None, workspace, values)
    assert retained.read_bytes() == b"unique evidence"
    assert metadata == commands == []


def test_real_clone_failure_returns_no_materialized_checkout(
    tmp_path, monkeypatch, local_public_remote,
):
    _, _, _, values = local_public_remote
    _, commands = install_local_transport(monkeypatch, tmp_path / "missing.git")
    workspace = tmp_path / "failed"
    with pytest.raises(subprocess.CalledProcessError):
        component.clone_public(None, workspace, values)
    assert len(commands) == 1
    assert not (workspace / "publicmech/scripts/payload.py").exists()


def test_missing_promised_objects_hold_even_when_source_is_reachable(
    tmp_path, monkeypatch, local_public_remote,
):
    remote, _, _, values = local_public_remote
    _, commands = install_local_transport(monkeypatch, remote, force_filtered=True)
    workspace = tmp_path / "unmaterialized"
    with pytest.raises(subprocess.CalledProcessError) as failure:
        component.clone_public(None, workspace, values)
    assert failure.value.returncode == 128
    assert b"lazy fetching disabled" in failure.value.stderr
    assert any("checkout" in command for command in commands)
    assert not (workspace / "publicmech/scripts/payload.py").exists()
