"""Restart identity is evidence-bound, exact, and independent of live discovery."""

import copy
import hashlib
import json

import pytest

from kg_microbe_workflows.port_pressure_identity import (
    IdentityError,
    validate_live_identity,
    validate_registration,
)

CID = '11111111-2222-3333-4444-555555555555'


def fixture():
    target = {'repository_key': 'communitymech', 'native_session_id': CID,
              'pid': 42, 'tty': '/dev/ttys020', 'root': '/owned/CommunityMech',
              'process_identity': '42 ttys020 Wed Nov 4 12:11:19 2026 agy'}
    record = {
        'schema_version': 1, 'repository_key': target['repository_key'],
        'native_session_id': CID, 'tty': target['tty'], 'cwd': target['root'],
        'agy_executable': '/owned/bin/agy', 'executable_sha256': 'a' * 64,
        'model': 'explicit-model-slug', 'effort': 'high',
        'model_label': 'Exact Model', 'effort_label': 'high',
        'evidence': {'path': '/owned/evidence/identity.json', 'sha256': ''},
    }
    capture = {key: record[key] for key in ('native_session_id', 'tty', 'cwd', 'agy_executable',
                                           'executable_sha256', 'model_label', 'effort_label')}
    capture.update(schema_version=1, source_kind='process_argv', observed_at='2026-11-10T00:00:00Z',
                   pid=target['pid'], process_identity=target['process_identity'],
                   argv=[record['agy_executable'], '--conversation=' + CID,
                         '--model=' + record['model'], '--effort=' + record['effort']])
    raw = json.dumps(capture).encode()
    record['evidence']['sha256'] = hashlib.sha256(raw).hexdigest()
    live = {key: value for key, value in capture.items()
            if key not in {'schema_version', 'source_kind', 'observed_at'}}
    live.update(model=record['model'], effort=record['effort'])
    return target, record, capture, raw, live


def validate_capture(record, target, capture):
    raw = json.dumps(capture).encode()
    record['evidence']['sha256'] = hashlib.sha256(raw).hexdigest()
    return validate_registration(record, target=target, evidence_bytes=raw)


def test_valid_exact_argv_registration_and_live_identity_return_independent_records():
    target, record, _, raw, live = fixture()
    result = validate_registration(record, target=target, evidence_bytes=raw)
    assert result == record and result is not record and result['evidence'] is not record['evidence']
    checked = validate_live_identity(result, target=target, observation=live)
    assert checked == live and checked is not live
    assert checked['argv'] is not live['argv']


@pytest.mark.parametrize('field,value', [
    ('schema_version', True), ('schema_version', 2), ('repository_key', 'CommunityMech'),
    ('native_session_id', 'not-a-conversation'), ('tty', '/dev/ttys020/../ttys021'),
    ('cwd', 'relative'), ('cwd', '/owned/../other'), ('agy_executable', '//other/agy'),
    ('agy_executable', '/owned/bin/./agy'), ('executable_sha256', 'not-a-digest'),
    ('model', 'name\n--option'), ('model', 'Model Label'), ('effort', ''),
    ('model_label', ' Exact Model'), ('effort_label', 'high\n'),
])
def test_malformed_registration_refuses(field, value):
    target, record, _, raw, _ = fixture()
    record[field] = value
    with pytest.raises(IdentityError):
        validate_registration(record, target=target, evidence_bytes=raw)


@pytest.mark.parametrize('field', ['extra', 'schema_version'])
def test_registration_is_closed(field):
    target, record, _, raw, _ = fixture()
    if field == 'extra':
        record[field] = True
    else:
        del record[field]
    with pytest.raises(IdentityError):
        validate_registration(record, target=target, evidence_bytes=raw)


