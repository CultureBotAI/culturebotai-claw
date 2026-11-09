from pathlib import Path
import sys,os,json,importlib.util,random,hashlib
import yaml
HERE=Path(__file__).resolve().parent;RUN=HERE.parents[1];CLAW=RUN/'claw-owned-name';sys.path.insert(0,str(CLAW/'src'))
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);module=importlib.util.module_from_spec(spec);sys.modules[name]=module;spec.loader.exec_module(module);return module
policy=load('kg_microbe_utils.owned_name_policy',HERE/'snapshot/src/kg_microbe_utils/owned_name_policy.py')
art=load('kg_microbe_utils.sssom_artifacts',HERE/'snapshot/src/kg_microbe_utils/sssom_artifacts.py')
native=load('independent_native_rule_k',HERE/'snapshot/native_mim_validate_sssom_invariants.py')
root=HERE/'policy-and-path-controls';root.mkdir(exist_ok=False);records_dir=root/'records';records_dir.mkdir()
rng=random.Random(669);comparisons=0
for trial in range(100):
 records={};paths={}
 for i in range(6):
  subject=f'MIM:S{i}';data={'identifier':rng.choice(['CHEBI:1','CHEBI:2','','chebi:1']),'preferred_term':rng.choice(['Parent','PARENT','Straße','STRASSE','Child','','  ','Other  Name']),'mapping_status':rng.choice(['MAPPED','AMBIGUOUS','REJECTED',' rejected ',None,'pending'])}
  if rng.randrange(2):data['representative']=rng.choice([None,'','CHEBI:1','CHEBI:2','CHEBI:missing'])
  path=records_dir/f'S{i}.yaml';path.write_text(yaml.safe_dump(data,allow_unicode=True));records[subject]=data;paths[subject]=path
 native._subject_to_path=lambda:paths
 native._other_baseline=lambda:frozenset()
 native._preferred_term_owners.cache_clear()
 actual=native._preferred_term_owners();expected=policy.build_owner_index(records);assert actual==expected
 for subject in list(records)+['MIM:Stranger']:
  tokens=['Parent','PARENT','Straße','STRASSE','Other Name',' Other  Name ','Unknown','']
  candidates=[policy.AliasCandidate(x,'fixture',('input.yaml#/synonyms',),('decision:669',)) for x in tokens]
  kept,events=policy.filter_owned_aliases(subject,candidates,expected)
  before=list(native.evaluate_rule_k([{'subject_id':subject,'other':'|'.join(tokens)}]))
  after=list(native.evaluate_rule_k([{'subject_id':subject,'other':'|'.join(x.text for x in kept)}]))
  assert bool(before)==bool(events) and not after
  rendered=policy.render_suppressed_aliases(events)
  assert all(event.owner_subject_ids==actual[event.token.casefold()] for event in events)
  comparisons+=1
# Original lexical symlink aliases must not be silently normalized away.
case=root/'lexical';case.mkdir();os.environ['OPENCLAW_WORKSPACE']=str(case/'workspace')
(case/'real').mkdir();(case/'real/sub').mkdir();(case/'alias').symlink_to(case/'real/sub',target_is_directory=True)
output=case/'alias/../candidate.tsv';source=case/'source.yaml';source.write_text('source\n');paths=art.artifact_paths(output)
sssom=(f'# mapping_set_description: "{art.POLICY_MARKER}"\nsubject_id\tother\nMIM:Subject\tkept\n').encode()
result={}
try:
 result=art.publish_candidate_artifacts(output,sssom,policy.render_suppressed_aliases([]),{'producer_revision':'fixture'},lambda:None,input_paths=[source],expected_before=art.capture_beforeimages(paths),claw_root=CLAW)
except Exception as exc:result={'exception':str(exc),'type':type(exc).__name__}
record={'native_validator_sha256':hashlib.sha256((HERE/'snapshot/native_mim_validate_sssom_invariants.py').read_bytes()).hexdigest(),'native_owner_snapshots':100,'native_rule_k_comparisons':comparisons,'native_empty_baseline_all_filtered_rows_pass':True,'lexical_alias':{'supplied_output':str(output),'filesystem_resolved_output':str(output.resolve()),'normalized_by_artifact_paths':str(paths[0]),'result':result,'normalized_output_written':paths[0].exists(),'actual_symlink_dotdot_destination_written':output.exists()}}
(HERE/'policy-and-path-results.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record,indent=2))
# Execute the frozen pure helper's own tests against the reviewed module as an additional positive control.
import pytest
raise SystemExit(pytest.main([str(HERE/'snapshot/tests/test_mim_owned_name_policy.py'),'-q','-o','addopts=','-p','no:cacheprovider']))
