"""Real wire/SQLite public-message proof; no live conversation or fixture reads."""
from __future__ import annotations

import copy
import hashlib
import sqlite3
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from test_mech_session_native import bytefield, goal_context, intfield, native
from test_native_historical_reconciliation import encoded_goal

REPOSITORY = "CultureBotAI/NaturalProductMech"
ROOT = "/example/NaturalProductMech"


def payload(text):
    return bytefield(20, bytefield(1, text.encode()))


def completion_line(item):
    return f"PR #{item['number']} (`{item['branch']}`, merged in `{item['merge_commit_sha']}`)"


def update_public(case, text, *, step=16985, kind=15, status=3, rehash=True):
    with sqlite3.connect(case.path) as connection:
        connection.execute("UPDATE steps SET step_type=?,status=?,step_payload=? WHERE idx=?", (kind, status, payload(text), step))
    if rehash:
        for item in case.items:
            item["native_statement"] = {"step_index": step, "text_sha256": hashlib.sha256(text.encode()).hexdigest()}


@pytest.fixture
def npm_native(tmp_path, monkeypatch):
    monkeypatch.setattr(native, "ROOT", tmp_path)
    (tmp_path / "conversations").mkdir()
    path = tmp_path / "conversations/synthetic-npm.db"
    old_epoch, new_epoch = 1792886400, 1793232000
    old = {"conversation_id": "synthetic-npm", "start_step_index": 13623,
           "started_at": datetime.fromtimestamp(old_epoch, timezone.utc).isoformat()}
    current = {**old, "start_step_index": 14303, "started_at": datetime.fromtimestamp(new_epoch, timezone.utc).isoformat()}
    items = [{"number": number, "head_sha": head * 40, "merge_commit_sha": merge * 40,
              "branch": f"synthetic-chelators-{index}", "goal_identity": copy.deepcopy(current)}
             for index, (number, head, merge) in enumerate([(1057, "d", "e"), (1062, "1", "2")], 1)]
    text = "\n".join([*(completion_line(item) for item in items), "<!-- GOAL_COMPLETE -->"])
    for item in items:
        item["native_statement"] = {"step_index": 16985, "text_sha256": hashlib.sha256(text.encode()).hexdigest()}
    declaration = bytefield(19, bytefield(3, bytefield(1, b"Synthetic external goal")) + goal_context())
    old_goal = encoded_goal(13623, old_epoch)
    checkpoint = bytefield(1, old_goal) + bytefield(2, encoded_goal(14303, new_epoch))
    with sqlite3.connect(path) as connection:
        connection.executescript("CREATE TABLE trajectory_meta (trajectory_id text,cascade_id text);"
                                "CREATE TABLE steps (idx integer,step_type integer,status integer,step_payload blob);"
                                "CREATE TABLE trajectory_metadata_blob (id text,data blob);")
        connection.execute("INSERT INTO trajectory_meta VALUES (?,?)", ("synthetic-npm", "synthetic-npm"))
        connection.execute("INSERT INTO trajectory_metadata_blob VALUES (?,?)", ("main", bytefield(7, f"file://{ROOT}".encode())))
        connection.executemany("INSERT INTO steps VALUES (?,?,?,?)", [
            (14275, 15, 3, payload("Historical goal done.\n<!-- GOAL_COMPLETE -->")),
            (14276, 23, 3, old_goal), (14303, 14, 3, declaration),
            (16807, 23, 3, checkpoint), (16985, 15, 3, payload(text)),
            (17000, 15, 3, payload("Ordinary later reply.")),
        ])
    return SimpleNamespace(path=path, old=old, current=current, items=items, text=text,
                           old_epoch=old_epoch, new_epoch=new_epoch)


def proof(case):
    return native.reconciliation_evidence(ROOT, "synthetic-npm", case.old, case.current,
                                          external_prs=case.items, github_repository=REPOSITORY)


