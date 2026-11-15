"""Offline guard-removal probes for PR 1243, issues 1241 and 1249; 2026-11-15.
Inputs: immutable review checkout and development Python. Output: exclusive mutation evidence.
Mutants use supported test overrides; committed source is never changed.
"""
import argparse,hashlib,json,os,subprocess
from pathlib import Path

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",type=Path,required=True);p.add_argument("--python",required=True)
    p.add_argument("--output",type=Path,required=True);a=p.parse_args()
    root=a.root.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    assert subprocess.check_output(["git","rev-parse","HEAD"],cwd=root,text=True).strip()=="04e14f6c0fe4c4e7e4aaa8da0b765546fdc9afa3"
    src=root/"scripts/adhoc/verify_tmux_observer_candidate.py"; skill=root/".claude/skills/boss/SKILL.md"
    hashes={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (src,skill)}
    specs=[("trust_consistent_wrong_counts",src,"MECH_TMUX_CANDIDATE_VERIFIER_SOURCE","tests/test_tmux_observer_candidate_verification.py",[('    require_counts(status.get("counts"), counts, "Status")','    # removed status count guard'),('    require_counts(heartbeat.get("counts"), counts, "Heartbeat")','    # removed heartbeat count guard')]),
           ("collapse_duplicate_targets",src,"MECH_TMUX_CANDIDATE_VERIFIER_SOURCE","tests/test_tmux_observer_candidate_verification.py",[('require(key not in indexed, label + " duplicate target key")','require(True, label + " duplicate target key")')]),
           ("omit_retention_before_launch",skill,"BOSS_SKILL_SOURCE","tests/test_boss_dispatch_contract.py",[('"$1" -N -S "$2" set-option -p -t "$TMUX_PANE" remain-on-exit on && cd -- "$3" && exec claude','cd -- "$3" && exec claude')])]
    receipts=[]
    for name,path,var,test,replacements in specs:
        text=path.read_text()
        for before,after in replacements:
            assert text.count(before)==1,(name,before)
            text=text.replace(before,after)
        mutant=out/(name+path.suffix);mutant.write_text(text)
        env={**os.environ,var:str(mutant),"PYTHONPATH":str(root/"src"),"PYTHONPYCACHEPREFIX":str(out/(name+"-cache"))}
        env.pop("MECH_TMUX_SAVED_EVIDENCE",None)
        r=subprocess.run([a.python,"-m","pytest","-q",test,"--basetemp",str(out/(name+"-fixtures"))],cwd=root,env=env,capture_output=True,text=True,timeout=120)
        (out/(name+".log")).write_text(r.stdout+r.stderr)
        assert r.returncode==1 and " failed" in r.stdout,(name,r.returncode)
        receipts.append({"mutation":name,"exit_code":r.returncode,"killed":True,"sha256":hashlib.sha256(mutant.read_bytes()).hexdigest()})
    assert hashes=={str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in (src,skill)}
    proof={"head":"04e14f6c0fe4c4e7e4aaa8da0b765546fdc9afa3","mutations":receipts,"source_unchanged":True,"helper_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    (out/"summary.json").write_text(json.dumps(proof,indent=2)+"\n");print(json.dumps(proof,indent=2))
if __name__=="__main__":main()
