"""Real native SQLite/wire payloads, without reading any live conversation."""
import sqlite3
from datetime import datetime, timezone

import pytest
from test_mech_session_native import bytefield, goal_context, intfield, native


def encoded_goal(step, epoch, state=2):
    goal = bytefield(1, b'synthetic goal') + bytefield(2, intfield(1, epoch)) + intfield(3, step) + intfield(5, state)
    return bytefield(1, native.ANY_TYPE) + bytefield(2, goal)


@pytest.fixture
def native_case(tmp_path, monkeypatch):
    monkeypatch.setattr(native, 'ROOT', tmp_path)
    (tmp_path / 'conversations').mkdir()
    db_path = tmp_path / 'conversations/synthetic.db'
    old_epoch, current_epoch = 1792886400, 1793232000
    old = {'conversation_id': 'synthetic', 'start_step_index': 10144,
           'started_at': datetime.fromtimestamp(old_epoch, timezone.utc).isoformat()}
    current = {'conversation_id': 'synthetic', 'start_step_index': 11642,
               'started_at': datetime.fromtimestamp(current_epoch, timezone.utc).isoformat()}
    completed = bytefield(20, bytefield(1, b'Finished synthetic work.\n<!-- GOAL_COMPLETE -->'))
    declaration = bytefield(19, bytefield(3, bytefield(1, b'External user-directed work')) + goal_context())
    old_goal = encoded_goal(10144, old_epoch)
    checkpoint = bytefield(1, old_goal) + bytefield(2, encoded_goal(11642, current_epoch))
    with sqlite3.connect(db_path) as db:
        db.executescript('CREATE TABLE trajectory_meta (trajectory_id text,cascade_id text);'
                        'CREATE TABLE steps (idx integer,step_type integer,status integer,step_payload blob);'
                        'CREATE TABLE trajectory_metadata_blob (id text,data blob);')
        db.execute('INSERT INTO trajectory_meta VALUES (?,?)', ('synthetic', 'synthetic'))
        db.execute('INSERT INTO trajectory_metadata_blob VALUES (?,?)', ('main', bytefield(7, b'file:///example/DUFMech')))
        db.executemany('INSERT INTO steps VALUES (?,?,?,?)', [
            (11000, 15, 3, completed), (11001, 23, 3, old_goal),
            (11642, 14, 3, declaration), (12000, 15, 3, completed),
            (12184, 23, 3, checkpoint), (12313, 15, 3, bytefield(20, bytefield(1, b'Ordinary reply.')))])
    return db_path, old, current, old_epoch, current_epoch


def test_native_proof_requires_both_completed_histories_and_is_read_only(native_case):
    path, old, current, _, _ = native_case
    before = path.read_bytes()
    proof = native.reconciliation_evidence('/example/DUFMech', 'synthetic', old, current)
    assert path.read_bytes() == before and not path.with_suffix('.db-wal').exists()
    assert proof['historical_goal_identity'] == old and proof['current_goal_identity'] == current
    assert proof['historical_completions'][0]['step_index'] == 11000
    assert proof['current_completions'][0]['step_index'] == 12000
    assert proof['latest_checkpoint_step'] == 12184 and proof['last_step']['index'] == 12313
    assert 'goal_text' not in str(proof)


@pytest.mark.parametrize('mutation', ['old_active', 'missing_old_checkpoint', 'missing_old_marker', 'old_cancelled',
                                      'intervening_goal', 'current_active', 'pending_tool', 'wrong_old_identity', 'missing_current_marker'])
def test_ambiguous_or_incomplete_native_history_refuses(native_case, mutation):
    path, old, current, old_epoch, current_epoch = native_case
    with sqlite3.connect(path) as db:
        if mutation == 'old_active':
            checkpoint = bytefield(1, encoded_goal(10144, old_epoch, 1)) + bytefield(2, encoded_goal(11642, current_epoch))
            db.execute('UPDATE steps SET step_payload=? WHERE idx=12184', (checkpoint,))
        elif mutation == 'missing_old_checkpoint':
            db.execute('DELETE FROM steps WHERE idx=11001')
        elif mutation == 'missing_old_marker':
            db.execute('DELETE FROM steps WHERE idx=11000')
        elif mutation == 'old_cancelled':
            db.execute('UPDATE steps SET step_payload=? WHERE idx=11000',
                       (bytefield(20, bytefield(1, b'Cancelled.\n<!-- GOAL_CANCELLED -->')),))
        elif mutation == 'intervening_goal':
            db.execute('INSERT INTO steps SELECT 11200,step_type,status,step_payload FROM steps WHERE idx=11642')
        elif mutation == 'current_active':
            checkpoint = bytefield(1, encoded_goal(10144, old_epoch)) + bytefield(2, encoded_goal(11642, current_epoch, 1))
            db.execute('UPDATE steps SET step_payload=? WHERE idx=12184', (checkpoint,))
        elif mutation == 'pending_tool':
            db.execute('INSERT INTO steps VALUES (12314,1,11,?)', (b'',))
        elif mutation == 'wrong_old_identity':
            old = {**old, 'started_at': '2026-10-25T00:00:01+00:00'}
        elif mutation == 'missing_current_marker':
            db.execute('DELETE FROM steps WHERE idx=12000')
    before = path.read_bytes()
    with pytest.raises(ValueError):
        native.reconciliation_evidence('/example/DUFMech', 'synthetic', old, current)
    assert path.read_bytes() == before
