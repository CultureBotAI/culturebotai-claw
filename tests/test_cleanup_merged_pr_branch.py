"""scripts/adhoc/cleanup_merged_pr_branch.py deletes only the merged work (#854-#856, #858, #867-#875, #878-#880, #891-#895).

Each case is built so the unsafe and the safe behaviour differ: a remote
branch that moved after the merge, a sibling branch whose name ends the same
way, an ignored result file, a status setting that hides it, an edit hidden
by skip-worktree or assume-unchanged, a detached commit, a locked worktree, a
worktree of another clone, a relative path that names a different worktree
from the checkout than from here, a tracking ref that moved, a held lock, an
origin that is not the expected repository, a failure before and after the
first deletion.

The repositories are real: a bare origin and a clone under tmp_path. What is
replaced: `gh pr view` always; the origin-identity check everywhere except the
test that runs the real one, since a local origin can never be a GitHub
repository (the stub records its arguments and whether the repository lock was
held when it ran); and, in three race tests, `remote_branch_sha` or
`tracking_sha`, to stand in for a change landing between the check and the
delete.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from kg_microbe_fleet import load_fleet_manifest
from plugins.lock_manager import LockManager

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/adhoc/cleanup_merged_pr_branch.py"
SPEC = importlib.util.spec_from_file_location("cleanup_merged_pr_branch", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
cleanup_script = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cleanup_script)

MECH = "traitmech"
REPO = load_fleet_manifest().mechs[MECH].github


def git(path: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(path), *args], text=True, capture_output=True,
                          check=True).stdout.strip()


def ref(path: Path, name: str) -> str | None:
    completed = subprocess.run(["git", "-C", str(path), "rev-parse", "--verify", "--quiet", name],
                               text=True, capture_output=True, check=False)
    return completed.stdout.strip() or None


def commit(path: Path, name: str) -> str:
    (path / name).write_text(name + "\n", encoding="utf-8")
    git(path, "add", name)
    git(path, "commit", "-q", "-m", name)
    return git(path, "rev-parse", "HEAD")


@pytest.fixture
def fleet(tmp_path, monkeypatch):
    """A bare origin, a clone on main, and a worktree on a pushed feature branch."""
    config = tmp_path / "gitconfig"
    config.write_text("[user]\n\tname = test\n\temail = test\n[init]\n\tdefaultBranch = main\n", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("OPENCLAW_WORKSPACE", str(tmp_path / "workspace"))
    monkeypatch.setenv("OPENCLAW_ORCHESTRATION_ROOT", str(tmp_path))
    source = tmp_path / "source"
    source.mkdir()
    git(source, "init", "-q")
    (source / ".gitignore").write_text("__pycache__/\nresults/\n.DS_Store*\n", encoding="utf-8")
    git(source, "add", ".gitignore")
    git(source, "commit", "-q", "-m", "initial")
    origin = tmp_path / "origin.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(source), str(origin)], check=True)
    checkout = tmp_path / "checkout"
    subprocess.run(["git", "clone", "-q", str(origin), str(checkout)], check=True)
    worktree = tmp_path / "wt"
    git(checkout, "worktree", "add", "-q", "-b", "feature", str(worktree), "origin/main")
    head = commit(worktree, "change")
    git(worktree, "push", "-q", "origin", "HEAD:refs/heads/feature")
    git(checkout, "fetch", "-q", "origin")
    origin_calls: list[tuple] = []

    def verify(key, path, repo):
        try:
            with LockManager().lock(key, "probe"):
                held = False
        except RuntimeError:
            held = True
        origin_calls.append((key, path, repo, held))

    return {"origin": origin, "checkout": checkout, "worktree": worktree, "head": head, "tmp": tmp_path,
            "verify": verify, "origin_calls": origin_calls}


def merged(fleet, **overrides):
    pr = {"state": "MERGED", "headRefName": "feature", "headRefOid": fleet["head"], "isCrossRepository": False}
    pr.update(overrides)
    return lambda repo, number: pr


def run_cleanup(fleet, worktree="default", apply=True, **overrides):
    return cleanup_script.cleanup(
        REPO, 1, fleet["checkout"], fleet["worktree"] if worktree == "default" else worktree, apply=apply,
        pr_view=merged(fleet, **overrides), verify_origin=fleet["verify"])


def run_main(fleet, monkeypatch, worktree="default"):
    monkeypatch.setattr(cleanup_script, "gh_pr_view", merged(fleet))
    monkeypatch.setattr(cleanup_script, "open_target", fleet["verify"])
    argv = ["cleanup_merged_pr_branch.py", "--repo", REPO, "--pr", "1", "--checkout", str(fleet["checkout"]), "--apply"]
    if worktree == "default":
        argv += ["--worktree", str(fleet["worktree"])]
    monkeypatch.setattr(sys, "argv", argv)
    return cleanup_script.main()


def untouched(fleet) -> bool:
    return (fleet["worktree"].exists()
            and ref(fleet["checkout"], "refs/heads/feature") is not None
            and ref(fleet["origin"], "refs/heads/feature") is not None)


def push_follow_up(fleet) -> str:
    other = fleet["tmp"] / "other"
    subprocess.run(["git", "clone", "-q", "-b", "feature", str(fleet["origin"]), str(other)], check=True)
    later = commit(other, "follow-up")
    git(other, "push", "-q", "origin", "feature")
    return later


def drop_worktree_and_local(fleet) -> None:
    git(fleet["checkout"], "worktree", "remove", str(fleet["worktree"]))
    git(fleet["checkout"], "branch", "-q", "-D", "feature")


def test_the_merged_branch_is_removed_everywhere_and_caches_do_not_block(fleet):
    (fleet["worktree"] / "__pycache__").mkdir()
    (fleet["worktree"] / "__pycache__" / "x.pyc").write_bytes(b"cache")
    assert git(fleet["checkout"], "config", "--get", "branch.feature.merge") == "refs/heads/main"

    done = run_cleanup(fleet)

    assert not fleet["worktree"].exists()
    assert ref(fleet["checkout"], "refs/heads/feature") is None
    assert ref(fleet["origin"], "refs/heads/feature") is None
    assert ref(fleet["checkout"], "refs/remotes/origin/feature") is None
    assert "branch.feature." not in git(fleet["checkout"], "config", "--get-regexp", "^branch\\.")
    assert "branch.main.merge" in git(fleet["checkout"], "config", "--get-regexp", "^branch\\.")
    assert done == [f"removed worktree {fleet['worktree'].resolve()}",
                    f"deleted local feature (was {fleet['head'][:10]})", "removed branch.feature config",
                    f"deleted remote feature (was {fleet['head'][:10]})",
                    f"refs/remotes/origin/feature went with the remote branch (was {fleet['head'][:10]})"]
    assert fleet["origin_calls"] == [(MECH, fleet["checkout"].resolve(), REPO, True)]


def test_a_stale_tracking_ref_is_deleted_when_the_remote_branch_is_already_gone(fleet):
    """What the claw PRs look like: GitHub deleted the branch on merge, the clone still tracks it."""
    other = fleet["tmp"] / "other"
    subprocess.run(["git", "clone", "-q", str(fleet["origin"]), str(other)], check=True)
    git(other, "push", "-q", "origin", "--delete", "feature")
    drop_worktree_and_local(fleet)
    assert ref(fleet["checkout"], "refs/remotes/origin/feature") == fleet["head"]

    done = run_cleanup(fleet, worktree=None)

    assert done == ["remote feature already gone", f"deleted refs/remotes/origin/feature (was {fleet['head'][:10]})"]
    assert ref(fleet["checkout"], "refs/remotes/origin/feature") is None


def test_a_dry_run_checks_everything_and_deletes_nothing(fleet):
    plan = run_cleanup(fleet, apply=False)

    assert plan == [f"would remove worktree {fleet['worktree'].resolve()}",
                    f"would delete local feature (at {fleet['head'][:10]})",
                    f"would delete remote feature (at {fleet['head'][:10]})",
                    f"would delete refs/remotes/origin/feature (at {fleet['head'][:10]})"]
    assert untouched(fleet)

    (fleet["worktree"] / "results").mkdir()
    (fleet["worktree"] / "results" / "out.tsv").write_text("kept\n", encoding="utf-8")
    with pytest.raises(cleanup_script.Refused, match="results/"):
        run_cleanup(fleet, apply=False)


def test_a_push_after_the_merge_keeps_every_copy_of_the_branch(fleet):
    later = push_follow_up(fleet)

    with pytest.raises(cleanup_script.Refused, match="origin feature is"):
        run_cleanup(fleet)

    assert untouched(fleet)
    assert ref(fleet["origin"], "refs/heads/feature") == later


def test_the_remote_delete_is_leased_on_the_merged_head_not_the_tracking_ref(fleet, monkeypatch):
    """With the tracking ref already at the follow-up, only a lease on the merged head still refuses."""
    later = push_follow_up(fleet)
    git(fleet["checkout"], "fetch", "-q", "origin")
    assert ref(fleet["checkout"], "refs/remotes/origin/feature") == later
    monkeypatch.setattr(cleanup_script, "remote_branch_sha", lambda checkout, branch: fleet["head"])
    monkeypatch.setattr(cleanup_script, "tracking_sha", lambda checkout, branch: fleet["head"])

    with pytest.raises(cleanup_script.PartialFailure, match="push"):
        run_cleanup(fleet)

    assert ref(fleet["origin"], "refs/heads/feature") == later


def test_a_moved_tracking_ref_is_refused_even_when_the_remote_branch_is_gone(fleet):
    later = push_follow_up(fleet)
    git(fleet["checkout"], "fetch", "-q", "origin")
    git(fleet["tmp"] / "other", "push", "-q", "origin", "--delete", "feature")
    drop_worktree_and_local(fleet)

    with pytest.raises(cleanup_script.Refused, match="refs/remotes/origin/feature is"):
        run_cleanup(fleet, worktree=None)

    assert ref(fleet["checkout"], "refs/remotes/origin/feature") == later


def test_a_failure_after_a_deletion_reports_what_was_done_and_how_to_recover(fleet, monkeypatch, capsys):
    push_follow_up(fleet)
    monkeypatch.setattr(cleanup_script, "remote_branch_sha", lambda checkout, branch: fleet["head"])

    assert run_main(fleet, monkeypatch) == 1

    out, err = capsys.readouterr()
    assert "removed worktree" in out and "deleted local feature" in out
    assert "failed after the steps above" in err
    assert f"branch feature {fleet['head']}" in err and "worktree add" in err
    assert "push origin" not in err


def test_a_failure_before_any_deletion_says_nothing_was_deleted(fleet, monkeypatch, capsys):
    drop_worktree_and_local(fleet)
    hook = fleet["origin"] / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho rejected >&2\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)

    assert run_main(fleet, monkeypatch, worktree=None) == 1

    out, err = capsys.readouterr()
    assert out == ""
    assert "failed, nothing deleted" in err and "recovery" not in err
    assert ref(fleet["origin"], "refs/heads/feature") == fleet["head"]


def test_a_config_lock_still_reports_the_local_branch_deletion(fleet):
    (fleet["checkout"] / ".git" / "config.lock").write_text("", encoding="utf-8")

    with pytest.raises(cleanup_script.PartialFailure, match="branch.feature.remote is still set") as caught:
        run_cleanup(fleet)

    assert caught.value.done == [f"removed worktree {fleet['worktree'].resolve()}",
                                 f"deleted local feature (was {fleet['head'][:10]})"]
    assert "branch feature" in caught.value.recovery and "worktree add" in caught.value.recovery
    assert ref(fleet["checkout"], "refs/heads/feature") is None
    assert ref(fleet["origin"], "refs/heads/feature") == fleet["head"]


def test_the_local_delete_compares_against_the_merged_head(fleet, monkeypatch):
    """A local branch that moves between the check and the delete survives."""
    git(fleet["checkout"], "worktree", "remove", str(fleet["worktree"]))
    main = ref(fleet["checkout"], "origin/main")

    def move_then_report(checkout, branch):
        git(checkout, "branch", "-q", "-f", "feature", main)
        return fleet["head"]

    monkeypatch.setattr(cleanup_script, "remote_branch_sha", move_then_report)

    with pytest.raises(RuntimeError, match="update-ref"):
        run_cleanup(fleet, worktree=None)

    assert ref(fleet["checkout"], "refs/heads/feature") == main


def test_only_the_exact_branch_name_is_matched_on_the_remote(fleet):
    """A sibling `team/feature` at another commit is neither matched nor touched."""
    drop_worktree_and_local(fleet)
    git(fleet["checkout"], "push", "-q", "origin", "--delete", "feature")
    git(fleet["checkout"], "update-ref", "-d", "refs/remotes/origin/feature")
    elsewhere = commit(fleet["checkout"], "elsewhere")
    git(fleet["checkout"], "push", "-q", "origin", "HEAD:refs/heads/team/feature")

    done = run_cleanup(fleet, worktree=None)

    assert done == ["remote feature already gone"]
    assert ref(fleet["origin"], "refs/heads/team/feature") == elsewhere


@pytest.mark.parametrize("overrides,message", [
    ({"state": "OPEN"}, "not MERGED"),
    ({"isCrossRepository": True}, "fork"),
])
def test_an_unmerged_or_forked_pr_is_refused(fleet, overrides, message):
    with pytest.raises(cleanup_script.Refused, match=message):
        run_cleanup(fleet, **overrides)
    assert untouched(fleet)


@pytest.mark.parametrize("kept", ["results/out.tsv", ".DS_Store.bak"])
def test_an_ignored_file_that_is_not_a_cache_blocks_removing_the_worktree(fleet, kept):
    path = fleet["worktree"] / kept
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("kept\n", encoding="utf-8")
    assert git(fleet["worktree"], "status", "--porcelain", "--ignored").startswith("!!")

    with pytest.raises(cleanup_script.Refused, match=kept.split("/")[0]):
        run_cleanup(fleet)

    assert path.read_text(encoding="utf-8") == "kept\n"
    assert untouched(fleet)


def test_a_status_setting_cannot_hide_untracked_or_ignored_files(fleet):
    git(fleet["checkout"], "config", "status.showUntrackedFiles", "no")
    (fleet["worktree"] / "results").mkdir()
    (fleet["worktree"] / "results" / "out.tsv").write_text("kept\n", encoding="utf-8")
    (fleet["worktree"] / "notes.md").write_text("kept\n", encoding="utf-8")

    with pytest.raises(cleanup_script.Refused, match="notes.md"):
        run_cleanup(fleet)

    assert (fleet["worktree"] / "results" / "out.tsv").exists()
    assert (fleet["worktree"] / "notes.md").exists()


@pytest.mark.parametrize("flag", ["--skip-worktree", "--assume-unchanged"])
def test_an_edit_hidden_from_status_blocks_removing_the_worktree(fleet, flag):
    git(fleet["worktree"], "update-index", flag, "change")
    (fleet["worktree"] / "change").write_text("edited\n", encoding="utf-8")
    assert git(fleet["worktree"], "status", "--porcelain") == ""

    with pytest.raises(cleanup_script.Refused, match="skip-worktree or assume-unchanged"):
        run_cleanup(fleet)

    assert (fleet["worktree"] / "change").read_text(encoding="utf-8") == "edited\n"


def test_a_detached_commit_in_the_worktree_blocks_removing_it(fleet):
    git(fleet["worktree"], "checkout", "-q", "--detach")
    detached = commit(fleet["worktree"], "local-only")

    with pytest.raises(cleanup_script.Refused, match="not the merged head"):
        run_cleanup(fleet)

    assert git(fleet["worktree"], "rev-parse", "HEAD") == detached
    assert untouched(fleet)


def test_a_locked_worktree_is_refused_by_the_dry_run_and_by_apply(fleet):
    git(fleet["checkout"], "worktree", "lock", "--reason", "in use", str(fleet["worktree"]))

    with pytest.raises(cleanup_script.Refused, match="locked"):
        run_cleanup(fleet, apply=False)
    with pytest.raises(cleanup_script.Refused, match="locked"):
        run_cleanup(fleet)

    assert untouched(fleet)


def test_a_worktree_of_another_clone_is_refused(fleet):
    clone2 = fleet["tmp"] / "clone2"
    subprocess.run(["git", "clone", "-q", str(fleet["origin"]), str(clone2)], check=True)
    foreign = fleet["tmp"] / "clone2-wt"
    git(clone2, "worktree", "add", "-q", "--detach", str(foreign), fleet["head"])

    with pytest.raises(cleanup_script.Refused, match="not a worktree of"):
        run_cleanup(fleet, worktree=foreign, apply=False)

    assert foreign.exists() and untouched(fleet)


def test_a_relative_worktree_is_the_one_checked_and_the_one_removed(fleet, monkeypatch):
    """`wt` names tmp/wt from here and checkout/wt from the checkout; only the first may go."""
    inner = fleet["checkout"] / "wt"
    git(fleet["checkout"], "worktree", "add", "-q", "--detach", str(inner), fleet["head"])
    inner_commit = commit(inner, "inner-only")
    monkeypatch.chdir(fleet["tmp"])

    run_cleanup(fleet, worktree=Path("wt"))

    assert not fleet["worktree"].exists()
    assert git(inner, "rev-parse", "HEAD") == inner_commit


def test_a_branch_checked_out_in_another_worktree_is_kept(fleet):
    with pytest.raises(cleanup_script.Refused, match="also checked out"):
        run_cleanup(fleet, worktree=None)
    assert untouched(fleet)


def test_a_local_branch_that_moved_is_kept(fleet):
    git(fleet["checkout"], "worktree", "remove", str(fleet["worktree"]))
    git(fleet["checkout"], "branch", "-q", "-f", "feature", "origin/main")

    with pytest.raises(cleanup_script.Refused, match="local feature"):
        run_cleanup(fleet, worktree=None)

    assert ref(fleet["checkout"], "refs/heads/feature") == ref(fleet["checkout"], "origin/main")


def test_a_held_lock_on_the_repository_stops_everything(fleet):
    with LockManager().lock(MECH, "held-by-test"):
        with pytest.raises(RuntimeError, match=f"Failed to acquire lock on {MECH}"):
            run_cleanup(fleet)
    assert untouched(fleet) and fleet["origin_calls"] == []


def test_the_real_origin_check_refuses_an_origin_that_is_not_the_repository(fleet):
    with pytest.raises(Exception, match="origin identity mismatch"):
        cleanup_script.cleanup(REPO, 1, fleet["checkout"], fleet["worktree"], apply=True, pr_view=merged(fleet))
    assert untouched(fleet)


def test_without_an_absolute_workspace_nothing_runs(fleet, monkeypatch):
    monkeypatch.setenv("OPENCLAW_WORKSPACE", "workspace")
    with pytest.raises(cleanup_script.Refused, match="OPENCLAW_WORKSPACE"):
        run_cleanup(fleet)
    monkeypatch.delenv("OPENCLAW_WORKSPACE")
    with pytest.raises(cleanup_script.Refused, match="OPENCLAW_WORKSPACE"):
        run_cleanup(fleet)
    assert untouched(fleet)
    assert not (Path(os.environ["OPENCLAW_ORCHESTRATION_ROOT"]) / "workspace").exists()


def test_the_lock_key_is_claw_or_the_manifest_mech():
    manifest = load_fleet_manifest()
    assert cleanup_script.lock_key(manifest.vendored_governance.canonical_repository.upper()) == "claw"
    assert cleanup_script.lock_key(REPO.lower()) == MECH
    with pytest.raises(cleanup_script.Refused, match="neither claw nor a manifest Mech"):
        cleanup_script.lock_key("CultureBotAI/not-in-the-fleet")


def reject_pushes(fleet) -> None:
    hook = fleet["origin"] / "hooks" / "pre-receive"
    hook.write_text("#!/bin/sh\necho rejected >&2\nexit 1\n", encoding="utf-8")
    hook.chmod(0o755)


def test_the_main_worktree_is_refused(fleet):
    git(fleet["checkout"], "worktree", "remove", str(fleet["worktree"]))
    git(fleet["checkout"], "switch", "-q", "feature")

    for apply in (False, True):
        with pytest.raises(cleanup_script.Refused, match="main worktree"):
            run_cleanup(fleet, worktree=fleet["checkout"], apply=apply)

    assert git(fleet["checkout"], "symbolic-ref", "--short", "HEAD") == "feature"
    assert ref(fleet["origin"], "refs/heads/feature") == fleet["head"]


def test_the_recovery_names_the_push_when_the_remote_branch_was_deleted(fleet, monkeypatch):
    """A failure at the tracking-ref step, after push --delete succeeded, must say how to put the branch back."""
    monkeypatch.setattr(cleanup_script, "tracking_sha", lambda checkout, branch: fleet["head"])

    with pytest.raises(cleanup_script.PartialFailure) as caught:
        run_cleanup(fleet)

    assert f"deleted remote feature (was {fleet['head'][:10]})" in caught.value.done
    assert f"push origin {fleet['head']}:refs/heads/feature" in caught.value.recovery
    assert ref(fleet["origin"], "refs/heads/feature") is None
    git(fleet["checkout"], "push", "-q", "origin", f"{fleet['head']}:refs/heads/feature")
    assert ref(fleet["origin"], "refs/heads/feature") == fleet["head"]


def test_the_tracking_ref_delete_compares_against_the_merged_head(fleet, monkeypatch):
    """A tracking ref that moved between the check and the delete survives."""
    later = push_follow_up(fleet)
    git(fleet["checkout"], "fetch", "-q", "origin")
    git(fleet["tmp"] / "other", "push", "-q", "origin", "--delete", "feature")
    drop_worktree_and_local(fleet)
    monkeypatch.setattr(cleanup_script, "tracking_sha", lambda checkout, branch: fleet["head"])

    with pytest.raises(RuntimeError, match="update-ref"):
        run_cleanup(fleet, worktree=None)

    assert ref(fleet["checkout"], "refs/remotes/origin/feature") == later


def test_a_failure_after_only_the_worktree_went_reports_it(fleet):
    (fleet["checkout"] / ".git" / "refs" / "heads" / "feature.lock").write_text("", encoding="utf-8")

    with pytest.raises(cleanup_script.PartialFailure) as caught:
        run_cleanup(fleet)

    assert caught.value.done == [f"removed worktree {fleet['worktree'].resolve()}"]
    assert "worktree add" in caught.value.recovery and "branch feature" not in caught.value.recovery
    assert ref(fleet["checkout"], "refs/heads/feature") == fleet["head"]


def test_a_failure_after_only_the_local_branch_went_reports_it(fleet, monkeypatch, capsys):
    git(fleet["checkout"], "worktree", "remove", str(fleet["worktree"]))
    git(fleet["checkout"], "config", "--remove-section", "branch.feature")
    reject_pushes(fleet)

    assert run_main(fleet, monkeypatch, worktree=None) == 1

    out, err = capsys.readouterr()
    assert "deleted local feature" in out and "no branch.feature config to remove" in out
    assert "failed after the steps above" in err and f"branch feature {fleet['head']}" in err
    assert ref(fleet["checkout"], "refs/heads/feature") is None


def test_a_detached_worktree_s_recovery_does_not_name_the_branch(fleet):
    git(fleet["worktree"], "checkout", "-q", "--detach")
    git(fleet["checkout"], "branch", "-q", "-D", "feature")
    git(fleet["checkout"], "update-ref", "-d", "refs/remotes/origin/feature")
    reject_pushes(fleet)

    with pytest.raises(cleanup_script.PartialFailure) as caught:
        run_cleanup(fleet)

    command = f"worktree add --detach {fleet['worktree'].resolve()} {fleet['head']}"
    assert command in caught.value.recovery and "branch feature" not in caught.value.recovery
    git(fleet["checkout"], "worktree", "add", "-q", "--detach", str(fleet["worktree"]), fleet["head"])
    assert git(fleet["worktree"], "rev-parse", "HEAD") == fleet["head"]


def test_a_missing_config_section_is_reported_as_such(fleet):
    git(fleet["checkout"], "config", "--remove-section", "branch.feature")

    done = run_cleanup(fleet)

    assert "no branch.feature config to remove" in done
    assert not any(step.startswith("removed branch.") for step in done)


def test_a_missing_worktree_path_is_reported_and_a_prunable_one_refused(fleet):
    git(fleet["checkout"], "worktree", "remove", str(fleet["worktree"]))
    nowhere = fleet["tmp"] / "nowhere"

    plan = run_cleanup(fleet, worktree=nowhere, apply=False)

    assert plan[0] == f"worktree {nowhere.resolve()} is not present, skipped"
    prunable = fleet["tmp"] / "prunable"
    git(fleet["checkout"], "worktree", "add", "-q", "--detach", str(prunable), fleet["head"])
    shutil.rmtree(prunable)
    with pytest.raises(cleanup_script.Refused, match="worktree prune"):
        run_cleanup(fleet, worktree=prunable, apply=False)
