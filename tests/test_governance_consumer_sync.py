"""Scaleup's independently sealed bootstrap pin never selects current bytes."""
import hashlib
import json
from pathlib import Path

import pytest
from test_governance_admitted_sync import repository

import kg_microbe_governance as governance
from kg_microbe_governance.artifacts.scripts.check_vendored_sync import (
    CANONICAL_MANIFEST_PATH,
    parse_manifest,
)
from kg_microbe_governance.consumer_admission import SPECS

ROOT = Path(__file__).parents[1]
REF = "88e719d5480d0008d6ce082510dcd066775f232b"


@pytest.fixture
def native_source(monkeypatch):
    raw = (ROOT / next(spec for spec in SPECS if spec.consumer.key == "scaleupmech").snapshot).read_bytes()
    manifest = parse_manifest(raw)
    payloads = {CANONICAL_MANIFEST_PATH: raw}
    for artifact in manifest.artifacts:
        content = (ROOT / artifact.source).read_bytes()
        assert hashlib.sha256(content).hexdigest() == artifact.sha256
        payloads[artifact.source] = content
    monkeypatch.setattr(governance, "fetch_url", lambda url: payloads[url.split("/", 6)[-1]])
    return payloads


def different_current_package(tmp_path, native_source, monkeypatch):
    """Force canonical equality and native historical routing to differ."""
    source_path = "src/kg_microbe_governance/artifacts/docs/record-reviews.md"
    old = native_source[source_path]
    current = old + b"\nDifferent current package payload.\n"
    manifest = json.loads((ROOT / CANONICAL_MANIFEST_PATH).read_bytes())
    next(a for a in manifest["artifacts"] if a["source"] == source_path)["sha256"] = hashlib.sha256(current).hexdigest()
    changed_manifest, changed_payload = tmp_path / "manifest.json", tmp_path / "payload.md"
    changed_manifest.write_text(json.dumps(manifest))
    changed_payload.write_bytes(current)
    resource = governance._artifact_resource
    monkeypatch.setattr(governance, "_manifest_resource", lambda: changed_manifest)
    monkeypatch.setattr(governance, "_artifact_resource", lambda path: changed_payload if path == source_path else resource(path))
    return old


def test_native_sync_uses_frozen_payload_when_current_package_differs(tmp_path, native_source, monkeypatch):
    old = different_current_package(tmp_path, native_source, monkeypatch)
    root = repository(tmp_path, "CultureBotAI/ScaleupMech")
    plan = governance.plan_sync("scaleupmech", root, REF)
    assert len(plan) == 23 and not (root / "scripts").exists()
    assert governance.sync_repository("scaleupmech", root, REF, apply=True) == plan
    assert (root / "docs/record-reviews.md").read_bytes() == old
    assert (root / "scripts/.vendored_canon_ref").read_text() == REF + "\n"


@pytest.mark.parametrize("case", ["wrong_identity", "wrong_ref", "generic_verifier", "manifest_corrupt", "payload_corrupt"])
def test_native_source_is_exact_and_never_a_generic_exception(tmp_path, native_source, monkeypatch, case):
    different_current_package(tmp_path, native_source, monkeypatch)
    root = repository(tmp_path, "CultureBotAI/TraitMech" if case == "wrong_identity" else "CultureBotAI/ScaleupMech")
    if case == "manifest_corrupt":
        native_source[CANONICAL_MANIFEST_PATH] += b"\n"
    if case == "payload_corrupt":
        native_source["src/kg_microbe_governance/artifacts/docs/record-reviews.md"] += b"\n"
    with pytest.raises(governance.GovernanceError):
        if case == "generic_verifier":
            governance.verify_canonical_ref(REF)
        else:
            governance.sync_repository("traitmech" if case == "wrong_identity" else "scaleupmech", root,
                                       "a" * 40 if case == "wrong_ref" else REF, apply=True)
    assert not (root / "scripts").exists()


def test_ordinary_canonical_equality_remains_supported(monkeypatch):
    current = governance.load_governance_manifest()
    payloads = {CANONICAL_MANIFEST_PATH: (ROOT / CANONICAL_MANIFEST_PATH).read_bytes()}
    payloads.update({a.source: (ROOT / a.source).read_bytes() for a in current.artifacts})
    monkeypatch.setattr(governance, "fetch_url", lambda url: payloads[url.split("/", 6)[-1]])
    assert governance.verify_canonical_ref("c" * 40) == current
