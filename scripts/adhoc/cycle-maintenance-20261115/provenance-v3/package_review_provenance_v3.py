"""Authenticate retained review inputs before public packaging (issues1266/1268).

2026-11-15. Inputs: explicit task root and the fixed digest-bound sibling input
manifest. Output: one exclusive public staging tree outside the input root.
Every expected original is validated before any output creation. Original helpers,
results and prior staging bundles remain unchanged. No research, tests, metadata
inventory, GitHub/runtime actions or cleanup are rerun. Harmless help paths are
checked in memory before publication. This is historical evidence packaging,
not current merge/adoption readiness.
"""
from __future__ import annotations
import argparse,ast,hashlib,json,os,re,stat,subprocess,sys
from pathlib import Path

MANIFEST_SHA256='fac861a12685b2859879dbb973dce85ae712634e34fbd9317e2061b4ccb8d7de'
PREFIX=Path('scripts/adhoc/cycle-maintenance-20261115')

def sha(raw):return hashlib.sha256(raw).hexdigest()
def strict_json(raw):
    def unique(rows):
        result={}
        for key,value in rows:
            if key in result:raise ValueError('Duplicate JSON key')
            result[key]=value
        return result
    return json.loads(raw,object_pairs_hook=unique)

def no_symlinks(path):
    if not path.is_absolute():raise ValueError('Explicit absolute path required')
    for part in (path,*path.parents):
        if part.is_symlink():raise ValueError('Symlink/alias path refused')

def read_regular(path):
    no_symlinks(path)
    info=path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_size>16000000:raise ValueError('Bounded regular input required')
    return path.read_bytes()

def safe_public(raw):
    text=raw.decode()
    if (re.search(r'/(?:Users|home)/[A-Za-z0-9]',text)
            or re.search(r'[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}',text)
            or re.search(r'PID\d+',text)):
        raise ValueError('Private path/email/process identity detected')
    return text

def syntax_help(raw):
    text=safe_public(raw);ast.parse(text)
    bootstrap="import sys;sys.argv=['publication-helper.py','--help'];exec(compile(sys.stdin.read(),'publication-helper.py','exec'),{'__name__':'__main__','__file__':'publication-helper.py'})"
    result=subprocess.run([sys.executable,'-B','-c',bootstrap],input=text,text=True,capture_output=True,timeout=10)
    if result.returncode:raise ValueError('Packaged helper help failed before output creation')

def inventory_edit(text):
    old="    parser.add_argument('--output',type=Path,required=True)"
    if text.count(old)!=1:raise ValueError('Unexpected inventory helper source')
    text=text.replace(old,old+"\n    parser.add_argument('--inventory-helper',type=Path,required=True,help='Canonical scripts/repo_crud_inventory.py')")
    old="helper=Path(__file__).with_name('repo_crud_inventory.py')"
    if text.count(old)!=1:raise ValueError('Unexpected inventory dependency source')
    return text.replace(old,'helper=args.inventory_helper.resolve()'),['Use explicit --inventory-helper instead of a private sibling lookup; inventory logic unchanged.']

def plan_edit(text,pins):
    text,n=re.subn(r'The observation recorded bash PID\d+, uv PID\d+ and Python PID\d+ using this task \(\d+ matching open descriptors/cwds\)\.', 'The retained observation recorded active test processes using this task; inspect private reader evidence for exact identities.',text)
    if n!=1:raise ValueError('Unexpected private process-label source')
    text,n=re.subn(r'The live collaboration census showed [^.]+ running\.', 'The live collaboration census showed cooperating owners and reviewers still active.',text)
    if n!=1:raise ValueError('Unexpected owner-label source')
    old="p.add_argument('--task-root',type=Path,required=True);a=p.parse_args()"
    if text.count(old)!=1:raise ValueError('Unexpected plan CLI')
    text=text.replace(old,"p.add_argument('--task-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()")
    old="task=a.task_root.resolve();audit=task/'cleanup';data=json.loads((audit/'inventory-20261115/summary.json').read_text())"
    if text.count(old)!=1:raise ValueError('Unexpected plan input loader')
    bound={name:pins[name]['sha256'] for name in ('cleanup/inventory-20261115/summary.json','cleanup/owned-review-content-drift.json')}
    new="task=a.task_root.resolve();audit=task/'cleanup';destination=a.output.absolute()\n    if destination.is_symlink() or destination!=destination.resolve() or os.path.lexists(destination) or destination==task or task in destination.parents or destination in task.parents:\n        raise ValueError('Plan output must be new and outside/unaliasing retained inputs')\n    authenticated={}\n    for relative,expected in "+repr(bound)+".items():\n        source=task/relative\n        for ancestor in (source,*source.parents):\n            if ancestor.is_symlink():\n                raise ValueError('Historical plan input aliases are refused')\n        raw=source.read_bytes()\n        if hashlib.sha256(raw).hexdigest()!=expected:\n            raise ValueError('Historical plan inputs differ from independently recorded bytes')\n        authenticated[relative]=raw\n    data=json.loads(authenticated['cleanup/inventory-20261115/summary.json'])"
    text=text.replace(old,new)
    old_drift="json.loads((audit/'owned-review-content-drift.json').read_text())"
    if text.count(old_drift)!=1:raise ValueError('Unexpected plan drift loader')
    text=text.replace(old_drift,"json.loads(authenticated['cleanup/owned-review-content-drift.json'])")
    text=text.replace("    (audit/'PLAN.md').write_text", "    destination.mkdir(parents=False,exist_ok=False)\n    (destination/'PLAN.md').write_text")
    text=text.replace("(audit/'PLAN.md').read_bytes()", "(destination/'PLAN.md').read_bytes()")
    text=text.replace("(audit/'ACTION-PLAN.json').write_text", "(destination/'ACTION-PLAN.json').write_text")
    return text,['Replace private process/session labels with neutral evidence pointers.','Parse inventory/drift from the same cached bytes authenticated against fixed historical hashes; refuse ancestor aliases; write only to a new explicit output outside retained inputs.']

