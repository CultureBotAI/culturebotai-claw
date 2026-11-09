# Historical review evidence: a Claude reviewer's probe for PR 851, the tenth round (8397708cd0); findings in culturebotai-claw issues; paths inside name that reviewer's scratch directories, so a re-run at head may need them recreated.
"""Review probes for PR 851 round 10 (2026-11-07): read-back failure path, both params' done lists,
main() output with the chained cause, KeyboardInterrupt at the read-back, glob boundary. Scratch only."""
import importlib.util
import sys
from pathlib import Path

import pytest

WT = Path("/Users/marcin/agent-work/culturebotai-claw/review851r10")
spec = importlib.util.spec_from_file_location("real_tests", WT / "tests/test_cleanup_merged_pr_branch.py")
T = importlib.util.module_from_spec(spec)
sys.modules["real_tests"] = T
spec.loader.exec_module(T)
fleet = T.fleet  # re-export the fixture
S = T.cleanup_script


def blip(fleet, monkeypatch, exc_factory):
    real = S.remote_branch_sha
    calls = []

    def stand_in(checkout, branch):
        calls.append(branch)
        if len(calls) == 2:
            raise exc_factory()
        return real(checkout, branch)

    monkeypatch.setattr(S, "remote_branch_sha", stand_in)
    return calls


@pytest.mark.parametrize("local_present", [True, False])
def test_done_lists_differ(fleet, monkeypatch, local_present):
    T.git(fleet["checkout"], "worktree", "remove", str(fleet["worktree"]))
    if not local_present:
        T.git(fleet["checkout"], "branch", "-q", "-D", "feature")
    calls = blip(fleet, monkeypatch, lambda: RuntimeError("ls-remote origin refs/heads/feature failed: could not read from remote"))
    with pytest.raises(S.PartialFailure) as caught:
        T.run_cleanup(fleet, worktree=None)
    print(f"\n[local_present={local_present}] calls={calls}\n  done={caught.value.done}\n  error={caught.value.error!r}\n  cause={caught.value.error.__cause__!r}\n  recovery={caught.value.recovery}")
    print(f"  tracking after push: {T.ref(fleet['checkout'], 'refs/remotes/origin/feature')}")


def test_main_output_on_readback_failure(fleet, monkeypatch, capsys):
    T.git(fleet["checkout"], "worktree", "remove", str(fleet["worktree"]))
    T.git(fleet["checkout"], "branch", "-q", "-D", "feature")
    blip(fleet, monkeypatch, lambda: RuntimeError("ls-remote origin refs/heads/feature failed: could not read from remote"))
    rc = T.run_main(fleet, monkeypatch, worktree=None)
    out, err = capsys.readouterr()
    print(f"\nrc={rc}\nSTDOUT:\n{out}STDERR:\n{err}")
    assert rc == 1
    assert "could not read from remote" in err


def test_main_output_on_keyboard_interrupt_at_readback(fleet, monkeypatch, capsys):
    T.git(fleet["checkout"], "worktree", "remove", str(fleet["worktree"]))
    T.git(fleet["checkout"], "branch", "-q", "-D", "feature")
    blip(fleet, monkeypatch, KeyboardInterrupt)
    with pytest.raises(KeyboardInterrupt):
        T.run_main(fleet, monkeypatch, worktree=None)
    out, err = capsys.readouterr()
    print(f"\nSTDOUT:{out!r}\nSTDERR:{err!r}\norigin feature now: {T.ref(fleet['origin'], 'refs/heads/feature')}")


@pytest.mark.parametrize("spec", ["+refs/heads/feature*:refs/heads/victim*", "refs/heads/feature*:refs/heads/victim*",
                                  "+refs/heads/*:refs/heads/*", "refs/heads/feature:", "+refs/heads/feature:", ":refs/heads/x"])
def test_fetch_mappings_boundary(fleet, spec):
    T.git(fleet["checkout"], "config", "remote.origin.fetch", spec)
    print(f"\n{spec!r} -> {S.fetch_mappings(fleet['checkout'], 'refs/heads/feature')}")
