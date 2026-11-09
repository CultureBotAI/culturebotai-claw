"""Observe native SSSOM generation in an isolated copy, with exact input receipts."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
import subprocess
import sys

from plugins.repository_settings import RepositorySettings

RUN = Path(__file__).resolve().parent
if len(sys.argv) != 5:
    raise SystemExit("usage: generate_candidate.py MIM_CHILD CLAW_CHILD NEW_OUTPUT_CHILD PRIOR_STAMPS")
step, producer, name, prior_arg = sys.argv[1:]
assert all(Path(value).name == value and value not in (".", "..") for value in (step, producer, name))
mim = RUN / step
claw = RUN / producer
prior = Path(prior_arg).resolve()
assert prior.is_file()
settings = RepositorySettings.from_environment()
assert settings.get_target("mediaingredientmech").path == mim.resolve()
kg = Path(os.environ["KGMICROBE_ROOT"]).resolve()
assert kg == (RUN.parent.parent / "../../KG-Hub/KG-Microbe/kg-microbe").resolve()
culture = settings.get_target("culturemech").path
def git(root, *args):
    return subprocess.check_output(["git", "-C", str(root), *args], text=True).strip()
assert not git(claw, "status", "--porcelain", "--untracked-files=all"), "producer must be clean"
out = mim / "output" / name
out.mkdir(parents=True, exist_ok=False)
candidate = out / "candidate.sssom.tsv"
residual = claw / "workspace/reports/kg_microbe_residual_p25_categorized.json"

def sha(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(8 * 1024 * 1024):
            result.update(chunk)
    return result.hexdigest()

def snapshot():
    paths = list((mim / "data/ingredients/mapped").glob("*.yaml"))
    paths += [prior, claw / "scripts/build_mim_ingredient_sssom.py", claw / "scripts/kgm_unified_mappings.py",
              kg / "mappings/kgmicrobe_unified_entity_mappings.sssom.tsv.gz"]
    paths += [claw / name for name in (
        "src/kg_microbe_utils/owned_name_policy.py", "src/kg_microbe_utils/sssom_artifacts.py",
        "src/kg_microbe_write/transaction.py", "plugins/lock_manager.py", "uv.lock", "pyproject.toml")]
    paths += list((Path(os.environ["PYSTOW_HOME"]) / "oaklib").glob("*.db"))
    if residual.is_file():
        paths.append(residual)
    return {str(path.resolve()): {"sha256": sha(path), "bytes": path.stat().st_size}
            for path in sorted(set(paths))}

def emit(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")

def comparison_snapshot():
    paths = [culture / "output" / name for name in
             ("ingredients_list.tsv", "ingredient_occurrences.tsv", "mapped_ingredients.yaml", "unmapped_ingredients.yaml")]
    paths.append(kg / "data/transformed/mediadive/nodes.tsv")
    return {str(path): {"sha256": sha(path), "bytes": path.stat().st_size,
                       "role": "comparison input only; not consumed by raw SSSOM builder"}
            for path in paths}

# The current builder owns its native publication lock; do not nest the same lease.
if __name__ == "__main__":
    before = snapshot()
    comparisons = comparison_snapshot()
    repositories = {}
    for key, root in (("mim", mim), ("claw", claw), ("kg_microbe", kg), ("culturemech", culture)):
        assert Path(git(root, "rev-parse", "--show-toplevel")).resolve() == root.resolve()
        repositories[key] = {"path": str(root), "revision": git(root, "rev-parse", "HEAD"),
            "origin": git(root, "remote", "get-url", "origin"),
            "branch": git(root, "branch", "--show-current"), "status": git(root, "status", "--porcelain"),
            "tracked_diff_sha256": hashlib.sha256(git(root, "diff", "--binary", "HEAD").encode()).hexdigest()}
    emit(out / "inputs-before.json", before)
    emit(out / "comparison-inputs.json", comparisons)
    emit(out / "repository-context.json", repositories)
    sys.path.insert(0, str(claw / "scripts"))
    spec = importlib.util.spec_from_file_location("observed_native_sssom", claw / "scripts/build_mim_ingredient_sssom.py")
    module = importlib.util.module_from_spec(spec)
    entry_source = (claw / "scripts/build_mim_ingredient_sssom.py").read_bytes()
    entry_sha256 = hashlib.sha256(entry_source).hexdigest()
    assert entry_sha256 == before[str((claw / "scripts/build_mim_ingredient_sssom.py").resolve())]["sha256"]
    sys.modules[spec.name] = module
    # Execute the exact recorded entry bytes, bypassing any timestamp-valid pyc.
    # Dependent producer code is loaded from the builder's own frozen snapshot.
    exec(compile(entry_source, str(claw / "scripts/build_mim_ingredient_sssom.py"), "exec"), module.__dict__)
    labels = []
    # Observe the native loader's returned map without substituting its results.
    for loader_name in ("_load_chebi_labels", "_load_ols_labels"):
        original = getattr(module, loader_name)
        def observed(*args, _original=original, _name=loader_name, **kwargs):
            result = _original(*args, **kwargs)
            record = {"loader": _name, "args": args, "kwargs": kwargs, "labels": result,
                      "accessed_at": datetime.now(timezone.utc).isoformat()}
            labels.append(record)
            emit(out / ("label-input-%02d.json" % len(labels)), record)
            return result
        setattr(module, loader_name, observed)
    sys.argv = [str(claw / "scripts/build_mim_ingredient_sssom.py"), "--output", str(candidate),
                "--prior-stamps-from", str(prior)]
    module.main()
    after = snapshot()
    emit(out / "inputs-after.json", after)
    assert before == after, "generation input bytes changed"
    assert comparison_snapshot() == comparisons, "comparison input bytes changed"
    assert not git(claw, "status", "--porcelain", "--untracked-files=all")
    receipt = {"timestamp": datetime.now(timezone.utc).isoformat(), "candidate": str(candidate),
        "candidate_sha256": sha(candidate),
        "sidecar_sha256": sha(out / "suppressed_aliases.tsv"),
        "native_generation_manifest_sha256": sha(candidate.with_suffix(candidate.suffix + ".manifest.json")),
        "prior_stamps": str(prior), "prior_sha256": sha(prior),
        "executed_entry_source_sha256": entry_sha256,
        "producer_revision": repositories["claw"]["revision"], "producer_sha256": sha(claw / "scripts/build_mim_ingredient_sssom.py"),
        "harness_sha256": sha(Path(__file__)), "input_manifest_sha256": sha(out / "inputs-before.json"),
        "label_maps": {str(path.name): sha(path) for path in sorted(out.glob("label-input-*.json"))},
        "optional_residual": {"path": str(residual), "present": residual.is_file()},
        "comparison_input_scope": "CultureMech outputs and Mediadive nodes are not imported by this SSSOM producer.",
        "input_bytes_unchanged": True, "scientific_approval_added": False, "supervisor_binding": None}
    emit(out / "generation-receipt.json", receipt)
    print(json.dumps(receipt, indent=2))
