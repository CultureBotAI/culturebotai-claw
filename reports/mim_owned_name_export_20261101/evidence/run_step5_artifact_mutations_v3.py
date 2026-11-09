from pathlib import Path
import os,sys,json,hashlib,shutil,subprocess,datetime
RUN=Path(__file__).resolve().parent
SOURCE=RUN/'claw-owned-name'
DEST=RUN/'step5-artifact-mutations-v3'
DEST.mkdir()
files=['src/kg_microbe_utils/sssom_artifacts.py','src/kg_microbe_utils/owned_name_policy.py','scripts/publish_sssom.py','tests/test_mim_sssom_artifacts.py']
frozen={f:hashlib.sha256((SOURCE/f).read_bytes()).hexdigest() for f in files}
variants=[
 ('positive',None,None,None,'tests/test_mim_sssom_artifacts.py'),
 ('tsv_only_noop','src/kg_microbe_utils/sssom_artifacts.py','if all(before[p] == content for p, content in intended.items()):','if before[paths[0]] == sssom_bytes:','tests/test_mim_sssom_artifacts.py::test_equal_tsv_is_not_a_noop_for_changed_or_missing_companions'),
 ('omit_native_boundary','src/kg_microbe_utils/sssom_artifacts.py','        check_before()\n\n    locker =','        pass\n\n    locker =','tests/test_mim_sssom_artifacts.py::test_real_native_precommit_checker_refuses_a_source_change_after_staging'),
 ('legacy_policy_bypass','scripts/publish_sssom.py','if POLICY_MARKER in WORKING_COPY.read_text(encoding="utf-8"):','if False:','tests/test_mim_sssom_artifacts.py::test_legacy_publisher_refuses_policy_candidate_even_without_manifest'),
 ('nonzero_validator_accepted','scripts/publish_sssom.py','if proc.returncode:','if False:','tests/test_mim_sssom_artifacts.py::test_legacy_validator_never_accepts_a_nonzero_exit'),
 ('input_output_overlap','src/kg_microbe_utils/sssom_artifacts.py','if overlap - allowed or (working_copy_stamp_input and paths[0] not in inputs):','if False:','tests/test_mim_sssom_artifacts.py::test_only_the_explicit_working_copy_input_can_overlap_outputs'),
 ('still_published_suppression','src/kg_microbe_utils/sssom_artifacts.py','or key in tokens[subject]):','or False):','tests/test_mim_sssom_artifacts.py::test_invalid_sidecar_never_publishes_a_tsv'),
]

variants.extend([('absent_portable_collision', 'src/kg_microbe_utils/sssom_artifacts.py', 'if len({portable_key(p) for p in paths}) != 3:', 'if False:', 'tests/test_mim_sssom_artifacts.py::test_absent_case_and_unicode_aliases_are_refused_before_any_artifact_write'), ('normalize_before_path_checks', 'src/kg_microbe_utils/sssom_artifacts.py', '    path = Path(path)\n    if ".." in path.parts:', '    return Path(os.path.abspath(path))\n    path = Path(path)\n    if ".." in path.parts:', 'tests/test_mim_sssom_artifacts.py::test_symlink_parent_traversal_is_refused_before_lexical_normalization'), ('callback_after_precommit_guards', 'src/kg_microbe_utils/sssom_artifacts.py', '    def check_before() -> None:\n        for path in inputs:\n            _check_path(path)\n        input_check()\n        check_journal_path()\n        # Hashing the sources may take time. Recheck destinations afterward,\n        # including the no-op and final native precommit boundary (#704).\n        for path, content in before.items():\n            if _regular(path) != content:\n                raise ValueError(f"Artifact beforeimage changed: {path}")\n', '    def check_before() -> None:\n        for path in inputs:\n            _check_path(path)\n        check_journal_path()\n        # Hashing the sources may take time. Recheck destinations afterward,\n        # including the no-op and final native precommit boundary (#704).\n        for path, content in before.items():\n            if _regular(path) != content:\n                raise ValueError(f"Artifact beforeimage changed: {path}")\n        input_check()\n', 'tests/test_mim_sssom_artifacts.py::test_callback_output_drift_never_returns_complete_or_unchanged'), ('callback_after_final_guards', 'src/kg_microbe_utils/sssom_artifacts.py', '        input_check()\n        check_journal_path()\n        if _regular(result.journal_path) != journal_before_check:\n            raise ValueError(f"Completed recovery journal changed: {result.journal_path}")\n        for path, content in intended.items():\n            if _regular(path) != content:\n                raise ValueError(f"Artifact publication mismatch: {path}; journal={result.journal_path}")\n', '        check_journal_path()\n        if _regular(result.journal_path) != journal_before_check:\n            raise ValueError(f"Completed recovery journal changed: {result.journal_path}")\n        for path, content in intended.items():\n            if _regular(path) != content:\n                raise ValueError(f"Artifact publication mismatch: {path}; journal={result.journal_path}")\n        input_check()\n', 'tests/test_mim_sssom_artifacts.py::test_callback_output_drift_never_returns_complete_or_unchanged'), ('precommit_journal_check_before_callback', 'src/kg_microbe_utils/sssom_artifacts.py', '        input_check()\n        check_journal_path()\n        # Hashing', '        check_journal_path()\n        input_check()\n        # Hashing', 'tests/test_mim_sssom_artifacts.py::test_last_callback_cannot_redirect_or_change_the_recovery_journal'), ('unverified_journal_capture', 'src/kg_microbe_utils/sssom_artifacts.py', 'if journal_before_check != expected_journal_bytes:', 'if False:', 'tests/test_mim_sssom_artifacts.py::test_missing_or_incorrect_native_completion_journal_never_reports_success')])
results=[]
for name,target,old,new,selector in variants:
 root=DEST/name;root.mkdir()
 for folder in ('src','plugins'):
  shutil.copytree(SOURCE/folder,root/folder,ignore=shutil.ignore_patterns('__pycache__'))
 for f in ('pyproject.toml','tests/conftest.py','tests/test_mim_sssom_artifacts.py','scripts/publish_sssom.py'):
  dst=root/f;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(SOURCE/f,dst)
 if target:
  p=root/target;s=p.read_text();assert s.count(old)==1,(name,s.count(old));p.write_text(s.replace(old,new))
 env=dict(os.environ,PYTHONPATH=str(root/'src')+':'+str(root),PYTHONPYCACHEPREFIX=str(root/'bytecode'))
 proc=subprocess.run([sys.executable,'-m','pytest','-q',selector],cwd=root,env=env,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
 log=DEST/(name+'.log');log.write_text(proc.stdout)
 expected=0 if target is None else 1
 assert proc.returncode==expected,(name,proc.returncode,proc.stdout[-3000:])
 if target:assert 'FAILED ' in proc.stdout and 'ERROR collecting' not in proc.stdout
 results.append({'name':name,'target':target,'old':old,'new':new,'selector':selector,'exit_code':proc.returncode,'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest()})
 print(name,proc.returncode,proc.stdout.splitlines()[-1],flush=True)
assert frozen=={f:hashlib.sha256((SOURCE/f).read_bytes()).hexdigest() for f in files}
(DEST/'results.json').write_text(json.dumps({'completed_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'source_hashes':frozen,'results':results},indent=2)+'\n')
