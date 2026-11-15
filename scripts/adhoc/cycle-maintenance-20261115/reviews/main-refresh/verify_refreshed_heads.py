"""Independent source-read-only integration reviews for PR1197/1138, 2026-11-15.

Inputs: exact owned checkout, previous reviewed head, verified main, original PR
source, expected new head, development Python and a new private evidence path.
Outputs: exact full-tree/source proof, authentic baseline proof when applicable,
focused pytest log/JUnit and derived counts. No Git object/ref write, network,
source edit, runtime action or adoption. Previous review evidence stays intact.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

CATALOGUE = 'src/kg_microbe_skills/skills.yaml'
BASELINE = 'src/kg_microbe_skills/template_baseline.json'
TESTS = {
    1197: ['tests/test_fleet_issue_status.py', 'tests/test_fleet_pr_status.py', 'tests/test_mech_template.py',
           'tests/test_mech_template_maintenance.py', 'tests/test_mech_template_source_fetch.py',
           'tests/test_fleet_scoped_skills.py',
           'tests/test_fleet_maintenance_skills.py'],
    1138: ['tests/test_freshness_archive_1138.py', 'tests/test_freshness_candidates.py', 'tests/test_freshness_contract.py'],
}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def git_blob(raw):
    return hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def require(ok, message):
    if not ok:
        raise ValueError(message)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--pr', type=int, choices=TESTS, required=True)
    for name in ('root', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    for name in ('head', 'previous', 'base', 'original', 'python'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    root, output = args.root, args.output
    require(root.is_absolute() and root == root.resolve(), 'Canonical explicit source required')
    require(output.is_absolute() and output == output.resolve() and not os.path.lexists(output), 'New canonical output required')
    require(root not in output.parents and output not in root.parents, 'Output overlaps source')
    env = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    env.update(GIT_OPTIONAL_LOCKS='0', GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL=os.devnull,
               GIT_NO_LAZY_FETCH='1', GIT_NO_REPLACE_OBJECTS='1', GIT_GRAFT_FILE=os.devnull)

    def git(*arguments):
        return subprocess.run(['git', '-c', 'core.hooksPath=' + os.devnull, '-c', 'core.fsmonitor=false',
                               '-c', 'gc.auto=0', '-C', str(root), *arguments],
                              env=env, check=True, capture_output=True, timeout=60).stdout

    def raw(ref, path):
        return git('show', f'{ref}:{path}')

    def mapping(ref):
        result = {}
        for row in git('ls-tree', '-r', '-z', ref).split(b'\0'):
            if row:
                metadata, path = row.split(b'\t', 1)
                mode, kind, oid = metadata.decode().split()
                result[path.decode()] = (mode, kind, oid)
        return result

    require(git('rev-parse', 'HEAD').decode().strip() == args.head, 'Source HEAD changed')
    origins = git('remote', 'get-url', 'origin').decode().strip()
    require(origins in ('https://github.com/CultureBotAI/culturebotai-claw.git',
                        'git@github.com:CultureBotAI/culturebotai-claw.git'), 'Wrong repository')
    for field in git('worktree', 'list', '--porcelain', '-z').split(b'\0'):
        if field.startswith(b'worktree '):
            checkout = Path(field[9:].decode())
            require(output != checkout and checkout not in output.parents, 'Output inside a checkout')
    actual = mapping(args.head)
    previous = mapping(args.previous)
    base = mapping(args.base)
    original = mapping(args.original)
    common = git('merge-base', args.original, args.base).decode().strip()
    ancestor = mapping(common)
    changed = {path for path in set(ancestor) | set(original) if ancestor.get(path) != original.get(path)}
    parents = git('rev-list', '--parents', '-n', '1', args.head).decode().split()[1:]
    integration = args.head
    if parents != [args.previous, args.base]:
        require(args.pr == 1197 and len(parents) == 1, 'Unexpected final commit shape')
        integration = parents[0]
        require(git('rev-list', '--parents', '-n', '1', integration).decode().split()[1:] == [args.previous, args.base], 'Not an ordinary integration')
        integrated = mapping(integration)
        require({path for path in set(integrated) | set(actual) if integrated.get(path) != actual.get(path)} == {BASELINE}, 'Unexpected post-merge source changes')
    expected = dict(base)
    for path in changed:
        require(path in original, 'Unexpected original deletion')
        expected[path] = original[path]
    baseline_proof = None
    if args.pr == 1138:
        require(len(changed) == 9, 'Original freshness scope changed')
        require(all(actual[path] == previous[path] == original[path] for path in changed), 'Archived/provenance path changed')
    else:
        require(len(changed) == 8 and CATALOGUE in changed, 'Original issue-review scope changed')
        for path in changed - {CATALOGUE}:
            require(actual[path] == previous[path] == original[path], 'Original source path changed')
        text = raw(args.base, CATALOGUE).decode()
        replacements = [
            ('One row per repository of open issues and open PRs across claw and the\n      manifest-defined Mechs, reading membership from the manifest.',
             'Count-ranked open-issue inventory across claw and the manifest-defined\n      Mechs, with Markdown and structured per-issue review-decision tables.'),
            ('Reviews the complete manifest-defined Mech backlog with thematic prioritization and dependency-aware parallel planning.',
             'Enriches the shared issue inventory with evidence-backed priority and keep/close/defer recommendations, thematic prioritization, and dependency-aware parallel planning.'),
        ]
        for old, new in replacements:
            require(text.count(old) == 1, 'Main catalogue replacement anchor differs')
            text = text.replace(old, new)
        expected[CATALOGUE] = (base[CATALOGUE][0], 'blob', git_blob(text.encode()))
        require(raw(args.head, CATALOGUE) == text.encode(), 'Catalogue contains other changes')
        expected[BASELINE] = actual[BASELINE]
        baseline = json.loads(raw(args.head, BASELINE))
        for path, pin in baseline['sources'].items():
            require(digest(raw(baseline['source_ref'], path)) == pin == digest(raw(args.head, path)), 'Baseline immutable source mismatch')
        sys.path[:0] = [str(root / 'src'), str(root)]
        from kg_microbe_skills.template import check_baseline, refresh_baseline
        require(check_baseline(root) == baseline == refresh_baseline(root), 'Maintained baseline replay differs')
        baseline_proof = {'source_ref': baseline['source_ref'], 'version': baseline['baseline_version'],
                          'authority_sources': len(baseline['sources']), 'sha256': digest(raw(args.head, BASELINE)),
                          'unchanged_from_previous': raw(args.head, BASELINE) == raw(args.previous, BASELINE),
                          'canonical_check_and_refresh_equal': True}
    require(actual == expected, 'Full tree differs from independently derived base-plus-reviewed-source tree')

    def verify_worktree():
        for path, (mode, kind, oid) in actual.items():
            source = root / path
            require(kind == 'blob', 'Unexpected submodule')
            info = source.lstat()
            if mode == '120000':
                require(stat.S_ISLNK(info.st_mode), 'Symlink replaced')
                content = os.readlink(source).encode()
            else:
                require(stat.S_ISREG(info.st_mode), 'Tracked file type changed')
                require(bool(info.st_mode & 0o111) == (mode == '100755'), 'Executable mode changed')
                content = source.read_bytes()
            require(git_blob(content) == oid, 'Working source differs from committed tree')
        require(git('rev-parse', 'HEAD').decode().strip() == args.head, 'HEAD changed during review')

    verify_worktree()
    output.mkdir(parents=False, mode=0o700)
    test_env = dict(env, PYTHONPATH=str(root / 'src') + os.pathsep + str(root),
                    PYTHONDONTWRITEBYTECODE='1', PYTHONPYCACHEPREFIX=str(output / 'fresh-bytecode'))
    command = [args.python, '-B', '-m', 'pytest', '-q', '-rs', '-p', 'no:cacheprovider',
               *TESTS[args.pr], '--basetemp', str(output / 'fixtures'), '--junitxml', str(output / 'pytest.xml')]
    process = subprocess.run(command, cwd=root, env=test_env, capture_output=True, timeout=300)
    log = process.stdout + process.stderr
    with (output / 'pytest.log').open('xb') as stream:
        stream.write(log)
    require(process.returncode == 0, 'Focused tests failed; retained log is not a success receipt')
    tests = ET.fromstring((output / 'pytest.xml').read_bytes())
    suites = list(tests.iter('testsuite'))
    counts = {key: sum(int(suite.attrib.get(key, 0)) for suite in suites) for key in ('tests', 'failures', 'errors', 'skipped')}
    require(counts['tests'] > 0 and not any(counts[key] for key in ('failures', 'errors', 'skipped')), 'Unexpected incomplete validation')
    verify_worktree()
    proof = {'pr': args.pr, 'head': args.head, 'previous': args.previous, 'base': args.base,
             'original': args.original, 'integration_commit': integration, 'ordinary_integration_parents': [args.previous, args.base],
             'tree': git('rev-parse', args.head + '^{tree}').decode().strip(),
             'full_tree_exactly_matches_independent_composition': True, 'reviewed_paths_preserved': sorted(changed),
             'baseline': baseline_proof, 'tests': counts, 'focused_test_files': TESTS[args.pr],
             'test_log_sha256': digest(log), 'helper_sha256': digest(Path(__file__).read_bytes()),
             'tracked_source_unchanged': True, 'git_object_or_ref_writes': False,
             'runtime_or_adoption': False, 'review_scope': 'local exact integration; hosted gates require owner readback after publication'}
    with (output / 'proof.json').open('x') as stream:
        json.dump(proof, stream, indent=2)
        stream.write('\n')
    print(json.dumps(proof, indent=2))


if __name__ == '__main__':
    main()
