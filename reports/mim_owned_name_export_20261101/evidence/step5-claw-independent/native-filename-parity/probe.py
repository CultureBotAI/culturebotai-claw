from pathlib import Path
import sys,json,ast,re,importlib.util,hashlib
import yaml
HERE=Path(__file__).resolve().parent;RUN=HERE.parents[1]
def load(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);sys.modules[name]=m;s.loader.exec_module(m);return m
source=RUN/'step5-claw-independent/code-e78e220/source/scripts/build_mim_ingredient_sssom.py'
parsed=ast.parse(source.read_text()); node=next(n for n in parsed.body if isinstance(n,ast.FunctionDef) and n.name=='_mim_curie')
ns={'Path':Path,'re':re};exec(compile(ast.Module(body=[node],type_ignores=[]),str(source),'exec'),ns)
policy=load('independent_owned_policy',RUN/'step5-claw-independent/code-e78e220/source/src/kg_microbe_utils/owned_name_policy.py')
native_path=RUN/'step4-mim/scripts/validate_sssom_invariants.py';native=load('independent_filename_validator',native_path)
checks=[]
for epoch in range(2):
 folder=HERE/f'checkout-{epoch}'/'mapped';folder.mkdir(parents=True)
 raw={'Α1~ salt.yaml':{'identifier':'CHEBI:1','preferred_term':'Shared name','mapping_status':'AMBIGUOUS'},'Straße stock.yaml':{'identifier':'CHEBI:1','preferred_term':'Sibling','mapping_status':'MAPPED'},'literal~3911.yaml':{'identifier':'CHEBI:old','preferred_term':'Legacy name','mapping_status':'REJECTED','representative':'CHEBI:1'},'Ω dangling.yaml':{'identifier':'CHEBI:1','preferred_term':'Unresolved','mapping_status':'REJECTED','representative':None}}
 if epoch:raw['Α1~ salt.yaml']['preferred_term']='Changed owner name'
 for name,data in raw.items():(folder/name).write_text(yaml.safe_dump(data,allow_unicode=True))
 (folder/'.gitignore').write_text('*.yaml\n')
 rec={ns['_mim_curie'](p.name):yaml.safe_load(p.read_text()) for p in folder.glob('*.yaml')}
 native.INGREDIENTS_DIR=folder;native._subject_to_path.cache_clear();native._preferred_term_owners.cache_clear();native._other_baseline=lambda:frozenset()
 subjects=native._subject_to_path();assert set(subjects)==set(rec)
 owners=policy.build_owner_index(rec);assert owners==native._preferred_term_owners()
 for subject in rec:
  tokens=['Shared name','Changed owner name','Sibling','Legacy name','Unresolved']
  candidates=[policy.AliasCandidate(t,'fixture',('source.yaml',),('decision:669',)) for t in tokens]
  kept,events=policy.filter_owned_aliases(subject,candidates,owners)
  assert not list(native.evaluate_rule_k([{'subject_id':subject,'other':'|'.join(x.text for x in kept)}]))
 checks.append({'epoch':epoch,'subjects':sorted(subjects),'owner_index':{k:sorted(v) for k,v in owners.items()},'actual_native_rule_k_filtered_rows':len(rec)})
result={'status':'PASS','scope':'Exact e78 builder _mim_curie AST executed unmodified; complete actual native forward filename index/owner index/Rule K; two distinct fixture directories with true Unicode and literal tilde filenames, ignored YAML included. No production files changed.','builder_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'native_validator_sha256':hashlib.sha256(native_path.read_bytes()).hexdigest(),'checks':checks}
(HERE/'result.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n');print(json.dumps(result,indent=2,ensure_ascii=False))
