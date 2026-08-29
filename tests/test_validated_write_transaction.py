"""Contracts for the shared validated-write transaction (Phase 3).

The property that matters is all-or-nothing: validation runs over the complete
staged set before any target is touched, so one invalid record cannot leave the
earlier ones already written. That is precisely what #156 lacked -- a
per-record writer wrote everything classified before the first record that
needed an unreadable vocabulary, then aborted.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kg_microbe_write import (
    JOURNAL_VERSION,
    ValidatedWriteTransaction,
    ValidationFailed,
    WriteError,
    recover,
)


@pytest.fixture
def root(tmp_path: Path) -> Path:
    (tmp_path / "corpus").mkdir()
    return tmp_path / "corpus"


def _seed(root: Path, name: str, text: str) -> Path:
    path = root / name
    path.write_text(text, encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# Nothing is written before commit
# --------------------------------------------------------------------------


def test_staging_writes_nothing(root):
    _seed(root, "a.yaml", "old\n")
    transaction = ValidatedWriteTransaction(root)

    transaction.stage("a.yaml", "new\n")

    assert (root / "a.yaml").read_text(encoding="utf-8") == "old\n"


def test_a_dry_run_commit_writes_nothing_but_reports_the_change(root):
    _seed(root, "a.yaml", "old\n")
    transaction = ValidatedWriteTransaction(root)
    transaction.stage("a.yaml", "new\n")

    result = transaction.commit()

    assert result.applied is False
    assert result.changed == (root / "a.yaml",)
    assert (root / "a.yaml").read_text(encoding="utf-8") == "old\n"


def test_apply_writes_the_staged_content(root):
    _seed(root, "a.yaml", "old\n")
    transaction = ValidatedWriteTransaction(root)
    transaction.stage("a.yaml", "new\n")

    result = transaction.commit(apply=True)

    assert result.applied is True
    assert (root / "a.yaml").read_text(encoding="utf-8") == "new\n"


def test_an_unchanged_file_is_reported_and_not_rewritten(root):
    path = _seed(root, "a.yaml", "same\n")
    before = path.stat().st_mtime_ns
    transaction = ValidatedWriteTransaction(root)
    transaction.stage("a.yaml", "same\n")

    result = transaction.commit(apply=True)

    assert result.unchanged == (path,)
    assert result.changed == ()
    assert path.stat().st_mtime_ns == before, "an identical file must not be touched"


def test_a_new_file_is_reported_as_created(root):
    transaction = ValidatedWriteTransaction(root)
    transaction.stage("new.yaml", "content\n")

    result = transaction.commit(apply=True)

    assert result.created == (root / "new.yaml",)
    assert (root / "new.yaml").read_text(encoding="utf-8") == "content\n"


# --------------------------------------------------------------------------
# All-or-nothing: the #156 property
# --------------------------------------------------------------------------


def test_one_invalid_change_prevents_every_other_write(root):
    """#156: a per-record writer wrote everything before the record that failed.

    The staged set is validated in full first, so the valid records that sort
    ahead of the invalid one are still untouched when it is rejected.
    """
    _seed(root, "aaa.yaml", "old-a\n")
    _seed(root, "zzz.yaml", "old-z\n")

    def reject_z(path: Path, text: str) -> None:
        if path.name.startswith("zzz"):
            raise ValueError("this record is not acceptable")

    transaction = ValidatedWriteTransaction(root, validator=reject_z)
    transaction.stage("aaa.yaml", "new-a\n")
    transaction.stage("zzz.yaml", "new-z\n")

    with pytest.raises(ValidationFailed, match="nothing was written"):
        transaction.commit(apply=True)

    assert (root / "aaa.yaml").read_text(encoding="utf-8") == "old-a\n"
    assert (root / "zzz.yaml").read_text(encoding="utf-8") == "old-z\n"


def test_validation_runs_on_a_dry_run_too(root):
    """A dry run must be a real check, not a preview that defers the verdict."""
    _seed(root, "a.yaml", "old\n")

    def always_reject(path: Path, text: str) -> None:
        raise ValueError("no")

    transaction = ValidatedWriteTransaction(root, validator=always_reject)
    transaction.stage("a.yaml", "new\n")

    with pytest.raises(ValidationFailed):
        transaction.commit()


def test_every_validation_failure_is_reported_not_just_the_first(root):
    def always_reject(path: Path, text: str) -> None:
        raise ValueError(f"bad {path.name}")

    transaction = ValidatedWriteTransaction(root, validator=always_reject)
    transaction.stage("a.yaml", "x\n")
    transaction.stage("b.yaml", "y\n")

    with pytest.raises(ValidationFailed) as excinfo:
        transaction.commit(apply=True)

    assert "bad a.yaml" in str(excinfo.value)
    assert "bad b.yaml" in str(excinfo.value)


# --------------------------------------------------------------------------
# The target must stay inside the root
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "escape", ["../outside.yaml", "sub/../../outside.yaml", "/etc/passwd"]
)
def test_a_path_outside_the_root_is_refused(root, escape):
    """A writer aiming outside the repository it was handed is a bug; silently
    rewriting the destination would hide it."""
    transaction = ValidatedWriteTransaction(root)

    with pytest.raises(WriteError, match="outside the transaction root"):
        transaction.stage(escape, "x\n")


def test_a_symlink_that_leaves_the_root_is_refused(root, tmp_path):
    outside = tmp_path / "outside.yaml"
    outside.write_text("secret\n", encoding="utf-8")
    (root / "link.yaml").symlink_to(outside)
    transaction = ValidatedWriteTransaction(root)

    with pytest.raises(WriteError, match="outside the transaction root"):
        transaction.stage("link.yaml", "x\n")

    assert outside.read_text(encoding="utf-8") == "secret\n"


def test_non_string_content_is_refused(root):
    transaction = ValidatedWriteTransaction(root)

    with pytest.raises(WriteError, match="must be str"):
        transaction.stage("a.yaml", {"not": "text"})


# --------------------------------------------------------------------------
# Diff
# --------------------------------------------------------------------------


def test_the_diff_shows_what_would_change(root):
    _seed(root, "a.yaml", "old\n")
    transaction = ValidatedWriteTransaction(root)
    transaction.stage("a.yaml", "new\n")

    diff = transaction.diff()

    assert "-old" in diff
    assert "+new" in diff


def test_an_unchanged_file_contributes_no_diff(root):
    _seed(root, "a.yaml", "same\n")
    transaction = ValidatedWriteTransaction(root)
    transaction.stage("a.yaml", "same\n")

    assert transaction.diff() == ""


# --------------------------------------------------------------------------
# Recovery journal
# --------------------------------------------------------------------------


def test_the_journal_records_prior_contents_before_the_write(root, tmp_path):
    _seed(root, "a.yaml", "old\n")
    transaction = ValidatedWriteTransaction(
        root, journal_dir=tmp_path / "journal"
    )
    transaction.stage("a.yaml", "new\n")

    result = transaction.commit(apply=True)

    assert result.journal_path is not None
    previous = recover(result.journal_path)
    assert previous[str(root / "a.yaml")] == "old\n"


def test_a_completed_journal_says_so(root, tmp_path):
    _seed(root, "a.yaml", "old\n")
    transaction = ValidatedWriteTransaction(
        root, journal_dir=tmp_path / "journal"
    )
    transaction.stage("a.yaml", "new\n")

    result = transaction.commit(apply=True)
    payload = json.loads(result.journal_path.read_text(encoding="utf-8"))

    assert payload["status"] == "complete"
    assert payload["version"] == JOURNAL_VERSION


def test_no_journal_is_written_on_a_dry_run(root, tmp_path):
    _seed(root, "a.yaml", "old\n")
    journal = tmp_path / "journal"
    transaction = ValidatedWriteTransaction(root, journal_dir=journal)
    transaction.stage("a.yaml", "new\n")

    result = transaction.commit()

    assert result.journal_path is None
    assert not journal.exists()


def test_recover_refuses_an_unknown_journal_version(tmp_path):
    path = tmp_path / "j.json"
    path.write_text(json.dumps({"version": 999}), encoding="utf-8")

    with pytest.raises(WriteError, match="unsupported journal version"):
        recover(path)


# --------------------------------------------------------------------------
# Atomicity
# --------------------------------------------------------------------------


def test_a_failed_write_leaves_no_temporary_files(root, monkeypatch):
    _seed(root, "a.yaml", "old\n")
    transaction = ValidatedWriteTransaction(root)
    transaction.stage("a.yaml", "new\n")

    import kg_microbe_write.transaction as module

    def boom(src, dst):
        raise OSError("replace failed")

    monkeypatch.setattr(module.os, "replace", boom)

    with pytest.raises(WriteError, match="journal at|write failed"):
        transaction.commit(apply=True)

    leftovers = [p.name for p in root.iterdir() if p.name.startswith(".")]
    assert leftovers == [], f"temporary files left behind: {leftovers}"
    assert (root / "a.yaml").read_text(encoding="utf-8") == "old\n"


# --------------------------------------------------------------------------
# #168: journals must stay bounded, without losing an interrupted one
# --------------------------------------------------------------------------


def _commit_once(root: Path, journal: Path, text: str, retention: int = 3):
    transaction = ValidatedWriteTransaction(
        root, journal_dir=journal, journal_retention=retention
    )
    transaction.stage("a.yaml", text)
    return transaction.commit(apply=True)


def test_completed_journals_are_pruned_to_the_retention_limit(root, tmp_path):
    """Each journal embeds every changed file's prior content, so an apply over
    a few thousand records is large and they otherwise accumulate for ever."""
    journal = tmp_path / "journal"
    _seed(root, "a.yaml", "v0\n")

    for index in range(8):
        _commit_once(root, journal, f"v{index + 1}\n", retention=3)

    assert len(list(journal.glob("write-*.json"))) == 3


def test_retention_of_one_keeps_only_the_run_that_just_finished(root, tmp_path):
    journal = tmp_path / "journal"
    _seed(root, "a.yaml", "v0\n")

    _commit_once(root, journal, "v1\n", retention=1)
    result = _commit_once(root, journal, "v2\n", retention=1)

    remaining = list(journal.glob("write-*.json"))
    assert remaining == [result.journal_path]


def test_an_in_progress_journal_is_never_pruned(root, tmp_path):
    """It is the one an interrupted run left behind, and the only record of
    what it was doing. Pruning by age alone would delete exactly that."""
    journal = tmp_path / "journal"
    journal.mkdir()
    stranded = journal / "write-interrupted.json"
    stranded.write_text(
        json.dumps({
            "version": JOURNAL_VERSION,
            "status": "in_progress",
            "root": str(root),
            "changed": [str(root / "a.yaml")],
            "created": [],
            "previous": {str(root / "a.yaml"): "the only copy\n"},
        }),
        encoding="utf-8",
    )
    _seed(root, "a.yaml", "v0\n")

    for index in range(6):
        _commit_once(root, journal, f"v{index + 1}\n", retention=2)

    assert stranded.is_file(), "the interrupted journal was pruned"
    assert recover(stranded)[str(root / "a.yaml")] == "the only copy\n"


def test_a_retention_below_one_is_refused(root, tmp_path):
    with pytest.raises(WriteError, match="at least 1"):
        ValidatedWriteTransaction(
            root, journal_dir=tmp_path / "j", journal_retention=0
        )


def test_pruning_ignores_an_unreadable_journal_rather_than_crashing(root, tmp_path):
    """A corrupt file in the directory must not take down an unrelated write."""
    journal = tmp_path / "journal"
    journal.mkdir()
    (journal / "write-garbage.json").write_text("{not json", encoding="utf-8")
    _seed(root, "a.yaml", "v0\n")

    result = _commit_once(root, journal, "v1\n", retention=2)

    assert result.applied is True
    assert (journal / "write-garbage.json").is_file()


# --------------------------------------------------------------------------
# #169: every exit from the public surface raises the declared error type
# --------------------------------------------------------------------------


def test_an_absent_root_raises_write_error_not_a_bare_oserror(tmp_path):
    """`except WriteError` is the obvious thing a caller writes; it must work.

    Third instance of this class here -- #150 (AttributeError escaping
    VocabularyError) and #151 (TypeError from inside an error message) were the
    others -- so the message also says what an absent root usually means.
    """
    with pytest.raises(WriteError, match="not an existing directory"):
        ValidatedWriteTransaction(tmp_path / "nonexistent")


def test_a_file_as_the_root_is_refused(tmp_path):
    target = tmp_path / "a-file"
    target.write_text("x", encoding="utf-8")

    with pytest.raises(WriteError, match="not a directory"):
        ValidatedWriteTransaction(target)


def test_the_absent_root_message_names_the_likely_cause(tmp_path):
    with pytest.raises(WriteError) as excinfo:
        ValidatedWriteTransaction(tmp_path / "nonexistent")

    assert "checkout is missing" in str(excinfo.value)