def test_real_native_completion_binds_both_exact_external_merges_read_only(npm_native):
    case = npm_native
    before = case.path.read_bytes()
    result = proof(case)
    assert case.path.read_bytes() == before and not case.path.with_suffix(".db-wal").exists()
    assert result["historical_goal_identity"]["start_step_index"] == 13623
    assert result["current_goal_identity"]["start_step_index"] == 14303
    assert [item["number"] for item in result["external_pr_bindings"]] == [1057, 1062]
    assert all(item["goal_identity"] == case.current for item in result["external_pr_bindings"])
    assert all(item["native_statement"]["step_index"] == 16985 for item in result["external_pr_bindings"])
    assert "Synthetic external goal" not in str(result)


def test_canonical_repository_pr_urls_are_also_accepted(npm_native):
    text = "\n".join([*(f"https://github.com/{REPOSITORY}/pull/{item['number']} `{item['branch']}` `{item['merge_commit_sha']}`"
                         for item in npm_native.items), "<!-- GOAL_COMPLETE -->"])
    update_public(npm_native, text)
    assert len(proof(npm_native)["external_pr_bindings"]) == 2


@pytest.mark.parametrize("mutation", ["multiple_prs", "multiple_shas", "sha_prefix", "sha_suffix", "number_prefix", "branch_prefix",
                                      "different_line", "literal_newline", "wrong_repo", "wrong_url_kind", "stale_hash", "ordinary",
                                      "user", "tool", "pending", "wrong_goal", "missing_pr", "missing_branch"])
def test_native_external_reference_is_exact_unambiguous_public_and_completed(npm_native, mutation):
    case = npm_native
    lines = case.text.splitlines()
    first = case.items[0]
    if mutation == "multiple_prs":
        lines[0] += " PR #999"
    elif mutation == "multiple_shas":
        lines[0] += " " + "9" * 40
    elif mutation == "sha_prefix":
        lines[0] = lines[0].replace(first["merge_commit_sha"], first["merge_commit_sha"][:12])
    elif mutation == "sha_suffix":
        lines[0] = lines[0].replace(first["merge_commit_sha"], first["merge_commit_sha"] + "a")
    elif mutation == "number_prefix":
        lines[0] = lines[0].replace("PR #1057", "PR #10570")
    elif mutation == "branch_prefix":
        lines[0] = lines[0].replace(first["branch"], first["branch"] + "-unrelated")
    elif mutation == "different_line":
        lines[0] = lines[0].replace(first["merge_commit_sha"], "\n" + first["merge_commit_sha"])
    elif mutation == "literal_newline":
        lines[0] += "\\n" + lines[1]
        lines[1] = ""
    elif mutation == "wrong_repo":
        lines[0] += " https://github.com/Other/NaturalProductMech/pull/1057"
    elif mutation == "wrong_url_kind":
        lines[0] += f" https://github.com/{REPOSITORY}/issues/1057"
    elif mutation == "ordinary":
        lines = lines[:-1]
    elif mutation == "wrong_goal":
        case.items[0]["goal_identity"] = copy.deepcopy(case.old)
    elif mutation == "missing_pr":
        lines[0] = lines[0].replace("PR #1057", "Unattributed change")
    elif mutation == "missing_branch":
        lines[0] = lines[0].replace(first["branch"], "")
    elif mutation == "stale_hash":
        lines[0] += " changed text"
    text = "\n".join(lines)
    update_public(case, text, kind={"user": 1, "tool": 4}.get(mutation, 15),
                  status=11 if mutation == "pending" else 3, rehash=mutation != "stale_hash")
    before = case.path.read_bytes()
    with pytest.raises(ValueError):
        proof(case)
    assert case.path.read_bytes() == before


@pytest.mark.parametrize("mutation", ["no_pre_external_checkpoint", "cleared_declaration", "cleared_old_completion", "resumed", "intervening"])
def test_later_or_cleared_history_cannot_silently_relax_existing_native_proof(npm_native, mutation):
    case = npm_native
    with sqlite3.connect(case.path) as connection:
        if mutation == "no_pre_external_checkpoint":
            connection.execute("DELETE FROM steps WHERE idx=14276")
        elif mutation == "cleared_declaration":
            connection.execute("UPDATE steps SET status=5 WHERE idx=14303")
        elif mutation == "cleared_old_completion":
            connection.execute("UPDATE steps SET status=5 WHERE idx=14275")
        elif mutation == "resumed":
            connection.execute("UPDATE steps SET step_payload=? WHERE idx=16807", (
                bytefield(1, encoded_goal(13623, case.old_epoch, 1)) + bytefield(2, encoded_goal(14303, case.new_epoch)),))
        else:
            connection.execute("INSERT INTO steps SELECT 14300,step_type,status,step_payload FROM steps WHERE idx=14303")
    before = case.path.read_bytes()
    with pytest.raises(ValueError):
        proof(case)
    assert case.path.read_bytes() == before