@pytest.mark.parametrize('field,value', [
    ('repository_key', 'habitatmech'), ('native_session_id', 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'),
    ('tty', '/dev/ttys024'), ('root', '/owned/HabitatMech'),
])
def test_valid_registration_cannot_be_used_for_another_target(field, value):
    target, record, _, raw, _ = fixture()
    target[field] = value
    with pytest.raises(IdentityError, match='different target'):
        validate_registration(record, target=target, evidence_bytes=raw)


def test_changed_retained_bytes_refused_even_when_json_meaning_is_unchanged():
    target, record, _, raw, _ = fixture()
    with pytest.raises(IdentityError, match='digest changed'):
        validate_registration(record, target=target, evidence_bytes=raw + b'\n')


def test_evidence_duplicate_fields_cannot_hide_a_different_argv():
    target, record, _, raw, _ = fixture()
    raw = raw[:-1] + b', "argv": []}'
    record['evidence']['sha256'] = hashlib.sha256(raw).hexdigest()
    with pytest.raises(IdentityError, match='unambiguous JSON'):
        validate_registration(record, target=target, evidence_bytes=raw)


@pytest.mark.parametrize('change', [
    {'source_kind': 'footer'}, {'source_kind': 'native_state'}, {'schema_version': True},
    {'observed_at': '2026-11-10T00:00:00'}, {'observed_at': 'yesterday'},
    {'pid': True}, {'process_identity': '99 ttys020 Wed Nov 4 12:11:19 2026 agy'},
    {'executable_sha256': 'b' * 64}, {'model_label': 'Exact Model Max'},
    {'extra': 'unreviewed'},
])
def test_insufficient_or_changed_provenance_refused(change):
    target, record, capture, _, _ = fixture()
    capture.update(change)
    with pytest.raises(IdentityError):
        validate_capture(record, target, capture)


@pytest.mark.parametrize('argv', [
    ['/owned/bin/agy', '-c'],
    ['/owned/bin/agy', '--conversation=' + CID],
    ['/owned/bin/agy', '--conversation=' + CID, '--model=wrong-slug', '--effort=high'],
    ['/owned/bin/agy', '--conversation=' + CID, '--model=explicit-model-slug', '--effort=highest'],
    ['/owned/bin/agy', '--conversation=aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
     '--model=explicit-model-slug', '--effort=high'],
    ['/different/agy', '--conversation=' + CID, '--model=explicit-model-slug', '--effort=high'],
])
def test_registration_requires_real_explicit_cli_values_not_footer_inference(argv):
    target, record, capture, _, _ = fixture()
    capture['argv'] = argv
    with pytest.raises(IdentityError, match='argv is unproven'):
        validate_capture(record, target, capture)


@pytest.mark.parametrize('field,value', [
    ('executable_sha256', 'b' * 64), ('agy_executable', '/replacement/agy'),
    ('model', 'wrong-slug'), ('effort', 'highest'), ('model_label', 'Exact Model Max'),
    ('effort_label', 'highest'), ('cwd', '/owned/Other'),
    ('native_session_id', 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'),
    ('tty', '/dev/ttys024'), ('pid', 43),
    ('process_identity', '42 ttys020 Thu Nov 5 12:11:19 2026 agy'),
])
def test_live_identity_change_refused(field, value):
    target, record, _, raw, live = fixture()
    registration = validate_registration(record, target=target, evidence_bytes=raw)
    live[field] = value
    with pytest.raises(IdentityError):
        validate_live_identity(registration, target=target, observation=live)


def test_live_same_footer_with_unproven_argv_still_refuses():
    target, record, _, raw, live = fixture()
    registration = validate_registration(record, target=target, evidence_bytes=raw)
    live['argv'] = ['/owned/bin/agy', '--conversation=' + CID]
    with pytest.raises(IdentityError, match='argv is unproven'):
        validate_live_identity(registration, target=target, observation=live)


def test_post_restart_new_pid_requires_matching_new_binding_and_unchanged_registration():
    target, record, _, raw, live = fixture()
    original = copy.deepcopy(record)
    registration = validate_registration(record, target=target, evidence_bytes=raw)
    target.update(pid=100, process_identity='100 ttys020 Tue Nov 10 00:30:00 2026 agy')
    live.update(pid=target['pid'], process_identity=target['process_identity'])
    assert validate_live_identity(registration, target=target, observation=live)['pid'] == 100
    assert record == original


def test_evidence_size_is_bounded_before_json_or_digest_validation():
    target, record, _, _, _ = fixture()
    raw = b'x' * (1024 * 1024 + 1)
    record['evidence']['sha256'] = hashlib.sha256(raw).hexdigest()
    with pytest.raises(IdentityError, match='1 MiB'):
        validate_registration(record, target=target, evidence_bytes=raw)