def build(task,manifest,manifest_raw):
    pins=manifest['inputs'];originals={}
    # Authenticate every original first; no narrative/output exists yet.
    for name,item in pins.items():
        relative=Path(name)
        if relative.is_absolute() or '..' in relative.parts:raise ValueError('Unsafe fixed input path')
        raw=read_regular(task/relative)
        if sha(raw)!=item['sha256']:raise ValueError('Original input hash differs: '+name)
        originals[name]=raw
    payload={};provenance=[]
    for name,item in pins.items():
        destination=item.get('output');edits=[]
        if not destination:continue
        raw=originals[name]
        if item['transform']=='inventory':text,edits=inventory_edit(raw.decode());raw=text.encode()
        elif item['transform']=='plan':text,edits=plan_edit(raw.decode(),pins);raw=text.encode()
        safe_public(raw)
        if destination.endswith('.py'):syntax_help(raw)
        elif destination.endswith('.json'):strict_json(raw)
        payload[PREFIX/destination]=raw
        provenance.append({'original_relative_path':name,'original_sha256':item['sha256'],'packaged_path':destination,'packaged_sha256':sha(raw),'packaging_edits':edits})
    for number,count,path in ((1112,243,'reviews/1112/final-integration/review.json'),(1138,36,'reviews/1138/final-integration/review.json')):
        value=strict_json(originals[path])
        if value['pr']!=number or value['independent_tests']!={'passed':count,'skipped':0}:raise ValueError('Historical integration result contract differs')
    remote=strict_json(originals['reviews/permanent-cycle/remote-independent/review.json'])
    if remote['head']!='1d0034ebe4fea0f4371e82e211db13d1b5ec2253' or remote['tests']!={'passed':118,'skipped':0}:raise ValueError('Historical remote review differs')
    fresh=strict_json(originals['reviews/1267/review.json'])
    if fresh['issue']!=1267 or fresh['control_tests_passed']!=17 or fresh['restored_test_passed'] is not True or fresh['mutations'][0]['killed'] is not True:raise ValueError('Historical issue1267 result differs')
    data=strict_json(originals['cleanup/inventory-20261115/summary.json'])
    drift=strict_json(originals['cleanup/owned-review-content-drift.json'])
    if len(data['repositories'])!=18 or len(data['groups'])!=2 or data['removal_performed'] is not False or sum(len(row['unstaged_status']) for row in drift)!=7:raise ValueError('Historical cleanup result differs')
    summary={'kind':'authenticated_historical_read_only_cleanup_preparation','observed_at':data['observed_at'],'registered_checkouts':len(data['repositories']),'common_git_groups':len(data['groups']),'bounded_candidate_scans_complete':all(r['inventory_complete'] for r in data['repositories']),'nested_fixture_git_boundaries_retained':len(data['additional_nested_git_boundaries_retained']),'protected_subtree_contents_and_sizes_unmeasured':True,'actual_modified_snapshot_paths':7,'cleanup_actions_performed':0,'remote_ref_changes':False,'private_inventory_sha256':pins['cleanup/inventory-20261115/summary.json']['sha256'],'private_plan_sha256':pins['cleanup/PLAN.md']['sha256'],'private_action_ledger_sha256':pins['cleanup/ACTION-PLAN.json']['sha256'],'private_paths_processes_operations_history_included':False}
    payload[PREFIX/'cleanup-inventory/SUMMARY.json']=(json.dumps(summary,indent=2,sort_keys=True)+'\n').encode()
    note='''# Authenticated historical helper provenance

Prepared for issues1266/1268 on2026-11-15. These results describe their recorded source
revisions and observation times. Every selected original byte stream is checked
against a fixed reviewed SHA256 manifest before any output is created. The
manifest itself is bound by the packager source's literal digest. Caller-supplied
substitute pins are not accepted. All syntax, harmless help paths, shapes and
public-data checks pass before writing an exclusive output outside input roots.

The original v1 and v2 packagers and stages remain retained privately. This correction
replaces their historical-narrative packaging path; it does not rerun or rewrite
the review results. PROVENANCE-V3.json records exact original/packaged hashes and
all packaging edits. Private plans, absolute paths, process/session identities
and raw histories are excluded. Cleanups, current CI readiness, merges, runtime
adoption and deployment are not authorized by these historical receipts.

The canonical packager and fixed manifest are in the sibling provenance-v3
folder under scripts/adhoc/cycle-maintenance-20261115. The cleanup inventory
helper uses an explicit --inventory-helper path. Its plan renderer accepts only
the pinned historical input bytes, parsing those exact cached bytes without rereading, and a new --output outside retained inputs;
it performs no cleanup. Audit helpers retain their original explicit arguments.
'''
    for folder in ('reviews/final-closeout','reviews/1267-final','cleanup-inventory'):
        payload[PREFIX/folder/'README.md']=note.encode()
    helper_raw=Path(__file__).read_bytes();syntax_help(helper_raw)
    payload[PREFIX/'provenance-v3/package_review_provenance_v3.py']=helper_raw
    payload[PREFIX/'provenance-v3/expected-original-inputs.json']=manifest_raw
    result={'schema_version':3,'issue':1268,'related_issue':1266,'previous_v2_packager_sha256':'f554cd8120ce2dfd3dffc298ca28ec605c4cf41d975a4b02b0ed6c3a1bdd8250','fixed_manifest_sha256':MANIFEST_SHA256,'original_inputs_verified':{name:entry['sha256'] for name,entry in pins.items()},'files':provenance,'originals_and_v1_stages_preserved':True,'historical_validation_rerun':False,'all_inputs_validated_before_output_creation':True,'syntax_help_privacy_and_shape_checked_before_output_creation':True,'output_inside_or_aliasing_inputs_refused':True,'packager_sha256':sha(helper_raw)}
    payload[PREFIX/'provenance-v3/PROVENANCE-V3.json']=(json.dumps(result,indent=2,sort_keys=True)+'\n').encode()
    payload[PREFIX/'provenance-v3/README.md']=note.encode()
    for relative,raw in payload.items():
        if relative.is_absolute() or '..' in relative.parts:raise ValueError('Unsafe output path')
        safe_public(raw)
    return payload,result

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--task-root',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();task=a.task_root.absolute();out=a.output.absolute();no_symlinks(task);no_symlinks(out)
    if task!=task.resolve() or out!=out.resolve() or not task.is_dir():raise ValueError('Canonical input/output paths required')
    if os.path.lexists(out) or out==task or task in out.parents or out in task.parents:raise ValueError('Output must be new and outside/unaliasing every input')
    if not out.parent.is_dir():raise ValueError('Existing output parent required')
    manifest_raw=read_regular(Path(__file__).absolute().with_name('expected-original-inputs.json'))
    if sha(manifest_raw)!=MANIFEST_SHA256:raise ValueError('Fixed original-input manifest authentication failed')
    manifest=strict_json(manifest_raw)
    if manifest['schema_version']!=2 or manifest['issue']!=1266 or len(manifest['inputs'])!=30:raise ValueError('Unexpected fixed input manifest')
    payload,result=build(task,manifest,manifest_raw)
    # This is the first filesystem mutation. Every input/output byte is validated.
    out.mkdir(mode=0o700)
    for relative,raw in sorted(payload.items()):
        destination=out/relative;destination.parent.mkdir(parents=True,exist_ok=True)
        with destination.open('xb') as stream:stream.write(raw)
    print(json.dumps({'files':len(payload),'fixed_manifest_sha256':MANIFEST_SHA256,'packager_sha256':result['packager_sha256'],'provenance_sha256':sha(payload[PREFIX/'provenance-v3/PROVENANCE-V3.json'])}))
if __name__=='__main__':main()
