"""Fresh-process controls in isolated two-file copies; never mutate author source."""
from pathlib import Path
import datetime,hashlib,json,os,subprocess,sys
HERE=Path(__file__).resolve().parent
RUN=HERE.parent
ROOT=RUN/'claw-owned-name'
MODULE=Path('src/kg_microbe_utils/owned_name_policy.py')
TEST=Path('tests/test_mim_owned_name_policy.py')
original={p:(ROOT/p).read_bytes() for p in (MODULE,TEST)}
mutations=[
 ('baseline',None,None,None),
 ('disable_suppression','if not holders or subject in holders:','if True:',
  'test_real_generic_and_form_examples_suppress_without_chemical_inference'),
 ('truthy_representative_fallback','target = data.get("representative") if "representative" in data else data.get("identifier")',
  'target = data.get("representative") or data.get("identifier")',
  'test_explicit_empty_or_unresolved_representative_never_uses_old_identifier'),
 ('first_owner_only','return {term: frozenset(subjects) for term, subjects in owners.items()}',
  'return {term: frozenset(sorted(subjects)[:1]) for term, subjects in owners.items()}',
  'test_tombstone_credits_all_live_identifier_holders_and_keeps_current_owner'),
 ('discard_later_sources','group["source_refs"].update(source_refs)',
  'group["source_refs"].update(source_refs if not group["source_refs"] else ())',
  'test_repeated_pair_aggregates_every_origin_and_owner_in_one_deterministic_row'),
 ('lower_instead_of_casefold','.casefold()', '.lower()',
  'test_casefold_without_punctuation_internal_space_or_unicode_normalization'),
]
results=[]
for name,before,after,selection in mutations:
 control=HERE/'controls'/name;control.mkdir(parents=True,exist_ok=False)
 source=original[MODULE].decode()
 if before:
  assert before in source
  if name!='lower_instead_of_casefold':assert source.count(before)==1
  source=source.replace(before,after)
 for rel,data in [(MODULE,source.encode()),(TEST,original[TEST])]:
  path=control/rel;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
 (control/'src/kg_microbe_utils/__init__.py').write_bytes(b'')
 env=dict(os.environ);env['PYTHONPATH']=str(control/'src');env['PYTHONPYCACHEPREFIX']=str(control/'bytecode');env['PYTHONDONTWRITEBYTECODE']='1'
 argv=[sys.executable,'-m','pytest','-q','-p','no:cacheprovider','-c','/dev/null','--confcutdir',str(control),str(control/TEST)]
 if selection:argv.extend(['-k',selection])
 start=datetime.datetime.now(datetime.timezone.utc).isoformat()
 proc=subprocess.run(argv,cwd=control,env=env,capture_output=True)
 log=proc.stdout+proc.stderr;(control/'pytest.log').write_bytes(log)
 passed=proc.returncode==0 if before is None else (proc.returncode==1 and b'AssertionError' in log and b'ERROR collecting' not in log and b'ModuleNotFoundError' not in log and b'SyntaxError' not in log)
 result={'name':name,'argv':argv,'started_at':start,'finished_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'exit_code':proc.returncode,'expected_failure':bool(before),'control_pass':passed,'selection':selection,'mutation':{'before':before,'after':after},'source_sha256':hashlib.sha256(source.encode()).hexdigest(),'test_sha256':hashlib.sha256(original[TEST]).hexdigest(),'log':str(control/'pytest.log'),'log_sha256':hashlib.sha256(log).hexdigest(),'fresh_process':True,'fresh_bytecode_prefix':env['PYTHONPYCACHEPREFIX']}
 (control/'receipt.json').write_text(json.dumps(result,indent=2)+'\n');results.append(result)
 print(json.dumps({k:result[k] for k in ('name','exit_code','expected_failure','control_pass')}),flush=True)
 assert passed, log.decode()
assert all((ROOT/path).read_bytes()==data for path,data in original.items())
(HERE/'mutation-results.json').write_text(json.dumps({'author_source_unchanged':True,'results':results},indent=2)+'\n')
