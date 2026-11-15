"""Offline exact merged-source and publication proof; no GitHub writes."""
from __future__ import annotations

import copy
import hashlib
import json
import subprocess

import pytest

from kg_microbe_governance.artifacts.scripts.auto_merge_ready_prs import Rules
from kg_microbe_workflows import freshness_release as release


def git(root, *args):
    return subprocess.check_output(['git', '-C', str(root), *args], text=True).strip()


@pytest.fixture
def source(tmp_path, monkeypatch):
    monkeypatch.setenv('GIT_CONFIG_NOSYSTEM', '1')
    monkeypatch.setenv('GIT_CONFIG_GLOBAL', '/dev/null')
    root = tmp_path / 'repo'
    root.mkdir()
    git(root, 'init', '-b', 'main')
    git(root, 'config', 'user.name', 'Offline fixture')
    git(root, 'config', 'user.email', 'fixture@example.invalid')
    git(root, 'config', 'commit.gpgsign', 'false')
    git(root, 'remote', 'add', 'origin', f'https://github.com/{release.REPOSITORY}.git')
    (root / 'README.md').write_text('base\n')
    git(root, 'add', '.')
    git(root, 'commit', '-m', 'base')
    base = git(root, 'rev-parse', 'HEAD')
    git(root, 'switch', '-c', 'feature')
    for path in release.PAYLOADS:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('reviewed payload ' + path)
    (root / release.DECLARATION).write_text(json.dumps(release.POLICY))
    git(root, 'add', '.')
    git(root, 'commit', '-m', 'reviewed feature')
    head = git(root, 'rev-parse', 'HEAD')
    tree = git(root, 'rev-parse', 'HEAD^{tree}')
    git(root, 'switch', 'main')
    git(root, 'merge', '--squash', 'feature')
    git(root, 'commit', '-m', 'squash feature')
    merge = git(root, 'rev-parse', 'HEAD')

    class API:
        def __init__(self):
            self.pull = {'number': 1128, 'state': 'closed', 'merged': True,
                         'merged_at': '2026-01-01T00:00:00Z', 'merge_commit_sha': merge,
                         'head': {'sha': head, 'repo': {'full_name': release.REPOSITORY}},
                         'base': {'ref': 'main', 'repo': {'full_name': release.REPOSITORY}}}
            self.main = merge
            self.required = Rules((('pytest', 15368),), False)
            self.conclusion = 'success'
            self.integrity = ''
        def pr(self, number):
            assert number == 1128
            return copy.deepcopy(self.pull)
        def rules(self):
            return self.required
        def checks(self, sha):
            assert sha == head
            return ([{'name': 'pytest', 'app': {'id': 15368}, 'head_sha': head,
                      'status': 'completed', 'conclusion': self.conclusion}], [])
        def integrity_reason(self):
            return self.integrity
        def get(self, endpoint):
            assert endpoint == f'repos/{release.REPOSITORY}/commits/main'
            return {'sha': self.main}
    return root, {'reviewed_head': head, 'merge_commit': merge,
                  'reviewed_base': base, 'reviewed_tree': tree}, API()


def test_exact_source_proof_has_public_payloads_and_no_adoption(source):
    root, args, api = source
    before = git(root, 'status', '--porcelain')
    result = release.audit_source(root, **args, api=api)
    assert result['source_commit'] == args['merge_commit']
    assert result['source_tree'] == args['reviewed_tree']
    assert set(result['payloads']) == set(release.PAYLOADS)
    assert result['payloads'][release.DECLARATION]['sha256'] == hashlib.sha256(
        (root / release.DECLARATION).read_bytes()).hexdigest()
    assert not result['installed'] and not result['adopted']
    assert str(root) not in json.dumps(result)
    assert git(root, 'status', '--porcelain') == before


@pytest.mark.parametrize('fault', ['unmerged', 'head', 'repository', 'base_branch', 'merge',
                                 'parent', 'tree', 'outside_main', 'checks', 'no_checks', 'integrity'])
def test_source_contradictions_hold(source, fault):
    root, args, api = source
    if fault == 'unmerged':
        api.pull['merged'] = False
    elif fault == 'head':
        api.pull['head']['sha'] = 'a' * 40
    elif fault == 'repository':
        api.pull['base']['repo']['full_name'] = 'Other/repo'
    elif fault == 'base_branch':
        api.pull['base']['ref'] = 'feature'
    elif fault == 'merge':
        api.pull['merge_commit_sha'] = args['reviewed_head']
    elif fault == 'parent':
        args['reviewed_base'] = args['reviewed_head']
    elif fault == 'tree':
        args['reviewed_tree'] = git(root, 'rev-parse', args['reviewed_base'] + '^{tree}')
    elif fault == 'outside_main':
        api.main = args['reviewed_base']
    elif fault == 'checks':
        api.conclusion = 'failure'
    elif fault == 'no_checks':
        api.required = Rules((), False)
    else:
        api.integrity = 'pending'
    with pytest.raises(release.ReleaseError):
        release.audit_source(root, **args, api=api)


