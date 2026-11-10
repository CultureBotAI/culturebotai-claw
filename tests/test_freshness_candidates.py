"""Isolated consumer proposals are inert, exact-source and batch-preflighted."""
import json
import subprocess
from pathlib import Path

import pytest

from kg_microbe_governance import freshness_candidates as candidates


@pytest.fixture(autouse=True)
def offline_owners(monkeypatch):
    # OS process inventory is tested by the shared engine and the real canary.
    # These unit tests inject deterministic owner observations, never call lsof.
    monkeypatch.setattr(candidates, 'owner_snapshot', lambda roots, allowed: {'cwd_holders': {}})


def git(root, *args):
    return subprocess.run(['git', '-C', str(root), *args], check=True,
                          capture_output=True, text=True).stdout.strip()


def repo(path, identity, branch='candidate/freshness'):
    path.mkdir()
    git(path, 'init', '-b', branch)
    git(path, 'config', 'user.name', 'Fixture')
    git(path, 'config', 'user.email', 'fixture@example.invalid')
    git(path, 'remote', 'add', 'origin', 'https://github.com/' + identity + '.git')
    (path / 'README.md').write_text('original\n')
    git(path, 'add', '.')
    git(path, 'commit', '-m', 'initial')
    return path


def setup(tmp_path):
    source = repo(tmp_path / 'claw', 'CultureBotAI/culturebotai-claw')
    for relative in candidates.SOURCE_PATHS.values():
        package = Path(candidates.__file__).parents[1] / relative.removeprefix('src/')
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(package.read_bytes())
    git(source, 'add', '.')
    git(source, 'commit', '-m', 'candidate canonical source')
    target = repo(tmp_path / 'mim', 'CultureBotAI/MediaIngredientMech')
    for relative in candidates.PRESERVED_PATHS:
        path = target / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('frozen original ' + relative + '\n')
    git(target, 'add', '.')
    git(target, 'commit', '-m', 'frozen workflow')
    key = 'mediaingredientmech'
    head = git(target, 'rev-parse', 'HEAD')
    row = {'root': str(target), 'expected_head': head, 'expected_branch': 'candidate/freshness',
           'default_branch': 'main',
           'ownership': {'owner_id': 'test-owner', 'repository_key': key, 'root': str(target),
                         'head': head, 'branch': 'candidate/freshness'}}
    args = dict(source_root=source, source_commit=git(source, 'rev-parse', 'HEAD'),
                root_map={key: row}, locks_dir=tmp_path / 'locks', owner_id='test-owner', keys=[key])
    assert len(candidates._source(source, args['source_commit'])) == 3
    return target, args


def test_batch_dry_run_apply_readback_and_frozen_pins(tmp_path):
    target, args = setup(tmp_path)
    old = {p: (target / p).read_bytes() for p in candidates.PRESERVED_PATHS}
    dry = candidates.prepare_batch(**args)
    assert dry['selected'] == 1 and dry['canonical_denominator'] >= 16
    assert dry['results'][0]['status'] == 'would_prepare'
    assert not (target / candidates.CANDIDATE_PATH).exists()
    result = candidates.prepare_batch(**args, apply=True)
    assert result['results'][0]['status'] == 'prepared'
    proposal = json.loads((target / candidates.CANDIDATE_PATH / 'proposal.json').read_text())
    assert proposal['authority'] == 'proposal_only'
    assert proposal['canonical_source']['reviewed_source_commit'] == args['source_commit']
    assert proposal['canonical_source']['released'] is False
    assert proposal['installed'] is False and proposal['adopted'] is False
    assert {p: (target / p).read_bytes() for p in old} == old
    assert git(target, 'rev-parse', 'HEAD') == args['root_map']['mediaingredientmech']['expected_head']
    assert 'MediaIngredientMech' in (target / candidates.CANDIDATE_PATH / 'SKILL.md').read_text()


@pytest.mark.parametrize('case', ['dirty', 'staged', 'untracked', 'ignored_collision', 'wrong_remote',
                                  'head_race', 'other_owner', 'default', 'operation', 'detached'])
