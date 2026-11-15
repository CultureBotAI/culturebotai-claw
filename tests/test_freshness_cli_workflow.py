"""Complete approved workflow snapshots protect portable gate boundaries offline."""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest
import test_goal_freshness_cli as fixtures
import yaml
from test_goal_freshness import REPOSITORY, git

from kg_microbe_workflows import PARENT_PATH, load_effective_workflow, sha256
from kg_microbe_workflows import freshness_cli as cli
from scripts.mech_session_supervisor import digest as workflow_digest

gate_request = fixtures.gate_request
isolated_git = fixtures.isolated_git
profile = fixtures.profile
repo = fixtures.repo


def reference(path, value):
    path.write_text(json.dumps(value))
    return {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}


def bind_snapshot(request, effective):
    """Explicit synthetic operator fixture, never a live adoption record."""
    request['effective_workflow'] = reference(Path(request['effective_workflow']['path']), effective)
    request['workflow_sha256'] = workflow_digest(effective)
    path = Path(request['adoption']['path'])
    adoption = json.loads(path.read_text())
    adoption['boundary']['workflow_sha256'] = request['workflow_sha256']
    request['adoption'] = reference(path, adoption)


@pytest.fixture
def extension_gate(repo, gate_request):
    path = repo.checkout / 'workflow/mech-workflow.yaml'
    model = yaml.safe_load(path.read_text())
    schema = {'id': 'https://example.org/local', 'name': 'local', 'default_range': 'string',
              'types': {'string': {'base': 'str', 'uri': 'http://www.w3.org/2001/XMLSchema#string'}},
              'classes': {'Adaptation': {'attributes': {'domain': {'range': 'string', 'required': True}}}}}
    schema_raw = yaml.safe_dump(schema)
    data_raw = 'domain: Traits\n'
    model['extension'] = {'schema_path': 'schema/local.yaml', 'schema_sha256': sha256(schema_raw.encode()),
                          'data_path': 'adaptation.yaml', 'data_sha256': sha256(data_raw.encode()),
                          'class_name': 'Adaptation'}
    repo.publish('workflow/schema/local.yaml', schema_raw)
    repo.publish('workflow/adaptation.yaml', data_raw)
    repo.publish('workflow/mech-workflow.yaml', yaml.safe_dump(model, sort_keys=False))
    git(repo.checkout, 'fetch', 'origin')
    git(repo.checkout, 'merge', '--ff-only', 'origin/main')
    repo.initial = repo.head()
    effective = load_effective_workflow(PARENT_PATH, path)
    bind_snapshot(gate_request, effective)
    return gate_request


@pytest.mark.parametrize('phase', ['pre_goal', 'post_merge'])
@pytest.mark.parametrize('changed', ['workflow/adaptation.yaml', 'workflow/schema/local.yaml'])
def test_extension_change_holds_before_fast_forward(repo, extension_gate, phase, changed):
    request = extension_gate
    preserved = {}
    if phase == 'post_merge':
        initial = cli.execute(request, apply=True)
        preserved[initial['artifact']['path']] = Path(initial['artifact']['path']).read_bytes()
        own_merge = repo.publish('own.txt', 'actual merged work\n')
        request = copy.deepcopy(request)
        request.update(phase=phase, prior_inventory=initial['artifact'],
                       pull_requests=[{'number': 42, 'head_sha': 'e' * 40, 'merge_commit_sha': own_merge}])
        observed = {'number': 42, 'merged': True, 'merged_at': '2026-01-01T01:00:00Z',
                    'head': {'sha': 'e' * 40}, 'merge_commit_sha': own_merge,
                    'base': {'ref': 'main', 'repo': {'full_name': REPOSITORY}}}
    else:
        observed = {}
    old = repo.head()
    before = (repo.checkout / changed).read_bytes()
    repo.publish(changed, 'changed upstream\n')
    result = cli.execute(request, apply=True, observe_pr=lambda *args: observed)
    assert result['status'] == 'hold'
    assert result['reason'] == 'workflow_pin_change_requires_adoption'
    assert repo.head() == old
    assert (repo.checkout / changed).read_bytes() == before
    assert all(Path(path).read_bytes() == raw for path, raw in preserved.items())


