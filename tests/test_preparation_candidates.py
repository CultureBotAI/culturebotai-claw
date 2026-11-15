"""Candidate admission is explicit, closed, provenance-bound and fleet-independent."""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess
from pathlib import Path

import pytest

import kg_microbe_governance as governance
from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_governance import candidates as candidates_module
from kg_microbe_governance.artifacts.scripts import check_vendored_sync as checker
from kg_microbe_governance.candidates import load_candidates, registry_bytes
from kg_microbe_skills.template import _identity
from plugins.repository_settings import RepositoryConfigurationError, RepositorySettings

ROOT = Path(__file__).resolve().parents[1]
KEY = "stressresponsemech"
PIN = "a" * 40


def manifest():
    return checker.parse_manifest((ROOT / checker.CANONICAL_MANIFEST_PATH).read_bytes())


def document():
    return json.loads(registry_bytes())


def parse(value):
    return checker.parse_candidate_registry(json.dumps(value).encode(), manifest())


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout.strip()


def repository(tmp_path):
    root = tmp_path / "StressResponseMech"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "remote", "add", "origin", "https://github.com/CultureBotAI/StressResponseMech.git")
    return root


def test_preparation_is_not_deployed_membership_or_capability_enablement():
    candidate = load_candidates()[KEY]
    assert KEY not in load_fleet_manifest().mechs
    assert KEY not in manifest().consumers
    assert set(candidate["capabilities"]) == set(load_fleet_manifest().capability_catalogue)
    assert {value["status"] for value in candidate["capabilities"].values()} <= {"disabled", "not_applicable"}
    with pytest.raises(RepositoryConfigurationError, match="Unknown repository"):
        RepositorySettings.from_environment(environ={}).get_target(KEY)
    identity = _identity(KEY)
    assert identity["candidate"] is True
    assert identity["values"]["schema_paths"] == "`src/stressresponsemech/schema/stressresponsemech.yaml`"


def test_candidate_target_revalidates_actual_origin_and_never_defaults_path(tmp_path):
    root = repository(tmp_path)
    target = RepositorySettings.get_candidate_target(KEY, root=root, environ={})
    assert target.path == root
    with pytest.raises(RepositoryConfigurationError, match="not configured"):
        RepositorySettings.get_candidate_target(KEY, environ={})
    with pytest.raises(RepositoryConfigurationError, match="Unknown preparation"):
        RepositorySettings.get_candidate_target("invented", root=root)
    git(root, "remote", "set-url", "origin", "https://github.com/CultureBotAI/AssayMech.git")
    with pytest.raises(RepositoryConfigurationError):
        RepositorySettings.get_candidate_target(KEY, root=root)
    with pytest.raises(RepositoryConfigurationError):
        target.open()


@pytest.mark.parametrize(("field", "value"), [
    ("github", "https://github.com/CultureBotAI/StressResponseMech"),
    ("github", "CultureBotAI/AssayMech"),
    ("package_path", "src/../escape"),
    ("package_path", "src/assaymech"),
    ("schema_paths", ["src/stressresponsemech/schema/../escape.yaml"]),
    ("schema_paths", ["src/foreign/schema/schema.yaml"]),
    ("record_globs", ["../data/*.yaml"]),
    ("record_globs", ["data/.git/*.yaml"]),
    ("environment_variable", "ROOT;BAD"),
    ("repository_id", True),
    ("bootstrap_main_ref", "main"),
    ("state", "active"),
    ("capabilities", {"testing": {"status": "enabled", "reason": "unsupported"}}),
])
def test_closed_registry_rejects_unsafe_or_unsealed_fields(field, value):
    doc = document()
    doc["candidates"][KEY][field] = value
    with pytest.raises(checker.GovernanceError):
        parse(doc)


def test_registry_rejects_duplicate_json_and_colliding_identities():
    with pytest.raises(checker.GovernanceError, match="duplicate"):
        checker.parse_candidate_registry(b'{"version":1,"version":1,"candidates":{}}', manifest())
    doc = document()
    doc["candidates"]["different"] = copy.deepcopy(doc["candidates"][KEY])
    with pytest.raises(checker.GovernanceError, match="collision"):
        parse(doc)
    doc = document()
    doc["candidates"][KEY]["source_url"] = "https://example.org/payload"
    with pytest.raises(checker.GovernanceError, match="unknown keys"):
        parse(doc)


def test_only_universal_artifacts_from_same_manifest_are_composed():
    base = manifest()
    prepared = checker.candidate_manifest(registry_bytes(), base, KEY)
    assert set(prepared.consumers) == {KEY}
    assert prepared.artifacts == tuple(item for item in base.artifacts if not item.consumers)
    assert any(item.consumers for item in base.artifacts), "Contrast requires scoped artifacts"
    with pytest.raises(checker.GovernanceError, match="Unknown preparation"):
        checker.candidate_manifest(registry_bytes(), base, "assaymech")


