"""Offline builder-to-native-publication regressions for Claw #701/#702."""

import csv
import gzip
import hashlib
import importlib.util
import io
import json
import os
import shutil
import subprocess
import sys
from contextlib import nullcontext
from pathlib import Path

import pytest
import yaml

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
SPEC = importlib.util.spec_from_file_location("owned_name_builder", SCRIPTS / "build_mim_ingredient_sssom.py")
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)
sssom_artifacts = (builder._ARTIFACT_PRODUCER if hasattr(builder, "_ARTIFACT_PRODUCER")
                   else importlib.import_module("kg_microbe_utils.sssom_artifacts"))


def write_record(directory, name="Subject", **changes):
    data = {
        "identifier": "CHEBI:1", "preferred_term": name, "mapping_status": "MAPPED",
        "ontology_mapping": {"ontology_id": "CHEBI:1", "ontology_label": name,
                             "mapping_quality": "EXACT_MATCH"},
        "curation_history": [{"timestamp": "2026-10-01T00:00:00Z"}],
    }
    data.update(changes)
    path = directory / f"{name}.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def read_rows(content):
    return list(csv.DictReader(io.StringIO("".join(
        line for line in content.decode().splitlines(keepends=True) if not line.startswith("#")
    )), delimiter="\t"))


def sidecar_rows(events):
    return list(csv.DictReader(io.StringIO(builder.render_suppressed_aliases(events).decode()), delimiter="\t"))


@pytest.mark.parametrize("origin", ["stored", "kg-name", "kg-synonym", "yaml", "pipe"])
def test_all_alias_inputs_use_complete_unsupported_owner_snapshot(tmp_path, origin):
    subject = write_record(tmp_path)
    write_record(tmp_path, "Owned", identifier="UNMAPPED_001", mapping_status="AMBIGUOUS",
                 ontology_mapping={})
    data = yaml.safe_load(subject.read_bytes())
    labels = {}
    if origin == "stored":
        data["ontology_mapping"]["ontology_label"] = "Owned"
    elif origin == "kg-name":
        labels = {"CHEBI:1": ("Owned", [])}
    elif origin == "kg-synonym":
        labels = {"CHEBI:1": ("Subject", ["Owned"])}
    else:
        data["synonyms"] = [{"synonym_text": "allowed| OWNED |still allowed" if origin == "pipe" else "Owned",
                             "synonym_type": "EXACT_SYNONYM"}]
    subject.write_text(yaml.safe_dump(data))
    events = []
    rows = builder._row_from_yaml(subject, {}, {}, labels, {"CHEBI:1": "Subject"}, suppressions=events)
    assert "owned" not in {x.strip().casefold() for x in rows[0]["other"].split("|")}
    suppressed = sidecar_rows(events)
    assert len(suppressed) == 1
    assert json.loads(suppressed[0]["owner_subject_ids"]) == ["MIM:Owned"]
    assert suppressed[0]["token_key"] == "owned"
    if origin == "pipe":
        assert rows[0]["other"] == "allowed|still allowed"


def test_one_pair_sidecar_unions_origins_and_preserves_unowned_order(tmp_path):
    subject = write_record(tmp_path, synonyms=[{"synonym_text": "Owned|first|FIRST|last", "synonym_type": "RAW_TEXT"}])
    write_record(tmp_path, "Owned")
    events = []
    rows = builder._row_from_yaml(subject, {}, {}, {"CHEBI:1": (" OWNED ", ["Owned", "first"])}, {}, suppressions=events)
    assert rows[0]["other"] == "first|last"
    sidecar = sidecar_rows(events)
    assert len(sidecar) == 1
    assert json.loads(sidecar[0]["input_surfaces"]) == ["kgmicrobe.canonical_name", "kgmicrobe.synonym", "mim.synonym"]
    assert json.loads(sidecar[0]["source_refs"])
    assert json.loads(sidecar[0]["evidence_refs"]) == sorted(builder.OWNED_NAME_EVIDENCE)


