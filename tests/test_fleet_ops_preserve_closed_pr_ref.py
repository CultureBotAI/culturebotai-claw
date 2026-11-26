"""Offline failure gates for the one-time closed-source retention helper."""
import importlib.util
import json
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest


@pytest.fixture
def helper(monkeypatch):
    path = Path(__file__).parents[1] / 'scripts/adhoc/fleet_ops_20261126/preserve_closed_pr_ref.py'
    spec = importlib.util.spec_from_file_location('preserve_closed_source', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    target = SimpleNamespace(path=Path('/fixture'), expected_repository='Fixture/Mech', open=lambda: None)
    settings = SimpleNamespace(get_target=lambda key: target)
    monkeypatch.setattr(module, 'RepositorySettings', SimpleNamespace(from_environment=lambda **kwargs: settings))
    monkeypatch.setattr(module, 'merged_repository_environment', lambda path: {})
    monkeypatch.setattr(module, 'LockManager', lambda: SimpleNamespace(lock=lambda *args: nullcontext()))
    monkeypatch.setattr(module.subprocess, 'check_output', lambda *args, **kwargs: '')
    probe = SimpleNamespace(returncode=1, stdout='{"message":"Not Found"}', stderr='HTTP 404')
    monkeypatch.setattr(module.subprocess, 'run', lambda *args, **kwargs: probe)
    head = 'a' * 40
    ref = 'refs/heads/steward/fleet-ops-20261126T0620Z-pr42-retained'
    pr = {'state': 'CLOSED', 'mergedAt': None, 'headRefOid': head}
    calls = []

    def fake_gh(*arguments):
        calls.append(arguments)
        if arguments[0] == 'pr':
            return pr
        if '/git/commits/' in arguments[-1]:
            return {'sha': head}
        return {'ref': ref, 'object': {'sha': head}}

    monkeypatch.setattr(module, 'gh', fake_gh)
    argv = ['preserve', '--dotenv', '/fixture.env', '--mech', 'fixture', '--pr', '42', '--head', head, '--ref', ref]
    monkeypatch.setattr('sys.argv', argv)
    return module, argv, probe, pr, calls


def test_dry_run_does_not_create(helper, capsys):
    module, _, _, _, calls = helper
    module.main()
    assert all('POST' not in call for call in calls)
    assert json.loads(capsys.readouterr().out)['applied'] is False


def test_apply_creates_exact_ref_once_then_reads_back(helper, capsys):
    module, argv, _, _, calls = helper
    argv.append('--apply')
    module.main()
    posts = [call for call in calls if 'POST' in call]
    assert len(posts) == 1
    assert posts[0][-4:] == ('-f', 'ref=' + argv[-2], '-f', 'sha=' + 'a' * 40)
    assert '/git/ref/heads/steward/' in calls[-1][-1]
    assert json.loads(capsys.readouterr().out)['remote_exact_head_verified'] is True


@pytest.mark.parametrize('change', ['existing', 'forbidden', 'open', 'merged', 'different_head'])
def test_refuses_before_creation(helper, change):
    module, argv, probe, pr, calls = helper
    argv.append('--apply')
    if change == 'existing':
        probe.returncode = 0
    elif change == 'forbidden':
        probe.stderr = 'HTTP 403'
    elif change == 'open':
        pr['state'] = 'OPEN'
    elif change == 'merged':
        pr['mergedAt'] = '2026-11-26T00:00:00Z'
    else:
        pr['headRefOid'] = 'b' * 40
    with pytest.raises((ValueError, RuntimeError)):
        module.main()
    assert all('POST' not in call for call in calls)
