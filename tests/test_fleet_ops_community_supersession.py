"""Supersession replay counts the child's delta, excluding divergent base-only work."""
import json
import os
import subprocess
import sys
from pathlib import Path


def test_divergent_base_does_not_turn_base_only_files_into_child_contributions(tmp_path):
    checkout = tmp_path / 'community'
    checkout.mkdir()

    def git(*args):
        return subprocess.check_output(['git', '-C', str(checkout), *args], text=True).strip()

    def commit(name):
        git('add', name)
        git('-c', 'user.name=Offline Fixture', '-c', 'user.email=fixture@example.invalid',
            'commit', '-m', name)
        return git('rev-parse', 'HEAD')

    git('init', '-b', 'main')
    git('remote', 'add', 'origin', 'https://github.com/CultureBotAI/CommunityMech.git')
    (checkout / 'shared.txt').write_text('common\n')
    common = commit('shared.txt')
    git('checkout', '-b', 'divergent-base')
    (checkout / 'base-only.txt').write_text('not authored by child\n')
    base = commit('base-only.txt')
    git('checkout', '-b', 'child', common)
    (checkout / 'child.txt').write_text('preserved child contribution\n')
    child = commit('child.txt')
    baseline = tmp_path / 'baseline'
    baseline.mkdir()
    names = ['history', 'Audit Network Integrity', 'docs-current',
             'label-correspondence / label-correspondence', 'lint', 'validate-strict', 'vendored-sync']
    (baseline / 'pr-2804-baseline.json').write_text(json.dumps({
        'state': 'OPEN', 'headRefOid': child,
        'statusCheckRollup': [{'name': name, 'status': 'COMPLETED', 'conclusion': 'SUCCESS'} for name in names]}))
    (baseline / 'pr-1-baseline.json').write_text(json.dumps({'state': 'OPEN', 'headRefOid': child}))
    prior = tmp_path / 'prior.json'
    prior.write_text(json.dumps({'parent': child, 'children': [{
        'number': 1, 'head': child, 'base': base, 'changed_paths': 1,
        'identical_paths': 1, 'extended_paths': []}]}))
    dotenv = tmp_path / 'empty.env'
    dotenv.write_text('')
    source = Path(__file__).resolve().parents[1] / 'scripts/adhoc/fleet_ops_20261126/community_trait_review.py'
    output = tmp_path / 'result'
    result = subprocess.run([sys.executable, str(source), '--dotenv', str(dotenv),
        '--checkout', str(checkout), '--prior', str(prior), '--baseline', str(baseline),
        '--output', str(output)], capture_output=True, text=True, timeout=30,
        env={**os.environ, 'PYTHONPATH': str(source.parents[3])})
    assert result.returncode == 0, result.stderr
    replay = json.loads((output / 'replay.json').read_text())
    assert replay['children'][0]['changed_paths'] == 1
    assert replay['children'][0]['current_identical_paths'] == 1
    assert replay['children'][0]['current_different_paths'] == []
