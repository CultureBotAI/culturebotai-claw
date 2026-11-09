"""Explicit Step 5 evidence freeze/publication; verification is offline/read-only."""
from pathlib import Path
import argparse
import datetime
import gzip
import hashlib
import json
import subprocess

HERE = Path(__file__).resolve().parent
RUN = HERE.parent
DESTINATION = Path('reports/mim_owned_name_export_20261101')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def relative(value):
    path = Path(value)
    require(not path.is_absolute() and path.parts and '..' not in path.parts, 'Unsafe relative path')
    return path


def read(path):
    require(not any(p.is_symlink() for p in (path, *path.parents)), 'Aliased evidence path: '+str(path))
    require(path.is_file(), 'Missing regular evidence file: '+str(path))
    return path.read_bytes()


def source(name):
    path = RUN / relative(name)
    require(path.suffix not in {'.pyc', '.db', '.sqlite', '.sqlite3'}, 'Excluded cache/database')
    require('__pycache__' not in path.parts, 'Excluded bytecode cache')
    return path


def json_pointer(document, pointer):
    for component in pointer.strip('/').split('/') if pointer else []:
        component = component.replace('~1', '/').replace('~0', '~')
        document = document[int(component)] if isinstance(document, list) else document[component]
    return document


def validate_bindings(plan, originals):
    for command in plan['commands']:
        receipt = json.loads(originals[command['path']])
        require(receipt.get('finished_at') and type(receipt.get('exit_code')) is int, 'Unfinished command')
        require(receipt['exit_code'] == command['expected_exit'], 'Command status differs')
        require(receipt.get('argv'), 'Command argv missing')
        if receipt['exit_code']:
            require(command.get('disposition'), 'Failed/interrupted command lacks disposition')
        log = str(Path(receipt['log']).relative_to(Path(plan['run_root'])))
        require(digest(originals[log]) == receipt['log_sha256'], 'Command/log hash differs')
    for binding in plan['json_bindings']:
        value = json_pointer(json.loads(originals[binding['json_source']]), binding['pointer'])
        expected = digest(originals[binding['target_source']]) if 'target_source' in binding else binding['expected']
        require(value == expected, 'JSON evidence binding differs: '+str(binding))
    generation = plan['generation']
    manifest = json.loads(originals[generation['manifest']])
    artifacts = {item['role']: item for item in manifest['artifacts']}
    require(set(artifacts) == {'sssom', 'suppressed_aliases'}, 'Unexpected generation artifact roles')
    for role in artifacts:
        require(artifacts[role]['sha256'] == digest(originals[generation[role]]), 'Candidate artifact hash differs')
        require(Path(artifacts[role]['path']) == Path(plan['run_root'])/generation[role], 'Candidate original path differs')
    require('owned-name-policy-v1; suppression-sidecar-required' in originals[generation['sssom']].decode(), 'Missing diagnostic policy marker')
    journal = json.loads(originals[generation['journal']])
    expected_paths = {str(Path(plan['run_root'])/generation[role]) for role in ['sssom','suppressed_aliases','manifest']}
    changed, created = set(journal['changed']), set(journal['created'])
    require(journal['status'] == 'complete' and not changed & created, 'Incomplete/malformed generation journal')
    require(changed | created and changed | created <= expected_paths and set(journal['previous']) == changed, 'Journal scope differs')
    require({str(Path(p).parent) for p in expected_paths} == {journal['root']}, 'Journal output root differs')
    acceptance = json.loads(originals[generation['acceptance']])
    require(acceptance['status'] in {'PASS', 'PASS_WITH_LIMITATIONS'}, 'Actual candidate acceptance has not passed')
    if acceptance['status'] == 'PASS_WITH_LIMITATIONS':
        coverage = acceptance.get('b4_coverage')
        limitations = acceptance.get('limitations')
        require(isinstance(coverage, dict) and coverage.get('full_prefix_coverage') is False,
                'Limited acceptance requires explicit incomplete B4 coverage')
        missing = coverage.get('missing_transforms')
        require(isinstance(missing, list) and bool(missing)
                and all(isinstance(item, dict) and item.get('prefix') and item.get('expected_path')
                        and type(item.get('affected_row_count')) is int for item in missing),
                'Limited acceptance requires explicit missing B4 inputs')
        require(isinstance(limitations, list) and any(isinstance(item, dict)
                and item.get('rule') == 'B4' and item.get('prefixes') for item in limitations),
                'Limited acceptance requires the recorded B4 limitation')
        require(generation.get('b4_coverage') in originals
                and json.loads(originals[generation['b4_coverage']]) == coverage,
                'Standalone B4 coverage differs or was not archived')


