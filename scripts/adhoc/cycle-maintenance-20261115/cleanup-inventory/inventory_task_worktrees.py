"""Read-only task-owned cleanup inventory; 2026-11-15.

Inputs: explicit durable task root and two existing Git-group anchors. Outputs:
private metadata inventories, ignored/untracked pathname lists, references,
active operations/readers, and a summary. No file contents beyond this helper,
Git metadata and regular Git alternates declarations are opened. No cleanup,
ref changes, source mutation, runtime input or GitHub writes are supported.
Protected environments/evidence are retained; their descendants/sizes are not
claimed complete by the generic inventory. Scoped lsof matches are observation,
not proof that an unlisted agent has stopped using a path.
"""
from __future__ import annotations
import argparse, concurrent.futures, hashlib, importlib.util, json, os, stat, subprocess
from datetime import datetime, timezone
from pathlib import Path

IDENTITY='CultureBotAI/culturebotai-claw'

def save(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,sort_keys=True)+'\n')

def within(path,root):
    return path==root or root in path.parents

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--task-root',type=Path,required=True)
    parser.add_argument('--anchor',type=Path,action='append',required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--inventory-helper',type=Path,required=True,help='Canonical scripts/repo_crud_inventory.py')
    args=parser.parse_args(); task=args.task_root.resolve(); out=args.output.resolve()
    if not within(out,task) or any(within(out,a.resolve()) for a in args.anchor):
        raise ValueError('audit output must be inside task but outside checkouts')
    out.mkdir(parents=True,exist_ok=False)
    helper=args.inventory_helper.resolve()
    spec=importlib.util.spec_from_file_location('read_only_crud',helper)
    crud=importlib.util.module_from_spec(spec);spec.loader.exec_module(crud)
    roots={};groups={};discovered=[]
    for anchor in args.anchor:
        git=crud.Git(anchor.resolve())
        if crud.github_identity(git.text('remote','get-url','origin'))!=IDENTITY:
            raise ValueError('anchor identity differs')
        common=git.text('rev-parse','--path-format=absolute','--git-common-dir')
        meta=crud.git_metadata(git,Path(git.text('rev-parse','--absolute-git-dir')))
        groups[common]={'anchor':str(anchor.resolve()),'worktrees':meta['worktrees'],
                        'branches':meta['branches'],'stashes':meta['stashes']}
        for entry in meta['worktrees']:
            path=Path(entry['worktree']).resolve()
            if within(path,task):roots[str(path)]=entry
    # Gitignore-independent filename discovery, preserving nested fixture Git
    # boundaries separately and never following symlinks into another checkout.
    exclusions=[]
    for directory,dirs,files in os.walk(task,followlinks=False):
        here=Path(directory)
        if within(here,out):dirs[:]=[];continue
        if str(here) in roots:dirs[:]=[];continue
        if '.git' in dirs or '.git' in files:
            discovered.append(str(here));dirs[:]=[];continue
        for name in list(dirs):
            child=here/name
            if child.is_symlink() or name in {'.venv','venv','__pycache__','.git'}:
                exclusions.append(str(child));dirs.remove(name)
    reports=[]
    def one(item):
        root,registration=item;path=Path(root)
        key=path.relative_to(task).as_posix().replace('/','__')
        report=crud.inventory(path,IDENTITY,max_entries=100000,max_seconds=45,git_max_bytes=24000000)
        save(out/'repositories'/f'{key}.json',report)
        extra={'root':root,'registration':registration,'inventory_complete':report['complete'],
               'errors':report['errors'],'source_report':f'repositories/{key}.json'}
        if report.get('provenance'):
            git=crud.Git(path,max_bytes=24000000)
            def names(*argv):return sorted(crud.nul_paths(git.run(*argv)))
            ignored=names('ls-files','--others','--ignored','--exclude-standard','--directory','--no-empty-directory','-z')
            untracked=names('ls-files','--others','--exclude-standard','--directory','--no-empty-directory','-z')
            extra.update(head=report['provenance']['head'],git_common_dir=report['provenance']['git_common_dir'],
                         staged_status=report['staged_status'],operations=report['operations'],
                         git_path_counts=report['git_path_counts'],ignored_roots=ignored,untracked_roots=untracked,
                         retained_subtrees=report.get('retained_subtrees',[]),
                         unstaged_content_state=report['unstaged_content_state'])
            # Only filter-key names are inspected; no configured commands or
            # environment values are emitted. Filter-aware content comparison is
            # explicitly deferred to each later authorized removal preflight.
            alternate=Path(extra['git_common_dir'])/'objects/info/alternates'
            if alternate.is_file() and not alternate.is_symlink():
                extra['object_alternates']=alternate.read_text().splitlines()
        save(out/'details'/f'{key}.json',extra);return extra
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        for result in pool.map(one,sorted(roots.items())):reports.append(result)
    # Read metadata from open file descriptors, retaining task matches only.
    process_readers=[];reader_errors=[]
    try:
        proc=subprocess.run(['/usr/sbin/lsof','-nP','-Fpcfn'],capture_output=True,text=True,timeout=45)
        pid=comm=fd=None
        for line in proc.stdout.splitlines():
            if line.startswith('p'):pid=line[1:]
            elif line.startswith('c'):comm=line[1:]
            elif line.startswith('f'):fd=line[1:]
            elif line.startswith('n') and line[1:].startswith(str(task)+'/'):
                process_readers.append({'pid':pid,'command':comm,'fd':fd,'path':line[1:]})
        if proc.returncode not in {0,1}:reader_errors.append('lsof failed with exit '+str(proc.returncode))
        if proc.stderr:reader_errors.append('lsof emitted diagnostics; complete process coverage is not asserted')
    except subprocess.TimeoutExpired:
        reader_errors.append('lsof exceeded its 45 second bound')
    live={}
    for number in (1112,1138,1197,1211,1236,1243):
        proc=subprocess.run(['gh','pr','view',str(number),'--repo',IDENTITY,'--json','number,state,headRefOid,headRefName,baseRefName,mergeCommit,mergedAt,url'],capture_output=True,text=True,timeout=30)
        live[str(number)]=json.loads(proc.stdout) if proc.returncode==0 else {'error':'live PR read failed'}
    proc=subprocess.run(['gh','api','--method','GET','repos/'+IDENTITY+'/commits/main','--jq','.sha'],capture_output=True,text=True,timeout=30)
    main=proc.stdout.strip() if proc.returncode==0 else None
    save(out/'summary.json',{'observed_at':datetime.now(timezone.utc).isoformat(),'task_root':str(task),
        'mode':'read_only','helper_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        'upstream_inventory_helper_sha256':hashlib.sha256(helper.read_bytes()).hexdigest(),
        'actual_main':main,'groups':groups,'repositories':reports,
        'additional_nested_git_boundaries_retained':discovered,'discovery_exclusions_retained':exclusions,
        'active_reader_matches':process_readers,'reader_limitations':reader_errors,
        'live_prs':live,'removal_performed':False,'remote_ref_changes':False,
        'limitations':['Protected subtree contents and sizes remain unmeasured.','Unstaged content comparison deferred; metadata cleanliness is insufficient for removal.','Nested fixture Git repositories and excluded environments are preserved, not disposal candidates.','Live collaborators may retain readers between observations; owner completion confirmation is required.']})
    print(json.dumps({'inventoried_roots':len(reports),'complete':sum(r['inventory_complete'] for r in reports),'nested_boundaries_retained':len(discovered),'active_reader_matches':len(process_readers),'reader_limitations':reader_errors}))
if __name__=='__main__':main()
