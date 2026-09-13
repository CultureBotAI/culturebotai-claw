"""A passing PR cannot establish that a skipped or foreign queue job validates it."""
import pytest

from kg_microbe_merge_queue import workflow_errors

WORKFLOW = """on:
  pull_request:
  merge_group:
    types: [checks_requested]
jobs:
  qc:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: python validate.py
"""


def test_required_dependency_closure_rejects_skipped_prerequisite():
    candidate = WORKFLOW.replace('  qc:\n', '  qc:\n    needs: build\n')
    candidate += """  build:
    needs: prepare
    runs-on: ubuntu-latest
    steps:
      - run: echo build
  prepare:
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    steps:
      - run: echo prepare
"""
    assert any('prepare' in error and 'unconditional' in error
               for error in workflow_errors(candidate, ['qc']))
    assert workflow_errors(candidate.replace("    if: github.event_name == 'pull_request'\n", ''), ['qc']) == []


def test_advisory_dependent_does_not_block_required_ancestor():
    candidate = WORKFLOW + """  advisory:
    needs: qc
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-latest
    steps:
      - run: echo advisory
"""
    assert workflow_errors(candidate, ['qc']) == []


def test_explicit_false_job_condition_is_not_absent():
    assert workflow_errors(WORKFLOW.replace('  qc:\n', '  qc:\n    if: false\n'), ['qc'])


@pytest.mark.parametrize('needs', ['missing', '[missing]', "'${{ inputs.jobs }}'", '{wrong: shape}'])
def test_unresolvable_required_dependency_is_rejected(needs):
    assert workflow_errors(WORKFLOW.replace('  qc:\n', f'  qc:\n    needs: {needs}\n'), ['qc'])


def test_foreign_checkout_cannot_replace_candidate_without_ref():
    candidate = WORKFLOW.replace('      - uses: actions/checkout@v4\n',
                                '      - uses: actions/checkout@v4\n        with:\n          repository: other/project\n')
    assert workflow_errors(candidate, ['qc'])


def auxiliary(ref, path):
    return WORKFLOW.replace('      - run: python validate.py', f'''        with:
          path: candidate
      - uses: actions/checkout@v4
        with:
          repository: tools/project
          ref: {ref}
          path: {path}
      - run: python candidate/validate.py''')


def test_separate_pinned_auxiliary_checkout_is_allowed():
    assert workflow_errors(auxiliary('a' * 40, 'tools'), ['qc']) == []


@pytest.mark.parametrize('ref,path', [('main', 'tools'), ('a' * 40, 'candidate'),
                                     ('a' * 40, 'candidate/tools'), ('a' * 40, '.')])
def test_mutable_or_overlapping_auxiliary_checkout_is_rejected(ref, path):
    assert workflow_errors(auxiliary(ref, path), ['qc'])


@pytest.mark.parametrize('path', ['./tools', 'candidate/../tools', '/tools',
                                  "'${{ inputs.path }}'", 'candidate//tools',
                                  "' tools '", "'\ufefftools'"])
def test_candidate_path_alias_cannot_hide_checkout_overlap(path):
    candidate = auxiliary('a' * 40, 'tools').replace('path: candidate\n', f'path: {path}\n')
    assert workflow_errors(candidate, ['qc'])


def test_candidate_dot_prefix_is_normalized_for_separate_checkouts():
    candidate = auxiliary('a' * 40, 'tools').replace('path: candidate\n', 'path: ./candidate\n')
    assert workflow_errors(candidate, ['qc']) == []


@pytest.mark.parametrize('job_id', ['qc', 'workflow'])
def test_job_concurrency_cannot_collide_with_its_own_workflow_in_merge_group(job_id):
    candidate = WORKFLOW.replace('jobs:\n', '''concurrency:
  group: ci-${{ github.run_id }}
jobs:
''').replace('  qc:\n', '''  qc:
    concurrency:
      group: ci-${{ github.event_name == 'pull_request' && github.ref || github.run_id }}
''')
    candidate = candidate.replace('  qc:\n', f'  {job_id}:\n    name: qc\n')
    assert any('job concurrency' in error for error in workflow_errors(candidate, ['qc']))
