"""Fresh-process builder controls; copy-only mutations and no live ingestion."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile

RUN = Path(__file__).resolve().parent.parent
CLAW = RUN / 'claw-owned-name'
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent
OUT.mkdir(parents=True, exist_ok=True)
original = (CLAW / 'scripts/build_mim_ingredient_sssom.py').read_text()
mutations = [
    ('ownership-bypass', 'kept, events = filter_owned_aliases(_mim_curie(path.name), candidates, owners)',
     'kept, events = tuple(candidates), ()', 'all_alias_inputs or late_cas'),
    ('cas-bypass', '''    cas_token = _pipe(keep_owned(owned_tokens(
        cas_token, "mim.cas", f"{path}#chemical_properties.cas_rn-or-cross_references")),
        drop=rejected_labels)''', '    cas_token = _cas_token(data)', 'late_cas'),
    ('input-byte-check-bypass', 'if capture_beforeimages(immutable) != immutable:', 'if False:', 'input_drift or code_input_drift'),
    ('path-set-check-bypass', 'if tuple(sorted(MIM_INGREDIENTS_DIR.glob("*.yaml"))) != yamls:', 'if False:', 'input_drift and added'),
    ('validator-returncode-bypass', 'if proc.returncode:', 'if False:', 'returncode_is_authoritative'),
    ('tsv-only-noop', '    result = publish_candidate_artifacts(', '    if args.output.exists() and args.output.read_bytes() == proposed:\n        return\n    result = publish_candidate_artifacts(', 'sidecar_refresh'),
    ('rejected-label-bypass', 'if a.text.strip().casefold() not in rejected_labels', 'if True', 'source_bound_rejection'),
    ('kgm-reread', 'kgm_labels = load_kgm_labels(kgm_frozen) if kgm_frozen else {}', 'kgm_labels = load_kgm_labels(KGM_UNIFIED_TSV) if kgm_frozen else {}', 'frozen_kgm_consumption'),
]
mutations.append(('lexical-stamp-normalization-bypass', '[checked_path(p) for p in (args.prior_stamps_from or', '[Path(os.path.abspath(p)) for p in (args.prior_stamps_from or', 'lexical_prior_stamp_alias'))
results = []
for name, old, new, selector in [('baseline', '', '', '')] + mutations:
    with tempfile.TemporaryDirectory(prefix='owned-name-builder-control-') as temporary:
        root = Path(temporary)
        for directory in ('src', 'plugins', 'scripts'):
            shutil.copytree(CLAW/directory, root/directory, ignore=shutil.ignore_patterns('__pycache__'))
        (root/'tests').mkdir()
        shutil.copyfile(CLAW/'tests/test_mim_owned_name_export.py', root/'tests/test_mim_owned_name_export.py')
        (root/'scripts/build_mim_ingredient_sssom.py').write_text(original if not old else original.replace(old,new,1))
        if old:
            assert original.count(old) == 1, (name, original.count(old))
        environment = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', PYTHONPYCACHEPREFIX=str(root/'cache'),
                           PYTHONPATH=os.pathsep.join([str(root/'src'), str(root)]))
        command = [sys.executable, '-m', 'pytest', '-q', 'tests/test_mim_owned_name_export.py']
        if selector:
            command.extend(['-k',selector])
        result = subprocess.run(command,cwd=root,env=environment,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
        log = OUT/f'mutation-{name}.log'
        log.write_text(result.stdout)
        expected = result.returncode == (0 if name == 'baseline' else 1)
        valid = expected and 'ERROR collecting' not in result.stdout and 'ImportError' not in result.stdout
        results.append({'name':name,'argv':command,'exit_code':result.returncode,'expected_outcome':valid,
                        'log':str(log),'sha256':hashlib.sha256(log.read_bytes()).hexdigest()})
        (OUT/'mutation-results.json').write_text(json.dumps(results,indent=2)+'\n')
        assert valid, (name,result.stdout[-3000:])
assert hashlib.sha256((CLAW/'scripts/build_mim_ingredient_sssom.py').read_bytes()).hexdigest() == hashlib.sha256(original.encode()).hexdigest()
print(json.dumps(results,indent=2))
