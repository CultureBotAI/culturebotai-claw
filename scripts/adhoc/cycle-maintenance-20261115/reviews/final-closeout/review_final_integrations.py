"""Final ordinary-merge rereviews for PRs 1138 and 1112; 2026-11-15.
Inputs: exact isolated refreshed checkout, development Python, new evidence path.
Outputs: merge/tree proof, preserved blob inventory, offline tests and GH readback.
No original-source changes, GitHub writes, native/runtime actions or adoption.
"""
import argparse,hashlib,json,os,subprocess
from pathlib import Path
BASE="99fb0ac11e2e6aeabedc8d08f29a5f08aac0892d"
SPECS={1138:("3046fed7f3fda2d24f19c38e6e874fef68a794e4","6aeeb55105659cb740a0e7410eeb03a67855569d",["tests/test_freshness_archive_1138.py","tests/test_freshness_candidates.py"]),1112:("812bb455828dd32611da3b603732cd62e16cc37f","3da76c840590b8f579535aacd853b65ebf4f0009",["tests/test_port_pressure_supervisor_integration.py","tests/test_mech_session_supervisor.py","tests/test_port_pressure_boundary_only.py","tests/test_port_pressure_restart_registration_transport.py"])}
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--pr",type=int,choices=SPECS,required=True)
    p.add_argument("--root",type=Path,required=True);p.add_argument("--python",required=True);p.add_argument("--output",type=Path,required=True)
    a=p.parse_args();root=a.root.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    old,head,tests=SPECS[a.pr];env={**os.environ,"PYTHONPATH":str(root/"src")}
    def run(args,name):
        result=subprocess.run(args,cwd=root,env=env,capture_output=True,text=True,timeout=300)
        (out/name).write_text(result.stdout+result.stderr)
        if result.returncode:raise ValueError(name+" failed")
        return result.stdout.strip()
    def git(*args):return subprocess.check_output(["git",*args],cwd=root,text=True).strip()
    assert git("rev-parse","HEAD")==head
    assert not git("status","--porcelain","--untracked-files=no")
    assert git("rev-list","--parents","-n","1",head).split()==[head,old,BASE]
    expected=run(["git","merge-tree","--write-tree",old,BASE],"merge-tree.txt").splitlines()[0]
    observed=git("rev-parse",head+"^{tree}");assert observed==expected
    main=git("rev-parse","origin/main")
    prospective=run(["git","merge-tree","--write-tree",main,head],"current-main-integration.txt").splitlines()[0]
    oldbase=git("merge-base",old,BASE)
    names=git("diff","--name-only",oldbase,old).splitlines()
    preserved=[];integrated=[]
    for name in names:
        before=git("ls-tree",old,"--",name);after=git("ls-tree",head,"--",name)
        (preserved if before==after else integrated).append(name)
    if a.pr==1138:assert len(preserved)==9 and not integrated
    run(["git","diff",main+"..."+head],"diff.patch")
    run([a.python,"-m","pytest","-q","-rs",*tests,"--basetemp",str(out/"pytest-fixtures")],"pytest.log")
    raw=run(["gh","pr","view",str(a.pr),"--repo","CultureBotAI/culturebotai-claw","--json","number,title,headRefOid,baseRefOid,state,isDraft,mergeable,mergeStateStatus,statusCheckRollup"],"pr.json")
    remote=json.loads(raw);assert remote["headRefOid"]==head
    assert not git("status","--porcelain","--untracked-files=no")
    proof={"pr":a.pr,"reviewed_original_head":old,"refreshed_head":head,"merge_parents":[old,BASE],"refreshed_tree":observed,"independently_computed_tree":expected,"actual_main":main,"prospective_current_main_tree":prospective,"reviewed_paths_preserved_exactly":preserved,"reviewed_paths_integrating_main":integrated,"helper_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),"test_log_sha256":hashlib.sha256((out/"pytest.log").read_bytes()).hexdigest(),"tracked_source_unchanged":True,"runtime_operations":False}
    (out/"proof.json").write_text(json.dumps(proof,indent=2)+"\n");print(json.dumps(proof,indent=2))
if __name__=="__main__":main()