@pytest.mark.parametrize("quality", ["EXACT_MATCH", "CLOSE_MATCH", "NARROW_MATCH"])
def test_late_cas_and_direct_and_b1_registry_paths_are_filtered(tmp_path, quality):
    subject = write_record(tmp_path, identifier="cas:12-34-5", chemical_properties={"cas_rn": "12-34-5"},
                           ontology_mapping={"ontology_id": "CHEBI:2", "ontology_label": "Parent", "mapping_quality": quality})
    write_record(tmp_path, "CAS owner", preferred_term="CAS:12-34-5", ontology_mapping={})
    events = []
    rows = builder._row_from_yaml(subject, {}, {}, {}, {}, suppressions=events)
    assert len(rows) >= 2
    assert all("cas:12-34-5" not in row["other"].casefold() for row in rows)
    assert len(sidecar_rows(events)) == 1
    if quality == "NARROW_MATCH":
        assert any(r["object_id"] == "kgmicrobe.compound:subject" for r in rows)


def test_cap_does_not_hide_suppression_and_allowed_cas_stays_after_cap(tmp_path, monkeypatch):
    subject = write_record(tmp_path, synonyms=[{"synonym_text": "one|two|Owned|three", "synonym_type": "RAW_TEXT"}],
                           chemical_properties={"cas_rn": "12-34-5"})
    write_record(tmp_path, "Owned", ontology_mapping={})
    monkeypatch.setattr(builder, "MAX_OTHER_ENTRIES", 2)
    events = []
    rows = builder._row_from_yaml(subject, {}, {}, {}, {}, suppressions=events)
    assert rows[0]["other"] == "one|two|CAS:12-34-5"
    assert sidecar_rows(events)[0]["token_key"] == "owned"


def test_source_bound_rejection_is_not_a_suppression_or_kg_backdoor(tmp_path):
    subject = write_record(tmp_path, synonyms=[{"synonym_text": "Wrong|Also wrong", "synonym_type": "REJECTED_LABEL"}])
    events = []
    rows = builder._row_from_yaml(subject, {}, {}, {"CHEBI:1": ("Wrong", ["ALSO WRONG", "safe"])}, {}, suppressions=events)
    assert rows[0]["other"] == "safe"
    assert events == []


def test_owner_index_is_fresh_each_direct_call_and_malformed_owner_refuses(tmp_path):
    subject = write_record(tmp_path, synonyms=[{"synonym_text": "Owned", "synonym_type": "RAW_TEXT"}])
    assert builder._row_from_yaml(subject, {}, {}, {}, {})[0]["other"] == "Owned"
    owner = write_record(tmp_path, "Owned", ontology_mapping={})
    assert builder._row_from_yaml(subject, {}, {}, {}, {})[0]["other"] == ""
    owner.write_text("- not a record\n")
    with pytest.raises(ValueError, match="not a mapping"):
        builder._row_from_yaml(subject, {}, {}, {}, {})