def retained_row(kind, status, body, *, created=None, completed=None):
    """Wire metadata is original input evidence, never inferred from row status."""
    metadata = b""
    if created is not None:
        metadata += bytefield(1, intfield(1, created))
    if completed is not None:
        metadata += bytefield(8, intfield(1, completed))
    return intfield(1, kind) + intfield(4, status) + bytefield(5, metadata) + body


def replace_retained(case, index, kind, status, body, *, created=None, completed=None):
    with sqlite3.connect(case.path) as connection:
        connection.execute("UPDATE steps SET step_type=?,status=?,step_payload=? WHERE idx=?",
                           (kind, status, retained_row(kind, status, body, created=created, completed=completed), index))


@pytest.fixture
def npm_retained(npm_native):
    case = npm_native
    declaration = bytefield(19, bytefield(3, bytefield(1, b"Synthetic declared goal")) + goal_context())
    checkpoint = bytefield(11, bytefield(1, encoded_goal(13623, case.old_epoch)) + bytefield(2, encoded_goal(14303, case.new_epoch)))
    with sqlite3.connect(case.path) as connection:
        connection.execute("DELETE FROM steps")
        rows = []
        for index in range(13623, 17001):
            kind, status, body = 15, 3, payload("Ordinary retained reply.")
            created = completed = None
            if index in {13623, 14303}:
                kind, status, body = 14, 5, declaration
                created = case.old_epoch if index == 13623 else case.new_epoch
            elif index == 14275:
                status, body = 5, payload("Historical done.\n<!-- GOAL_COMPLETE -->")
                created, completed = case.old_epoch + 60, case.old_epoch + 120
            elif index == 16807:
                kind, body = 23, checkpoint
            elif index == 16985:
                body = payload(case.text)
                created, completed = case.new_epoch + 1000, case.new_epoch + 1100
            rows.append((index, kind, status, retained_row(kind, status, body, created=created, completed=completed)))
        connection.executemany("INSERT INTO steps VALUES (?,?,?,?)", rows)
    return case


def retained_proof(case):
    return native.reconciliation_evidence(ROOT, "synthetic-npm", case.old, case.current,
        external_prs=case.items, github_repository=REPOSITORY, native_proof_mode="retained_public_attestation")


def test_explicit_retained_mode_corroborates_original_timed_public_history_read_only(npm_retained):
    case = npm_retained
    before = case.path.read_bytes()
    result = retained_proof(case)
    assert case.path.read_bytes() == before and not case.path.with_suffix(".db-wal").exists()
    assert result["native_proof_mode"] == "retained_public_attestation"
    assert result["authority"] == "corroboration_for_reviewed_operator_attestation_not_task_acceptance"
    assert result["retained_row_count"] == 3378 and len(result["retained_rows_sha256"]) == 64
    assert [(item["step_index"], item["status"]) for item in result["declarations"]] == [(13623, "cleared"), (14303, "cleared")]
    assert result["historical_completions"][0]["status"] == "cleared"
    assert result["historical_completions"][0]["completed_at"] < case.current["started_at"]
    assert all(item["step_index"] > 14303 for item in result["historical_checkpoints"])
    assert [item["number"] for item in result["external_pr_bindings"]] == [1057, 1062]
    assert all(item["goal_identity"] == case.current for item in result["external_pr_bindings"])
    # This is not a transparent fallback and does not weaken the schema1 proof.
    with pytest.raises(ValueError):
        proof(case)
    assert case.path.read_bytes() == before


