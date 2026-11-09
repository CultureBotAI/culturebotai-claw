from pathlib import Path
import yaml,shlex,subprocess,sys,json,hashlib,ast
HERE=Path(__file__).resolve().parent;RUN=HERE.parents[1];ROOT=RUN/'claw-owned-name'
p=ROOT/'.github/workflows/tests.yaml';workflow=yaml.safe_load(p.read_text());commands=[step['run'] for job in workflow['jobs'].values() for step in job['steps'] if step.get('name')=='Type-check safety-critical modules'];assert len(commands)==1
argv=shlex.split(commands[0]);assert argv[:5]==['uv','run','--extra','dev','mypy'];assert 'src/kg_microbe_utils/owned_name_policy.py' in argv and 'src/kg_microbe_utils/sssom_artifacts.py' in argv
actual=[sys.executable,'-m','mypy',*argv[5:]];result=subprocess.run(actual,cwd=ROOT,capture_output=True,text=True)
# The exact new regression must reject the prior maintained workflow.
test=ROOT/'tests/test_mim_sssom_artifacts.py';tree=ast.parse(test.read_text());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='test_ci_actually_type_checks_both_artifact_policy_helpers')
fixture=HERE/'prior-ci-fixture';(fixture/'.github/workflows').mkdir(parents=True);old=subprocess.check_output(['git','show','e78e220d153e41d4340ad0f8abfbd83d96d01b57:.github/workflows/tests.yaml'],cwd=ROOT);(fixture/'.github/workflows/tests.yaml').write_bytes(old)
ns={'ROOT':fixture,'yaml':yaml,'shlex':shlex};exec(compile(ast.Module(body=[fn],type_ignores=[]),str(test),'exec'),ns)
try:ns[fn.name]();red=False
except AssertionError:red=True
proof={'workflow_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'exact_maintained_run':commands[0],'runtime_translation':'Use the maintained already-installed Python interpreter -m mypy; no install/network/provider calls. Module selection/options are unchanged.','argv':actual,'exit_code':result.returncode,'stdout':result.stdout,'stderr':result.stderr,'prior_workflow_sha256':hashlib.sha256(old).hexdigest(),'exact_regression_rejects_prior_workflow':red}
(HERE/'ci-gate-result.json').write_text(json.dumps(proof,indent=2)+'\n');print(json.dumps(proof,indent=2));assert result.returncode==0 and red