@pytest.fixture
def cli(tmp_path, monkeypatch):
    root = tmp_path / "mim"
    records = root / "data/ingredients/mapped"
    records.mkdir(parents=True)
    write_record(records, synonyms=[{"synonym_text": "Owned|safe", "synonym_type": "EXACT_SYNONYM"}])
    write_record(records, "Owned", ontology_mapping={})
    canonical = root / "mappings/published.tsv"
    canonical.parent.mkdir()
    canonical.write_text("subject_id\tpredicate_id\tobject_id\tvalidation_method\n"
                         "MIM:Subject\tskos:exactMatch\tCHEBI:1\tprior-reviewed-stamp\n")
    kgm = tmp_path / "kgm.tsv.gz"
    kgm.write_bytes(gzip.compress(
        b"subject_id\tsubject_label\tpredicate_id\tobject_id\tobject_label\tsource\n"
        b"x:1\tOwned\tskos:exactMatch\tCHEBI:1\tSubject\tsource-a\n", mtime=0))
    residual = tmp_path / "residual.json"
    output = tmp_path / "artifacts/candidate.tsv"
    monkeypatch.setattr(builder, "MIM_ROOT", root)
    monkeypatch.setattr(builder, "MIM_INGREDIENTS_DIR", records)
    monkeypatch.setattr(builder, "MIM_PUBLISHED_SSSOM", canonical)
    monkeypatch.setattr(builder, "KGM_UNIFIED_TSV", kgm)
    monkeypatch.setattr(builder, "RESIDUAL_JSON", residual)
    monkeypatch.setattr(builder, "require_mech_roots", lambda *a, **kw: None)
    monkeypatch.setattr(builder, "_load_chebi_labels", lambda *a: {"CHEBI:1": "Subject"})
    monkeypatch.setattr(builder, "_sssom_validate", lambda path: [])

    class FixtureLock:
        def lock(self, *args):
            return nullcontext()

    # Only repository identity/lease transport is adapted; stage/validation/
    # journal/publication use the actual native transaction.
    monkeypatch.setattr(sssom_artifacts, "_load_lock_manager", lambda root: FixtureLock)

    def run(*flags, destination=output):
        monkeypatch.setattr(sys, "argv", ["builder", "--identity-mode", "legacy", "--output", str(destination), *flags])
        builder.main()
        return builder.artifact_paths(destination)

    return {"run": run, "records": records, "canonical": canonical, "kgm": kgm,
            "residual": residual, "output": output, "root": root}


def test_native_cli_publishes_bound_triplet_and_replays_frozen_stamps(cli):
    output, sidecar, manifest = cli["run"]()
    row = read_rows(output.read_bytes())[0]
    assert row["other"] == "safe"
    assert row["validation_method"] == "prior-reviewed-stamp"
    assert builder.POLICY_MARKER in output.read_text()
    report = json.loads(manifest.read_bytes())
    assert report["external_sssom_validation"] == "passed"
    assert report["scope"].startswith("diagnostic candidate")
    for artifact in report["artifacts"]:
        assert hashlib.sha256(Path(artifact["path"]).read_bytes()).hexdigest() == artifact["sha256"]
    assert len(list(csv.DictReader(io.StringIO(sidecar.read_text()), delimiter="\t"))) == 1
    source_rows = {item["path"]: item["sha256"] for item in report["source_inputs"]}
    assert source_rows[str(cli["canonical"])] == hashlib.sha256(cli["canonical"].read_bytes()).hexdigest()
    assert source_rows[str(cli["residual"])] is None


def test_no_validate_skips_only_external_validator(cli, monkeypatch):
    monkeypatch.setattr(builder, "_sssom_validate", lambda path: pytest.fail("external validator invoked"))
    output, sidecar, manifest = cli["run"]("--no-validate")
    assert "Owned" not in read_rows(output.read_bytes())[0]["other"]
    assert sidecar.exists()
    assert json.loads(manifest.read_bytes())["external_sssom_validation"] == "skipped_explicitly"


def test_working_copy_beforeimage_and_sidecar_refresh_are_not_tsv_only_noop(cli):
    paths = cli["run"]()
    # The first refresh records the newly available working-copy stamp input.
    cli["run"]()
    settled = [p.read_bytes() for p in paths]
    cli["run"]()
    assert [p.read_bytes() for p in paths] == settled
    paths[1].write_text("stale sidecar\n")
    cli["run"]()
    assert [p.read_bytes() for p in paths] == settled


@pytest.mark.parametrize("kind", ["record", "added-owner", "removed-owner", "kgm", "canonical", "residual-created"])
def test_native_precommit_rejects_input_drift_with_prior_artifacts_preserved(cli, monkeypatch, kind):
    paths = cli["run"]()
    before = [p.read_bytes() for p in paths]
    native = sssom_artifacts.ValidatedWriteTransaction

    class Drift(native):
        def commit(self, **kwargs):
            if kind == "record":
                path = cli["records"] / "Subject.yaml"
                path.write_bytes(path.read_bytes() + b"# drift\n")
            elif kind == "added-owner":
                write_record(cli["records"], "New owner", ontology_mapping={})
            elif kind == "removed-owner":
                (cli["records"] / "Owned.yaml").unlink()
            elif kind == "residual-created":
                cli["residual"].write_text('{"decisions": []}')
            else:
                path = cli[kind]
                path.write_bytes(path.read_bytes() + b"drift")
            return super().commit(**kwargs)

    monkeypatch.setattr(sssom_artifacts, "ValidatedWriteTransaction", Drift)
    with pytest.raises(Exception, match="changed during generation"):
        cli["run"]()
    assert [p.read_bytes() for p in paths] == before


