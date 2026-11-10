"""Closed, evidence-bound restart registration; no process or filesystem access.

The caller supplies independently captured process evidence and its retained raw
bytes. A digest binds that capture; it is not authentication of who observed it.
This module never infers a CLI model identifier from a displayed model label.
The transport must remeasure executable bytes and current process/native state
immediately before quit, before resume, and after resume.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from collections.abc import Mapping
from datetime import datetime
from pathlib import PurePosixPath
from typing import Any


class IdentityError(ValueError):
    """Restart identity is absent, malformed, changed, or insufficiently proven."""


REGISTRATION_KEYS = {
    'schema_version', 'repository_key', 'native_session_id', 'tty', 'cwd',
    'agy_executable', 'executable_sha256', 'model', 'effort', 'model_label',
    'effort_label', 'evidence',
}
EVIDENCE_KEYS = {
    'schema_version', 'source_kind', 'observed_at', 'pid', 'process_identity',
    'native_session_id', 'tty', 'cwd', 'agy_executable', 'executable_sha256',
    'argv', 'model_label', 'effort_label',
}
LIVE_KEYS = EVIDENCE_KEYS - {'schema_version', 'source_kind', 'observed_at'} | {'model', 'effort'}
IDENTITY_KEYS = ('native_session_id', 'tty', 'cwd', 'agy_executable',
                 'executable_sha256', 'model_label', 'effort_label')
UUID = r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}'


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise IdentityError(reason)


def _closed(value: Any, keys: set[str], name: str) -> dict[str, Any]:
    _require(isinstance(value, Mapping) and set(value) == keys, name + ' has unexpected or missing fields')
    return dict(value)


def _text(value: Any, name: str) -> str:
    _require(isinstance(value, str) and bool(value) and value == value.strip()
             and not any(ord(char) < 32 or ord(char) == 127 for char in value), 'invalid ' + name)
    return value


def _path(value: Any, name: str) -> str:
    value = _text(value, name)
    path = PurePosixPath(value)
    _require(path.is_absolute() and str(path) == value and '..' not in path.parts
             and not value.startswith('//'), name + ' must be a canonical absolute path')
    return value


def _digest(value: Any, name: str) -> str:
    value = _text(value, name)
    _require(re.fullmatch(r'[0-9a-f]{64}', value) is not None, 'invalid ' + name)
    return value


def _common(value: Mapping[str, Any]) -> None:
    _require(re.fullmatch(UUID, _text(value['native_session_id'], 'native_session_id')) is not None,
             'invalid native_session_id')
    _require(re.fullmatch(r'/dev/ttys[0-9]+', _text(value['tty'], 'tty')) is not None, 'invalid tty')
    _path(value['cwd'], 'cwd')
    _path(value['agy_executable'], 'agy_executable')
    _digest(value['executable_sha256'], 'executable_sha256')
    for key in ('model_label', 'effort_label'):
        _text(value[key], key)


def _process(value: Mapping[str, Any]) -> None:
    _require(type(value['pid']) is int and value['pid'] > 0, 'invalid process PID')
    identity = _text(value['process_identity'], 'process_identity')
    words = identity.split()
    _require(len(words) >= 8 and words[0] == str(value['pid'])
             and words[1] == PurePosixPath(value['tty']).name
             and PurePosixPath(words[-1]).name == 'agy', 'process identity disagrees with PID or tty')


def _argv(value: Any, registration: Mapping[str, Any]) -> list[str]:
    expected = [registration['agy_executable'], '--conversation=' + registration['native_session_id'],
                '--model=' + registration['model'], '--effort=' + registration['effort']]
    _require(isinstance(value, list) and value == expected, 'exact conversation/model/effort argv is unproven')
    return list(value)


def _pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result, 'duplicate evidence field: ' + key)
        result[key] = value
    return result


def _target(registration: Mapping[str, Any], target: Mapping[str, Any]) -> None:
    expected = {'repository_key': target.get('repository_key'),
                'native_session_id': target.get('native_session_id'),
                'tty': target.get('tty'), 'cwd': target.get('root', target.get('cwd'))}
    _require(all(registration[key] == value for key, value in expected.items()),
             'registration belongs to a different target')


def validate_registration(
    value: Any, *, target: Mapping[str, Any], evidence_bytes: bytes,
) -> dict[str, Any]:
    """Validate a closed immutable record and exact-argv provenance capture.

    ``evidence.path`` is the durable artifact named by the record. The caller
    reads it without following an unapproved symlink and passes its bytes here.
    Only an explicit process-argv capture is supported initially; a bare footer,
    model marketing name, legacy ``agy -c`` command, or unrecognised native/log
    record cannot establish the CLI values and must hold deployment.
    """
    record = _closed(value, REGISTRATION_KEYS, 'restart registration')
    _require(type(record['schema_version']) is int and record['schema_version'] == 1,
             'unsupported restart registration version')
    _common(record)
    _require(re.fullmatch(r'[a-z][a-z0-9_-]*', _text(record['repository_key'], 'repository_key')) is not None,
             'invalid repository_key')
    for key in ('model', 'effort'):
        _require(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', _text(record[key], key)) is not None,
                 'invalid CLI ' + key)
    _target(record, target)
    reference = _closed(record['evidence'], {'path', 'sha256'}, 'restart evidence reference')
    _path(reference['path'], 'evidence path')
    _digest(reference['sha256'], 'evidence sha256')
    _require(isinstance(evidence_bytes, bytes) and 0 < len(evidence_bytes) <= 1024 * 1024,
             'restart evidence exceeds the 1 MiB bound or is empty')
    _require(hashlib.sha256(evidence_bytes).hexdigest() == reference['sha256'],
             'restart evidence digest changed')
    try:
        capture = json.loads(evidence_bytes, object_pairs_hook=_pairs)
    except (ValueError, UnicodeError) as error:
        raise IdentityError('restart evidence is not unambiguous JSON') from error
    capture = _closed(capture, EVIDENCE_KEYS, 'restart evidence')
    _require(type(capture['schema_version']) is int and capture['schema_version'] == 1,
             'unsupported restart evidence version')
    _require(capture['source_kind'] == 'process_argv', 'unrecognised model/effort evidence source')
    _common(capture)
    _process(capture)
    try:
        observed = datetime.fromisoformat(_text(capture['observed_at'], 'observed_at').replace('Z', '+00:00'))
    except ValueError as error:
        raise IdentityError('invalid evidence observed_at') from error
    _require(observed.tzinfo is not None and observed.utcoffset() is not None, 'evidence time must be timezone-aware')
    _require(all(capture[key] == record[key] for key in IDENTITY_KEYS), 'restart evidence identity disagreement')
    _argv(capture['argv'], record)
    return copy.deepcopy(record)


def validate_live_identity(
    registration: Mapping[str, Any], *, target: Mapping[str, Any], observation: Any,
) -> dict[str, Any]:
    """Compare fresh trusted measurements with an already validated registration.

    Before quit, ``target`` is the old binding. After resume, it is the newly
    verified PID/start binding. Both require explicit conversation/model/effort argv.
    Capture generation/freshness, filesystem canonicalisation, process queries,
    and independent conversation ownership remain the transport's responsibility.
    """
    _target(registration, target)
    live = _closed(observation, LIVE_KEYS, 'live restart evidence')
    _common(live)
    _process(live)
    _require(live['pid'] == target.get('pid') and live['process_identity'] == target.get('process_identity'),
             'live process identity changed')
    _require(all(live[key] == registration[key] for key in (*IDENTITY_KEYS, 'model', 'effort')),
             'live executable, conversation, model or effort changed')
    _require(isinstance(live['argv'], list) and all(isinstance(arg, str) for arg in live['argv']),
             'live argv is unavailable')
    _argv(live['argv'], registration)
    return copy.deepcopy(live)