def fetcher(url):
    prefix = f"https://raw.githubusercontent.com/CultureBotAI/culturebotai-claw/{PIN}/"
    assert url.startswith(prefix)
    return (ROOT / url.removeprefix(prefix)).read_bytes()


def test_sync_and_standalone_check_require_explicit_candidate_and_exact_bytes(tmp_path, monkeypatch):
    root = repository(tmp_path)
    # This synthetic consumer runs inside controller CI, not its own workflow.
    monkeypatch.setenv("GITHUB_REPOSITORY", "CultureBotAI/culturebotai-claw")
    monkeypatch.setattr(governance, "fetch_url", fetcher)
    with pytest.raises(checker.GovernanceError, match="Unknown Mech"):
        governance.plan_sync(KEY, root, PIN)
    changes = governance.plan_sync(KEY, root, PIN, candidate=True)
    assert {change.artifact_id for change in changes} >= {"vendored_checker", "shared_mech_schema"}
    prepared = checker.candidate_manifest(registry_bytes(), manifest(), KEY)
    assert governance.sync_repository(KEY, root, PIN, candidate=True, apply=True) == changes
    assert governance.plan_sync(KEY, root, PIN, candidate=True) == ()
    target = root / checker.expand_target(prepared.artifacts[-1], prepared.consumer_for(KEY))
    assert checker.check_repository(root, repository=KEY, fetch=fetcher, candidate=True) == (len(prepared.artifacts), ())
    with pytest.raises(checker.GovernanceError, match="Unknown Mech"):
        checker.check_repository(root, fetch=fetcher, candidate=True)
    # Native CI supplies its own matching assertion; that ordinary path passes.
    monkeypatch.setenv("GITHUB_REPOSITORY", "CultureBotAI/StressResponseMech")
    assert checker.check_repository(root, fetch=fetcher, candidate=True) == (len(prepared.artifacts), ())
    with pytest.raises(checker.GovernanceError, match="Unknown Mech"):
        checker.check_repository(root, fetch=fetcher)
    with pytest.raises(checker.GovernanceError, match="Unknown Mech"):
        checker.check_repository(root, repository="assaymech", fetch=fetcher, candidate=True)
    target.write_bytes(b"drift")
    assert checker.check_repository(root, fetch=fetcher, candidate=True)[1]
    def changed_registry(url):
        raw = fetcher(url)
        return raw + b" " if url.endswith("candidates.json") else raw
    monkeypatch.setattr(governance, "fetch_url", changed_registry)
    with pytest.raises(checker.GovernanceError, match="registry differs"):
        governance.plan_sync(KEY, root, PIN, candidate=True)


def test_governed_checker_checksum_matches_source():
    artifact = next(item for item in manifest().artifacts if item.artifact_id == "vendored_checker")
    assert artifact.sha256 == hashlib.sha256((ROOT / artifact.source).read_bytes()).hexdigest()


@pytest.mark.parametrize("change", ["missing_capability", "fleet_root", "private_key", "private_package", "export_inapplicable"])
def test_packaged_candidate_completeness_and_reserved_identity_checks(change, monkeypatch):
    doc = document()
    candidate = doc["candidates"][KEY]
    if change == "missing_capability":
        del candidate["capabilities"]["testing"]
    elif change == "fleet_root":
        candidate["environment_variable"] = "ASSAYMECH_ROOT"
    elif change == "private_key":
        doc["candidates"]["scaleupmech"] = doc["candidates"].pop(KEY)
    elif change == "private_package":
        candidate["package_path"] = "src/scaleupmech"
        candidate["schema_paths"] = ["src/scaleupmech/schema/native.yaml"]
    else:
        candidate["capabilities"]["kgx_export"]["status"] = "not_applicable"
    monkeypatch.setattr(candidates_module, "registry_bytes", lambda: json.dumps(doc).encode())
    with pytest.raises(checker.GovernanceError):
        load_candidates()


@pytest.mark.parametrize("reserved", ["key", "github", "github_case"])
def test_control_plane_cannot_be_prepared_as_downstream_candidate(reserved):
    doc = document()
    if reserved == "key":
        doc["candidates"]["claw"] = doc["candidates"].pop(KEY)
    else:
        identity = manifest().canonical_repository
        doc["candidates"][KEY]["github"] = identity.swapcase() if reserved == "github_case" else identity
    with pytest.raises(checker.GovernanceError, match="reserved|collision"):
        parse(doc)