def test_staged_validator_failure_and_tampering_preserve_all_artifacts(cli, monkeypatch):
    paths = cli["run"]()
    before = [p.read_bytes() for p in paths]
    monkeypatch.setattr(builder, "_sssom_validate", lambda path: ["arbitrary failure"])
    with pytest.raises(ValueError, match="validation FAILED"):
        cli["run"]()
    assert [p.read_bytes() for p in paths] == before

    def alter(path):
        path.write_bytes(path.read_bytes() + b"unexpected\n")
        return []

    monkeypatch.setattr(builder, "_sssom_validate", alter)
    with pytest.raises(ValueError, match="changed during validation"):
        cli["run"]()
    assert [p.read_bytes() for p in paths] == before


@pytest.mark.parametrize("target", ["canonical", "kgm", "record"])
def test_protected_source_output_alias_refuses_before_write(cli, target):
    path = cli["records"] / "Subject.yaml" if target == "record" else cli[target]
    before = path.read_bytes()
    with pytest.raises(ValueError, match="protected source"):
        cli["run"](destination=path)
    assert path.read_bytes() == before


def test_sidecar_input_alias_refuses_before_write(cli):
    before = cli["canonical"].read_bytes()
    with pytest.raises(ValueError):
        cli["run"]("--suppressed-aliases-output", str(cli["canonical"]))
    assert cli["canonical"].read_bytes() == before
    assert not cli["output"].exists()


@pytest.mark.parametrize(("returncode", "stderr", "fails"), [
    (0, "", False), (0, "informational warning", False),
    (0, "is not well-formed", True), (2, "arbitrary validator failure", True), (1, "", True),
])
def test_external_validator_returncode_is_authoritative(monkeypatch, tmp_path, returncode, stderr, fails):
    monkeypatch.setattr(builder.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, returncode, "", stderr))
    assert bool(builder._sssom_validate(tmp_path / "candidate.tsv")) is fails


def test_frozen_kgm_consumption_survives_transient_source_replacement(cli, monkeypatch):
    original_bytes = cli["kgm"].read_bytes()
    source_loader = builder.load_kgm_source_index
    label_loader = builder.load_kgm_labels
    observed = []

    def sources(path):
        observed.append(path)
        cli["kgm"].write_bytes(gzip.compress(gzip.decompress(original_bytes).replace(b"Owned", b"Injected"), mtime=0))
        return source_loader(path)

    def labels(path):
        observed.append(path)
        result = label_loader(path)
        cli["kgm"].write_bytes(original_bytes)
        return result

    monkeypatch.setattr(builder, "load_kgm_source_index", sources)
    monkeypatch.setattr(builder, "load_kgm_labels", labels)
    output, _, _ = cli["run"]()
    assert observed[0] == observed[1] and observed[0] != cli["kgm"]
    assert "Injected" not in output.read_text()


def test_mapped_yaml_is_parsed_once_per_record(cli, monkeypatch):
    parse = builder.yaml.safe_load
    parsed = []

    def count(content):
        parsed.append(content)
        return parse(content)

    monkeypatch.setattr(builder.yaml, "safe_load", count)
    cli["run"]()
    assert len(parsed) == len(list(cli["records"].glob("*.yaml")))


