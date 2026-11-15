"""Read-only PR 1138 closeout reproduction; issue 1252; 2026-11-15.
Inputs: isolated exact-head checkout, existing development Python, new output directory.
Outputs: Git/GitHub proof, exact preserved hashes, offline tests, fresh GET-only receipt.
No source changes, remote writes, generation, runtime operations, or adoption.
"""
import argparse, hashlib, json, os, subprocess
from pathlib import Path

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",required=True,type=Path)
    p.add_argument("--python",required=True)
    p.add_argument("--output",required=True,type=Path)
    a=p.parse_args(); root=a.root.resolve(); out=a.output.resolve()
    out.mkdir(parents=True,exist_ok=False)
    def run(args,name):
        r=subprocess.run(args,cwd=root,capture_output=True,env={**os.environ,"PYTHONPATH":str(root/"src")},timeout=300)
        (out/name).write_bytes(r.stdout+r.stderr)
        if r.returncode: raise RuntimeError(f"{name} failed: {r.returncode}")
        return r.stdout.decode().strip()
    head=run(["git","rev-parse","HEAD"],"head.txt")
    assert head=="3046fed7f3fda2d24f19c38e6e874fef68a794e4"
    assert not run(["git","status","--porcelain","--untracked-files=no"],"status-before.txt")
    main=run(["git","rev-parse","origin/main"],"main.txt")
    run(["git","diff","origin/main...HEAD"],"diff.patch")
    tree=run(["git","merge-tree","--write-tree",main,head],"merge-tree.txt").splitlines()[0]
    run(["gh","pr","view","1138","--repo","CultureBotAI/culturebotai-claw","--json","number,title,headRefOid,baseRefOid,state,isDraft,mergeable,mergeStateStatus,body,statusCheckRollup"],"pr.json")
    run(["gh","issue","view","1252","--repo","CultureBotAI/culturebotai-claw","--json","number,state,title,body"],"issue1252.json")
    hashes={}
    for name in ("SKILL.md","contract.yaml","schema.yaml","proposal.json"):
        path="workflow/candidates/repository-freshness-v1/"+name
        current=(root/path).read_bytes()
        previous=subprocess.check_output(["git","show","d8d3b2ba8f101be2e2bc44aee57ef0525c0b7d53:"+path],cwd=root)
        assert current==previous
        hashes[path]=hashlib.sha256(current).hexdigest()
    helper=root/"scripts/adhoc/repository-freshness-closeout-20261115/verify_release.py"
    before=hashlib.sha256(helper.read_bytes()).hexdigest()
    run([a.python,"-m","pytest","-q","-rs","tests/test_freshness_archive_1138.py","--basetemp",str(out/"pytest-fixtures")],"pytest.log")
    run([a.python,str(helper),"--repository-root",str(root),"--output",str(out/"live-verification.json")],"live-verification.log")
    assert hashlib.sha256(helper.read_bytes()).hexdigest()==before
    assert not run(["git","status","--porcelain","--untracked-files=no"],"status-after.txt")
    proof={"head":head,"main":main,"prospective_merge_tree":tree,"candidate_sha256":hashes,"helper_sha256":before,"review_helper_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),"runtime_operations":False}
    (out/"source-head-proof.json").write_text(json.dumps(proof,indent=2)+"\n")
    print(json.dumps(proof,indent=2))
if __name__=="__main__": main()
