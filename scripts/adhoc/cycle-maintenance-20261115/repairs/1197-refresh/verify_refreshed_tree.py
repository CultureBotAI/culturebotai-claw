"""Read-only PR1197 integration verification, 2026-11-15, issue1262.

Inputs: explicit checkout and retained baseline check/preview outputs. Verifies
full merged tree, ordinary parents, unchanged original scope and authentic
unchanged baseline. Output: public-safe JSON on stdout. No writes/network.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

OLD_MAIN="99fb0ac11e2e6aeabedc8d08f29a5f08aac0892d"
BEFORE="98345116994d17eaee050efb13f5414f5faaf3d4"
MAIN="bd2b07480afd3b3984491a7fc729c64220d4dd81"
HEAD="748cfaf510e96ffa6f8b4b08c877742cf8a492d8"
BASELINE="src/kg_microbe_skills/template_baseline.json"


def require(ok, message):
    if not ok:
        raise ValueError(message)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root",type=Path,required=True)
    parser.add_argument("--evidence",type=Path,required=True)
    args=parser.parse_args()
    def git(*words):
        return subprocess.check_output(["git","-c","core.fsmonitor=false","-c","core.hooksPath=/dev/null","-C",str(args.root),*words])
    def tree(ref):
        result={}
        for row in git("ls-tree","-r","-z",ref).split(b"\0"):
            if row:
                metadata,path=row.split(b"\t",1)
                result[path.decode()]=metadata.decode()
        return result
    require(git("rev-parse","HEAD").decode().strip()==HEAD,"Head drift")
    require(git("rev-list","--parents","-n","1",HEAD).decode().split()==[HEAD,BEFORE,MAIN],"Parents differ")
    old,before,main_tree,actual=map(tree,(OLD_MAIN,BEFORE,MAIN,HEAD))
    own={path for path in set(old)|set(before) if old.get(path)!=before.get(path)}
    incoming={path for path in set(old)|set(main_tree) if old.get(path)!=main_tree.get(path)}
    require(not own & incoming,"Unexpected changed-path overlap")
    expected=dict(main_tree)
    for path in own:
        if path in before:
            expected[path]=before[path]
        else:
            expected.pop(path,None)
    require(actual==expected,"Whole-tree union mismatch")
    baseline_raw=(args.root/BASELINE).read_bytes()
    require(git("show",BEFORE+":"+BASELINE)==baseline_raw,"Baseline bytes changed")
    baseline=json.loads(baseline_raw)
    for path in ("baseline-check.json","baseline-preview.json"):
        require(json.loads((args.evidence/path).read_bytes())==baseline,"Maintained output differs")
    for name,digest in baseline["sources"].items():
        require(hashlib.sha256((args.root/name).read_bytes()).hexdigest()==digest,"Working authority differs")
        require(hashlib.sha256(git("show",baseline["source_ref"]+":"+name)).hexdigest()==digest,"Source authority differs")
    git("diff","--check")
    require(not git("status","--porcelain=v1","--untracked-files=all"),"Worktree not clean")
    print(json.dumps({"head":HEAD,"tree":git("rev-parse","HEAD^{tree}").decode().strip(),"parents":[BEFORE,MAIN],
                      "full_tree_exact_union":True,"original_paths_preserved":sorted(own),"incoming_path_count":len(incoming),
                      "baseline_source":baseline["source_ref"],"baseline_version":baseline["baseline_version"],
                      "baseline_source_count":len(baseline["sources"]),"baseline_sha256":hashlib.sha256(baseline_raw).hexdigest(),
                      "baseline_refresh_noop":True,"tracked_status_clean":True,
                      "helper_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},indent=2,sort_keys=True))

if __name__=="__main__":
    main()