def test_precommit_code_input_drift_refuses(cli, monkeypatch, tmp_path):
    control = tmp_path / "producer-control.py"
    control.write_text("# original producer bytes\n")
    inventory = builder._producer_paths()
    monkeypatch.setattr(builder, "_producer_paths", lambda: (*inventory, control))
    monkeypatch.setattr(builder, "_IMPORTED_PRODUCER_BYTES", {
        **builder._IMPORTED_PRODUCER_BYTES, control: control.read_bytes(),
    })
    native = sssom_artifacts.ValidatedWriteTransaction

    class Drift(native):
        def commit(self, **kwargs):
            control.write_text("# changed producer bytes\n")
            return super().commit(**kwargs)

    monkeypatch.setattr(sssom_artifacts, "ValidatedWriteTransaction", Drift)
    with pytest.raises(Exception, match="Producer source bytes changed"):
        cli["run"]()
    assert not cli["output"].exists()


@pytest.mark.parametrize("shape", ["dotdot", "symlink", "symlink-dotdot"])
def test_lexical_prior_stamp_alias_refuses_before_output_write(cli, shape):
    before = cli["canonical"].read_bytes()
    if shape == "dotdot":
        source = cli["canonical"].parent / ".." / "mappings" / cli["canonical"].name
    else:
        link = cli["root"] / "linked-mappings"
        link.symlink_to(cli["canonical"].parent, target_is_directory=True)
        source = link / cli["canonical"].name
        if shape == "symlink-dotdot":
            source = link / ".." / "mappings" / cli["canonical"].name
    with pytest.raises(ValueError):
        cli["run"]("--prior-stamps-from", str(source))
    assert not cli["output"].exists()
    assert cli["canonical"].read_bytes() == before


@pytest.mark.parametrize("quality", ["EXACT_MATCH", "CLOSE_MATCH", "NARROW_MATCH"])
@pytest.mark.parametrize("eligible", [False, True])
def test_rejected_cas_precedes_ownership_on_every_emitted_path(tmp_path, quality, eligible):
    subject = write_record(
        tmp_path, identifier="cas:12-34-5", chemical_properties={"cas_rn": "12-34-5"},
        ontology_mapping={"ontology_id": "CHEBI:2", "ontology_label": "Parent", "mapping_quality": quality},
        synonyms=[] if eligible else [{"synonym_text": "cas:12-34-5", "synonym_type": "REJECTED_LABEL"}],
    )
    write_record(tmp_path, "CAS owner", preferred_term="CAS:12-34-5", ontology_mapping={})
    events = []
    rows = builder._row_from_yaml(subject, {}, {}, {}, {}, suppressions=events)
    assert all("cas:12-34-5" not in row["other"].casefold() for row in rows)
    assert len(rows) >= 2
    if quality == "NARROW_MATCH":
        assert len(rows) == 3
    if eligible:
        assert sidecar_rows(events)[0]["token_key"] == "cas:12-34-5"
    else:
        assert events == []
        assert sidecar_rows(events) == []


def test_subject_owned_eligible_cas_remains_published(tmp_path):
    subject = write_record(tmp_path, preferred_term="CAS:12-34-5", chemical_properties={"cas_rn": "12-34-5"})
    events = []
    rows = builder._row_from_yaml(subject, {}, {}, {}, {}, suppressions=events)
    assert rows[0]["other"] == "CAS:12-34-5"
    assert events == []


