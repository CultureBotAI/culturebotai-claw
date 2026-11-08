"""Independent PR 897 mutations, 2026-11-07; only mutates the disposable .temp copy.
Inputs: copied head and its tests. Outputs: mutation results under .temp/review897.
"""
import os
import subprocess
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
COPY = ROOT / '.temp/review897/copy'
path = COPY / 'src/kg_microbe_links/taxa.py'
original = path.read_text()
mutants = {
    'farthest_ancestor': ('next((a for a in chain[1:] if a in self.scope), None)', 'next((a for a in reversed(chain[1:]) if a in self.scope), None)'),
    'plants_microbial': ('NON_MICROBIAL_KINGDOMS = {"Metazoa", "Viridiplantae"}', 'NON_MICROBIAL_KINGDOMS = {"Metazoa"}'),
    'archaea_outside': ('MICROBIAL_DOMAINS = {"Bacteria", "Archaea"}', 'MICROBIAL_DOMAINS = {"Bacteria"}'),
    'accept_newline_fix': ('CURIE.match(value)', 'CURIE.fullmatch(value)'),
}
for name, (before, after) in mutants.items():
    assert original.count(before) == 1
    try:
        path.write_text(original.replace(before, after))
        run = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', 'tests/test_taxon_links.py', 'tests/test_taxon_links_cli.py'], cwd=COPY, capture_output=True, text=True, env=dict(os.environ, OPENCLAW_WORKSPACE=str(ROOT / '.temp/review897/own-workspace')))
        (ROOT / f'.temp/review897/{name}.log').write_text(run.stdout + run.stderr)
        print(name, 'exit', run.returncode, run.stdout.splitlines()[-1:], flush=True)
    finally:
        path.write_text(original)
