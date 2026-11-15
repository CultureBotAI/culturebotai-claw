"""Independent source-only review controls for claw PR 1236 (MIM issue 1418).

Date: 2026-11-15. Inputs: exact PR head, existing synthetic tests/native fixture.
Outputs: matrix and counterfactual JSON plus pytest logs in the private review
root. No MIM checkout or GitHub mutations. Source substitutions are restricted
to this isolated detached review worktree and always restored in finally.
"""
from __future__ import annotations
import hashlib
import json
import subprocess
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

_parser = __import__("argparse").ArgumentParser(description=__doc__)
_parser.add_argument("--review-tree", type=Path, required=True,
                     help="Owned isolated detached worktree at the exact reviewed head")
ROOT = _parser.parse_args().review_tree.resolve()
if Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"],
                               cwd=ROOT, text=True).strip()).resolve() != ROOT:
    raise SystemExit("Review path is not a worktree root")
if subprocess.run(["git", "symbolic-ref", "--quiet", "HEAD"], cwd=ROOT,
                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 1:
    raise SystemExit("Review tree must be detached; feature branches are refused")
if subprocess.run(["git", "diff-index", "--quiet", "HEAD", "--"], cwd=ROOT).returncode:
    raise SystemExit("Tracked source differs from the reviewed head")
OUT = ROOT.parent
EXPECTED = '7070392fcb5e31282499a599f7147b56b96e5aca'
if subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip() != EXPECTED:
    raise SystemExit('Unexpected source head')
source = ROOT / 'scripts/build_mim_ingredient_sssom.py'
original = source.read_bytes()
sha = lambda value: hashlib.sha256(value).hexdigest()
sys.path[:0] = [str(ROOT / 'tests'), str(ROOT / 'src')]
from test_mim_additional_mappings import CONTRACT, emit, owner
matrix = []
for predicate in ('skos:exactMatch','skos:closeMatch','skos:broadMatch','skos:narrowMatch'):
    for status in ('SUPPORTED','WITHHOLD'):
        record = owner()
        item = record['additional_ontology_mappings'][0]
        item.update(predicate_id=predicate, review_status=status)
        if status == 'WITHHOLD':
            item['evidence'][0]['supports'] = 'REFUTE'
        before = deepcopy(record)
        rows = emit(record)
        extra = rows[1]
        assert len(rows) == 2 and extra['predicate_id'] == predicate
        assert extra['other'] == extra['confidence'] == extra['validation_method'] == ''
        assert CONTRACT.row_assertion(record, extra) == item
        assert record == before
        matrix.append({'predicate':predicate,'status':status,'rows':len(rows),'result':'passed'})
(OUT / 'additional-assertion-matrix.json').write_text(json.dumps(matrix, indent=2)+'\n')
target = 'tests/test_mim_additional_mappings.py::test_exact_primary_and_broad_extra_have_independent_provenance_and_identity'
replay = 'tests/test_mim_stable_identity.py::test_stable_changed_science_cannot_replay_a_matching_numeric_triple'
mutations = [
 ('omit-additional-rows','for assertion in additional:', 'for assertion in []:', target),
 ('collapse-additional-predicate','"predicate_id": assertion["predicate_id"],','"predicate_id": "skos:exactMatch",', target),
 ('inherit-primary-aliases','"other": "",\n            "validation_method": "",\n        })\n    return rows', '"other": parent_row["other"],\n            "validation_method": "",\n        })\n    return rows', target),
 ('replay-old-science-stamp','if not args.no_preserve_validation and args.identity_mode == "legacy":', 'if not args.no_preserve_validation:', replay),
]
receipts=[]
def run(name,tests):
    cmd=[sys.executable,'-m','pytest','-q',*tests,'--basetemp='+str(OUT/('pytest-'+name))]
    process=subprocess.run(cmd,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    (OUT/(name+'.log')).write_bytes(process.stdout)
    return {'name':name,'command':cmd,'exit_code':process.returncode,'log_sha256':sha(process.stdout)}
receipts.append(run('mutation-control',[target,replay]))
assert receipts[-1]['exit_code']==0
try:
    for name,old,new,test in mutations:
        assert original.decode().count(old)==1, name
        changed=original.decode().replace(old,new).encode()
        source.write_bytes(changed)
        receipt=run(name,[test])
        receipt.update(original_source_sha256=sha(original),mutated_source_sha256=sha(changed),old=old,new=new)
        receipts.append(receipt)
        source.write_bytes(original)
finally:
    source.write_bytes(original)
proof={'at':datetime.now(timezone.utc).isoformat(),'head':EXPECTED,
       'helper_sha256':sha(Path(__file__).read_bytes()),'original_source_sha256':sha(original),
       'restored_source_sha256':sha(source.read_bytes()),'receipts':receipts}
(OUT/'counterfactuals.json').write_text(json.dumps(proof,indent=2)+'\n')
print(json.dumps({'matrix_cases':len(matrix),'controls':[(r['name'],r['exit_code']) for r in receipts], 'restored':source.read_bytes()==original}))
