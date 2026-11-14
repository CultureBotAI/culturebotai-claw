"""Squash-history preparation retrieves data, preserving the checkout and refs."""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest

from plugins.repository_settings import RepositoryConfigurationError

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('ensure_template_source', ROOT / 'scripts/ensure_mech_template_source.py')
assert spec and spec.loader
fetcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fetcher)


@pytest.fixture
def squashed_checkout(tmp_path, monkeypatch):
    for key, value in {'GIT_CONFIG_GLOBAL': os.devnull, 'GIT_CONFIG_NOSYSTEM': '1',
                       'GIT_AUTHOR_NAME': 'Fixture', 'GIT_COMMITTER_NAME': 'Fixture',
                       'GIT_AUTHOR_EMAIL': 'fixture@example.org',
                       'GIT_COMMITTER_EMAIL': 'fixture@example.org',
                       'OPENCLAW_WORKSPACE': str(tmp_path / 'locks-workspace')}.items():
        monkeypatch.setenv(key, value)

    def git(*args):
        return subprocess.run(['git', *map(str, args)], capture_output=True, text=True, check=True).stdout.strip()

    source = tmp_path / 'source'
    git('init', '-q', '-b', 'main', source)
    (source / 'README.md').write_text('initial\n')
    git('-C', source, 'add', '.')
    git('-C', source, 'commit', '-qm', 'initial')
    base = git('-C', source, 'rev-parse', 'HEAD')
    git('-C', source, 'switch', '-qc', 'candidate')
    authority = source / 'src/kg_microbe_skills/canonical/example.md'
    authority.parent.mkdir(parents=True)
    authority.write_text('canonical input\n')
    git('-C', source, 'add', '.')
    git('-C', source, 'commit', '-qm', 'input')
    ref = git('-C', source, 'rev-parse', 'HEAD')
    baseline = source / 'src/kg_microbe_skills/template_baseline.json'
    baseline.write_text(json.dumps({'schema_version': 1, 'baseline_version': '1.0.0',
                                   'source_ref': ref, 'sources': {'src/kg_microbe_skills/canonical/example.md': '1' * 64}}))
    git('-C', source, 'add', '.')
    git('-C', source, 'commit', '-qm', 'lock')
    candidate = git('-C', source, 'rev-parse', 'HEAD')
    git('-C', source, 'switch', 'main')
    assert git('-C', source, 'rev-parse', 'HEAD') == base
    git('-C', source, 'merge', '--squash', 'candidate')
    git('-C', source, 'commit', '-qm', 'squash baseline')
    remote = tmp_path / 'remote.git'
    git('init', '-q', '--bare', remote)
    git('-C', source, 'push', remote, 'main', f'{candidate}:refs/pull/1/head')
    checkout = tmp_path / 'checkout'
    git('clone', '-q', '--single-branch', '--branch', 'main', '--depth', '1', remote.as_uri(), checkout)
    return checkout, ref, git


def test_fetches_unavailable_source_after_squash_without_changing_checkout(squashed_checkout, monkeypatch):
    checkout, ref, git = squashed_checkout
    # Identity rejection has its own test. This fixture uses a local real Git
    # transport to exercise missing-object retrieval without GitHub network.
    monkeypatch.setattr(fetcher.RepositoryTarget, 'open', lambda self: None)
    before = git('-C', checkout, 'rev-parse', 'HEAD')
    missing = subprocess.run(['git', '-C', str(checkout), 'cat-file', '-e', f'{ref}^{{commit}}'], capture_output=True)
    assert missing.returncode != 0
    assert fetcher.ensure_source(checkout)
    assert git('-C', checkout, 'show', f'{ref}:src/kg_microbe_skills/canonical/example.md') == 'canonical input'
    assert git('-C', checkout, 'rev-parse', 'HEAD') == before
    assert git('-C', checkout, 'status', '--porcelain') == ''
    assert not fetcher.ensure_source(checkout)


def test_wrong_origin_is_refused_before_fetch(squashed_checkout):
    checkout, ref, git = squashed_checkout
    before = git('-C', checkout, 'rev-parse', 'HEAD')
    with pytest.raises(RepositoryConfigurationError):
        fetcher.ensure_source(checkout)
    assert git('-C', checkout, 'rev-parse', 'HEAD') == before
    assert subprocess.run(['git', '-C', str(checkout), 'cat-file', '-e', ref], capture_output=True).returncode != 0
