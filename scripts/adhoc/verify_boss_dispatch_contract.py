#!/usr/bin/env python3
"""Run the exact boss preflight fixtures for claw #670 / PR #669 (2026-10-25).

Input: current skill or BOSS_SKILL_SOURCE Markdown snapshot. Output: unittest
results. The regression source is under tests/ so normal CI also runs it.
No live tmux session, worktree, GUI application or worker is created.
"""
from pathlib import Path
import runpy


runpy.run_path(str(Path(__file__).resolve().parents[2] /
                   "tests/test_boss_dispatch_contract.py"), run_name="__main__")
