"""Assay's and Cofactor's independently sealed bootstrap pins never select current bytes."""
import hashlib
import json
from pathlib import Path

import pytest
from test_governance_admitted_sync import frozen_payload, repository

import kg_microbe_governance as governance
from kg_microbe_governance.artifacts.scripts.check_vendored_sync import (
    CANONICAL_MANIFEST_PATH,
    parse_manifest,
)
from kg_microbe_governance.consumer_admission import SPECS

ROOT = Path(__file__).parents[1]
REFS = {
    "cofactormech": "5790569efd881bd8bca82a04ea278cc462c0c2c8",
    "assaymech": "89bfcebaee8a0fcf99055b2acd1709abb64f8666",
}


def _configure_native_source(spec, monkeypatch):
    raw = (ROOT / spec.snapshot).read_bytes()
    manifest = parse_manifest(raw)
    payloads = {CANONICAL_MANIFEST_PATH: raw}
    for artifact in manifest.artifacts:
        payloads[artifact.source] = frozen_payload(artifact)
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


@pytest.mark.parametrize("spec", SPECS, ids=lambda s: s.consumer.key)
def test_native_sync_uses_frozen_payload_when_current_package_differs(tmp_path, monkeypatch, spec):
    native_source = _configure_native_source(spec, monkeypatch)
    old = different_current_package(tmp_path, native_source, monkeypatch)
    ref = REFS[spec.consumer.key]
    root = repository(tmp_path, spec.consumer.github)
    plan = governance.plan_sync(spec.consumer.key, root, ref)
    assert len(plan) == 23 and not (root / "scripts").exists()
    assert governance.sync_repository(spec.consumer.key, root, ref, apply=True) == plan
    assert (root / "docs/record-reviews.md").read_bytes() == old
    assert (root / "scripts/.vendored_canon_ref").read_text() == ref + "\n"


@pytest.mark.parametrize("spec", SPECS, ids=lambda s: s.consumer.key)
@pytest.mark.parametrize("case", ["wrong_identity", "cross_consumer_pin", "wrong_ref", "generic_verifier", "manifest_corrupt", "payload_corrupt"])
def test_native_source_is_exact_and_never_a_generic_exception(tmp_path, monkeypatch, spec, case):
    other_spec = next(s for s in SPECS if s.consumer.key != spec.consumer.key)
    source_spec = other_spec if case == "cross_consumer_pin" else spec
    native_source = _configure_native_source(source_spec, monkeypatch)
    different_current_package(tmp_path, native_source, monkeypatch)
    ref = REFS[source_spec.consumer.key]
    root = repository(tmp_path, "CultureBotAI/TraitMech" if case == "wrong_identity" else spec.consumer.github)
    if case == "manifest_corrupt":
        native_source[CANONICAL_MANIFEST_PATH] += b"\n"
    if case == "payload_corrupt":
        native_source["src/kg_microbe_governance/artifacts/docs/record-reviews.md"] += b"\n"
    with pytest.raises(governance.GovernanceError):
        if case == "generic_verifier":
            governance.verify_canonical_ref(ref)
        else:
            governance.sync_repository("traitmech" if case == "wrong_identity" else spec.consumer.key, root,
                                       "a" * 40 if case == "wrong_ref" else ref, apply=True)
    assert not (root / "scripts").exists()


def test_ordinary_canonical_equality_remains_supported(monkeypatch):
    current = governance.load_governance_manifest()
    payloads = {CANONICAL_MANIFEST_PATH: (ROOT / CANONICAL_MANIFEST_PATH).read_bytes()}
    payloads.update({a.source: (ROOT / a.source).read_bytes() for a in current.artifacts})
    monkeypatch.setattr(governance, "fetch_url", lambda url: payloads[url.split("/", 6)[-1]])
    assert governance.verify_canonical_ref("c" * 40) == current
