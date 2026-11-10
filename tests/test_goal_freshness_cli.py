"""Offline executable batch handoff; no live goals or provider gate_requests."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
from test_goal_freshness import REPOSITORY, git, isolated_git  # noqa: F401
from test_goal_freshness import repo as _repo

from kg_microbe_workflows import freshness_cli as cli
from kg_microbe_workflows.freshness import FreshnessError

repo = _repo


@pytest.fixture
def gate_request(repo, monkeypatch):
    path = repo.root / 'adoption.json'
    record = {'boundary': {'run_id': 'test', 'cycle': 1, 'predecessor_receipt_sha256': None},
              'contract_sha256': 'b' * 64}
    path.write_text(json.dumps(record))
    ref = {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    monkeypatch.setattr(cli, 'repository_identity', lambda key: REPOSITORY)
    monkeypatch.setattr(cli, 'load_adoption', lambda *args, **kwargs: record)
    return {'schema_version': '1.0.0', 'repository_key': 'fixturemech',
            'repository_root': str(repo.checkout), 'lock_directory': str(repo.root / 'locks'),
            'receipt_directory': str(repo.root / 'portable'), 'protected_roots': [],
            'adoption': ref, 'boundary_id': 'cycle2-stage1', 'phase': 'pre_goal',
            'workflow_sha256': 'a' * 64, 'prior_inventory': None, 'pull_requests': []}


def test_batch_inventory_reads_fetched_tree_after_persisted_head(repo, gate_request):
    wanted = repo.publish('INFRA_TASKS.md', 'New external backlog\n')
    result = cli.run_batch([gate_request], apply=True)
    assert result['status'] == 'verified'
    row = result['results'][0]
    artifact = cli.read_artifact(row['artifact'])
    assert row['head'] == artifact['head'] == repo.head() == wanted
    infra = next(item for item in artifact['files'] if item['path'] == 'INFRA_TASKS.md')
    assert infra['object_sha'] == git(repo.writer, 'rev-parse', 'HEAD:INFRA_TASKS.md')
    assert artifact['completion_authority'] is False


def test_held_gate_never_reads_inventory(repo, gate_request, monkeypatch):
    (repo.checkout / 'tracked.txt').write_text('active work')
    original = cli.Git.run
    def run(self, *args, **kwargs):
        assert args[0] != 'ls-tree'
        return original(self, *args, **kwargs)
    monkeypatch.setattr(cli.Git, 'run', run)
    result = cli.run_batch([gate_request], apply=True)
    assert result['status'] == 'hold'
    assert repo.head() == repo.initial


def test_post_merge_requires_actual_merge_and_fetches_newer_external_commit(repo, gate_request):
    initial = cli.execute(gate_request, apply=True)
    frozen = Path(initial['artifact']['path']).read_bytes()
    merged = repo.publish('own.txt', 'own merged change')
    newest = repo.publish('INFRA_TASKS.md', 'newer independent backlog')
    post = copy.deepcopy(gate_request)
    post.update(phase='post_merge', prior_inventory=initial['artifact'],
                pull_requests=[{'number': 42, 'head_sha': 'e' * 40, 'merge_commit_sha': merged}])
    remote = {'number': 42, 'merged': True, 'merged_at': '2026-01-01T01:00:00Z',
              'head': {'sha': 'e' * 40}, 'merge_commit_sha': merged,
              'base': {'repo': {'full_name': REPOSITORY}, 'ref': 'main'}}
    result = cli.execute(post, apply=True, observe_pr=lambda *args: remote)
    assert result['head'] == newest == repo.head()
    artifact = cli.read_artifact(result['artifact'])
    assert artifact['merges'][0]['merge_commit_sha'] == merged
    assert artifact['freshness']['fetched'] != merged
    assert Path(initial['artifact']['path']).read_bytes() == frozen


def test_unmerged_pr_cannot_authorize_post_merge(repo, gate_request):
    initial = cli.execute(gate_request, apply=True)
    gate_request.update(phase='post_merge', prior_inventory=initial['artifact'],
                   pull_requests=[{'number': 42, 'head_sha': 'e' * 40, 'merge_commit_sha': 'f' * 40}])
    with pytest.raises(FreshnessError, match='actual_merge_identity'):
        cli.execute(gate_request, apply=True, observe_pr=lambda *args: {'number': 42, 'merged': False})
    assert repo.head() == repo.initial


def test_active_goal_cannot_be_replaced_by_new_goal_gate_request(repo, gate_request):
    initial = cli.execute(gate_request, apply=True)
    gate_request['prior_inventory'] = initial['artifact']
    with pytest.raises(FreshnessError, match='cannot_replace'):
        cli.execute(gate_request, apply=True)


def test_no_change_goal_still_runs_pre_goal_fetch(repo, gate_request):
    calls = []
    original = cli.Git.run
    def record(self, *args, **kwargs):
        calls.append(args[0])
        return original(self, *args, **kwargs)
    from unittest.mock import patch
    with patch.object(cli.Git, 'run', record):
        result = cli.execute(gate_request, apply=True)
    assert result['status'] == 'verified'
    assert 'fetch' in calls and 'ls-tree' in calls


def test_batch_reports_partial_failure_nonzero_without_hiding_success(repo, gate_request):
    bad = copy.deepcopy(gate_request)
    bad['boundary_id'] = 'different-goal'
    bad['extra'] = True
    result = cli.run_batch([gate_request, bad], apply=True)
    assert result['status'] == 'hold'
    assert [row['status'] for row in result['results']] == ['verified', 'hold']


def test_repeated_boundary_never_refreezes_after_remote_advance(repo, gate_request):
    first = cli.execute(gate_request, apply=True)
    raw = Path(first['artifact']['path']).read_bytes()
    old = repo.head()
    repo.publish('INFRA_TASKS.md', 'new remote work after freeze')
    with pytest.raises(FreshnessError, match='remote_moved'):
        cli.execute(gate_request, apply=True)
    assert repo.head() == old
    assert Path(first['artifact']['path']).read_bytes() == raw


def test_no_change_closure_keeps_inventory_and_rejects_new_remote(repo, gate_request):
    first = cli.execute(gate_request, apply=True)
    gate_request.update(phase='no_change', prior_inventory=first['artifact'])
    closed = cli.execute(gate_request, apply=True)
    assert closed['kind'] == 'verified_no_change_freshness'
    old = repo.head()
    repo.publish('INFRA_TASKS.md', 'late unrelated change')
    with pytest.raises(FreshnessError, match='remote_moved'):
        cli.execute(gate_request, apply=True)
    assert repo.head() == old


def test_frozen_inventory_repeat_is_idempotent(repo, gate_request):
    first = cli.execute(gate_request, apply=True)
    second = cli.execute(gate_request, apply=True)
    assert first['artifact'] == second['artifact']
    assert second['reused_frozen_inventory'] is True
