"""Author verification against the actual native Rule K; synthetic fixtures only."""
from pathlib import Path
import hashlib,importlib.util,json,sys,tempfile
from kg_microbe_utils.owned_name_policy import AliasCandidate,build_owner_index,filter_owned_aliases,render_suppressed_aliases
HERE=Path(__file__).resolve().parent
RUN=HERE.parent
native_path=RUN/'step4-mim/scripts/validate_sssom_invariants.py'
spec=importlib.util.spec_from_file_location('step5_native_rule_k',native_path)
native=importlib.util.module_from_spec(spec);sys.modules[spec.name]=native;spec.loader.exec_module(native)
def rec(term,identifier='CHEBI:1',status='MAPPED',**other):
 return dict(preferred_term=term,identifier=identifier,mapping_status=status,**other)
records={
 'Live_old.yaml':rec('Old owner'),
 'Live_target_A.yaml':rec('Target A','CHEBI:2'),
 'Live_target_Z.yaml':rec('Target Z','CHEBI:2','AMBIGUOUS'),
 'No_target.yaml':rec('Unsupported owner','CHEBI:33',ontology_mapping={'ontology_id':'unsupported:33'}),
 'No_name.yaml':rec('', 'CHEBI:44'),
 'Explicit.yaml':rec('Corrected tombstone','CHEBI:1','REJECTED',representative='CHEBI:2'),
 'Legacy.yaml':rec('Legacy tombstone','CHEBI:2','REJECTED'),
 'Empty.yaml':rec('Empty representative','CHEBI:2','REJECTED',representative=''),
 'Null.yaml':rec('Null representative','CHEBI:2','REJECTED',representative=None),
 'Dangling.yaml':rec('Dangling representative','CHEBI:2','REJECTED',representative='CHEBI:missing'),
 'Orphan.yaml':rec('Orphan name','CHEBI:99','REJECTED'),
 'α1~name.yaml':rec('Straße','CHEBI:50'),
 'Shared_A.yaml':rec('Same name','CHEBI:51'),
 'Shared_Z.yaml':rec('SAME NAME','CHEBI:52'),
}
with tempfile.TemporaryDirectory(prefix='native-k-',dir=HERE) as directory:
 root=Path(directory);mapped=root/'mapped';mapped.mkdir()
 for name,data in records.items():(mapped/name).write_text(json.dumps(data,ensure_ascii=False)+'\n')
 (root/'unmapped').mkdir();(root/'unmapped/Outside.yaml').write_text(json.dumps(rec('Unmapped directory does not own'))+'\n')
 native.INGREDIENTS_DIR=mapped;native._subject_to_path.cache_clear();native._preferred_term_owners.cache_clear();native._other_baseline=lambda:frozenset()
 by_subject={subject:records[path.name] for subject,path in native._subject_to_path().items()}
 ours=build_owner_index(by_subject);theirs=native._preferred_term_owners();assert ours==theirs
 subjects=[*sorted(by_subject),'MIM:Stranger']
 tokens=sorted({str(x['preferred_term']).strip() for x in records.values() if x['preferred_term']}|{'STRASSE','Unknown unowned','Unmapped directory does not own'})
 before=[];after=[];events=[]
 for subject in subjects:
  for token in tokens:
   before.append({'subject_id':subject,'other':token})
   candidate=AliasCandidate(token,'synthetic_native_parity',(f'synthetic:{subject}/{token}',),('https://github.com/CultureBotAI/MediaIngredientMech/issues/669',))
   kept,suppressed=filter_owned_aliases(subject,[candidate],ours);events.extend(suppressed)
   after.append({'subject_id':subject,'other':'|'.join(x.text for x in kept)})
 violations=list(native.evaluate_rule_k(before));remaining=list(native.evaluate_rule_k(after));assert not remaining
 expected={(row['subject_id'],row['other'].strip().casefold()) for _,row,_ in violations};actual={(x.subject_id,x.token.casefold()) for x in events};assert actual==expected
 sidecar=render_suppressed_aliases(events);(HERE/'native-parity-sidecar.tsv').write_bytes(sidecar)
 result={'classification':'Synthetic native-validator parity, not live generation or independent scientific approval','native_validator_path':str(native_path),'native_validator_sha256':hashlib.sha256(native_path.read_bytes()).hexdigest(),'helper_sha256':hashlib.sha256((RUN/'claw-owned-name/src/kg_microbe_utils/owned_name_policy.py').read_bytes()).hexdigest(),'fixtures':records,'owner_index':{k:sorted(v) for k,v in sorted(ours.items())},'owner_index_equal':True,'row_token_trials':len(before),'native_rule_k_before':len(violations),'native_rule_k_after':len(remaining),'unique_suppressed_pairs':len(actual),'sidecar_sha256':hashlib.sha256(sidecar).hexdigest(),'no_outside_mapped_directory_owner': 'unmapped directory does not own' not in ours,'empty_native_baseline':True}
 assert result['no_outside_mapped_directory_owner']
 (HERE/'native-parity-results.json').write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
 print(json.dumps({k:v for k,v in result.items() if k not in ('fixtures','owner_index')},indent=2))
