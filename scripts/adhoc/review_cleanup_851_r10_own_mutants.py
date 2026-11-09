#!/usr/bin/env python3
# Historical review evidence: a Claude reviewer's probe for PR 851, the tenth round (8397708cd0); findings in culturebotai-claw issues; paths inside name that reviewer's scratch directories, so a re-run at head may need them recreated.
"""Review probe for PR 851 round 10 (2026-11-07): seven reviewer mutants of cleanup_merged_pr_branch.py,
each run in a fresh pytest process against both helper test files in the review worktree; the script is
restored after each. Scratch only."""
import subprocess, sys
from pathlib import Path

WT = Path("/Users/marcin/agent-work/culturebotai-claw/review851r10")
SCRIPT = WT / "scripts/adhoc/cleanup_merged_pr_branch.py"
TESTS = ["tests/test_cleanup_merged_pr_branch.py", "tests/test_commit_and_push_mech_branch_locked.py"]
MUTANTS = [
    ("M1 glob boundary >= -> >", "len(ref) >= len(prefix) + len(suffix)", "len(ref) > len(prefix) + len(suffix)"),
    ("M2 inner except narrowed to RuntimeError", "                except Exception as exc:\n                    # The delete was accepted",
     "                except RuntimeError as exc:\n                    # The delete was accepted"),
    ("M3 done.append dropped in the except",
     '                    done.append(f"deleted remote {branch} (was {head[:10]}; accepted, not confirmed)")\n', ""),
    ("M4 no exception chaining", 'could not be asked again: {exc}") from exc', 'could not be asked again: {exc}")'),
    ("M5 accepted step not prefixed 'deleted remote '",
     'done.append(f"deleted remote {branch} (was {head[:10]}; accepted, not confirmed)")',
     'done.append(f"remote {branch} delete accepted, not confirmed (was {head[:10]})")'),
    ("M6 empty src also skipped", "        if not dst:  #", "        if not dst or not src:  #"),
    ("M7 pushInsteadOf equal to the push URL ignored", "            if prefix and push_url.startswith(prefix):",
     "            if prefix and push_url.startswith(prefix) and push_url != prefix:"),
]
original = SCRIPT.read_text(encoding="utf-8")
try:
    for name, before, after in MUTANTS:
        assert original.count(before) == 1, (name, original.count(before))
        SCRIPT.write_text(original.replace(before, after), encoding="utf-8")
        p = subprocess.run(["uv", "run", "--quiet", "python", "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", *TESTS],
                           cwd=WT, capture_output=True, text=True)
        failed = [l for l in p.stdout.splitlines() if l.startswith("FAILED")]
        tail = p.stdout.strip().splitlines()[-1] if p.stdout.strip() else p.stderr.strip()[-300:]
        print(f"{'KILLED  ' if p.returncode == 1 else 'SURVIVED' if p.returncode == 0 else f'rc={p.returncode}'} {name}: {tail}")
        for l in failed[:3]:
            print("    " + l[:220])
        sys.stdout.flush()
finally:
    SCRIPT.write_text(original, encoding="utf-8")
print("restored:", SCRIPT.read_text(encoding="utf-8") == original)