def test_remote_race_holds(source):
    root, args, api = source
    observations = iter([args['merge_commit'], args['reviewed_base']])
    api.get = lambda endpoint: {'sha': next(observations)}
    with pytest.raises(release.ReleaseError, match='changed during'):
        release.audit_source(root, **args, api=api)


def test_wrong_remote_and_missing_payload_fail_closed(source):
    root, args, api = source
    git(root, 'remote', 'set-url', 'origin', 'https://github.com/Other/repo.git')
    with pytest.raises(release.ReleaseError, match='origin differs'):
        release.audit_source(root, **args, api=api)
    git(root, 'remote', 'set-url', 'origin', f'https://github.com/{release.REPOSITORY}.git')
    with pytest.raises(release.ReleaseError, match='payload missing'):
        release.Git(root).blob(args['reviewed_base'], release.DECLARATION)


def test_local_grafts_cannot_falsify_squash_parent_or_main_ancestry(source):
    root, args, api = source
    # A separate commit with the base's tree is NOT the actual squash parent.
    # A local graft must not turn it into authoritative release ancestry.
    fake = git(root, 'commit-tree', git(root, 'rev-parse', args['reviewed_base'] + '^{tree}'),
               '-p', args['reviewed_base'], '-m', 'not the actual reviewed parent')
    graft = root / '.git/info/grafts'
    graft.write_text(args['merge_commit'] + ' ' + fake + '\n')
    wrong = dict(args, reviewed_base=fake)
    with pytest.raises(release.ReleaseError, match='squash parent differs'):
        release.audit_source(root, **wrong, api=api)
    assert release.audit_source(root, **args, api=api)['source_commit'] == args['merge_commit']
    graft.write_text(args['merge_commit'] + '\n')
    assert release.audit_source(root, **args, api=api)['source_commit'] == args['merge_commit']


def test_duplicate_declaration_key_is_rejected():
    with pytest.raises(release.ReleaseError, match='duplicate'):
        json.loads('{"version":1,"version":2}', object_pairs_hook=release._pairs)


@pytest.fixture
def publication():
    audit = {'kind': 'verified_freshness_release_source', 'declaration': release.POLICY,
             'source_commit': 'a' * 40}
    raw = release.encoded(audit)
    class API:
        def __init__(self):
            self.ref = {'object': {'type': 'commit', 'sha': 'a' * 40}}
            self.release = {'id': 1, 'tag_name': release.TAG, 'draft': False,
                            'published_at': '2026-01-01T00:00:00Z', 'target_commitish': 'a' * 40,
                            'html_url': 'https://github.com/example/release', 'immutable': False}
            self.asset = {'name': 'release-audit.json', 'size': len(raw),
                          'digest': 'sha256:' + hashlib.sha256(raw).hexdigest()}
        def get(self, endpoint):
            if '/git/ref/' in endpoint:
                return copy.deepcopy(self.ref)
            assert endpoint.endswith('/releases/tags/' + release.TAG)
            return copy.deepcopy(self.release)
        def pages(self, endpoint):
            assert endpoint.endswith('/releases/1/assets')
            return [copy.deepcopy(self.asset)]
    return audit, API()


def test_publication_exact_asset_readback(publication):
    audit, api = publication
    result = release.verify_publication(audit, api)
    assert result['status'] == 'verified'
    assert result['release_immutable_observed'] is False
    assert result['adopted'] is False


@pytest.mark.parametrize('fault', ['tag', 'draft', 'target', 'unpublished', 'digest', 'size'])
def test_publication_mismatch_holds(publication, fault):
    audit, api = publication
    if fault == 'tag':
        api.ref['object']['sha'] = 'b' * 40
    elif fault == 'draft':
        api.release['draft'] = True
    elif fault == 'target':
        api.release['target_commitish'] = 'main'
    elif fault == 'unpublished':
        api.release['published_at'] = None
    elif fault == 'digest':
        api.asset['digest'] = 'sha256:' + 'b' * 64
    else:
        api.asset['size'] += 1
    with pytest.raises(release.ReleaseError):
        release.verify_publication(audit, api)


def test_tag_moves_during_readback(publication):
    audit, api = publication
    original = api.get
    calls = 0
    def get(endpoint):
        nonlocal calls
        if '/git/ref/' in endpoint:
            calls += 1
            if calls == 2:
                return {'object': {'type': 'commit', 'sha': 'b' * 40}}
        return original(endpoint)
    api.get = get
    with pytest.raises(release.ReleaseError, match='tag changed'):
        release.verify_publication(audit, api)
