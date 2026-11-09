from pathlib import Path
import sys,os,importlib.util,json,hashlib
HERE=Path(__file__).resolve().parent;RUN=HERE.parents[1];CLAW=RUN/'claw-owned-name';sys.path.insert(0,str(CLAW/'src'))
for name in ['owned_name_policy','sssom_artifacts']:
 fullname='kg_microbe_utils.'+name;spec=importlib.util.spec_from_file_location(fullname,HERE/'snapshot/src/kg_microbe_utils'/f'{name}.py');m=importlib.util.module_from_spec(spec);sys.modules[fullname]=m;spec.loader.exec_module(m)
a=sys.modules['kg_microbe_utils.sssom_artifacts'];p=sys.modules['kg_microbe_utils.owned_name_policy']
root=HERE/'positive-café';root.mkdir(exist_ok=False);os.environ['OPENCLAW_WORKSPACE']=str(root/'workspace');source=root/'input.yaml';source.write_text('input\n');output=root/'out/candidate.tsv';paths=a.artifact_paths(output)
text=(f'# mapping_set_description: "{a.POLICY_MARKER}"\nsubject_id\tother\nMIM:Subject\tkept\n').encode();aliases=p.render_suppressed_aliases([]);results=[]
def publish(label,sssom,sidecar):
 before=a.capture_beforeimages(paths)
 def check():assert source.read_bytes()==b'input\n'
 result=a.publish_candidate_artifacts(output,sssom,sidecar,{'producer_revision':'fixture'},check,input_paths=[source],expected_before=before,claw_root=CLAW)
 assert output.read_bytes()==sssom and paths[1].read_bytes()==sidecar
 if result['status']=='complete':
  journal=json.loads(Path(result['journal']).read_text());assert journal['status']=='complete';assert journal['previous']=={x:before[Path(x)].decode() for x in result['changed']};assert set(journal['created'])==set(result['created'])
 results.append({'case':label,'result':result,'exact_postimages':True});return result
first=publish('first_create',text,aliases);assert len(first['created'])==3 and not first['changed']
text=text.replace(b'kept',b'replacement');second=publish('replace_existing_tsv',text,aliases);assert len(second['changed'])==2 and second['unchanged']==[str(paths[1])]
event=p.Suppression('MIM:Subject','Owned',frozenset({'MIM:Owner'}),'fixture',('input.yaml#/alias',),('decision:669',));aliases=p.render_suppressed_aliases([event]);third=publish('sidecar_only_refresh',text,aliases);assert len(third['changed'])==2 and third['unchanged']==[str(paths[0])]
paths[2].unlink();fourth=publish('missing_manifest_refresh',text,aliases);assert fourth['created']==[str(paths[2])] and len(fourth['unchanged'])==2
before={str(x):(x.read_bytes(),x.stat().st_mtime_ns) for x in paths};journals=list((output.parent/'.sssom-artifact-journals').glob('*.json'));fifth=publish('true_all_artifact_noop',text,aliases);assert fifth['status']=='unchanged';assert before=={str(x):(x.read_bytes(),x.stat().st_mtime_ns) for x in paths};assert len(journals)==len(list((output.parent/'.sssom-artifact-journals').glob('*.json')))
(HERE/'positive-publication-results.json').write_text(json.dumps(results,indent=2)+'\n');print(json.dumps([{'case':x['case'],'status':x['result']['status'],'exact_postimages':True} for x in results],indent=2))
