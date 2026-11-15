"""Independent offline counterfactual review for claw PR 1112; 2026-11-15.
Related issues: claw 1104-1111. Inputs: exact reviewed head and synthetic tests.
Outputs: mutation logs, hashes and receipt in the owned private review root.
Only this isolated review worktree is changed, always restored in finally.
No live monitor, process, session, GitHub or deployment is accessed by this helper.
"""
from __future__ import annotations
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
_parser = __import__("argparse").ArgumentParser(description=__doc__)
_parser.add_argument("--review-tree", type=Path, required=True,
                     help="Owned isolated detached worktree at the exact reviewed head")
ROOT = _parser.parse_args().review_tree.resolve()
if Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"],
                               cwd=ROOT, text=True).strip()).resolve() != ROOT:
    raise SystemExit("Review path is not a worktree root")
if subprocess.run(["git", "symbolic-ref", "--quiet", "HEAD"], cwd=ROOT,
                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 1:
    raise SystemExit("Review tree must be detached; feature branches are refused")
if subprocess.run(["git", "diff-index", "--quiet", "HEAD", "--"], cwd=ROOT).returncode:
    raise SystemExit("Tracked source differs from the reviewed head")
OUT=ROOT.parent
HEAD='812bb455828dd32611da3b603732cd62e16cc37f'
assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()==HEAD
sha=lambda raw:hashlib.sha256(raw).hexdigest()
cases=[
 ('idle-fallback', 'src/kg_microbe_workflows/port_pressure.py',
  'if boundary is None and settings["restart_policy"] == "goal_boundary_only":',
  'if False and boundary is None and settings["restart_policy"] == "goal_boundary_only":',
  'tests/test_port_pressure_boundary_only.py::test_critical_pressure_without_boundary_never_selects_idle_canary'),
 ('direct-transport-bypass','scripts/mech_session_port_pressure.py',
  'require(policy != "goal_boundary_only" or self.boundary is not None,',
  'require(True or policy != "goal_boundary_only" or self.boundary is not None,',
  'tests/test_port_pressure_restart_registration_transport.py::test_transport_rejects_boundary_only_without_boundary_even_if_called_directly'),
 ('changed-executable','scripts/mech_session_port_pressure.py',
  'require(digest == registration["executable_sha256"], "registered executable bytes changed")',
  'require(True, "registered executable bytes changed")',
  'tests/test_port_pressure_restart_registration_transport.py::test_changed_executable_after_quit_is_refused_before_resume'),
 ('effective-map-ack','scripts/mech_approval_bindings.py',
  "for key in ('generation', 'targets_sha256', 'config_sha256', 'source_sha256', 'effective'):",
  "for key in ('generation', 'targets_sha256', 'config_sha256', 'source_sha256'):",
  'tests/test_mech_approval_bindings.py::test_each_ack_proof_is_required[effective]'),
 ('wrong-lock-root','scripts/mech_approval_bindings.py',
  'def verify_lock_root(service, actual):\n',
  'def verify_lock_root(service, actual):\n    return\n',
  'tests/test_mech_approval_bindings.py::test_lock_root_mismatch_refuses_baseline_and_prequit'),
 ('missing-prequit-evidence','scripts/mech_session_port_pressure.py',
  '                self.preserve_attempt()\n',
  '                pass  # simulated lost pre-quit evidence\n',
  'tests/test_mech_port_pressure_native_transport.py::test_failed_restart_keeps_exact_immutable_prequit_evidence'),
 ('stale-source-pins','scripts/mech_approval_bindings.py',
  "    _raw, _config, service, sources = configuration(plan['controller'])\n",
  "    _raw, _config, service, sources = None, None, plan['service'], plan['expected']['source_sha256']\n",
  'tests/test_mech_approval_bindings.py::test_pinned_monitor_code_drift_refuses_under_lease_before_input'),
 ('pretend-code-reload','scripts/mech_approval_bindings.py',
  "require(code_pins(sources) == code_pins(self.snapshot['source_sha256']),",
  "require(True,",
  'tests/test_mech_approval_bindings.py::test_resident_cannot_claim_reloaded_code_after_disk_and_pin_change'),
]
originals={path:(ROOT/path).read_bytes() for _,path,_,_,_ in cases}
receipts=[]
def run(name,selected):
    cmd=[sys.executable,'-m','pytest','-q',*selected,'--basetemp='+str(OUT/('pytest-'+name))]
    env=dict(os.environ,PYTHONPYCACHEPREFIX=str(OUT/('pycache-'+name)))
    process=subprocess.run(cmd,cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    (OUT/(name+'.log')).write_bytes(process.stdout)
    return {'name':name,'command':cmd,'exit_code':process.returncode,'log_sha256':sha(process.stdout), 'fresh_pycache':env['PYTHONPYCACHEPREFIX']}
receipts.append(run('mutation-control',list(dict.fromkeys(c[-1] for c in cases))))
assert receipts[-1]['exit_code']==0
try:
    for name,path,old,new,selected in cases:
        original=originals[path]
        assert original.decode().count(old)==1, name
        altered=original.decode().replace(old,new).encode()
        (ROOT/path).write_bytes(altered)
        receipt=run(name,[selected])
        receipt.update(path=path,old=old,new=new,original_sha256=sha(original),mutated_sha256=sha(altered))
        receipts.append(receipt)
        (ROOT/path).write_bytes(original)
finally:
    for path,original in originals.items(): (ROOT/path).write_bytes(original)
proof={'at':datetime.now(timezone.utc).isoformat(),'head':HEAD,'helper_sha256':sha(Path(__file__).read_bytes()),
       'restored_source_sha256':{p:sha((ROOT/p).read_bytes()) for p in originals},'receipts':receipts}
(OUT/'counterfactuals.json').write_text(json.dumps(proof,indent=2)+'\n')
print(json.dumps([(r['name'],r['exit_code']) for r in receipts]))
