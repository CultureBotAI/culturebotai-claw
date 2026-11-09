#!/usr/bin/env python3
"""Run verify_repin_script_fixes_729.py against mutants that undo each fix.

Purpose: show the verification is not vacuous (AGENTS.md: "mutation is how you
find out"). Each mutant is one exact text replacement in a temporary copy of
one script, asserted to match exactly once, and it undoes one fix. A mutant is
killed when at least one verification check fails against it. The run fails
if any mutant survives.
Inputs: argv[1], the claw directory holding scripts/adhoc; argv[2], an empty
scratch directory; argv[3:7], the CellStructureMech and HabitatMech LICENSE
and ledger files, as for the verification.
Outputs: one line per mutant, killed or SURVIVED with the failing checks; a
nonzero exit on any survivor.
Serves: culturebotai-claw#806 / PR #803. Written 2026-11-04.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

claw, scratch = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()
inputs = sys.argv[3:7]
PUBLISH = "open_repin_prs_evidence_rollout_729.py"
REPIN = "repin_fleet_evidence_rollout_729.py"
MUTANTS = [
    ("hosting wording dropped (#796)", PUBLISH, "        elif hosting:\n", "        elif False:\n"),
    ("publish owners hard-coded (#796)", PUBLISH,
     'owner_text = ", ".join(owner_reference(url, slug) for url in owners) or "no issue"', 'owner_text = "#2873"'),
    ("staged-abstract refusal removed (#796)", PUBLISH, "        if caches and hosting:\n", "        if False:\n"),
    ("missing LICENSE read as no policy (#807)", PUBLISH,
     '        if licence is None:\n            raise RuntimeError(f"{key}: the commit has no LICENSE',
     '        if licence is None:\n            licence = ""\n        if False:\n            raise RuntimeError(f"{key}: the commit has no LICENSE'),
    ("LICENSE read from the working tree (#807)", PUBLISH,
     '        licence = show(worktree, head, "LICENSE")\n',
     '        licence = (worktree / "LICENSE").read_text() if (worktree / "LICENSE").is_file() else None\n'),
    ("dirty worktree accepted (#807)", PUBLISH,
     '            if run("git", "-C", str(worktree), "status", "--porcelain", "--untracked-files=all").strip():\n',
     "            if False:\n"),
    ("origin check removed (#805)", PUBLISH,
     "    RepositoryTarget(name=key, path=worktree.resolve(), expected_repository=slug).open()\n",
     "    return None\n"),
    ("origin check reads only the first URL (#805)", PUBLISH,
     "    RepositoryTarget(name=key, path=worktree.resolve(), expected_repository=slug).open()\n",
     "    for flag in ([], ['--push']):\n"
     "        url = run('git', '-C', str(worktree), 'remote', 'get-url', *flag, 'origin').strip()\n"
     "        if slug.lower() not in url.lower():\n"
     "            raise RuntimeError(f'{key}: origin is not {slug}')\n"),
    ("origin check ignores push URLs (#805)", PUBLISH,
     "    RepositoryTarget(name=key, path=worktree.resolve(), expected_repository=slug).open()\n",
     "    for url in run('git', '-C', str(worktree), 'remote', 'get-url', '--all', 'origin').split():\n"
     "        if slug.lower() not in url.lower():\n"
     "            raise RuntimeError(f'{key}: origin is not {slug}')\n"),
    ("no lease around the push (#805)", PUBLISH,
     '                with LockManager().lock(key, "publish-repin-729"):\n', "                if True:\n"),
    ("pushes HEAD, not the recorded commit (#805)", PUBLISH,
     'f"{head}:refs/heads/{branch}"', 'f"HEAD:refs/heads/{branch}"'),
    ("re-pin owners hard-coded (#804)", REPIN,
     '        owners = ", ".join(ledger_owners(worktree)) or "no issue"\n', '        owners = "#2873"\n'),
    ("re-pin refusal removed (#804)", REPIN,
     "            if untracked and has_hosting_policy(worktree):\n", "            if False:\n"),
    ("re-pin refuses whenever abstracts exist (#808)", REPIN,
     "            if untracked and has_hosting_policy(worktree):\n",
     '            if (worktree / "references_cache").exists() and has_hosting_policy(worktree):\n'),
    ("re-pin stages every prepared path (#804)", REPIN,
     '            prepared = (["references_cache"] if untracked else []) + [\n',
     "            prepared = list(ADOPTER_PREPARED) + [\n"),
    ("re-pin accepts a missing LICENSE (#807)", REPIN,
     '            if not (worktree / "LICENSE").is_file():\n', "            if False:\n"),
]

survivors = 0
for index, (name, script, old, new) in enumerate(MUTANTS):
    mutant = scratch / f"mutant-{index:02d}"
    shutil.rmtree(mutant, ignore_errors=True)
    (mutant / "scripts/adhoc").mkdir(parents=True)
    for file in (PUBLISH, REPIN, "verify_repin_script_fixes_729.py"):
        shutil.copyfile(claw / "scripts/adhoc" / file, mutant / "scripts/adhoc" / file)
    target = mutant / "scripts/adhoc" / script
    text = target.read_text()
    if text.count(old) != 1:
        print(f"ERROR  {name}: replacement matched {text.count(old)} times")
        survivors += 1
        continue
    target.write_text(text.replace(old, new))
    run_dir = scratch / f"run-{index:02d}"
    shutil.rmtree(run_dir, ignore_errors=True)
    run_dir.mkdir()
    completed = subprocess.run(
        [sys.executable, str(mutant / "scripts/adhoc/verify_repin_script_fixes_729.py"), str(mutant), str(run_dir),
         *inputs], capture_output=True, text=True)
    failed = [line[6:].split("  --")[0] for line in completed.stdout.splitlines() if line.startswith("FAIL")]
    if failed:
        print(f"killed    {name}: {'; '.join(failed)}")
    elif completed.returncode:
        last = (completed.stderr.strip().splitlines() or ["no stderr"])[-1]
        print(f"killed    {name}: verification crashed ({last[:160]})")
    else:
        print(f"SURVIVED  {name}")
        survivors += 1
print(f"{len(MUTANTS) - survivors} of {len(MUTANTS)} mutants killed")
sys.exit(1 if survivors else 0)