def test_unsafe_targets_hold_without_candidate(tmp_path, case):
    target, args = setup(tmp_path)
    row = args['root_map']['mediaingredientmech']
    candidates.prepare_batch(**args)  # Prove the same fixture is eligible before the defect.
    if case in {'dirty', 'staged'}:
        (target / 'README.md').write_text('changed')
        if case == 'staged':
            git(target, 'add', '.')
    elif case == 'untracked':
        (target / 'evidence').write_text('unique')
    elif case == 'ignored_collision':
        (target / '.git/info/exclude').write_text('workflow/candidates/\n')
        destination = target / candidates.CANDIDATE_PATH
        destination.mkdir(parents=True)
        (destination / 'unique.txt').write_text('keep')
    elif case == 'wrong_remote':
        git(target, 'remote', 'set-url', 'origin', 'https://github.com/other/repo.git')
    elif case == 'head_race':
        git(target, 'commit', '--allow-empty', '-m', 'race')
    elif case == 'other_owner':
        row['ownership']['owner_id'] = 'other'
    elif case == 'default':
        row['default_branch'] = row['expected_branch']
    elif case == 'operation':
        (target / '.git/index.lock').write_text('owner')
    elif case == 'detached':
        git(target, 'checkout', '--detach')
    with pytest.raises((candidates.CandidateError, ValueError)):
        candidates.prepare_batch(**args, apply=True)
    assert not (target / candidates.CANDIDATE_PATH / 'proposal.json').exists()
    if case == 'ignored_collision':
        assert (target / candidates.CANDIDATE_PATH / 'unique.txt').read_text() == 'keep'


def test_source_different_bytes_and_scope_omission_fail_closed(tmp_path):
    target, args = setup(tmp_path)
    source = args['source_root']
    (source / candidates.SOURCE_PATHS['contract.yaml']).write_text('weak policy')
    git(source, 'add', '.')
    git(source, 'commit', '-m', 'bad source')
    args['source_commit'] = git(source, 'rev-parse', 'HEAD')
    with pytest.raises(candidates.CandidateError, match='source payload'):
        candidates.prepare_batch(**args)
    args['keys'] = None
    with pytest.raises(candidates.CandidateError, match='exactly cover'):
        candidates.prepare_batch(**args)
    assert not (target / candidates.CANDIDATE_PATH).exists()


def test_noncolliding_ignored_evidence_is_preserved(tmp_path):
    target, args = setup(tmp_path)
    (target / '.git/info/exclude').write_text('evidence/\n')
    (target / 'evidence').mkdir()
    (target / 'evidence/review.txt').write_text('unique')
    candidates.prepare_batch(**args, apply=True)
    assert (target / 'evidence/review.txt').read_text() == 'unique'


def test_live_shared_owner_holds_and_recheck_detects_new_owner(tmp_path, monkeypatch):
    target, args = setup(tmp_path)
    calls = []
    def owner(roots, allowed):
        calls.append((roots, allowed))
        assert target in roots and allowed == {}
        if len(calls) >= 3:
            raise candidates.FreshnessError('other_live_owner:123')
        return {'cwd_holders': {}}
    monkeypatch.setattr(candidates, 'owner_snapshot', owner)
    with pytest.raises(candidates.CandidateError, match='other_live_owner'):
        candidates.prepare_batch(**args, apply=True)
    assert len(calls) == 3
    assert not (target / candidates.CANDIDATE_PATH).exists()


def test_explicit_claw_consumer_is_prepared_without_live_fallback(tmp_path):
    _, args = setup(tmp_path)
    claw = repo(tmp_path / 'claw-consumer', 'CultureBotAI/culturebotai-claw')
    head = git(claw, 'rev-parse', 'HEAD')
    args['keys'] = ['claw']
    args['root_map'] = {'claw': {
        'root': str(claw), 'expected_head': head, 'expected_branch': 'candidate/freshness',
        'default_branch': 'main', 'ownership': {
            'owner_id': 'test-owner', 'repository_key': 'claw', 'root': str(claw),
            'head': head, 'branch': 'candidate/freshness'}}}
    result = candidates.prepare_batch(**args, apply=True)
    assert result['results'][0]['repository_key'] == 'claw'
    assert (claw / candidates.CANDIDATE_PATH / 'proposal.json').exists()


def test_individual_candidate_file_ignore_is_rejected(tmp_path):
    target, args = setup(tmp_path)
    (target / '.git/info/exclude').write_text('proposal.json\n')
    with pytest.raises(candidates.CandidateError, match='ignored'):
        candidates.prepare_batch(**args, apply=True)
    assert not (target / candidates.CANDIDATE_PATH).exists()


def test_all_targets_preflight_before_first_write(tmp_path):
    target, args = setup(tmp_path)
    second = repo(tmp_path / 'community', 'CultureBotAI/CommunityMech')
    head = git(second, 'rev-parse', 'HEAD')
    args['keys'].append('communitymech')
    args['root_map']['communitymech'] = {
        'root': str(second), 'expected_head': head, 'expected_branch': 'candidate/freshness',
        'default_branch': 'main', 'ownership': {
            'owner_id': 'test-owner', 'repository_key': 'communitymech', 'root': str(second),
            'head': head, 'branch': 'candidate/freshness'}}
    (second / 'unique-evidence.txt').write_text('keep')
    with pytest.raises(candidates.CandidateError, match='untracked'):
        candidates.prepare_batch(**args, apply=True)
    assert not (target / candidates.CANDIDATE_PATH).exists()
    assert (second / 'unique-evidence.txt').read_text() == 'keep'