def check_references(plan, repository):
    revision = plan['implementation_revision']
    require(len(revision) == 40 and all(c in '0123456789abcdef' for c in revision), 'Full implementation SHA required')
    subprocess.run(['git','merge-base','--is-ancestor',revision,'HEAD'],cwd=repository,check=True)
    for name, expected in plan['maintained_file_references'].items():
        raw = read(repository/relative(name))
        require(digest(raw) == expected['sha256'] and len(raw) == expected['bytes'], 'Maintained reference differs: '+name)
        committed = subprocess.check_output(['git','show',revision+':'+name],cwd=repository)
        require(committed == raw, 'Reference was not committed at the declared implementation revision: '+name)


def freeze(selection, output):
    raw = read(selection)
    plan = json.loads(raw)
    require(plan['state'] == 'final' and not plan['pending_final_inputs'], 'Selection is draft or incomplete')
    require(plan['intended_worktree'] == 'claw-owned-name' and plan['proposed_repository_destination'] == str(DESTINATION), 'Wrong package scope')
    require(plan['commands'] and plan['json_bindings'] and plan['generation'], 'Final command/generation bindings required')
    plan['run_root'] = str(RUN)
    originals = {}
    for name, item in plan['selected_existing_files'].items():
        data = read(source(name))
        require(digest(data) == item['source_sha256'] and len(data) == item['source_bytes'], 'Selected evidence changed: '+name)
        originals[name] = data
    validate_bindings(plan, originals)
    check_references(plan, RUN/'claw-owned-name')
    require(output.parent == HERE and not output.exists(), 'Freeze output must be a fresh run-owned file')
    result = {'kind':'frozen_step5_claw_evidence','captured_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
              'selection_path':str(selection),'selection_sha256':digest(raw),
              'packager_sha256':digest(read(Path(__file__))), 'plan':plan}
    with output.open('x') as stream:
        json.dump(result,stream,indent=2,sort_keys=True);stream.write('\n')
    print(json.dumps({'frozen':str(output),'sha256':digest(read(output))},indent=2))


def publish(inputs):
    frozen_bytes=read(inputs);frozen=json.loads(frozen_bytes);plan=frozen['plan']
    require(frozen['kind']=='frozen_step5_claw_evidence' and plan['run_root']==str(RUN), 'Wrong frozen scope')
    require(digest(read(Path(__file__)))==frozen['packager_sha256'], 'Packager changed after freeze')
    require(digest(read(Path(frozen['selection_path'])))==frozen['selection_sha256'], 'Final selection changed')
    repository=RUN/'claw-owned-name';destination=repository/DESTINATION
    require(not destination.exists() and not destination.is_symlink(), 'Package destination already exists')
    check_references(plan,repository)
    payloads={};sources={};by_hash={};originals={}
    for name,item in plan['selected_existing_files'].items():
        data=read(source(name));sha=digest(data)
        require(sha==item['source_sha256'] and len(data)==item['source_bytes'], 'Frozen source changed')
        originals[name]=data
        if sha not in by_hash:
            encoding='gzip' if len(data)>=65536 else 'identity'
            archive='evidence/'+name+('.gz' if encoding=='gzip' else '')
            require(archive not in payloads, 'Archive collision')
            payloads[archive]=gzip.compress(data,mtime=0) if encoding=='gzip' else data
            by_hash[sha]=(archive,encoding)
        archive,encoding=by_hash[sha]
        sources[name]={**item,'archive_path':archive,'encoding':encoding,
                       'archive_sha256':digest(payloads[archive]),'archive_bytes':len(payloads[archive])}
    validate_bindings(plan,originals)
    payloads['final-inputs.json']=frozen_bytes
    payloads['selection.final.json']=read(Path(frozen['selection_path']))
    payloads['verify.py']=read(Path(__file__))
    payloads['README.md']=plan['package_readme'].encode()
    manifest={'schema_version':1,'files':{p:{'sha256':digest(b),'bytes':len(b)} for p,b in sorted(payloads.items())},
              'sources':sources,'scientific_approval_added':False,'supervisor_binding':None}
    destination.parent.mkdir(parents=True,exist_ok=True)
    require(not any(p.is_symlink() for p in destination.parents), 'Aliased publication parent')
    destination.mkdir(exist_ok=False)
    for name,data in payloads.items():
        path=destination/relative(name);path.parent.mkdir(parents=True,exist_ok=True)
        with path.open('xb') as stream:stream.write(data)
    # Preserve an incomplete directory on any race; never overwrite it silently.
    for name,item in plan['selected_existing_files'].items():
        require(digest(read(source(name)))==item['source_sha256'], 'Input changed during packaging')
    check_references(plan,repository)
    with (destination/'manifest.json').open('x') as stream:
        json.dump(manifest,stream,indent=2,sort_keys=True);stream.write('\n')
    verify(destination,repository,False)


