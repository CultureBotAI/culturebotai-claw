"""Boundary adoption never follows from a candidate or edited workflow pin."""
import hashlib
import json

import pytest

from kg_microbe_workflows import WorkflowError
from kg_microbe_workflows.freshness_contract import (
    canonical_contract,
    contract_sha256,
    load_adoption,
)


def approved(tmp_path):
    root = tmp_path / 'repo'
    root.mkdir()
    record = {
        'schema_version': '1.0.0', 'authority': 'approved_boundary_adoption',
        'repository_key': 'mediaingredientmech',
        'github_repository': 'CultureBotAI/MediaIngredientMech',
        'repository_root': str(root), 'canonical_release_commit': 'a' * 40,
        'contract_sha256': contract_sha256(),
        'boundary': {'run_id': 'run-1', 'cycle': 2, 'stage': 1,
                     'workflow_sha256': 'b' * 64,
                     'predecessor_receipt_sha256': 'c' * 64},
        'approval': {'record_id': 'operator-approved-1', 'approved_at': '2026-01-01T00:00:00Z',
                     'approved_by': 'operator'},
    }
    path = tmp_path / 'adoption.json'
    def save():
        path.write_text(json.dumps(record))
        return hashlib.sha256(path.read_bytes()).hexdigest()
    kwargs = dict(expected_sha256=save(), repository_key='mediaingredientmech',
                  repository_root=root, workflow_sha256='b' * 64, run_id='run-1',
                  cycle=2, predecessor_receipt_sha256='c' * 64)
    return record, path, kwargs, save


def test_contract_schema_and_exact_boundary(tmp_path):
    contract = canonical_contract()
    assert contract['pre_goal_before_inventory'] is True
    assert contract['post_merge_before_closure'] is True
    assert contract['no_change_goals'] is True
    record, path, kwargs, _ = approved(tmp_path)
    before = path.read_bytes()
    assert load_adoption(path, **kwargs) == record
    assert path.read_bytes() == before


@pytest.mark.parametrize('field,value', [
    ('authority', 'proposal_only'), ('schema_version', '2.0.0'),
    ('repository_key', 'claw'), ('github_repository', 'other/repo'),
    ('canonical_release_commit', 'main'), ('contract_sha256', 'd' * 64),
])
def test_candidate_and_identity_are_not_adoption(tmp_path, field, value):
    record, path, kwargs, save = approved(tmp_path)
    record[field] = value
    kwargs['expected_sha256'] = save()
    with pytest.raises(WorkflowError):
        load_adoption(path, **kwargs)


@pytest.mark.parametrize('field,value', [
    ('cycle', 3), ('cycle', True), ('stage', 2), ('stage', True),
    ('workflow_sha256', 'd' * 64), ('predecessor_receipt_sha256', None),
])
def test_wrong_or_active_boundary_refuses(tmp_path, field, value):
    record, path, kwargs, save = approved(tmp_path)
    record['boundary'][field] = value
    kwargs['expected_sha256'] = save()
    with pytest.raises(WorkflowError):
        load_adoption(path, **kwargs)


def test_missing_configuration_digest_and_extra_fields_refuse(tmp_path):
    record, path, kwargs, save = approved(tmp_path)
    record['extra'] = True
    with pytest.raises(WorkflowError, match='digest'):
        save()
        load_adoption(path, **kwargs)
    kwargs['expected_sha256'] = save()
    with pytest.raises(WorkflowError, match='fields'):
        load_adoption(path, **kwargs)


def test_symlink_and_duplicate_json_refuse(tmp_path):
    _, path, kwargs, _ = approved(tmp_path)
    alias = tmp_path / 'alias.json'
    alias.symlink_to(path)
    with pytest.raises(WorkflowError, match='symlink'):
        load_adoption(alias, **kwargs)
    path.write_text('{"authority":"proposal_only","authority":"approved_boundary_adoption"}')
    kwargs['expected_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
    with pytest.raises(WorkflowError, match='JSON|duplicate'):
        load_adoption(path, **kwargs)


def test_original_v1_v2_parent_bytes_remain_available():
    from kg_microbe_workflows import LEGACY_PARENT_PATH, PARENT_PATH, load_document
    assert load_document(LEGACY_PARENT_PATH.read_bytes())['version'].startswith('1.')
    assert load_document(PARENT_PATH.read_bytes())['version'] == '2.0.0'
    assert 'repository_freshness' not in load_document(PARENT_PATH.read_bytes())
