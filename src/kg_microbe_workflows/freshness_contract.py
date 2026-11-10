"""Versioned freshness policy and immutable operator-approved boundary adoption.

A proposal, a PR source commit, or a matching policy hash is not approval. The
operator-owned configuration's exact adoption SHA is the trust boundary. The
caller must prove the real boundary and released source before configuring it;
this module only validates that immutable record and its supplied context.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kg_microbe_fleet import FleetManifest, load_fleet_manifest

from . import WorkflowError, _validator, load_document

CONTRACT_PATH = Path(__file__).parent / 'templates/repository-freshness-v1.yaml'
CONTRACT_SCHEMA = Path(__file__).parent / 'schema/repository-freshness-v1.yaml'
_BOOL_KEYS = frozenset({
    'pre_goal_before_inventory', 'post_merge_before_closure', 'no_change_goals',
    'canonical_remote_only', 'clean_default_branch_only', 'actual_merge_ancestry',
    'verify_fetched_revision', 'bounded_ref_race', 'preserve_frozen_workflow',
    'live_control_requires_deployment',
})
_RECORD_FIELDS = frozenset({
    'schema_version', 'authority', 'repository_key', 'github_repository',
    'repository_root', 'canonical_release_commit', 'contract_sha256',
    'boundary', 'approval',
})
_BOUNDARY_FIELDS = frozenset({
    'run_id', 'cycle', 'stage', 'workflow_sha256', 'predecessor_receipt_sha256',
})


def _digest(value: Any, width: int = 64) -> str:
    if not isinstance(value, str) or not re.fullmatch('[0-9a-f]{' + str(width) + '}', value):
        raise WorkflowError('freshness requires a complete lowercase digest')
    return value


def _text(value: Any) -> str:
    if not isinstance(value, str) or not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise WorkflowError('freshness requires nonempty safe text')
    return value


def repository_identity(key: str, manifest: FleetManifest | None = None) -> str:
    if manifest is None:
        if 'KG_MICROBE_FLEET_MANIFEST' in os.environ:
            raise WorkflowError('freshness identity forbids ambient manifest overrides')
        manifest = load_fleet_manifest(Path(__file__).parents[1] / 'kg_microbe_fleet/fleet.yaml')
    if key == 'claw':
        return 'CultureBotAI/culturebotai-claw'
    try:
        return manifest.get(key).github
    except (KeyError, ValueError) as exc:
        raise WorkflowError('freshness repository is outside the canonical fleet') from exc


def canonical_contract() -> dict[str, Any]:
    contract = load_document(CONTRACT_PATH.read_bytes())
    errors = list(_validator(CONTRACT_SCHEMA.read_text(), 'RepositoryFreshnessContract').iter_errors(contract))
    if errors or any(contract.get(key) is not True for key in _BOOL_KEYS):
        raise WorkflowError('canonical freshness contract is invalid or weakened')
    return contract


def contract_sha256() -> str:
    canonical_contract()
    return hashlib.sha256(CONTRACT_PATH.read_bytes()).hexdigest()


def _pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in items:
        if key in result:
            raise WorkflowError('duplicate freshness record key')
        result[key] = value
    return result


def load_adoption(
    path: Path, *, expected_sha256: str, repository_key: str,
    repository_root: Path, workflow_sha256: str, run_id: str, cycle: int,
    predecessor_receipt_sha256: str | None,
) -> dict[str, Any]:
    """Read one approved record; never install, migrate, fetch or edit anything.

    The caller supplies the freshly verified boundary, including the exact
    verified prior closure receipt digest (null only for an assessed initial
    boundary). Existing stages must retain their original adoption context.
    """
    path = Path(path)
    if not path.is_absolute() or path.resolve() != path:
        raise WorkflowError('freshness adoption path must be absolute and have no symlink')
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 65536:
                raise WorkflowError('freshness adoption must be a bounded regular file')
            raw = stream.read(65537)
        if len(raw) > 65536:
            raise WorkflowError('freshness adoption exceeds the byte bound')
    except OSError as exc:
        raise WorkflowError('freshness adoption cannot be read safely') from exc
    if hashlib.sha256(raw).hexdigest() != _digest(expected_sha256):
        raise WorkflowError('freshness adoption configuration digest differs')
    try:
        record = json.loads(raw, object_pairs_hook=_pairs)
    except (ValueError, UnicodeError) as exc:
        raise WorkflowError('invalid freshness adoption JSON') from exc
    if not isinstance(record, dict) or set(record) != _RECORD_FIELDS:
        raise WorkflowError('freshness adoption has unknown or missing fields')
    if record['schema_version'] != '1.0.0' or record['authority'] != 'approved_boundary_adoption':
        raise WorkflowError('freshness proposal has no execution authority')
    if record['repository_key'] != repository_key or record['github_repository'] != repository_identity(repository_key):
        raise WorkflowError('freshness adoption repository identity differs')
    root = Path(repository_root)
    if not root.is_absolute() or root.resolve() != root or record['repository_root'] != str(root):
        raise WorkflowError('freshness adoption checkout differs or aliases another path')
    _digest(record['canonical_release_commit'], 40)
    if record['contract_sha256'] != contract_sha256():
        raise WorkflowError('freshness adoption policy differs from the installed contract')
    boundary = record['boundary']
    if not isinstance(boundary, dict) or set(boundary) != _BOUNDARY_FIELDS:
        raise WorkflowError('freshness adoption boundary has unknown or missing fields')
    _text(run_id)
    if type(cycle) is not int or cycle < 1 or type(boundary['cycle']) is not int or type(boundary['stage']) is not int:
        raise WorkflowError('freshness adoption requires an integral cycle boundary')
    _digest(workflow_sha256)
    if predecessor_receipt_sha256 is not None:
        _digest(predecessor_receipt_sha256)
    expected = {'run_id': run_id, 'cycle': cycle, 'stage': 1,
                'workflow_sha256': workflow_sha256,
                'predecessor_receipt_sha256': predecessor_receipt_sha256}
    if boundary != expected:
        raise WorkflowError('freshness adoption does not match the verified boundary')
    approval = record['approval']
    if not isinstance(approval, dict) or set(approval) != {'record_id', 'approved_at', 'approved_by'}:
        raise WorkflowError('freshness approval has unknown or missing fields')
    _text(approval['record_id'])
    _text(approval['approved_by'])
    try:
        approved = datetime.fromisoformat(_text(approval['approved_at']).replace('Z', '+00:00'))
    except ValueError as exc:
        raise WorkflowError('freshness approval needs an aware UTC timestamp') from exc
    if approved.tzinfo is None or approved.utcoffset() != timezone.utc.utcoffset(approved) or approved > datetime.now(timezone.utc):
        raise WorkflowError('freshness approval needs a past aware UTC timestamp')
    return record
