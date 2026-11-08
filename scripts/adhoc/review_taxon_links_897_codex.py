# Historical: ran against PR 897 at c1b3ce6b47; its fixes landed in round 7, so a re-run at head fails by design.
"""Read-only PR 897 probes; inputs: bundled fixtures; outputs: scratch CLI results.
Independent review 2026-11-07; only scratch fixtures are changed.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from tests.test_taxon_links import taxonmech
from tests.test_taxon_links_cli import _mech

PARENT = ROOT / '.temp/review897'
PARENT.mkdir(parents=True, exist_ok=True)
BASE = Path(tempfile.mkdtemp(prefix='probes-', dir=PARENT))
print('Artifacts:', BASE)
CASES = ['newline', 'bad_scope', 'empty_scope', 'bad_conf', 'empty_conf', 'cycle', 'long_id', 'negative_sample']
for case in CASES:
    base = BASE / case
    base.mkdir(exist_ok=True)
    tx = taxonmech.__wrapped__(base)
    value = 'NCBITaxon:562'
    if case == 'newline':
        value += '\n'
    elif case == 'bad_scope':
        (tx / 'curation/seed_scope.tsv').write_text('wrong_column\nNCBITaxon:562\n')
    elif case == 'empty_scope':
        (tx / 'curation/seed_scope.tsv').write_text('')
    elif case in ('bad_conf', 'empty_conf'):
        value = 'NCBITaxon:511145'
        (tx / 'conf/ncbi_taxdump.yaml').write_text('path: [\n' if case == 'bad_conf' else '')
    elif case == 'cycle':
        (tx / 'data/raw/ncbi_merged_ids.tsv').write_text('old_taxon_id\tcurrent_taxon_id\nNCBITaxon:562\tNCBITaxon:562\n')
    elif case == 'long_id':
        value = 'NCBITaxon:' + '1' * 5000
    mech = _mech(base, 'dufmech', {'data/families/a.yaml': {'causal_graphs': [{'taxon': value}]}})
    cmd = [sys.executable, '-m', 'kg_microbe_links', 'taxa', '--mech', 'dufmech', '--root', str(mech), '--taxonmech-root', str(tx), '--strict']
    if case == 'negative_sample':
        cmd += ['--sample', '-1']
    env = dict(os.environ, PYTHONPATH=str(ROOT / 'src') + os.pathsep + str(ROOT), OPENCLAW_WORKSPACE=str(BASE / 'workspace'))
    run = subprocess.run(cmd, capture_output=True, text=True, env=env)
    (base / 'stdout.txt').write_text(run.stdout)
    (base / 'stderr.txt').write_text(run.stderr)
    print(case, 'exit=', run.returncode, 'stderr=', run.stderr.splitlines()[-1:] )
    if run.stdout:
        import json
        result = json.loads(run.stdout)
        print(' records=', result['records'], 'verdicts=', {k:v['occurrences'] for k,v in result['verdicts'].items() if v['occurrences']})