def test_unchanged_extension_allows_new_code_and_preserves_snapshot(repo, extension_gate):
    snapshot_path = Path(extension_gate['effective_workflow']['path'])
    raw = snapshot_path.read_bytes()
    wanted = repo.publish('new-code.txt', 'unrelated code\n')
    first = cli.execute(extension_gate, apply=True)
    assert first['status'] == 'verified' and first['head'] == wanted == repo.head()
    artifact = cli.read_artifact(first['artifact'])
    assert artifact['effective_workflow'] == extension_gate['effective_workflow']
    assert cli.execute(extension_gate, apply=False)['reused_frozen_inventory']
    no_change = dict(extension_gate, phase='no_change', prior_inventory=first['artifact'])
    closure = cli.execute(no_change, apply=True)
    assert closure['status'] == 'verified'
    assert cli.read_artifact(closure['artifact'])['effective_workflow'] == extension_gate['effective_workflow']
    assert snapshot_path.read_bytes() == raw


@pytest.mark.parametrize('fault', ['missing', 'identity', 'omitted_extension', 'duplicate', 'kind', 'no_sources'])
def test_bad_snapshot_holds_without_fetch_or_inventory(repo, extension_gate, monkeypatch, fault):
    request = copy.deepcopy(extension_gate)
    snapshot = cli.read_artifact(request['effective_workflow'])
    if fault == 'missing':
        del request['effective_workflow']
    elif fault == 'identity':
        snapshot['profile_id'] = 'wrong-approved-content'
        request['effective_workflow'] = reference(Path(request['effective_workflow']['path']), snapshot)
    else:
        if fault == 'omitted_extension':
            snapshot['sources'] = [s for s in snapshot['sources'] if s['kind'] != 'extension']
        elif fault == 'duplicate':
            snapshot['sources'].append(copy.deepcopy(snapshot['sources'][0]))
        elif fault == 'kind':
            snapshot['sources'][0]['kind'] = 'invented'
        else:
            snapshot.pop('sources')
        # Even an accidentally approved malformed snapshot must not become a
        # partial-source exception to the actual native workflow loader.
        bind_snapshot(request, snapshot)
    def forbidden(*args, **kwargs):
        pytest.fail('Malformed workflow proof reached the Git mutation engine')
    monkeypatch.setattr(cli, 'ensure_freshness', forbidden)
    report = cli.run_batch([request], apply=True)
    assert report['status'] == 'hold'
    assert repo.head() == repo.initial
    assert not (repo.root / 'portable/boundaries').exists()


@pytest.mark.parametrize('phase', ['pre_goal', 'no_change', 'post_merge'])
def test_reuse_and_closure_require_original_snapshot_reference(repo, extension_gate, phase):
    initial = cli.execute(extension_gate, apply=True)
    alternate = repo.root / 'same-content-other-reference.json'
    request = copy.deepcopy(extension_gate)
    request['effective_workflow'] = reference(alternate, cli.read_artifact(request['effective_workflow']))
    if phase != 'pre_goal':
        request.update(phase=phase, prior_inventory=initial['artifact'])
    with pytest.raises(cli.FreshnessError, match='inventory_context_differs'):
        cli.execute(request, apply=True)
    assert repo.head() == repo.initial


def test_read_only_verify_rejects_changed_pinned_source(repo, extension_gate, monkeypatch):
    cli.execute(extension_gate, apply=True)
    (repo.checkout / 'workflow/adaptation.yaml').write_text('tampered after freeze\n')
    path = repo.root / 'verify-request.json'
    path.write_text(json.dumps([extension_gate]))
    monkeypatch.setattr(cli, 'ensure_freshness', lambda *a, **k: pytest.fail('verify attempted mutation'))
    assert cli.main(['verify', '--request', str(path)]) == 1
    assert repo.head() == repo.initial


def test_existing_supervisor_workflow_identity_is_preserved(repo, gate_request):
    effective = cli.read_artifact(gate_request['effective_workflow'])
    old_identity = workflow_digest(effective)
    assert old_identity != cli.digest(effective)
    assert gate_request['workflow_sha256'] == old_identity
    assert cli.execute(gate_request, apply=True)['status'] == 'verified'
    with pytest.raises(cli.FreshnessError, match='snapshot_identity_differs'):
        cli.frozen_workflow_sources(gate_request['effective_workflow'], root=repo.checkout,
                                    key='fixturemech', repository=REPOSITORY,
                                    workflow_sha256=cli.digest(effective))
