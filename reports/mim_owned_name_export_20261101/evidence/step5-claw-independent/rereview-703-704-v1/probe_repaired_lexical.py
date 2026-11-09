from pathlib import Path
import sys,importlib.util,json,hashlib
HERE=Path(__file__).resolve().parent;RUN=HERE.parents[1];CLAW=RUN/'claw-owned-name';sys.path.insert(0,str(CLAW/'src'))
for name in ['owned_name_policy','sssom_artifacts']:
 fullname='kg_microbe_utils.'+name;spec=importlib.util.spec_from_file_location(fullname,HERE/'snapshot/src/kg_microbe_utils'/f'{name}.py');m=importlib.util.module_from_spec(spec);sys.modules[fullname]=m;spec.loader.exec_module(m)
a=sys.modules['kg_microbe_utils.sssom_artifacts'];root=HERE/'lexical-recheck';root.mkdir(exist_ok=False);(root/'real/sub').mkdir(parents=True);(root/'alias').symlink_to(root/'real/sub',target_is_directory=True);raw=root/'alias/../candidate.tsv'
try:a.artifact_paths(raw);raise AssertionError('unsafe lexical path accepted')
except ValueError as exc:result={'supplied_path':str(raw),'exception':str(exc),'normalized_candidate_absent':not(root/'candidate.tsv').exists(),'resolved_candidate_absent':not raw.exists()}
assert result['normalized_candidate_absent'] and result['resolved_candidate_absent']
(HERE/'lexical-recheck.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
