"""Independent read-only PR1197 integration review, 2026-11-15; issue1262.
Inputs: exact repaired checkout, original PR, and published main Git objects.
Output: hash-bound JSON on stdout. No network, Git writes, runtime or adoption.
Retains the original8-path semantics and authenticates the new baseline source.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

HEAD='98345116994d17eaee050efb13f5414f5faaf3d4'
SOURCE='66e6c6a15ff05a098bcb275686bcc6d74b20eaeb'
ORIGINAL='345a63c31e44cf77e7323d7c2647a4d7d8d61683'
BASE='99fb0ac11e2e6aeabedc8d08f29a5f08aac0892d'
CATALOGUE='src/kg_microbe_skills/skills.yaml'
BASELINE='src/kg_microbe_skills/template_baseline.json'

def sha(raw):return hashlib.sha256(raw).hexdigest()
def blob(raw):return hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root',required=True,type=Path)
    root=parser.parse_args().root.resolve()
    def git(*args):return subprocess.check_output(['git','-C',str(root),*args])
    def raw(ref,path):return git('show',f'{ref}:{path}')
    def mapping(ref):
        result={}
        for item in git('ls-tree','-rz',ref).split(b'\0'):
            if not item:continue
            metadata,path=item.split(b'\t',1)
            mode,kind,oid=metadata.decode().split()
            result[path.decode()]=(mode,kind,oid)
        return result
    assert git('rev-parse','HEAD').decode().strip()==HEAD
    assert git('rev-list','--parents','-n','1',SOURCE).decode().split()==[SOURCE,ORIGINAL,BASE]
    mergebase=git('merge-base',ORIGINAL,BASE).decode().strip()
    original_paths=set(git('diff','--name-only',mergebase,ORIGINAL).decode().splitlines())
    assert len(original_paths)==8 and CATALOGUE in original_paths
    expected=mapping(BASE);observed=mapping(SOURCE);original=mapping(ORIGINAL)
    for path in original_paths-{CATALOGUE}:
        expected[path]=original[path]
        assert raw(SOURCE,path)==raw(ORIGINAL,path)==(root/path).read_bytes()
    main_catalogue=raw(BASE,CATALOGUE).decode()
    prior='One row per repository of open issues and open PRs across claw and the\n      manifest-defined Mechs, reading membership from the manifest.'
    new='Count-ranked open-issue inventory across claw and the manifest-defined\n      Mechs, with Markdown and structured per-issue review-decision tables.'
    prior_review='Reviews the complete manifest-defined Mech backlog with thematic prioritization and dependency-aware parallel planning.'
    new_review='Enriches the shared issue inventory with evidence-backed priority and keep/close/defer recommendations, thematic prioritization, and dependency-aware parallel planning.'
    assert main_catalogue.count(prior)==1 and main_catalogue.count(prior_review)==1
    expected_catalogue=main_catalogue.replace(prior,new).replace(prior_review,new_review).encode()
    assert expected_catalogue==raw(SOURCE,CATALOGUE)==(root/CATALOGUE).read_bytes()
    expected[CATALOGUE]=(expected[CATALOGUE][0],'blob',blob(expected_catalogue))
    assert expected==observed
    final_expected=expected.copy();final_expected[BASELINE]=mapping(HEAD)[BASELINE]
    assert final_expected==mapping(HEAD)
    assert git('diff','--name-only',SOURCE,HEAD).decode().splitlines()==[BASELINE]
    baseline=json.loads((root/BASELINE).read_bytes())
    assert baseline['source_ref']==SOURCE and baseline['baseline_version']=='1.0.0'
    assert len(baseline['sources'])==60
    for path,expected_hash in baseline['sources'].items():
        assert sha(raw(SOURCE,path))==expected_hash==sha((root/path).read_bytes())
    sys.path[:0]=[str(root/'src'),str(root)]
    from kg_microbe_skills.template import check_baseline,refresh_baseline
    assert check_baseline(root)==baseline==refresh_baseline(root)
    bad=json.loads((root/BASELINE).read_bytes());bad['source_ref']=BASE
    child='''import json,pathlib,sys\nroot=pathlib.Path(sys.argv[1]);sys.path[:0]=[str(root/'src'),str(root)]\nimport kg_microbe_skills.template as m\noriginal=m._source_text;bad=json.loads(sys.argv[2])\nm._source_text=lambda path, source_root:json.dumps(bad) if path==m.BASELINE_PATH else original(path,source_root)\ntry:m.check_baseline(root)\nexcept m.TemplateError as exc:\n print(str(exc));sys.exit(0)\nraise SystemExit(1)\n'''
    probe=subprocess.run([sys.executable,'-c',child,str(root),json.dumps(bad)],capture_output=True,text=True)
    assert probe.returncode==0 and any(marker in probe.stdout for marker in ('does not authenticate bytes', 'authority inventory differs from baseline')), (probe.stdout, probe.stderr)
    original_probe=subprocess.run([sys.executable,'-c',child,str(root),raw(BASE,BASELINE).decode()],capture_output=True,text=True)
    assert original_probe.returncode==0 and 'canonical baseline drift: src/kg_microbe_skills/skills.yaml' in original_probe.stdout
    print(json.dumps({'head':HEAD,'base':BASE,'original':ORIGINAL,'source':SOURCE,
        'source_tree':git('rev-parse',f'{SOURCE}^{{tree}}').decode().strip(),
        'final_tree':git('rev-parse','HEAD^{tree}').decode().strip(),
        'original_paths':sorted(original_paths),'seven_original_paths_identical':True,
        'catalogue_only_two_original_reason_changes':True,'exact_source_tree_match':True,
        'only_baseline_after_integration':True,'baseline_version':baseline['baseline_version'],
        'authority_sources':len(baseline['sources']),'baseline_sha256':sha((root/BASELINE).read_bytes()),
        'catalogue_sha256':sha((root/CATALOGUE).read_bytes()),'old_source_counterfactual_rejected':True,
        'counterfactual_message':probe.stdout.strip(),'unchanged_main_baseline_rejected':True,
        'unchanged_main_baseline_message':original_probe.stdout.strip(),'helper_sha256':sha(Path(__file__).read_bytes()),
        'source_files_sha256':{p:sha((root/p).read_bytes()) for p in sorted(original_paths|{BASELINE})},
        'git_status':git('status','--porcelain').decode(),'authority':'read_only'},indent=2))

if __name__=='__main__':main()
