"""A passing PR cannot establish that a skipped or foreign queue job validates it."""
from pathlib import Path

import pytest

from kg_microbe_merge_queue import workflow_errors

GOVERNED_QC_EVIDENCE = (Path(__file__).resolve().parents[1]
                        / "src/kg_microbe_governance/artifacts/workflows/qc-evidence.yaml")
AUXILIARY_ERROR = "auxiliary checkout needs an immutable full commit SHA"

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


def test_governed_workflow_may_check_claw_out_at_its_pin_derived_ref():
    """#793: the governed qc-evidence job checks claw out at the consumer's committed pin."""
    text = GOVERNED_QC_EVIDENCE.read_text(encoding='utf-8')
    assert 'ref: ${{ steps.claw-pin.outputs.ref }}' in text
    assert workflow_errors(text, ['qc-evidence']) == []


def test_pin_derived_claw_checkout_needs_the_governed_bytes():
    """The same structure with one comment added is no longer the reviewed artifact."""
    text = GOVERNED_QC_EVIDENCE.read_text(encoding='utf-8') + '# local edit\n'
    assert any(AUXILIARY_ERROR in error for error in workflow_errors(text, ['qc-evidence']))


@pytest.mark.parametrize('variant', [
    lambda text: text.replace('\n', '\r\n'),  # CRLF line endings
    lambda text: '﻿' + text,             # byte-order mark
], ids=['crlf', 'bom'])
def test_byte_variants_of_the_governed_workflow_are_not_the_governed_bytes(variant):
    """#818: the digest is over the exact bytes; normalising them would admit a non-canonical file."""
    text = variant(GOVERNED_QC_EVIDENCE.read_text(encoding='utf-8'))
    assert any(AUXILIARY_ERROR in error for error in workflow_errors(text, ['qc-evidence']))


def test_pin_derived_checkout_of_another_repository_is_rejected():
    text = GOVERNED_QC_EVIDENCE.read_text(encoding='utf-8').replace(
        'repository: CultureBotAI/culturebotai-claw', 'repository: CultureBotAI/other')
    assert any(AUXILIARY_ERROR in error for error in workflow_errors(text, ['qc-evidence']))


def test_step_output_ref_outside_a_governed_workflow_is_rejected():
    candidate = auxiliary('${{ steps.pin.outputs.ref }}', 'tools').replace(
        'repository: tools/project', 'repository: CultureBotAI/culturebotai-claw')
    assert any(AUXILIARY_ERROR in error for error in workflow_errors(candidate, ['qc']))


@pytest.mark.parametrize('ref,repository', [
    ('main', 'CultureBotAI/culturebotai-claw'),                      # governed bytes, mutable ref
    ('${{ steps.pin.outputs.ref }}', 'CultureBotAI/other'),         # governed bytes, other repository
])
def test_governed_bytes_alone_do_not_admit_any_checkout(monkeypatch, ref, repository):
    """Each condition holds on its own: a governed digest admits only a pin-derived claw ref."""
    import hashlib

    import kg_microbe_merge_queue as queue

    candidate = auxiliary(ref, 'tools').replace('repository: tools/project', f'repository: {repository}')
    digest = hashlib.sha256(candidate.encode('utf-8')).hexdigest()
    monkeypatch.setattr(queue, 'governed_workflow_digests', lambda: frozenset({digest}))
    assert any(AUXILIARY_ERROR in error for error in workflow_errors(candidate, ['qc']))
    allowed = auxiliary('${{ steps.pin.outputs.ref }}', 'tools').replace(
        'repository: tools/project', 'repository: CultureBotAI/culturebotai-claw')
    monkeypatch.setattr(queue, 'governed_workflow_digests',
                        lambda: frozenset({hashlib.sha256(allowed.encode('utf-8')).hexdigest()}))
    assert workflow_errors(allowed, ['qc']) == []


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
