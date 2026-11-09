#!/usr/bin/env python3
# Historical review evidence: a Claude reviewer's probe for PR 851, the eleventh round (560faf2499); findings in culturebotai-claw issues; paths inside name that reviewer's scratch directories, so a re-run at head may need them recreated.
"""Reviewer's own mutants against PR 851 round 11 (560faf2499), 2026-11-08.

Inputs: the worktree root as argv[1]. Each mutant is applied to
scripts/adhoc/cleanup_merged_pr_branch.py there, the whole
tests/test_cleanup_merged_pr_branch.py is run in a fresh pytest process, and the
script is restored. Outputs: KILLED/SURVIVED per mutant with the failing test ids.
Scratch only; never run against the main checkout.
"""
from __future__ import annotations

import ast
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(sys.argv[1]).resolve()
SCRIPT = ROOT / "scripts/adhoc/cleanup_merged_pr_branch.py"
TESTS = "tests/test_cleanup_merged_pr_branch.py"

MUTANTS = [
    ("outer guard: any record counts as a deletion",
     '            if not any(step.startswith(("removed ", "deleted ")) for step in done):\n                raise\n',
     "            if not done:\n                raise\n"),
    ("glob: star handled only at the end of src",
     '        if "*" in src:\n',
     '        if src.endswith("*"):\n'),
    ("inner handler: Exception or KeyboardInterrupt only",
     "                except BaseException as exc:  # an interrupt here must leave the record too\n",
     "                except (Exception, KeyboardInterrupt) as exc:\n"),
    ("outer handler: Exception or KeyboardInterrupt only",
     "        except BaseException as exc:  # a KeyboardInterrupt after a deletion still gets the record and the recovery\n",
     "        except (Exception, KeyboardInterrupt) as exc:\n"),
    ("inner handler: record appended after the raise is built (cause dropped)",
     '                    raise RuntimeError(f"origin accepted the delete but could not be asked again: {exc}") from exc\n',
     '                    raise RuntimeError(f"origin accepted the delete but could not be asked again: {exc}") from None\n'),
    ("pushInsteadOf: empty value skipped is kept, but a value equal to the URL plus slash is not a prefix",
     "            if prefix and push_url.startswith(prefix):\n",
     "            if prefix and push_url.startswith(prefix) and not push_url.endswith(prefix):\n"),
]


def main() -> int:
    original = SCRIPT.read_text(encoding="utf-8")
    survived = 0
    try:
        for name, before, after in MUTANTS:
            if original.count(before) != 1:
                print(f"ANCHOR  {name}: occurs {original.count(before)} times")
                return 1
            mutated = original.replace(before, after)
            ast.parse(mutated)
            SCRIPT.write_text(mutated, encoding="utf-8")
            done = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "-x", "--no-header",
                                   "-o", "console_output_style=classic", TESTS],
                                  cwd=ROOT, capture_output=True, text=True, check=False)
            failed = re.findall(r"^FAILED (\S+)", done.stdout, flags=re.M)
            if done.returncode == 1:
                print(f"KILLED   {name} -> {failed[:3]}")
            elif done.returncode == 0:
                survived += 1
                print(f"SURVIVED {name}")
            else:
                print(f"EXIT {done.returncode} {name}\n{done.stdout[-1500:]}\n{done.stderr[-800:]}")
    finally:
        SCRIPT.write_text(original, encoding="utf-8")
    print(f"{len(MUTANTS) - survived}/{len(MUTANTS)} killed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
