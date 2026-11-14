"""Behavioral coverage of template drift in the existing maintenance rail."""
from pathlib import Path
from types import SimpleNamespace

import pytest

from kg_microbe_fleet.roots import MechRootError
from kg_microbe_skills import template_fleet


def test_consumer_drift_retains_full_coverage(tmp_path, monkeypatch):
    keys = ['missing', 'unadopted', 'current', 'drift', 'conflict']
    monkeypatch.setattr(template_fleet, 'load_fleet_manifest',
                        lambda: SimpleNamespace(mechs=dict.fromkeys(keys)))
    for key in keys[1:]:
        path = tmp_path / key / 'workflow'
        path.mkdir(parents=True)
        if key != 'unadopted':
            (path / 'mech-template.json').write_text('{}')

    def resolve(key, **kwargs):
        if key == 'missing':
            raise MechRootError('not configured')
        return tmp_path / key

    def plan(root, **kwargs):
        if root.name == 'conflict':
            raise template_fleet.CatalogueError('canonical region names differ')
        return SimpleNamespace(report={'repository': root.name, 'status': root.name})

    monkeypatch.setattr(template_fleet, 'resolve_mech_root', resolve)
    monkeypatch.setattr(template_fleet, 'plan_repository', plan)
    report = template_fleet.collect_template_drift(tmp_path)
    rows = {r['repository']: r for r in report['repositories']}
    assert set(rows) == set(keys)
    assert rows['missing']['status'] == 'not_configured'
    assert rows['unadopted']['status'] == 'not_adopted'
    assert rows['drift']['status'] == 'drift'
    assert rows['conflict']['status'] == 'error'
    assert not report['ok']
    assert template_fleet.main(['--claw-root', str(tmp_path)]) == 1


def test_unadopted_is_visible_without_claiming_deployment(tmp_path, monkeypatch):
    monkeypatch.setattr(template_fleet, 'load_fleet_manifest',
                        lambda: SimpleNamespace(mechs={'newmech': None}))
    monkeypatch.setattr(template_fleet, 'resolve_mech_root', lambda *a, **k: tmp_path)
    monkeypatch.setattr(template_fleet, 'plan_repository',
                        lambda *a, **k: pytest.fail('must not plan absent adoption'))
    report = template_fleet.collect_template_drift(tmp_path)
    assert report['repositories'] == [{'repository': 'newmech', 'status': 'not_adopted'}]
    assert report['ok']


def test_maintenance_runs_template_checks_and_retains_drift_details(tmp_path, monkeypatch):
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
    import fleet_maintenance_cycle as cycle

    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if 'kg_microbe_skills.template_fleet' in command:
            return SimpleNamespace(returncode=1, stdout='{"repositories": [{"status": "drift"}]}', stderr='')
        return SimpleNamespace(returncode=0, stdout='OK', stderr='')

    monkeypatch.setattr(cycle.subprocess, 'run', run)
    report = cycle.run_governance_checks(tmp_path)
    assert any('kg_microbe_skills.template_cli' in call for call in calls)
    assert report['template_baseline']['ok']
    assert not report['template_consumers']['ok']
    assert 'drift' in report['template_consumers']['details']


def test_ci_checkout_retains_baseline_source_revision(tmp_path):
    """Exercise the configured checkout depth against an actual two-commit source."""
    import os
    import subprocess

    import yaml

    workflow = yaml.safe_load((Path(__file__).resolve().parents[1] / '.github/workflows/tests.yaml').read_text())
    checkout = next(step for step in workflow['jobs']['pytest']['steps']
                    if step.get('uses', '').startswith('actions/checkout@'))
    depth = checkout.get('with', {}).get('fetch-depth', 1)
    source = tmp_path / 'source'
    source.mkdir()
    env = {**os.environ, 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': os.devnull,
           'GIT_AUTHOR_NAME': 'Fixture', 'GIT_AUTHOR_EMAIL': 'fixture@example.org',
           'GIT_COMMITTER_NAME': 'Fixture', 'GIT_COMMITTER_EMAIL': 'fixture@example.org'}

    def git(*args):
        return subprocess.run(['git', *args], env=env, text=True, capture_output=True, check=True).stdout.strip()

    git('init', '-q', str(source))
    (source / 'authority').write_text('canonical input\n')
    git('-C', str(source), 'add', 'authority')
    git('-C', str(source), 'commit', '-qm', 'source')
    source_ref = git('-C', str(source), 'rev-parse', 'HEAD')
    (source / 'baseline').write_text(source_ref)
    git('-C', str(source), 'add', 'baseline')
    git('-C', str(source), 'commit', '-qm', 'baseline')
    clone = tmp_path / 'checkout'
    args = ['clone', '-q'] + (['--depth', str(depth)] if depth else [])
    git(*args, source.as_uri(), str(clone))
    assert git('-C', str(clone), 'show', f'{source_ref}:authority') == 'canonical input'
