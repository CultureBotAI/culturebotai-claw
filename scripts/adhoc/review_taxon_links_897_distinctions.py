# Historical: ran against PR 897 at c1b3ce6b47; its fixes landed in round 7, so a re-run at head fails by design.
"""PR 897 contrast fixtures for surviving mutants; 2026-11-07.
Inputs: disposable source copy. Outputs: fresh pytest runs; no tracked files edited.
"""
import subprocess
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
COPY = ROOT / '.temp/review897/copy'
(COPY / 'tests/test_review897.py').write_text('''from tests.test_taxon_links import taxonmech
from kg_microbe_links.taxa import TaxonIndex

def test_nearest(taxonmech):
    index = TaxonIndex(taxonmech)
    index.scope.add(83333)
    index.inventory[83333] = ('no rank', 562)
    index.inventory[511145] = ('no rank', 83333)
    assert index.judge('NCBITaxon:511145').ancestor == 83333

def test_plant(taxonmech):
    index = TaxonIndex(taxonmech)
    index.inventory[33090] = ('kingdom', 2759)
    index.inventory[3702] = ('species', 33090)
    assert index.judge('NCBITaxon:3702').verdict.value == 'outside_domain'

def test_archaea(taxonmech):
    index = TaxonIndex(taxonmech)
    index.inventory[2157] = ('superkingdom', 1)
    index.inventory[12345] = ('species', 2157)
    assert index.judge('NCBITaxon:12345').verdict.value == 'unattested_microbial'
''')
path = COPY / 'src/kg_microbe_links/taxa.py'
original = path.read_text()
mutants = {
'baseline': ('',''),
'farthest': ('next((a for a in chain[1:] if a in self.scope), None)', 'next((a for a in reversed(chain[1:]) if a in self.scope), None)'),
'plant': ('NON_MICROBIAL_KINGDOMS = {"Metazoa", "Viridiplantae"}', 'NON_MICROBIAL_KINGDOMS = {"Metazoa"}'),
'archaea': ('MICROBIAL_DOMAINS = {"Bacteria", "Archaea"}', 'MICROBIAL_DOMAINS = {"Bacteria"}'),
}
for name, (before, after) in mutants.items():
    try:
        path.write_text(original.replace(before, after) if before else original)
        result = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider', 'tests/test_review897.py'], cwd=COPY, text=True, capture_output=True)
        print(name, result.returncode, result.stdout.splitlines()[-1], flush=True)
        (ROOT / f'.temp/review897/contrast-{name}.log').write_text(result.stdout + result.stderr)
    finally:
        path.write_text(original)
