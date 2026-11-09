"""Offline native-boundary regressions for Claw #699.

HTTP responses here are synthetic counterexamples, not claims about current
PubChem responses. Fixtures never mutate the sibling Mech repositories.
"""
from __future__ import annotations

import copy
import csv
import importlib.util
import io
import json
import os
import re
import sys
from functools import partial
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

SCRIPTS = Path(os.environ.get("CLAW_LEGACY_TEST_SCRIPTS", Path(__file__).resolve().parents[1] / "scripts"))
BAD = "CHEBI:48601"
NAMES = ("Carnitine Hydrochloride", "Carnitine (Dl) Hydrochloride")
CASES = [(name, cas) for name in NAMES for cas in (None, "461-06-3", "461-05-2")]
CONTROLS = (("carnitinamide chloride", None), ("DL-carnitine", None),
            ("L-carnitine hydrochloride", None), ("unrelated salt", "1-00-0"))


def load(name):
    spec = importlib.util.spec_from_file_location(f"legacy_699_{name}", SCRIPTS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def record(name, cas=None, identifier="UNMAPPED_699"):
    result = {"identifier": identifier, "preferred_term": name,
              "mapping_status": "UNMAPPED", "curation_history": [],
              "ontology_mapping": {"ontology_id": "CHEBI:91318"}}
    if cas:
        result["chemical_properties"] = {"cas_rn": cas}
    return result


def write_yaml(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return path.read_bytes()


def json_response(data):
    return io.BytesIO(json.dumps(data).encode())


def http_sequence(monkeypatch, module, responses):
    pending = iter(responses)
    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *a, **k: json_response(next(pending)))


def setup_main(monkeypatch, module, tmp_path, args=()):
    monkeypatch.setattr(sys, "argv", [module.__name__, *args])
    monkeypatch.setattr(module, "require_mech_roots", lambda *a, **k: None)
    if hasattr(module, "time"):
        monkeypatch.setattr(module.time, "sleep", lambda *a: None)
    for attr in ("REPO_ROOT", "MIM_ROOT", "WORKSPACE", "OUT_DIR", "CULTUREBOT_ROOT"):
        if hasattr(module, attr):
            monkeypatch.setattr(module, attr, tmp_path)
    for attr in ("OUT_TSV", "OUT_MD", "SUMMARY_MD", "CACHE_PATH", "PUBCHEM_CACHE", "OLS_CACHE", "QUEUE_TSV", "QUEUE_MD"):
        if hasattr(module, attr):
            monkeypatch.setattr(module, attr, tmp_path / f"{attr.lower()}.out")


@pytest.mark.parametrize("cached", [True, False])
def test_pubchem_pair_cache_and_fresh_rejected_without_cache_erasure(monkeypatch, capsys, cached):
    module = load("cas_chebi_lookup_pubchem")
    cache = {"461-05-2": BAD} if cached else {}
    http_sequence(monkeypatch, module, [
        {"InformationList": {"Information": [{"CID": [5970]}]}},
        {"InformationList": {"Information": [{"Synonym": [BAD]}]}},
    ])
    assert module.pubchem_cas_to_chebi("461-05-2", cache) is None
    assert cache == {"461-05-2": BAD}
    assert "Rejected CHEBI:48601" in capsys.readouterr().out


def test_pubchem_filter_continues_to_unrelated_candidate(monkeypatch):
    module = load("cas_chebi_lookup_pubchem")
    http_sequence(monkeypatch, module, [
        {"InformationList": {"Information": [{"CID": [5970]}]}},
        {"InformationList": {"Information": [{"Synonym": [BAD, "CHEBI:17126"]}]}},
    ])
    assert module.pubchem_cas_to_chebi("461-05-2", {}) == "CHEBI:17126"
    assert module.pubchem_cas_to_chebi("1-00-0", {"1-00-0": BAD}) == BAD


@pytest.mark.parametrize("cached", [True, False])
@pytest.mark.parametrize("lookup,value", [("cas", "461-05-2"), *(('name', name) for name in NAMES)])
def test_legacy_ols_cache_and_fresh_return_explicit_rejection(monkeypatch, cached, lookup, value):
    module = load("integrate_culturebotht_ingredients")
    candidate = {"chebi": BAD, "label": "carnitinamide chloride", "synonyms": [value]}
    cache = {f"{lookup}::{value}": candidate} if cached else {}
    before = copy.deepcopy(cache)
    http_sequence(monkeypatch, module, [{"response": {"docs": [
        {"obo_id": BAD, "label": "carnitinamide chloride", "synonym": [value]}]}}])
    result = getattr(module, f"search_ols_by_{lookup}")(value, cache)
    assert result["chebi"] == BAD
    assert "rejected" in result["error"]
    if cached:
        assert cache == before


@pytest.mark.parametrize("script", ["cas_chebi_lookup_pubchem", "integrate_culturebotht_ingredients", "apply_mim_chebi_fixes"])
@pytest.mark.parametrize("name,cas", CASES)
def test_direct_creators_refuse_reviewed_names_before_write(tmp_path, script, name, cas):
    module = load(script)
    path = tmp_path / "owner.yaml"
    if script == "cas_chebi_lookup_pubchem":
        result = module._create_yaml(path, name, BAD, "amide target label", cas, [], "fixture")
    elif script == "integrate_culturebotht_ingredients":
        result = module._create_yaml(path, name, BAD, "amide target label", cas, [], [], "")
    else:
        result = module._create_new_yaml(path, f"cas:{cas}" if cas else "kgmicrobe.compound:fixture", name, BAD, "amide target label")
    assert result[0] is False
    assert "rejected" in result[1]
    assert not path.exists()


@pytest.mark.parametrize("script", ["cas_chebi_lookup_pubchem", "integrate_culturebotht_ingredients", "apply_mim_chebi_fixes"])
def test_direct_creator_legitimate_amide_and_existing_noop(tmp_path, script):
    module = load(script)
    path = tmp_path / "owner.yaml"
    if script == "cas_chebi_lookup_pubchem":
        call = partial(module._create_yaml, path, "carnitinamide chloride", BAD, "amide", "1-00-0", [], "fixture")
    elif script == "integrate_culturebotht_ingredients":
        call = partial(module._create_yaml, path, "carnitinamide chloride", BAD, "amide", "1-00-0", [], [], "")
    else:
        call = partial(module._create_new_yaml, path, "kgmicrobe.compound:amide", "carnitinamide chloride", BAD, "amide")
    assert call()[0] is True
    before = path.read_bytes()
    assert call()[0] is False
    assert path.read_bytes() == before


@pytest.mark.parametrize("apply", [False, True])
def test_oak_cache_main_does_not_count_rejected_pair_as_hit(tmp_path, monkeypatch, capsys, apply):
    module = load("cas_chebi_lookup_pubchem")
    setup_main(monkeypatch, module, tmp_path, ["--no-pubchem", *(["--apply"] if apply else [])])
    monkeypatch.setattr(module, "CAS_CACHE", tmp_path / "oak.json")
    module.CAS_CACHE.write_text(json.dumps({"461-05-2": BAD}))
    module.QUEUE_TSV.write_text("Compound\tCAS\nUnrelated source label\t461-05-2\n")
    monkeypatch.setattr(module, "COMPOUNDS_CSV", tmp_path / "compounds.csv")
    module.COMPOUNDS_CSV.write_text("Compound,CAS\nUnrelated source label,461-05-2\n")
    monkeypatch.setattr(module, "MIM_MAPPED_DIR", tmp_path / "mapped")
    monkeypatch.setattr(module, "_build_mim_chebi_index", lambda: {})
    before = module.CAS_CACHE.read_bytes(), module.QUEUE_TSV.read_bytes()
    module.main()
    assert "[REJECTED]" in capsys.readouterr().out
    assert "| OAK CAS-xref hits → new MIM YAML | 0 |" in module.SUMMARY_MD.read_text()
    assert not module.MIM_MAPPED_DIR.exists()
    assert before == (module.CAS_CACHE.read_bytes(), module.QUEUE_TSV.read_bytes())


@pytest.mark.parametrize("method", ["query_chebi_simple", "query_chebi_by_cas"])
def test_feba_fresh_pair_rejected_and_saved_separately(tmp_path, monkeypatch, method):
    module = load("enrich_feba_ontology_from_cas")
    monkeypatch.setattr(module.time, "sleep", lambda *a: None)
    enricher = module.ChEBIEnricher()
    responses = iter([{"IdentifierList": {"CID": [5970]}},
                      {"InformationList": {"Information": [{"RegistryID": [BAD]}]}}])
    monkeypatch.setattr(enricher.session, "get", lambda *a, **k: SimpleNamespace(status_code=200, json=lambda: next(responses)))
    xml = ('<root xmlns:c="https://www.ebi.ac.uk/webservices/chebi"><c:return>'
           '<c:chebiId>48601</c:chebiId><c:chebiAsciiName>amide</c:chebiAsciiName>'
           '</c:return></root>').encode()
    monkeypatch.setattr(enricher.session, "post", lambda *a, **k: SimpleNamespace(status_code=200, content=xml))
    assert getattr(enricher, method)("461-05-2") is None
    assert enricher.rejections[0]["chebi_id"] == BAD
    path = tmp_path / "report.yaml"
    enricher.save_results(path)
    report = yaml.safe_load(path.read_text())
    assert report["enrichments"] == {}
    assert report["rejections"][0]["cas_rn"] == "461-05-2"
    assert report["statistics"]["chebi_found"] == 0


@pytest.mark.parametrize("name,cas", CASES)
def test_feba_original_name_rejected_after_successful_lookup(monkeypatch, name, cas):
    module = load("enrich_feba_ontology_from_cas")
    enricher = module.ChEBIEnricher()
    monkeypatch.setattr(enricher, "query_chebi_simple", lambda c: {"chebi_id": BAD, "chebi_name": "amide", "source": "synthetic"})
    assert enricher.process_ingredient(name, cas) is None
    assert enricher.stats["chebi_found"] == 0
    assert enricher.stats["chebi_not_found"] == 1
    assert enricher.results == {}
    assert enricher.rejections[0]["ingredient_name"] == name


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("name,cas", CASES)
def test_feba_persisted_create_refuses_without_success_count(tmp_path, name, cas, dry_run):
    module = load("create_mim_ingredients_from_enrichments")
    creator = module.MIMIngredientCreator(tmp_path, tmp_path / "enrich.yaml", tmp_path)
    artifact = {name: {"chebi_id": BAD, "cas_rn": cas}}
    creator.enrichments = copy.deepcopy(artifact)
    assert creator.create_ingredient_file(name, artifact[name], dry_run) is False
    creator.create_ingredients(dry_run)
    assert creator.stats["ingredients_to_create"] == 0
    assert creator.stats["files_created"] == 0
    assert creator.enrichments == artifact
    assert creator.rejections
    assert not (tmp_path / "data").exists()


@pytest.mark.parametrize("dry_run", [False, True])
@pytest.mark.parametrize("name,cas", CASES + [("unrelated owner", "461-05-2")])
def test_feba_persisted_update_keeps_owner_and_artifact_cas_independent(tmp_path, monkeypatch, name, cas, dry_run):
    module = load("update_mim_with_enrichments")
    updater = module.MIMEnrichmentUpdater(tmp_path, tmp_path / "enrich.yaml")
    path = tmp_path / "owner.yaml"
    before = write_yaml(path, record(name, cas))
    # Wrong artifact CAS must not mask the owner's true CAS or original name.
    updater.enrichments = {"artifact alias": {"chebi_id": BAD, "cas_rn": "461-06-3"}}
    monkeypatch.setattr(updater, "find_ingredient_file", lambda n: path)
    updater.apply_enrichments(dry_run)
    assert updater.stats["ingredients_updated"] == 0
    assert updater.stats["ingredients_already_mapped"] == 0
    assert updater.rejections
    assert path.read_bytes() == before


@pytest.mark.parametrize("name,cas", CASES + [("unrelated owner", "461-05-2")])
def test_feba_culturemech_persisted_enrichment_refuses_original_owner(tmp_path, name, cas):
    module = load("apply_ontology_enrichments")
    applicator = module.OntologyEnrichmentApplicator(tmp_path, tmp_path / "enrich.yaml")
    path = tmp_path / "data/normalized_yaml/feba.yaml"
    before = write_yaml(path, {"notes": "FEBA media definitions", "ingredients": [record(name, cas)]})
    applicator.enrichments = {name: {"chebi_id": BAD, "cas_rn": "461-06-3"}}
    applicator.apply_enrichments()
    assert applicator.stats["ingredients_updated"] == applicator.stats["media_updated"] == 0
    assert applicator.rejections
    assert path.read_bytes() == before


@pytest.mark.parametrize("name,cas", CASES + [("unrelated owner", "461-05-2")])
def test_persisted_patch_uses_owner_context_before_replacing_label(tmp_path, name, cas):
    module = load("apply_mim_chebi_fixes")
    path = tmp_path / "owner.yaml"
    before = write_yaml(path, record(name, cas))
    patch = {"bad_chebi": "CHEBI:91318", "new_chebi": BAD, "new_label": "carnitinamide chloride",
             "cas_rn": "461-06-3", "proposed_curation_entry": {"action": "FIX", "changes": "fixture"}}
    accepted, reason = module._update_existing_yaml(path, patch)
    assert not accepted and "rejected" in reason
    assert path.read_bytes() == before


@pytest.mark.parametrize("name,cas", CASES + [("unrelated owner", "461-05-2")])
def test_direct_parent_refusal_preserves_entire_record(name, cas):
    module = load("backfill_parent_terms")
    owner = record(name, cas)
    before = copy.deepcopy(owner)
    with pytest.raises(ValueError, match="rejected"):
        module.apply_parent(owner, {"id": BAD, "label": "amide", "match": "pubchem-xref"})
    assert owner == before


@pytest.mark.parametrize("name,cas", CASES + [("unrelated owner", "461-05-2")])
def test_direct_upgrade_refusal_does_not_stage(tmp_path, monkeypatch, name, cas):
    module = load("foodon_pass")
    path = tmp_path / "owner.yaml"
    before = write_yaml(path, record(name, cas))
    staged = []
    monkeypatch.setattr(module, "_staged_write", lambda *a: staged.append(a))
    assert module.upgrade_yaml(path, BAD, "amide target", "label-exact").startswith("rejected:")
    assert staged == []
    assert path.read_bytes() == before


@pytest.mark.parametrize("name,cas", CONTROLS)
def test_parent_and_upgrade_legitimate_controls_remain_admissible(tmp_path, monkeypatch, name, cas):
    module = load("backfill_parent_terms")
    owner = record(name, cas)
    module.apply_parent(owner, {"id": BAD, "label": "amide", "match": "fixture"})
    assert owner["ontology_mapping"]["ontology_id"] == BAD
    module = load("foodon_pass")
    path = tmp_path / "owner.yaml"
    write_yaml(path, record(name, cas))
    staged = []
    monkeypatch.setattr(module, "_staged_write", lambda *a: staged.append(a))
    assert module.upgrade_yaml(path, BAD, "amide", "label-exact") == "upgraded"
    assert staged[0][1]["identifier"] == BAD


@pytest.mark.parametrize("script", ["resolve_unmapped", "resolve_unmapped_v2"])
@pytest.mark.parametrize("name,cas", CASES + [("unrelated owner", "461-05-2")])
def test_resolvers_filter_original_owner_before_high_or_stem_verdict(tmp_path, monkeypatch, script, name, cas):
    module = load(script)
    setup_main(monkeypatch, module, tmp_path)
    path = tmp_path / "owner.yaml"
    before = write_yaml(path, record(name, cas))
    monkeypatch.setattr(module, "collect_targets", lambda *a: [path])
    hit = {"id": BAD, "label": "carnitinamide chloride", "match": "synonym-exact"}
    if script == "resolve_unmapped":
        monkeypatch.setattr(module, "cascade_resolve", lambda n: hit)
    else:
        monkeypatch.setattr(module, "ols_any_ontology", lambda n: hit)
        monkeypatch.setattr(module, "ols_stem_match", lambda n: hit)
    assert module.main() == 0
    row = json.loads((tmp_path / "shard_0_of_1.jsonl").read_text())
    assert row["verdict"] == "REJECTED"
    assert row["match"] == {}
    assert row["rejections"][0]["candidate"]["id"] == BAD
    assert path.read_bytes() == before


@pytest.mark.parametrize("cached", [True, False])
@pytest.mark.parametrize("name", NAMES)
def test_name_proposer_filters_every_candidate_slot_before_confidence(tmp_path, monkeypatch, cached, name):
    module = load("propose_chebi_for_unmapped")
    candidates = [{"chebi": BAD, "label": "amide", "synonyms": [name], "score": 99.0},
                  {"chebi": "CHEBI:17126", "label": "unrelated proposed term", "synonyms": [], "score": 1.0},
                  {"chebi": BAD, "label": name, "synonyms": [], "score": 5.0}]
    cache = {name: candidates} if cached else {}
    docs = [{"obo_id": c["chebi"], "label": c["label"], "synonym": c["synonyms"], "score": c["score"]} for c in candidates]
    http_sequence(monkeypatch, module, [{"response": {"docs": docs}}])
    result = module.process_one({"source_id": "kgmicrobe.compound:fixture", "preferred_term": name}, cache)
    assert result["confidence"] == "MEDIUM"
    assert result["candidate_1_chebi"] == "CHEBI:17126"
    assert result["candidate_2_chebi"] == result["candidate_3_chebi"] == ""
    assert len(json.loads(result["rejections"])) == 2
    assert cache[name] == candidates
    module.write_tsv(tmp_path / "result.tsv", [result])
    assert "rejections" in (tmp_path / "result.tsv").read_text()


@pytest.mark.parametrize("name", NAMES)
def test_antibiotic_classifier_does_not_accept_alias_as_high_or_medium(name):
    module = load("curate_unmapped_kgm_antibiotics")
    candidates = [{"chebi": BAD, "label": "amide", "synonyms": [name]}]
    before = copy.deepcopy(candidates)
    confidence, reason, selected = module.classify_search(name, candidates)
    assert confidence == "NONE" and selected is None
    assert "rejected" in reason
    assert candidates == before
    assert module.classify_search("carnitinamide chloride", candidates)[0] == "MEDIUM"


@pytest.mark.parametrize("cached", [True, False])
@pytest.mark.parametrize("apply", [True, False])
def test_parent_main_cached_and_fresh_refusal_has_no_success_or_write(tmp_path, monkeypatch, cached, apply):
    module = load("backfill_parent_terms")
    setup_main(monkeypatch, module, tmp_path, ["--apply"] if apply else [])
    path = tmp_path / "ingredients/owner.yaml"
    owner = record(NAMES[0], identifier="kgmicrobe.compound:fixture")
    owner.pop("ontology_mapping")
    before = write_yaml(path, owner)
    monkeypatch.setattr(module, "INGREDIENTS", path.parent)
    hit = {"id": BAD, "label": "amide", "match": "synonym-exact"}
    key = f"{owner['identifier']}|{owner['preferred_term']}"
    cache = {key: hit} if cached else {}
    monkeypatch.setattr(module, "load_cache", lambda: cache)
    monkeypatch.setattr(module, "cascade_parent", lambda n: hit)
    assert module.main() == 0
    rows = list(csv.DictReader(module.OUT_TSV.open(), delimiter="\t"))
    assert rows[0]["verdict"] == "REJECTED"
    assert "rejected" in rows[0]["action"]
    assert rows[0]["parent_id"] == BAD
    assert cache[key] == hit
    assert path.read_bytes() == before


@pytest.mark.parametrize("apply", [True, False])
def test_placeholder_main_rejects_before_high_count_or_writer(tmp_path, monkeypatch, apply):
    module = load("upgrade_placeholders")
    setup_main(monkeypatch, module, tmp_path, ["--apply"] if apply else [])
    path = tmp_path / "owner.yaml"
    owner = record(NAMES[1], "461-06-3", "kgmicrobe.compound:fixture")
    before = write_yaml(path, owner)
    monkeypatch.setattr(module, "find_placeholder_yamls", lambda: [(path, owner)])
    monkeypatch.setattr(module, "best_cascade_match", lambda n: ({"id": BAD, "label": "amide", "match": "label-exact"}, "chebi"))
    writes = []
    monkeypatch.setattr(module, "upgrade_yaml", lambda *a: writes.append(a))
    assert module.main() == 0
    rows = list(csv.DictReader(module.OUT_TSV.open(), delimiter="\t"))
    assert rows[0]["verdict"] == "REJECTED" and "Rejected CHEBI" in rows[0]["action"]
    assert writes == []
    assert path.read_bytes() == before


@pytest.mark.parametrize("apply", [True, False])
@pytest.mark.parametrize("source", ["compound-cache", "media-preset"])
@pytest.mark.parametrize("name,cas", [(NAMES[0], ""), (NAMES[1], "461-06-3")])
def test_legacy_integrator_native_replay_queues_rejection(tmp_path, monkeypatch, apply, source, name, cas):
    module = load("integrate_culturebotht_ingredients")
    setup_main(monkeypatch, module, tmp_path, ["--apply"] if apply else [])
    monkeypatch.setattr(module, "_build_mim_index", lambda: (set(), {}, {}))
    for attr in ("CONSOLIDATED_JSON", "COMPOUNDS_CSV", "SYNONYM_CACHE"):
        monkeypatch.setattr(module, attr, tmp_path / attr.lower())
    module.SYNONYM_CACHE.write_text("{}")
    module.COMPOUNDS_CSV.write_text("Compound,CAS\n" + (f'"{name}",{cas}\n' if source == "compound-cache" else ""))
    module.CONSOLIDATED_JSON.write_text(json.dumps({"fixture": {"ingredients": [
        {"name": name, "ontology_id": BAD, "cas_number": cas}]}} if source == "media-preset" else {}))
    # Wrong CAS cache is context-free; acceptance must still use the original reviewed name.
    module.OLS_CACHE.write_text(json.dumps({f"cas::{cas}" if cas else f"name::{name}":
                                            {"chebi": BAD, "label": "amide"}}))
    monkeypatch.setattr(module, "MIM_MAPPED_DIR", tmp_path / "mapped")
    raw = module.COMPOUNDS_CSV.read_bytes(), module.CONSOLIDATED_JSON.read_bytes()
    module.main()
    rows = list(csv.DictReader(module.QUEUE_TSV.open(), delimiter="\t"))
    assert len(rows) == 1 and rows[0]["_chebi"] == BAD
    assert "rejected" in rows[0]["_reason"]
    assert "| Created MIM YAML | 0 |" in module.SUMMARY_MD.read_text()
    assert not module.MIM_MAPPED_DIR.exists()
    assert raw == (module.COMPOUNDS_CSV.read_bytes(), module.CONSOLIDATED_JSON.read_bytes())


@pytest.mark.parametrize("apply", [True, False])
def test_direct_patch_cli_does_not_offer_rejected_persisted_claims(tmp_path, monkeypatch, capsys, apply):
    module = load("apply_mim_chebi_fixes")
    setup_main(monkeypatch, module, tmp_path, ["--apply"] if apply else [])
    path = tmp_path / "owner.yaml"
    before = write_yaml(path, record(NAMES[0]))
    monkeypatch.setattr(module, "RECURATION_YAML", tmp_path / "patches.yaml")
    write_yaml(module.RECURATION_YAML, [{"file": "owner.yaml", "confidence": "HIGH", "bad_chebi": "CHEBI:91318",
                                       "new_chebi": BAD, "new_label": "amide", "proposed_curation_entry": {"action": "FIX", "changes": "fixture"}}])
    monkeypatch.setattr(module, "CANDIDATES_TSV", tmp_path / "candidates.tsv")
    module.CANDIDATES_TSV.write_text("source_id\tpreferred_term\tconfidence\tcandidate_1_chebi\tcandidate_1_label\n"
                                    f"kgmicrobe.compound:fixture\t{NAMES[1]}\tHIGH\t{BAD}\tamide\n")
    monkeypatch.setattr(module, "INGREDIENTS_DIR", tmp_path / "mapped")
    module.main()
    output = capsys.readouterr().out
    assert output.count("[REJECTED]") == 2
    assert "0 HIGH (applyable)" in output
    assert "creates from HIGH candidates: 0" in output
    assert path.read_bytes() == before
    assert not module.INGREDIENTS_DIR.exists()


@pytest.mark.parametrize("apply", [True, False])
def test_foodon_fallback_main_rejects_before_high_count(tmp_path, monkeypatch, apply):
    module = load("foodon_pass")
    setup_main(monkeypatch, module, tmp_path, ["--apply"] if apply else [])
    path = tmp_path / "owner.yaml"
    owner = record(NAMES[0])
    before = write_yaml(path, owner)
    monkeypatch.setattr(module, "INVENTORY_TSV", tmp_path / "inventory.tsv")
    module.INVENTORY_TSV.write_text(f"name\tnorm_key\n{NAMES[0]}\tfixture\n")
    monkeypatch.setattr(module, "_COMPLEX_RE", re.compile(".*"))
    monkeypatch.setattr(module, "build_mim_name_index", lambda: {})
    monkeypatch.setattr(module, "find_mim_yaml_by_name", lambda *a: path)
    monkeypatch.setattr(module, "ols_foodon_search", lambda *a: {})
    monkeypatch.setattr(module, "ols_search", lambda *a: {"id": BAD, "label": "amide", "match": "label-exact"})
    writes = []
    monkeypatch.setattr(module, "upgrade_yaml", lambda *a: writes.append(a))
    assert module.main() == 0
    rows = list(csv.DictReader(module.OUT_TSV.open(), delimiter="\t"))
    assert rows[0]["confidence"] == "REJECTED"
    assert writes == []
    assert path.read_bytes() == before


@pytest.mark.parametrize("name", NAMES)
def test_antibiotic_native_main_preserves_rejections_outside_candidate_slots(tmp_path, monkeypatch, name):
    module = load("curate_unmapped_kgm_antibiotics")
    setup_main(monkeypatch, module, tmp_path)
    monkeypatch.setattr(module, "INPUT_TSV", tmp_path / "input.tsv")
    module.INPUT_TSV.write_text(f"placeholder_id\tlabel_token\tedge_count\nkgmicrobe.compound:fixture\t{name}\t1\n")
    monkeypatch.setattr(module, "_existing_mim_labels", lambda: (set(), {}))
    monkeypatch.setattr(module, "_load_cache", lambda: {})
    monkeypatch.setattr(module, "_save_cache", lambda c: None)
    monkeypatch.setattr(module, "search_ols", lambda *a, **k: [{"chebi": BAD, "label": "amide", "synonyms": [name]}])
    monkeypatch.setattr(module, "MIM_MAPPED_DIR", tmp_path / "mapped")
    module.main()
    rows = list(csv.DictReader(module.QUEUE_TSV.open(), delimiter="\t"))
    assert len(rows) == 1
    assert rows[0]["confidence"] == "NONE" and rows[0]["best_chebi"] == ""
    assert "rejected" in rows[0]["rationale"]
    assert json.loads(rows[0]["rejections"])[0]["candidate"]["chebi"] == BAD
    assert not module.MIM_MAPPED_DIR.exists()


def test_feba_culturemech_source_notes_cas_is_independent_of_artifact(tmp_path):
    module = load("apply_ontology_enrichments")
    applicator = module.OntologyEnrichmentApplicator(tmp_path, tmp_path / "enrich.yaml")
    path = tmp_path / "data/normalized_yaml/feba.yaml"
    before = write_yaml(path, {"notes": "FEBA media definitions", "ingredients": [
        {"preferred_term": "source alias", "notes": "FEBA; CAS: 461-05-2"}]})
    applicator.enrichments = {"source alias": {"chebi_id": BAD, "cas_rn": "461-06-3"}}
    applicator.apply_enrichments()
    assert applicator.stats["ingredients_updated"] == 0
    assert applicator.rejections
    assert path.read_bytes() == before


def test_feba_legitimate_amide_creator_updater_and_culturemech(tmp_path):
    creator_module = load("create_mim_ingredients_from_enrichments")
    updater_module = load("update_mim_with_enrichments")
    cm_module = load("apply_ontology_enrichments")
    artifact = {"chebi_id": BAD, "cas_rn": "1-00-0"}
    creator = creator_module.MIMIngredientCreator(tmp_path, tmp_path / "enrich.yaml", tmp_path)
    assert creator.create_ingredient_file("carnitinamide chloride", artifact)
    owner = tmp_path / "owner.yaml"
    write_yaml(owner, record("carnitinamide chloride"))
    updater = updater_module.MIMEnrichmentUpdater(tmp_path, tmp_path / "enrich.yaml")
    assert updater.update_ingredient_file(owner, BAD, "1-00-0")
    before = owner.read_bytes()
    assert not updater.update_ingredient_file(owner, BAD, "1-00-0")
    assert owner.read_bytes() == before
    media = tmp_path / "data/normalized_yaml/feba.yaml"
    write_yaml(media, {"notes": "FEBA media definitions", "ingredients": [{"preferred_term": "carnitinamide chloride"}]})
    applicator = cm_module.OntologyEnrichmentApplicator(tmp_path, tmp_path / "enrich.yaml")
    applicator.enrichments = {"carnitinamide chloride": artifact}
    applicator.apply_enrichments()
    assert yaml.safe_load(media.read_text())["ingredients"][0]["term"]["id"] == BAD
