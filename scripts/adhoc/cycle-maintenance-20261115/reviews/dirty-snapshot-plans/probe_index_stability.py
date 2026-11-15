"""Read-only source index stability probe, 2026-11-15.

Explicit root/output inputs. Saves the original raw index to a new private output,
then runs Git observations using ONLY an evidence copy as GIT_INDEX_FILE. Reports
copied-index transitions and whether the source index remained byte-identical.
No source/ref mutation, cleanup, restoration or GitHub action.
"""
import argparse
import hashlib
import json
import os
import subprocess
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if not args.root.is_absolute() or args.root != args.root.resolve():
        raise ValueError('Canonical explicit root required')
    if not args.output.is_absolute() or args.output != args.output.resolve() or os.path.lexists(args.output):
        raise ValueError('New canonical explicit output required')
    if args.root in args.output.parents or args.output in args.root.parents:
        raise ValueError('Output must be outside source')
    env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    env.update(GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull, GIT_OPTIONAL_LOCKS='0', GIT_NO_LAZY_FETCH='1')
    base = ['git', '-c', 'core.hooksPath='+os.devnull, '-c', 'core.fsmonitor=false', '-c', 'gc.auto=0', '-C', str(args.root)]
    configured = subprocess.run([*base, 'config', '--name-only', '--get-regexp', r'^filter\.'], env=env, capture_output=True)
    if configured.returncode not in (0, 1) or configured.stdout:
        raise ValueError('Configured filters require separate override review')
    gitdir = Path(subprocess.check_output([*base, 'rev-parse', '--absolute-git-dir'], env=env).decode().strip())
    source = gitdir/'index'
    raw = source.read_bytes()
    args.output.mkdir(mode=0o700)
    original, copy = args.output/'original.index', args.output/'observed.index'
    for path in (original, copy):
        with path.open('xb') as stream:
            stream.write(raw)
    env['GIT_INDEX_FILE'] = str(copy)
    def digest(value):
        return hashlib.sha256(value).hexdigest()
    rows = []
    queries = [('ls-files', '--stage', '-z'), ('diff', '--cached', '--binary', '--full-index', '--no-ext-diff', '--no-textconv', '--no-renames', 'HEAD', '--'), ('diff', '--binary', '--full-index', '--no-ext-diff', '--no-textconv', '--no-renames', '--')]
    for number, query in enumerate(queries):
        before = digest(copy.read_bytes())
        process = subprocess.run([*base, *query], env=env, capture_output=True, timeout=60)
        after = digest(copy.read_bytes())
        with (args.output/f'query-{number}.stdout').open('xb') as stream:
            stream.write(process.stdout)
        rows.append({'command': list(query), 'exit': process.returncode, 'copy_before': before,
                     'copy_after': after, 'source_unchanged': source.read_bytes() == raw,
                     'stdout_sha256': digest(process.stdout), 'stderr': process.stderr.decode()})
        if process.returncode:
            raise ValueError('Read-only probe query failed')
    result = {'source_original_sha256': digest(raw), 'source_final_sha256': digest(source.read_bytes()),
              'observations': rows, 'helper_sha256': digest(Path(__file__).read_bytes())}
    with (args.output/'result.json').open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
