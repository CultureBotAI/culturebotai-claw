#!/usr/bin/env python3
"""Fetch the baseline's immutable source object before offline verification.

A squash merge can leave the input commit in PR history rather than the main
ancestry. Fetching this data object never executes its code or changes HEAD.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from kg_microbe_skills.template import TemplateError, baseline_document  # noqa: E402
from plugins.lock_manager import LockManager  # noqa: E402
from plugins.repository_settings import RepositoryTarget  # noqa: E402


def ensure_source(root: Path) -> bool:
    """Return whether an object was fetched; require the exact canonical origin."""
    root = root.resolve(strict=True)
    target = RepositoryTarget('claw', root, 'CultureBotAI/culturebotai-claw')
    target.open()
    ref = baseline_document(root)['source_ref']

    def present() -> bool:
        return subprocess.run(['git', '-C', str(root), 'cat-file', '-e', f'{ref}^{{commit}}'],
                              capture_output=True, timeout=30).returncode == 0

    if present():
        return False
    with LockManager().lock('claw', 'fetch-mech-template-source', timeout=120):
        target.open()
        subprocess.run(['git', '-C', str(root), '-c', 'core.hooksPath=/dev/null',
                        'fetch', '--no-tags', '--no-recurse-submodules', '--no-write-fetch-head',
                        'origin', ref], check=True, timeout=60)
        if not present():
            raise TemplateError('canonical source commit unavailable after fetch')
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-root', type=Path, default=Path.cwd())
    args = parser.parse_args(argv)
    try:
        fetched = ensure_source(args.source_root)
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
        print(f'Cannot authenticate baseline source: {exc}', file=sys.stderr)
        return 1
    print('Baseline source object fetched' if fetched else 'Baseline source object already present')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
