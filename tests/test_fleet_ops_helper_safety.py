"""Offline regressions for the retained fleet campaign helpers; no action replay."""
import hashlib
import json
import subprocess
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.adhoc.fleet_ops_20261126 import (
    complete_git_batches,
    group_intake,
    guarded_gh,
    pr_batches,
)

ROOT = Path(__file__).resolve().parents[1]
HELPERS = ROOT / 'scripts/adhoc/fleet_ops_20261126'
REPOSITORY = 'CultureBotAI/EdgeMech'


@pytest.mark.parametrize('flag', [
    ['--repo', REPOSITORY], ['-R', REPOSITORY],
    [f'--repo={REPOSITORY}'], [f'-R{REPOSITORY}'],
])
def test_explicit_matching_repository_forms(flag):
    command = ['issue', 'edit', '7', *flag, '--add-label', 'bug']
    assert guarded_gh.validated_command(command, REPOSITORY) == command


@pytest.mark.parametrize('command', [
    ['issue', 'close', '7', '--repo', 'CultureBotAI/HabitatMech'],
    ['issue', 'close', '7', '--repo', REPOSITORY, '-R', 'CultureBotAI/HabitatMech'],
    ['issue', 'close', '7', '--repo', REPOSITORY, f'--repo={REPOSITORY}'],
    ['issue', 'close', 'https://github.com/CultureBotAI/HabitatMech/issues/7', '--repo', REPOSITORY],
    ['pr', 'close', 'https://github.com/CultureBotAI/HabitatMech/pull/7', '--repo', REPOSITORY],
    ['issue', 'close', '7'],
    ['pr', 'close', '7', '--repo', REPOSITORY, '--delete-branch'],
    ['issue', 'edit', '7', '--repo', REPOSITORY],
    ['issue', 'comment', '7', '--repo', REPOSITORY],
    ['issue', 'create', '--repo', REPOSITORY, '--title', 'missing explicit body'],
    ['pr', 'create', '--repo', REPOSITORY, '--title', 'forbidden', '--body', 'body'],
])
def test_repository_override_url_or_interactive_operation_refuses(command):
    with pytest.raises(ValueError):
        guarded_gh.validated_command(command, REPOSITORY)


def test_matching_repository_keeps_urls_inside_explicit_body():
    command = ['issue', 'comment', '7', '--repo', REPOSITORY,
               '--body', 'Evidence: https://github.com/other/repo/issues/8']
    assert guarded_gh.validated_command(command, REPOSITORY) == command


def test_mismatched_repository_never_enters_mutation_subprocess(monkeypatch):
    target = SimpleNamespace(expected_repository=REPOSITORY, open=lambda: None)
    settings = SimpleNamespace(get_target=lambda key: target)
    monkeypatch.setattr(guarded_gh, 'RepositorySettings',
                        SimpleNamespace(from_environment=lambda **kw: settings))
    monkeypatch.setattr(guarded_gh, 'merged_repository_environment', lambda path: {})
    monkeypatch.setattr(guarded_gh, 'LockManager',
                        lambda: SimpleNamespace(lock=lambda *args: nullcontext()))
    calls = []

    def mutation_spy(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(guarded_gh.subprocess, 'run', mutation_spy)
    with pytest.raises(SystemExit) as refused:
        guarded_gh.main(['--dotenv', 'unused.env', '--mech', 'edgemech', '--',
                         'issue', 'close', '7', '--repo', 'CultureBotAI/HabitatMech'])
    assert refused.value.code == 2
    assert calls == []


def test_acquire_refuses_existing_directory_before_any_write(tmp_path):
    output = tmp_path / 'existing'
    output.mkdir()
    sentinel = output / 'intake.json'
    sentinel.write_bytes(b'original evidence\n')
    result = subprocess.run(['bash', str(HELPERS / 'acquire.sh'), REPOSITORY,
                             str(output), '/bin/false'], cwd=tmp_path,
                            capture_output=True, text=True, timeout=10)
    assert result.returncode != 0
    assert sentinel.read_bytes() == b'original evidence\n'
    assert {p.name for p in output.iterdir()} == {'intake.json'}
    assert 'already exists' in result.stderr


@pytest.mark.parametrize('existing', ['pr-files-7.json', 'review-batches.json', 'review-batches.md'])
def test_pr_batch_preflight_refuses_existing_output_before_api(tmp_path, monkeypatch, existing):
    (tmp_path / 'counts.json').write_text(json.dumps({'data': {'repository': {'nameWithOwner': REPOSITORY}}}))
    (tmp_path / 'prs.json').write_text(json.dumps([{
        'number': 7, 'head': {'sha': 'a' * 40}, 'title': 'fixture', 'html_url': 'fixture',
    }]))
    sentinel = tmp_path / existing
    sentinel.write_bytes(b'original evidence\n')
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    calls = []

    def no_api(*args):
        calls.append(args)
        raise AssertionError('API must not run after output collision')

    monkeypatch.setattr(pr_batches, 'gh', no_api)
    with pytest.raises(FileExistsError):
        pr_batches.main([str(tmp_path)])
    assert calls == []
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


def test_exclusive_writer_refuses_collision_after_preflight(tmp_path):
    path = tmp_path / 'receipt.json'
    pr_batches.refuse_existing([path])
    path.write_bytes(b'concurrent original')
    with pytest.raises(FileExistsError):
        pr_batches.write_new(path, 'replacement')
    assert path.read_bytes() == b'concurrent original'


@pytest.mark.parametrize('existing', ['routing.json', 'routing.md'])
def test_grouping_refuses_existing_pair_before_writing_either(tmp_path, existing):
    for name in ('issues.json', 'prs.json'):
        (tmp_path / name).write_text('[]')
    (tmp_path / existing).write_bytes(b'original routing')
    before = {p.name: p.read_bytes() for p in tmp_path.iterdir()}
    with pytest.raises(FileExistsError):
        group_intake.route(tmp_path)
    assert {p.name: p.read_bytes() for p in tmp_path.iterdir()} == before


def test_git_supplement_preserves_unusual_filename_bytes(tmp_path):
    def git(*args):
        return subprocess.check_output(['git', '-C', str(tmp_path), *args])

    def commit():
        git('add', '--all')
        git('-c', 'user.name=Offline Fixture', '-c', 'user.email=fixture@example.invalid',
            '-c', 'commit.gpgsign=false', 'commit', '-m', 'fixture')
        return git('rev-parse', 'HEAD').decode().strip()

    git('init', '-b', 'main')
    (tmp_path / 'base.txt').write_text('base')
    base = commit()
    names = {' leading.txt', 'trailing.txt ', 'data/µ.tsv',
             'line\nbreak.txt', 'tab\tfile.txt', 'quote"file.txt'}
    for name in names:
        path = tmp_path / name
        path.parent.mkdir(exist_ok=True)
        path.write_text('added')
    head = commit()
    observed = complete_git_batches.git_paths(tmp_path, base, head)
    assert len(observed) == len(names)
    assert set(observed) == names


def test_retention_applescript_is_exact_inert_historical_source():
    original = HELPERS / 'request_mim_retention.applescript'
    archived = HELPERS / 'archive/request_mim_retention.applescript.txt'
    assert not original.exists()
    assert hashlib.sha256(archived.read_bytes()).hexdigest() == (
        '99c93137bc498577aaa645d71b16ad6dced848a0c1aa5ce9c7b9a6f02d0a3489'
    )
