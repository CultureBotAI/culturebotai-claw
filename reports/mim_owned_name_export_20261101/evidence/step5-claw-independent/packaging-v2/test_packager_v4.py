"""Offline integrity checks in a temporary synthetic repository, no real publication."""
from pathlib import Path
import hashlib
import importlib.util
import json
import subprocess
import tempfile

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('step5_evidence_packager',HERE/'package_evidence_v2.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
results=[]
def check(name,action,error=None):
    try:action()
    except Exception as exc:
        if error and error in str(exc):results.append({'name':name,'expected_refusal':True,'error':str(exc)});return
        raise
    assert error is None, (name,'did not refuse')
    results.append({'name':name,'passed':True})
def sha(b):return hashlib.sha256(b).hexdigest()
with tempfile.TemporaryDirectory(prefix='step5-evidence-test-') as temporary:
    run=Path(temporary).resolve();repo=run/'claw-owned-name';repo.mkdir();pack=run/'packaging';pack.mkdir()
    m.RUN=run;m.HERE=pack
    subprocess.run(['git','init','-q'],cwd=repo,check=True)
    (repo/'source.py').write_text('value = 1\n')
    subprocess.run(['git','add','source.py'],cwd=repo,check=True)
    subprocess.run(['git','-c','user.name=Evidence fixture','-c','user.email=fixture@example.invalid','commit','-qm','fixture'],cwd=repo,check=True)
    revision=subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()
    artifacts=run/'candidate';artifacts.mkdir()
    sssom=artifacts/'candidate.tsv';sidecar=artifacts/'suppressed_aliases.tsv';manifest=artifacts/'candidate.tsv.manifest.json';journal=artifacts/'journal.json'
    sssom.write_text('# owned-name-policy-v1; suppression-sidecar-required\nsubject_id\tother\nMIM:Test\t\n')
    sidecar.write_text('subject_id\ttoken\n')
    manifest.write_text(json.dumps({'artifacts':[{'role':'sssom','path':str(sssom),'sha256':sha(sssom.read_bytes())},{'role':'suppressed_aliases','path':str(sidecar),'sha256':sha(sidecar.read_bytes())}]}))
    journal.write_text(json.dumps({'root':str(artifacts),'status':'complete','changed':[],'created':[str(p) for p in [sssom,sidecar,manifest]],'previous':{}}))
    acceptance=artifacts/'acceptance.json';acceptance.write_text(json.dumps({'status':'PASS','artifact_sha256':sha(sssom.read_bytes())}))
    log=run/'check.log';log.write_text('synthetic completed check\n')
    receipt=run/'check.json';receipt.write_text(json.dumps({'finished_at':'2026-11-01T00:00:00Z','exit_code':0,'argv':['synthetic'],'log':str(log),'log_sha256':sha(log.read_bytes())}))
    names=[str(p.relative_to(run)) for p in [sssom,sidecar,manifest,journal,acceptance,log,receipt]]
    plan={'state':'final','pending_final_inputs':[],'intended_worktree':'claw-owned-name','proposed_repository_destination':str(m.DESTINATION),'implementation_revision':revision,
          'selected_existing_files':{n:{'category':'synthetic','source_sha256':sha((run/n).read_bytes()),'source_bytes':(run/n).stat().st_size} for n in names},
          'maintained_file_references':{'source.py':{'sha256':sha((repo/'source.py').read_bytes()),'bytes':(repo/'source.py').stat().st_size}},
          'commands':[{'path':'check.json','expected_exit':0}],
          'json_bindings':[{'json_source':'candidate/acceptance.json','pointer':'/artifact_sha256','target_source':'candidate/candidate.tsv'}],
          'generation':{'sssom':'candidate/candidate.tsv','suppressed_aliases':'candidate/suppressed_aliases.tsv','manifest':'candidate/candidate.tsv.manifest.json','journal':'candidate/journal.json','acceptance':'candidate/acceptance.json'},
          'package_readme':'Synthetic packager check only. No actual candidate approval.\n'}
    limited_coverage={"full_prefix_coverage":False,"missing_transforms":[{"prefix":"BTO","expected_path":"/fixture/missing/BTO.tsv","affected_row_count":1}]}
    limited={"status":"PASS_WITH_LIMITATIONS","b4_coverage":limited_coverage,"limitations":[{"rule":"B4","prefixes":["BTO"]}]}
    originals={n:(run/n).read_bytes() for n in names}
    originals['candidate/coverage.json']=json.dumps(limited_coverage).encode()
    original_acceptance=originals['candidate/acceptance.json']
    plan['run_root']=str(run)
    plan['generation']['b4_coverage']='candidate/coverage.json'
    # Exercise only acceptance classification: existing artifact/check bindings
    # remain real synthetic values and are independently verified below.
    original_bindings=plan['json_bindings'];plan['json_bindings']=[]
    originals['candidate/acceptance.json']=json.dumps(limited).encode()
    check('limited acceptance preserves explicit coverage',lambda:m.validate_bindings(plan,originals))
    for label,value,expected in [
        ('FAIL is never accepted',{"status":"FAIL"},'has not passed'),
        ('limited status without coverage refuses',{"status":"PASS_WITH_LIMITATIONS"},'explicit incomplete B4'),
        ('limited status without limitation refuses',{"status":"PASS_WITH_LIMITATIONS","b4_coverage":limited_coverage},'recorded B4 limitation'),
    ]:
        originals['candidate/acceptance.json']=json.dumps(value).encode()
        check(label,lambda:m.validate_bindings(plan,originals),expected)
    originals['candidate/acceptance.json']=json.dumps(limited).encode()
    originals['candidate/coverage.json']=b'{}'
    check('different standalone coverage refuses',lambda:m.validate_bindings(plan,originals),'Standalone B4 coverage differs')
    originals['candidate/acceptance.json']=original_acceptance
    plan['json_bindings']=original_bindings
    plan['generation'].pop('b4_coverage')
    selection=pack/'selection.json';selection.write_text(json.dumps(plan));frozen=pack/'inputs.json'
    draft=pack/'draft.json';draft.write_text(json.dumps({**plan,'state':'draft'}))
    check('draft refusal',lambda:m.freeze(draft,pack/'forbidden.json'),'draft or incomplete')
    assert not (pack/'forbidden.json').exists()
    check('freeze exact completed fixture',lambda:m.freeze(selection,frozen))
    check('publish only fresh fixture package',lambda:m.publish(frozen))
    target=repo/m.DESTINATION
    check('duplicate publication refuses',lambda:m.publish(frozen),'already exists')
    check('untracked package refuses',lambda:m.verify(target,repo,True),'untracked files')
    subprocess.run(['git','add',str(m.DESTINATION)],cwd=repo,check=True)
    check('tracked package verifies',lambda:m.verify(target,repo,True))
    archived=target/'evidence/check.log';before=archived.read_bytes();archived.write_bytes(before+b'changed')
    check('tampered archive refuses',lambda:m.verify(target,repo,False),'Archive bytes differ')
    archived.write_bytes(before)
    unexpected=target/'unindexed.txt';unexpected.write_text('unexpected')
    check('extra package member refuses',lambda:m.verify(target,repo,False),'membership differs');unexpected.unlink()
    (repo/'source.py').write_text('value = 2\n')
    check('maintained source drift refuses',lambda:m.verify(target,repo,False),'Maintained reference differs')
    (repo/'source.py').write_text('value = 1\n')
    check('restored fixture verifies',lambda:m.verify(target,repo,True))
(HERE/'packager-test-v4-results.json').write_text(json.dumps({'scope':'synthetic temporary repository only','results':results},indent=2)+'\n')
print(json.dumps(results,indent=2))