def verify(package,repository,require_tracked):
    manifest=json.loads(read(package/'manifest.json'))
    require(not any(p.is_symlink() for p in package.rglob('*')), 'Aliased package member')
    actual={str(p.relative_to(package)) for p in package.rglob('*') if p.is_file()}
    require(actual==set(manifest['files'])|{'manifest.json'}, 'Package membership differs')
    for name,item in manifest['files'].items():
        data=read(package/relative(name))
        require(digest(data)==item['sha256'] and len(data)==item['bytes'], 'Archive bytes differ')
    originals={}
    for name,item in manifest['sources'].items():
        data=read(package/relative(item['archive_path']))
        require(digest(data)==item['archive_sha256'] and len(data)==item['archive_bytes'], 'Source/archive binding differs')
        require(item['encoding'] in {'identity','gzip'}, 'Unknown archive encoding')
        raw=gzip.decompress(data) if item['encoding']=='gzip' else data
        require(digest(raw)==item['source_sha256'] and len(raw)==item['source_bytes'], 'Decoded original differs')
        originals[name]=raw
    frozen=json.loads(read(package/'final-inputs.json'));plan=frozen['plan']
    require(frozen['kind']=='frozen_step5_claw_evidence' and plan['state']=='final'
            and not plan['pending_final_inputs'], 'Wrong/incomplete frozen package')
    require(digest(read(package/'selection.final.json'))==frozen['selection_sha256'], 'Final selection binding differs')
    require(set(originals)==set(plan['selected_existing_files']), 'Frozen original identity set differs')
    for name,data in originals.items():
        expected=plan['selected_existing_files'][name]
        require(digest(data)==expected['source_sha256'] and len(data)==expected['source_bytes'], 'Original differs from frozen input')
    require(digest(read(package/'verify.py'))==frozen['packager_sha256'], 'Verifier/frozen packager binding differs')
    validate_bindings(plan,originals)
    if repository:
        check_references(plan,repository)
    require(not require_tracked or repository, 'Tracked check requires repository')
    if require_tracked:
        tracked=set(subprocess.check_output(['git','ls-files','-z'],cwd=repository).decode().split('\0'))
        required={str((package/p).relative_to(repository)) for p in actual}|set(plan['maintained_file_references'])
        require(required<=tracked, 'Package or maintained evidence includes untracked files')
    print(json.dumps({'status':'PASS','archive_members':len(actual),'original_identities':len(originals),
                      'tracked_checked':require_tracked,'scientific_approval_added':False},indent=2))


def main():
    parser=argparse.ArgumentParser(description=__doc__);modes=parser.add_subparsers(dest='mode',required=True)
    f=modes.add_parser('freeze');f.add_argument('--selection',type=Path,required=True);f.add_argument('--output',type=Path,required=True)
    p=modes.add_parser('publish');p.add_argument('--inputs',type=Path,required=True)
    v=modes.add_parser('verify');v.add_argument('--package',type=Path,required=True);v.add_argument('--repository',type=Path);v.add_argument('--require-tracked',action='store_true')
    args=parser.parse_args()
    if args.mode=='freeze':freeze(args.selection.absolute(),args.output.absolute())
    elif args.mode=='publish':publish(args.inputs.absolute())
    else:verify(args.package.absolute(),args.repository.absolute() if args.repository else None,args.require_tracked)


if __name__=='__main__':main()
