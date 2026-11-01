from pathlib import Path
import sys,os,importlib.util,json,hashlib
HERE=Path(__file__).resolve().parent;RUN=HERE.parents[1];CLAW=RUN/'claw-owned-name';sys.path.insert(0,str(CLAW/'src'))
for name in ['owned_name_policy','sssom_artifacts']:
 fullname='kg_microbe_utils.'+name;spec=importlib.util.spec_from_file_location(fullname,HERE/'snapshot/src/kg_microbe_utils'/f'{name}.py');m=importlib.util.module_from_spec(spec);sys.modules[fullname]=m;spec.loader.exec_module(m)
a=sys.modules['kg_microbe_utils.sssom_artifacts'];p=sys.modules['kg_microbe_utils.owned_name_policy'];from kg_microbe_write import transaction
original=transaction.ValidatedWriteTransaction.commit
root=HERE/'journal-initial-capture-controls';root.mkdir(exist_ok=False);results=[]
for kind in ['missing','invalid']:
 d=root/kind;d.mkdir();os.environ['OPENCLAW_WORKSPACE']=str(d/'workspace');source=d/'source.yaml';source.write_text('input\n');output=d/'out/candidate.tsv';paths=a.artifact_paths(output);sssom=(f'# mapping_set_description: "{a.POLICY_MARKER}"\nsubject_id\tother\nMIM:Subject\tkept\n').encode()
 def boundary(self,**kwargs):
  result=original(self,**kwargs)
  if kind=='missing':result.journal_path.unlink()
  else:result.journal_path.write_bytes(b'{}\n')
  return result
 transaction.ValidatedWriteTransaction.commit=boundary
 try:
  result=a.publish_candidate_artifacts(output,sssom,p.render_suppressed_aliases([]),{'producer_revision':'fixture'},lambda:None,input_paths=[source],expected_before=a.capture_beforeimages(paths),claw_root=CLAW)
 except Exception as exc:result={'exception':str(exc),'type':type(exc).__name__}
 finally:transaction.ValidatedWriteTransaction.commit=original
 results.append({'case':kind,'result':result,'journal_files':[{'path':str(x),'bytes':x.read_text()} for x in (output.parent/'.sssom-artifact-journals').glob('*.json')],'artifacts_exist':all(x.exists() for x in paths)})
(HERE/'journal-initial-capture-results.json').write_text(json.dumps(results,indent=2)+'\n');print(json.dumps(results,indent=2))
