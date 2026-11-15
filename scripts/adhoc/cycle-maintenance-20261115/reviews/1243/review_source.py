"""Offline independent PR 1243 source review, 2026-11-15.
Inputs: detached exact-head checkout, development Python, new output directory.
Outputs: source proof, public metadata, focused tests and mutation receipts.
No live tmux/process/session discovery, runtime configuration or remote writes.
"""
import argparse,hashlib,json,os,subprocess
from pathlib import Path

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",required=True,type=Path);p.add_argument("--python",required=True)
    p.add_argument("--output",required=True,type=Path)
    a=p.parse_args();root=a.root.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    env={**os.environ,"PYTHONPATH":str(root/"src")};env.pop("MECH_TMUX_SAVED_EVIDENCE",None)
    def run(args,name,timeout=300):
        r=subprocess.run(args,cwd=root,env=env,capture_output=True,timeout=timeout)
        (out/name).write_bytes(r.stdout+r.stderr)
        if r.returncode:raise RuntimeError(f"{name} failed ({r.returncode})")
        return r.stdout.decode().strip()
    head=run(["git","rev-parse","HEAD"],"head.txt");assert head=="04e14f6c0fe4c4e7e4aaa8da0b765546fdc9afa3"
    assert not run(["git","status","--porcelain","--untracked-files=no"],"status-before.txt")
    main=run(["git","rev-parse","origin/main"],"main.txt")
    base=run(["git","merge-base",main,head],"merge-base.txt")
    tree=run(["git","merge-tree","--write-tree",main,head],"merge-tree.txt").splitlines()[0]
    run(["git","diff",main+"...HEAD"],"diff.patch")
    run(["gh","pr","view","1243","--repo","CultureBotAI/culturebotai-claw","--json","number,title,headRefOid,baseRefOid,headRefName,state,isDraft,mergeable,mergeStateStatus,body,statusCheckRollup"],"pr.json")
    for n in (1238,1239,1240,1241,1242,1244,1245,1249):
        run(["gh","issue","view",str(n),"--repo","CultureBotAI/culturebotai-claw","--json","number,title,state,body,comments"],f"issue{n}.json")
    tests=["tests/test_mech_session_tmux.py","tests/test_tmux_observer_integration.py","tests/test_tmux_observer_candidate_verification.py","tests/test_boss_dispatch_contract.py","tests/test_fleet_scoped_skills.py","tests/test_mech_template.py"]
    run([a.python,"-m","pytest","-q","-rs",*tests,"--basetemp",str(out/"pytest-fixtures")],"pytest.log")
    for name in ("observer","integration"):
        run([a.python,f"scripts/adhoc/check_tmux_{name}_mutations.py"],f"mutations-{name}.log")
    assert not run(["git","status","--porcelain","--untracked-files=no"],"status-after.txt")
    proof={"head":head,"main":main,"merge_base":base,"prospective_merge_tree":tree,"helper_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),"runtime_operations":False}
    (out/"source-head-proof.json").write_text(json.dumps(proof,indent=2)+"\n")
    print(json.dumps(proof,indent=2))
if __name__=="__main__":main()
