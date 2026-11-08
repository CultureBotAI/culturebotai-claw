# Historical review evidence: a Claude reviewer's probe for PR 897, round 9 (c8e3fc7a15); findings in culturebotai-claw issues; paths inside name that reviewer's scratch directories, so a re-run at head may need them recreated.
"""Review scratch for PR 897 round 9 (2026-11-07): run the two gap tests at head and under the two surviving mutants.
Inputs: the review worktree and test_review897r9_gaps.py. Outputs: one line per (variant, result)."""
import os, subprocess, sys, tempfile
from pathlib import Path
ROOT = Path("/Users/marcin/agent-work/culturebotai-claw/review897r9"); TAXA = ROOT / "src/kg_microbe_links/taxa.py"
TEST = "/Users/marcin/agent-work/culturebotai-claw/review897r9-scratch/test_review897r9_gaps.py"
VARIANTS = [("head", None, None),
            ("M12 first data row only", "        for n, row in enumerate(rows, 2):\n            if None in row", "        for n, row in enumerate(rows[:1], 2):\n            if None in row"),
            ("M3b cycle only back at start", "                if taxon in on_path:\n", "                if path and taxon == start:\n")]
original = TAXA.read_text(encoding="utf-8")
try:
    for name, before, after in VARIANTS:
        if before: assert original.count(before) == 1; TAXA.write_text(original.replace(before, after), encoding="utf-8")
        env = {**os.environ, "PYTHONPATH": str(ROOT), "PYTHONPYCACHEPREFIX": tempfile.mkdtemp(dir="/Users/marcin/agent-work/culturebotai-claw/review897r9-scratch")}
        try:
            r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--rootdir", str(ROOT), "-rfE", TEST], cwd=ROOT, env=env, capture_output=True, text=True, timeout=30)
            lines = [l for l in r.stdout.splitlines() if l.startswith(("FAILED", "ERROR")) or "passed" in l or "failed" in l or "error" in l]
            print(f"{name:32s} rc={r.returncode}  {' | '.join(lines)[:230]}")
        except subprocess.TimeoutExpired:
            print(f"{name:32s} TIMEOUT after 30 s (an endless walk)")
        finally:
            TAXA.write_text(original, encoding="utf-8")
finally:
    TAXA.write_text(original, encoding="utf-8")
