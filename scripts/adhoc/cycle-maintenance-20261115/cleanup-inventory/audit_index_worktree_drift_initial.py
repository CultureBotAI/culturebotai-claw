"""Read-only tracked drift for explicitly owned finished review worktrees.

2026-11-15 cleanup preparation. Inputs: named worktrees. Output: JSON stdout.
Hooks, fsmonitor, external diff/textconv, clean/process filters, optional locks
and lazy fetch are disabled. No reset, source write or deletion is performed.
"""
import argparse,json,os,subprocess
from pathlib import Path

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,action='append',required=True)
    a=p.parse_args();result=[]
    for root in a.root:
        env={k:v for k,v in os.environ.items() if not k.startswith('GIT_')}
        env.update(GIT_CONFIG_NOSYSTEM='1',GIT_CONFIG_GLOBAL=os.devnull,GIT_NO_LAZY_FETCH='1',GIT_OPTIONAL_LOCKS='0',GIT_TERMINAL_PROMPT='0',GIT_TRACE2='0',GIT_TRACE2_EVENT='0',GIT_TRACE2_PERF='0')
        base=['git','--no-optional-locks','-c','core.fsmonitor=false','-c','core.hooksPath='+os.devnull,'-C',str(root)]
        keys=subprocess.run(base+['config','--name-only','--get-regexp',r'^filter\.'],env=env,capture_output=True,text=True,timeout=20)
        if keys.returncode not in {0,1}:raise ValueError('Cannot safely inventory filter keys')
        overrides=[]
        for key in keys.stdout.splitlines():
            if key.endswith(('.clean','.smudge','.process','.required')):
                overrides.extend(['-c',key+('=false' if key.endswith('.required') else '=')])
        cmd=base[:1]+overrides+base[1:]+['diff-files','--name-status','-z','--no-ext-diff','--no-textconv','--no-renames','--']
        observed=subprocess.run(cmd,env=env,capture_output=True,timeout=90)
        if observed.returncode or observed.stderr:raise ValueError('Tracked drift observation failed')
        fields=observed.stdout.decode().split('\0');assert fields[-1]=='';fields.pop();assert len(fields)%2==0
        result.append({'root':str(root.resolve()),'unstaged_status':[{'status':fields[i],'path':fields[i+1]} for i in range(0,len(fields),2)],'external_execution_disabled':True})
    print(json.dumps(result,indent=2))
if __name__=='__main__':main()