def isolated_producer_probe(tmp_path, mode):
    """Real fresh import/generation; only repository identity/lease is adapted."""
    fixture = tmp_path / "producer"
    (fixture / "scripts").mkdir(parents=True)
    for name in ("build_mim_ingredient_sssom.py", "kgm_unified_mappings.py"):
        shutil.copyfile(SCRIPTS / name, fixture / "scripts" / name)
    for package in ("kg_microbe_utils", "kg_microbe_write", "kg_microbe_fleet"):
        shutil.copytree(SCRIPTS.parent / "src" / package, fixture / "src" / package,
                        ignore=shutil.ignore_patterns("__pycache__"))
    (fixture / "plugins").mkdir()
    shutil.copyfile(SCRIPTS.parent / "plugins/lock_manager.py", fixture / "plugins/lock_manager.py")
    probe = tmp_path / "probe.py"
    probe.write_text(r'''
from pathlib import Path
import builtins, contextlib, hashlib, importlib.util, json, os, py_compile, shutil, sys
import yaml
root=Path(sys.argv[1]); mode=sys.argv[2]
sys.path[:0]=[str(root/'scripts'),str(root/'src')]
policy=root/'src/kg_microbe_utils/owned_name_policy.py'
original=policy.read_bytes()
import kg_microbe_fleet as public_fleet
public_fleet_before=id(public_fleet)
preloaded_policy=None
if mode in {'same-origin-preloaded','lazy-public-contamination'}:
    import kg_microbe_utils.owned_name_policy as preloaded_policy
    if mode=='same-origin-preloaded':
        policy.write_bytes(original+b'\ndef filter_owned_aliases(subject_id, candidates, owners):\n    return tuple(candidates), ()\n')
    else:
        preloaded_policy.SIDECAR_COLUMNS=('incorrect-public-columns',)
if mode=='stale-pyc':
    metadata=policy.stat()
    py_compile.compile(str(policy),doraise=True)
    changed=original.replace(b'not holders',b'True       ',1)
    assert len(changed)==len(original) and changed!=original
    policy.write_bytes(changed)
    os.utime(policy,ns=(metadata.st_atime_ns,metadata.st_mtime_ns))
if mode=='undeclared-local':
    (policy.parent/'unlisted.py').write_text('anything=1\n')
    policy.write_bytes(original+b'\nfrom kg_microbe_utils.unlisted import anything\n')
if mode=='wrong-origin':
    foreign=root.parent/'foreign'
    shutil.copytree(root/'src/kg_microbe_utils', foreign/'kg_microbe_utils')
    sys.path.insert(0,str(foreign))
    import kg_microbe_utils.owned_name_policy
    sys.path.remove(str(foreign))
original_compile=builtins.compile
fired=False

def controlled_compile(source, filename, *args, **kwargs):
    global fired
    code=original_compile(source,filename,*args,**kwargs)
    if filename==str(policy) and not fired:
        fired=True
        if mode=='during-import-bytes':policy.write_bytes(original+b'\n# import-boundary drift\n')
        if mode=='during-import-remove':policy.unlink()
        if mode=='during-import-pathset':(policy.parent/'added_producer.py').write_text('# new producer\n')
    return code
builtins.compile=controlled_compile
output=root.parent/'artifacts/candidate.tsv'
try:
    spec=importlib.util.spec_from_file_location('fixture_builder',root/'scripts/build_mim_ingredient_sssom.py')
    b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
    builtins.compile=original_compile
    if mode=='before-main':policy.write_bytes(original+b'\n# post-import drift\n')
    records=root.parent/'records';records.mkdir()
    for name in ['Subject','Owned']:
        data={'identifier':'CHEBI:1','preferred_term':name,'mapping_status':'MAPPED',
              'ontology_mapping':{'ontology_id':'CHEBI:1','ontology_label':name,'mapping_quality':'EXACT_MATCH'},
              'curation_history':[{'timestamp':'2026-10-01T00:00:00Z'}]}
        if name=='Subject':data['synonyms']=[{'synonym_text':'Owned','synonym_type':'EXACT_SYNONYM'}]
        (records/(name+'.yaml')).write_text(yaml.safe_dump(data))
    b.MIM_ROOT=root.parent/'mim';b.MIM_INGREDIENTS_DIR=records
    b.MIM_PUBLISHED_SSSOM=root.parent/'canonical-absent.tsv'
    b.KGM_UNIFIED_TSV=root.parent/'kgm-absent.tsv.gz';b.RESIDUAL_JSON=root.parent/'residual-absent.json'
    b.require_mech_roots=lambda *a,**kw: None
    b._load_chebi_labels=lambda *a:{'CHEBI:1':'Subject'}
    artifacts=b._ARTIFACT_PRODUCER if hasattr(b,"_ARTIFACT_PRODUCER") else importlib.import_module("kg_microbe_utils.sssom_artifacts")
    class FixtureLock:
        def lock(self,*a):return contextlib.nullcontext()
    if mode!='native-lock':
        artifacts._load_lock_manager=lambda root:FixtureLock
    else:
        os.environ['OPENCLAW_WORKSPACE']=str(root.parent/'native-workspace')
    sys.argv=['builder','--identity-mode','legacy','--no-validate','--output',str(output)]
    b.main()
    manifest=json.loads(output.with_suffix('.tsv.manifest.json').read_bytes())
    result={'status':'published','bound_policy_hash':manifest.get('producer_import_snapshot', {x['path']:x['sha256'] for x in manifest['source_inputs']})[str(policy)],
            'actual_policy_hash':hashlib.sha256(policy.read_bytes()).hexdigest(),
            'other_cells':[line.split('\t')[11] for line in output.read_text().splitlines() if line.startswith('MIM:')],
            'public_fleet_preserved':id(sys.modules['kg_microbe_fleet'])==public_fleet_before,
            'public_policy_preserved':preloaded_policy is None or sys.modules['kg_microbe_utils.owned_name_policy'] is preloaded_policy}
    if mode=='native-lock':
        result['native_lock_uses_snapshot_fleet']=(b._PRODUCER_MODULES['claw_lock_manager'].UniqueKeySafeLoader is b._PRODUCER_MODULES['kg_microbe_fleet'].UniqueKeySafeLoader)
except Exception as exc:
    result={'status':'refused','error':str(exc),'exception':type(exc).__name__}
finally:
    builtins.compile=original_compile
result['output_exists']=output.exists()
print('PROBE_RESULT='+json.dumps(result,sort_keys=True))
''')
    environment = dict(os.environ, PYTHONPATH=str(fixture / "src"),
                       PYTHONDONTWRITEBYTECODE="1", PYTHONPYCACHEPREFIX=str(tmp_path / "cache"))
    result = subprocess.run([sys.executable, str(probe), str(fixture), mode], env=environment,
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    line = next(line for line in result.stdout.splitlines() if line.startswith("PROBE_RESULT="))
    return json.loads(line.removeprefix("PROBE_RESULT="))


def test_import_snapshot_positive_generates_with_matching_source_hash(tmp_path):
    result = isolated_producer_probe(tmp_path, "positive")
    assert result["status"] == "published", result
    assert result["bound_policy_hash"] == result["actual_policy_hash"]


@pytest.mark.parametrize(("mode", "message"), [
    ("before-main", "Producer source bytes changed"),
    ("during-import-bytes", "Producer source bytes changed"),
    ("during-import-pathset", "Producer path set changed"),
    ("during-import-remove", "Producer path set changed"),
    ("wrong-origin", "Imported producer origin differs"),
])
def test_import_snapshot_drift_and_foreign_cached_module_refuse(tmp_path, mode, message):
    result = isolated_producer_probe(tmp_path, mode)
    assert result["status"] == "refused", result
    assert message in result["error"]
    assert result["output_exists"] is False


@pytest.mark.parametrize("mode", ["same-origin-preloaded", "stale-pyc"])
def test_captured_source_wins_over_same_origin_cache_and_stale_bytecode(tmp_path, mode):
    result = isolated_producer_probe(tmp_path, mode)
    assert result["status"] == "published", result
    assert result["bound_policy_hash"] == result["actual_policy_hash"]
    assert "Owned" in result["other_cells"]
    assert result["public_fleet_preserved"] and result["public_policy_preserved"]


@pytest.mark.parametrize("mode", ["lazy-public-contamination", "native-lock"])
def test_lazy_policy_and_native_lock_use_the_same_source_snapshot(tmp_path, mode):
    result = isolated_producer_probe(tmp_path, mode)
    assert result["status"] == "published", result
    assert result["bound_policy_hash"] == result["actual_policy_hash"]
    assert result["public_fleet_preserved"] and result["public_policy_preserved"]
    if mode == "native-lock":
        assert result["native_lock_uses_snapshot_fleet"]


def test_undeclared_local_import_refuses_even_when_file_was_snapshotted(tmp_path):
    result = isolated_producer_probe(tmp_path, "undeclared-local")
    assert result["status"] == "refused", result
    assert "Undeclared local producer dependency" in result["error"]
    assert result["output_exists"] is False
