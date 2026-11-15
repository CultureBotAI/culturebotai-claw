"""Independent offline review of issue1267, 2026-11-15.

Inputs: root source checkout with the proposed test and immutable base commit.
Outputs: exclusive isolated source snapshot, pytest receipts, one valid-YAML byte
mutation and exact provenance. Original checkout is read only. No GitHub or
runtime actions. Only the isolated historical template is temporarily changed,
and its original bytes are restored in finally.
"""
import argparse,hashlib,io,json,os,subprocess,sys,tarfile
from pathlib import Path

BASE='1f8e0a0db3a83ddd70723a6cdf8f1d579b3da099'
ORIGINAL='99fb0ac11e2e6aeabedc8d08f29a5f08aac0892d'
OLD='src/kg_microbe_workflows/templates/mech-cycle.yaml'
HIST='src/kg_microbe_workflows/templates/mech-cycle-v2.0.yaml'
TEST='tests/test_freshness_contract.py'
EXPECTED='0d3e218c22c4ffe4e6dcddce8287d0177aaa52f637e156df1c737e4e7d84f913'
def sha(raw):return hashlib.sha256(raw).hexdigest()
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--source-root',required=True,type=Path);p.add_argument('--output',required=True,type=Path)
    a=p.parse_args();root=a.source_root.resolve();out=a.output.resolve();out.mkdir(parents=True,exist_ok=False)
    proposed=(root/TEST).read_bytes()
    def git(*args):return subprocess.check_output(['git','-c','core.hooksPath='+os.devnull,'-C',str(root),*args])
    assert git('rev-parse','HEAD').decode().strip()==BASE
    original=git('show',ORIGINAL+':'+OLD);historical=git('show',BASE+':'+HIST)
    assert original==historical and sha(historical)==EXPECTED
    snapshot=out/'snapshot';snapshot.mkdir()
    archive=git('archive',BASE,'src')
    with tarfile.open(fileobj=io.BytesIO(archive)) as stream:stream.extractall(snapshot,filter='data')
    test=snapshot/TEST;test.parent.mkdir();test.write_bytes(proposed)
    baseline=git('show',BASE+':'+TEST);(out/'test-before.py').write_bytes(baseline)
    (out/'test-reviewed.py').write_bytes(proposed)
    env={**os.environ,'PYTHONPATH':str(snapshot/'src')}
    def check(name,node,expected):
        env['PYTHONPYCACHEPREFIX']=str(out/(name+'-pycache'))
        r=subprocess.run([sys.executable,'-m','pytest','-q','-rs','-c',os.devnull,str(test)+node,'--basetemp',str(out/(name+'-fixtures'))],cwd=snapshot,env=env,text=True,capture_output=True,timeout=120)
        (out/(name+'.log')).write_text(r.stdout+r.stderr)
        assert r.returncode==expected,(name,r.returncode,r.stdout,r.stderr)
        return r.stdout
    passed=check('control','',0);assert '17 passed' in passed
    hist=snapshot/HIST;assert hist.read_bytes()==historical
    altered=historical+b'\n# independent valid-YAML byte mutation\n'
    try:
        hist.write_bytes(altered)
        failed=check('historical-byte-mutant','::test_original_v1_v2_parent_bytes_remain_available',1)
        assert '1 failed' in failed and 'AssertionError' in failed
    finally:hist.write_bytes(historical)
    restored=check('restored','::test_original_v1_v2_parent_bytes_remain_available',0);assert '1 passed' in restored
    assert (root/TEST).read_bytes()==proposed and hist.read_bytes()==historical
    proof={'issue':1267,'base_commit':BASE,'original_parent_source_commit':ORIGINAL,'original_parent_path':OLD,'historical_parent_path':HIST,'historical_parent_sha256':EXPECTED,'historical_parent_equals_original_git_blob':True,'reviewed_test_sha256':sha(proposed),'previous_test_sha256':sha(baseline),'source_archive_sha256':sha(archive),'control_tests_passed':17,'mutations':[{'name':'valid_yaml_historical_byte','sha256':sha(altered),'killed':True,'fresh_interpreter':True}],'restored_test_passed':True,'original_source_unchanged':True,'runtime_operations':False,'helper_sha256':sha(Path(__file__).read_bytes())}
    (out/'proof.json').write_text(json.dumps(proof,indent=2)+'\n');print(json.dumps(proof,indent=2))
if __name__=='__main__':main()