@pytest.mark.parametrize("mutation", [
    "missing_row", "duplicate_row", "status_mismatch", "kind_mismatch", "unknown_status",
    "missing_old_declaration_time", "wrong_old_declaration_time", "missing_current_declaration_time",
    "wrong_current_declaration_time", "missing_old_completion_time", "completion_after_external",
    "completion_before_creation", "future_completion", "naive_identity", "missing_old_declaration",
    "missing_current_declaration", "cancelled_cleared", "resumed_cleared", "intervening_cleared",
    "stale_hash", "cleared_current_completion", "old_user_marker", "old_tool_marker", "current_user_marker",
])
def test_retained_mode_requires_complete_authentic_timed_unambiguous_history(npm_retained, mutation):
    case = npm_retained
    declaration = bytefield(19, bytefield(3, bytefield(1, b"Synthetic declared goal")) + goal_context())
    old_body = payload("Historical done.\n<!-- GOAL_COMPLETE -->")
    if mutation in {"missing_row", "duplicate_row", "status_mismatch", "kind_mismatch"}:
        with sqlite3.connect(case.path) as connection:
            if mutation == "missing_row":
                connection.execute("DELETE FROM steps WHERE idx=14000")
            elif mutation == "duplicate_row":
                connection.execute("INSERT INTO steps SELECT * FROM steps WHERE idx=14000")
            elif mutation == "status_mismatch":
                connection.execute("UPDATE steps SET status=5 WHERE idx=14000")
            else:
                connection.execute("UPDATE steps SET step_type=4 WHERE idx=14000")
    elif mutation == "unknown_status":
        replace_retained(case, 14000, 15, 99, payload("ordinary"))
    elif mutation in {"missing_old_declaration_time", "wrong_old_declaration_time"}:
        replace_retained(case, 13623, 14, 5, declaration,
                         created=None if mutation.startswith("missing") else case.old_epoch + 1)
    elif mutation in {"missing_current_declaration_time", "wrong_current_declaration_time"}:
        replace_retained(case, 14303, 14, 5, declaration,
                         created=None if mutation.startswith("missing") else case.new_epoch + 1)
    elif mutation == "missing_old_completion_time":
        replace_retained(case, 14275, 15, 5, old_body, created=case.old_epoch + 60)
    elif mutation == "completion_after_external":
        replace_retained(case, 14275, 15, 5, old_body, created=case.old_epoch + 60, completed=case.new_epoch + 1)
    elif mutation == "completion_before_creation":
        replace_retained(case, 14275, 15, 5, old_body, created=case.old_epoch + 60, completed=case.old_epoch + 1)
    elif mutation == "future_completion":
        replace_retained(case, 16985, 15, 3, payload(case.text), created=case.new_epoch + 1000, completed=4102444800)
    elif mutation == "naive_identity":
        case.old["started_at"] = case.old["started_at"].removesuffix("+00:00")
    elif mutation in {"missing_old_declaration", "missing_current_declaration"}:
        replace_retained(case, 13623 if mutation == "missing_old_declaration" else 14303, 15, 3, payload("ordinary"))
    elif mutation == "cancelled_cleared":
        replace_retained(case, 14280, 15, 5, payload("Cancelled.\n<!-- GOAL_CANCELLED -->"),
                         created=case.old_epoch + 130, completed=case.old_epoch + 150)
    elif mutation == "resumed_cleared":
        replace_retained(case, 14280, 23, 5, bytefield(11, encoded_goal(13623, case.old_epoch, 1)))
    elif mutation == "intervening_cleared":
        replace_retained(case, 14280, 14, 5, declaration, created=case.old_epoch + 200)
    elif mutation == "stale_hash":
        case.items[0]["native_statement"]["text_sha256"] = "0" * 64
    elif mutation == "cleared_current_completion":
        replace_retained(case, 16985, 15, 5, payload(case.text), created=case.new_epoch + 1000, completed=case.new_epoch + 1100)
    elif mutation in {"old_user_marker", "old_tool_marker"}:
        replace_retained(case, 14275, 14 if mutation == "old_user_marker" else 4, 5, old_body,
                         created=case.old_epoch + 60, completed=case.old_epoch + 120)
    else:
        replace_retained(case, 16985, 14, 3, payload(case.text), created=case.new_epoch + 1000, completed=case.new_epoch + 1100)
    before = case.path.read_bytes()
    with pytest.raises(ValueError):
        retained_proof(case)
    assert case.path.read_bytes() == before
