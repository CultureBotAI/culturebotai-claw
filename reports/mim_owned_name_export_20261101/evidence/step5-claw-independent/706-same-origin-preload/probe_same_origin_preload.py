from pathlib import Path
import sys,os,importlib.util,json,hashlib,csv,io
import yaml
HERE=Path(__file__).resolve().parent;FIX=HERE/'producer-fixture';sys.path[:0]=[str(FIX/'scripts'),str(FIX/'src')]
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);sys.modules[name]=m;spec.loader.exec_module(m);return m
import kg_microbe_utils.owned_name_policy as preloaded_policy
policy=FIX/'src/kg_microbe_utils/owned_name_policy.py';original=policy.read_bytes();original_hash=hashlib.sha256(original).hexdigest();policy.write_bytes(original+b'\n# Controlled same-path cached-module source drift before builder import.\ndef filter_owned_aliases(subject_id, candidates, owners):\n    return tuple(candidates), ()\n');mutated_hash=hashlib.sha256(policy.read_bytes()).hexdigest()
b=load('independent_code_head_builder',FIX/'scripts/build_mim_ingredient_sssom.py')
ROOT=HERE/'controls';ROOT.mkdir(exist_ok=False)
def write(root,filename,name,**changes):
 d={'identifier':'CHEBI:1','preferred_term':name,'mapping_status':'MAPPED','ontology_mapping':{'ontology_id':'CHEBI:1','ontology_label':name,'mapping_quality':'EXACT_MATCH'},'curation_history':[{'timestamp':'2026-10-01T00:00:00Z'}]};d.update(changes);p=root/filename;p.write_text(yaml.safe_dump(d,sort_keys=False));return p
cas=ROOT/'rejected-cas';cas.mkdir();subject=write(cas,'Subject.yaml','Subject',chemical_properties={'cas_rn':'12-34-5'},synonyms=[{'synonym_text':'CAS:12-34-5','synonym_type':'REJECTED_LABEL','source':'reviewed rejection fixture'}]);write(cas,'CAS_owner.yaml','CAS:12-34-5',ontology_mapping={});events=[];rows=b._row_from_yaml(subject,{},{},{},{'CHEBI:1':'Subject'},suppressions=events);sidecar=b.render_suppressed_aliases(events)
cas_result={'rows':rows,'suppression_rows':list(csv.DictReader(io.StringIO(sidecar.decode()),delimiter='\t')),'source_rejection_preserved':yaml.safe_load(subject.read_text())['synonyms'][0]['synonym_type']=='REJECTED_LABEL'}
root=ROOT/'import-provenance';records=root/'mim/data/ingredients/mapped';records.mkdir(parents=True);write(records,'Subject.yaml','Subject',synonyms=[{'synonym_text':'Owned','synonym_type':'EXACT_SYNONYM'}]);write(records,'Owned.yaml','Owned',ontology_mapping={});output=root/'artifacts/candidate.tsv'
b.MIM_ROOT=root/'mim';b.MIM_INGREDIENTS_DIR=records;b.MIM_PUBLISHED_SSSOM=root/'absent-canonical.tsv';b.RESIDUAL_JSON=root/'absent-residual.json';b.KGM_UNIFIED_TSV=root/'absent-kgm.tsv.gz';b.require_mech_roots=lambda *a,**k:None;b._load_chebi_labels=lambda *a:{'CHEBI:1':'Subject'};os.environ['OPENCLAW_WORKSPACE']=str(root/'workspace')
sys.argv=['builder','--output',str(output),'--no-validate']
try:b.main();outcome='published'
except Exception as exc:outcome=f'{type(exc).__name__}: {exc}'
proof={'cas_rejection_provenance':cas_result,'imported_code_provenance':{'outcome':outcome,'initial_preload_source_sha256':original_hash,'prebuilder_disk_source_sha256':mutated_hash,'actual_source_fixture':str(policy),'identity_transport':'require_mech_roots bypassed for synthetic fixture; production builder, snapshot, ownership, native lock and transaction are unchanged.','external_validation':'explicit --no-validate, offline label fixture'}}
if output.exists():
 manifest=json.loads(output.with_suffix('.tsv.manifest.json').read_text());bound=next(x for x in manifest['source_inputs'] if x['path']==str(policy));generated=list(csv.DictReader(io.StringIO(''.join(x for x in output.read_text().splitlines(True) if not x.startswith('#'))),delimiter='\t'));captured=load('policy_captured_after_import',policy);candidate=b.AliasCandidate('Owned','fixture',('source',),('decision',));replayed=captured.filter_owned_aliases('MIM:Subject',[candidate],{'owned':frozenset({'MIM:Owned'})})
 proof['imported_code_provenance'].update({'manifest_bound_policy_sha256':bound['sha256'],'generated_other':generated[0]['other'],'manifest_bound_source_would_keep':[x.text for x in replayed[0]],'emitted_suppressions':list(csv.DictReader(output.with_name('suppressed_aliases.tsv').open(),delimiter='\t'))})
(HERE/'builder-boundary-results.json').write_text(json.dumps(proof,indent=2)+'\n');print(json.dumps(proof,indent=2))
