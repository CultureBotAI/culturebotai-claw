"""Check public selection regression tests against a removed filter.

Inputs: fleet module and tests; output: pytest results, optional JSON receipt.
Serves fleet public-membership integration PR; 2026-11-10.
"""
import json
import subprocess
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
source = root / 'src/kg_microbe_fleet/__init__.py'
original = source.read_text()
needle = 'if mech.is_public}'
assert original.count(needle) == 1
command = [sys.executable, '-m', 'pytest', 'tests/test_fleet_public.py', '-q']
baseline = subprocess.run(command, cwd=root, check=False).returncode
try:
    source.write_text(original.replace(needle, '}'))
    mutated = subprocess.run(command, cwd=root, check=False).returncode
finally:
    source.write_text(original)
receipt = {'baseline_exit': baseline, 'removed_public_filter_exit': mutated}
print(json.dumps(receipt, indent=2))
if len(sys.argv) == 2:
    Path(sys.argv[1]).write_text(json.dumps(receipt, indent=2) + '\n')
if baseline != 0 or mutated == 0:
    raise SystemExit('Mutation contract failed')
