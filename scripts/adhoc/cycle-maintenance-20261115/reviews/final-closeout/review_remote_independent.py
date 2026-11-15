"""Independent production-module audit for parent 2.1, 2026-11-15.
Inputs: exact detached core snapshot and development Python. Outputs: exclusive
private test/mutation/API receipts. No source or GitHub mutations; no runtime work.
Reviewer authored initial focused tests, not production code. Issues1257/1258
are rechecked independently; 1259/1260 integration is a companion review scope.
"""
import argparse,hashlib,json,os,subprocess
from pathlib import Path

HEAD="1d0034ebe4fea0f4371e82e211db13d1b5ec2253"
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root",required=True,type=Path);p.add_argument("--python",required=True)
    p.add_argument("--output",required=True,type=Path);a=p.parse_args()
    root=a.root.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    assert subprocess.check_output(["git","rev-parse","HEAD"],cwd=root,text=True).strip()==HEAD
    source=root/"src/kg_microbe_workflows/pr_maintenance_remote.py";raw=source.read_bytes()
    env={**os.environ,"PYTHONPATH":str(root/"src")}
    def run(args,name,expected=0):
        r=subprocess.run(args,cwd=root,env=env,capture_output=True,text=True,timeout=300)
        (out/name).write_text(r.stdout+r.stderr)
        assert r.returncode==expected,(name,r.returncode)
        return r
    run([a.python,"-m","pytest","-q","-rs","tests/test_pr_maintenance_remote.py","--basetemp",str(out/"base-fixtures")],"pytest.log")
    specs=[("1257_union_id",' __typename ... on CheckRun{id name status conclusion}',' id __typename ... on CheckRun{name status conclusion}',"test_check_rollup_union_selects_ids_only_on_concrete_types"),
           ("1258_reopened_terminal",'if latest is not None:','if False:',"test_terminal_draft_reopened_at_final_inventory_cannot_claim_closure"),
           ("foreign_closure_status",'or proofs.get(number, {}).get("status") != "merged"','or False',"test_merged_disposition_needs_the_same_independently_verified_proof")]
    receipts=[]
    for name,before,after,node in specs:
        text=raw.decode();assert text.count(before)==1
        mutant=text.replace(before,after)
        variant=out/(name+".py");variant.write_text(mutant)
        bootstrap="import sys,types,pathlib;import kg_microbe_workflows as p; m=types.ModuleType('kg_microbe_workflows.pr_maintenance_remote');m.__file__=sys.argv[1];m.__package__='kg_microbe_workflows';exec(compile(pathlib.Path(sys.argv[1]).read_bytes(),sys.argv[1],'exec'),m.__dict__);sys.modules[m.__name__]=m;p.pr_maintenance_remote=m;import pytest;raise SystemExit(pytest.main(sys.argv[2:]))"
        r=run([a.python,"-c",bootstrap,str(variant),"-q","tests/test_pr_maintenance_remote.py::"+node,"--basetemp",str(out/(name+"-fixtures"))],name+".log",1)
        assert " failed" in r.stdout
        receipts.append({"name":name,"killed":True,"source_sha256":hashlib.sha256(variant.read_bytes()).hexdigest()})
    # A current public check query demonstrates the repaired real union shape.
    # Only GET and GraphQL query operations are used; no live session access.
    bootstrap="""import json,subprocess,sys
from kg_microbe_workflows import pr_maintenance_remote as m
repo='CultureBotAI/culturebotai-claw'
def runner(args,timeout=45):return subprocess.run(args,capture_output=True,text=True,timeout=timeout)
pr=json.loads(subprocess.check_output(['gh','api','--method','GET','repos/'+repo+'/pulls/1138'],text=True))
result=m.Observer(repo,runner).checks(1138,pr['head']['sha'])
print(json.dumps({'repository':repo,'pr':1138,'head':pr['head']['sha'],'checks':result},sort_keys=True))
"""
    run([a.python,"-c",bootstrap],"live-query.json")
    assert source.read_bytes()==raw
    proof={"head":HEAD,"source_sha256":hashlib.sha256(raw).hexdigest(),"test_sha256":hashlib.sha256((root/"tests/test_pr_maintenance_remote.py").read_bytes()).hexdigest(),"helper_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),"mutations":receipts,"source_unchanged":True,"runtime_operations":False,"reviewer_authored_initial_tests":True,"reviewer_authored_production_module":False}
    (out/"proof.json").write_text(json.dumps(proof,indent=2)+"\n");print(json.dumps(proof,indent=2))
if __name__=="__main__":main()
