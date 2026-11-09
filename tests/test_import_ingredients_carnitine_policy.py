"""#699: native importer acceptance, conditional intake preflight and provenance."""
import csv
import hashlib
import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
NAME = "Carnitine (Dl) Hydrochloride"
OLD, CORRECT, AMIDE = "461-06-3", "461-05-2", "CHEBI:48601"
OVERLAY_ROW = {
    "compound": NAME, "wrong_cas": OLD, "correct_cas": CORRECT,
    "correct_form": "hydrochloride",
    "evidence": '461-06-3 is DL-carnitine free base (C7H15NO3); DL-carnitine hydrochloride is 461-05-2 (C7H16ClNO3); the catalogue already uses 461-05-2 for the "Carnitine Hydrochloride" row',
}


@pytest.fixture
def importer(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("import_carnitine_test", ROOT / "scripts/import_ingredients.py")
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "CULTUREBOT_ROOT", tmp_path / "source")
    monkeypatch.setattr(module, "WORKSPACE", tmp_path / "workspace")
    monkeypatch.setattr(module, "MAPPED_DIR", tmp_path / "mim/mapped")
    monkeypatch.setattr(module, "UNMAPPED_DIR", tmp_path / "mim/unmapped")
    module.MAPPED_DIR.mkdir(parents=True)
    module.UNMAPPED_DIR.mkdir()
    for attribute in ("OLS_CAS_CACHE", "PUBCHEM_CACHE", "OAK_CAS_INDEX"):
        monkeypatch.setattr(module, attribute, tmp_path / "cache" / (attribute + ".json"))
    monkeypatch.setattr(module, "require_mech_roots", lambda *a, **k: None)
    monkeypatch.setattr(module.urllib.request, "urlopen", lambda *a, **k: pytest.fail("Unexpected network request"))
    return module


def write_rows(path, rows, delimiter=","):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        output = csv.DictWriter(fh, list(rows[0]), delimiter=delimiter, lineterminator="\n")
        output.writeheader()
        output.writerows(rows)
    return path


def sources(module, *, names=None, media_only=False, overlay=True):
    names = names or [("Earlier harmless ingredient", "50-99-7"), (NAME, OLD)]
    if media_only:
        path = module.CULTUREBOT_ROOT / "data/consolidated/consolidated_media.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"Fixture medium": {"ingredients": [
            {"name": name, "cas_number": cas} for name, cas in names]}}))
    else:
        path = write_rows(module.CULTUREBOT_ROOT / "data/raw/google_sheets/compounds_to_cas.csv",
                          [{"Compound": name, "CAS": cas, "Notes": "raw evidence"} for name, cas in names])
    correction = module.CULTUREBOT_ROOT / "data/curated/compound_cas_corrections.tsv"
    if overlay:
        write_rows(correction, [OVERLAY_ROW], "\t")
    return path, correction


@pytest.mark.parametrize("tier", ["preset", "ols_cached", "ols_fresh", "oak", "pubchem_cached", "pubchem_fresh"])
@pytest.mark.parametrize("name,cas", [("Carnitine Hydrochloride", ""), (NAME, OLD), ("Unknown exact material", CORRECT)])
def test_native_resolver_rejects_every_acceptance_tier(importer, monkeypatch, tier, name, cas):
    c = importer.Candidate(name=name, cas=cas)
    ols, oak, pubchem = {}, {}, {}
    # CAS tiers need an actual caller-supplied CAS; absence remains covered by name/preset paths.
    if tier in {"oak", "pubchem_cached", "pubchem_fresh"} and not cas:
        c.cas = OLD
    if tier == "preset":
        c.preset_id = AMIDE
    for ontology in ("chebi", "ncit"):
        ols[f"name::{ontology}::{name}"] = None
    if tier == "ols_cached":
        ols[f"name::chebi::{name}"] = {"chebi": AMIDE, "label": name, "match": "synonym-exact"}
    if tier == "oak":
        oak[c.cas] = AMIDE
    if tier == "pubchem_cached":
        pubchem[c.cas] = AMIDE
    responses = []
    if tier == "ols_fresh":
        ols.pop(f"name::chebi::{name}")
        responses = [{"response": {"docs": [{"obo_id": AMIDE, "label": name}]}}]
    elif tier == "pubchem_fresh":
        responses = [{"InformationList": {"Information": [{"CID": [5970]}]}},
                     {"InformationList": {"Information": [{"Synonym": [AMIDE]}]}}]
    if responses:
        monkeypatch.setattr(importer.urllib.request, "urlopen",
                            lambda *a, **k: io.BytesIO(json.dumps(responses.pop(0)).encode()))
    result = importer.Resolver(ols, oak, pubchem, accept_medium=True).resolve(c)
    assert result.primary == "" and result.confidence == "UNMAPPED"
    assert result.method == "reviewed-identity-rejection"
    assert c.rejected_proposals[0]["ontology_id"] == AMIDE
    assert "distinct amide" in c.rejected_proposals[0]["reason"]
    assert not responses


def test_legitimate_amide_and_unrelated_preset_still_resolve(importer):
    for name, cas, identifier in [("carnitinamide chloride", "5080-50-2", AMIDE),
                                   (NAME, CORRECT, "NCIT:C216679"),
                                   ("L-carnitine hydrochloride", "10018-58-7", AMIDE)]:
        c = importer.Candidate(name=name, cas=cas, preset_id=identifier)
        assert importer.Resolver({}, {}, {}).resolve(c).primary == identifier
        assert c.rejected_proposals == []


@pytest.mark.parametrize("name,cas", [("Carnitine Hydrochloride", ""), (NAME, OLD), ("Unknown", CORRECT)])
def test_direct_persisted_result_cannot_bypass_mapped_emitter(importer, name, cas):
    candidate = importer.Candidate(name=name, cas=cas)
    path = importer.MAPPED_DIR / "persisted.yaml"
    with pytest.raises(ValueError, match="distinct amide"):
        importer.emit_mapped_yaml(path, candidate, importer.ResolveResult(AMIDE, "amide", "stale-preset", "HIGH"), "fixture")
    assert not path.exists()
    assert candidate.rejected_proposals[0]["method"] == "stale-preset"


@pytest.mark.parametrize("media_only", [False, True])
@pytest.mark.parametrize("failure", ["missing", "unreadable", "columns", "malformed", "omitted", "changed", "form", "evidence", "duplicate", "conflict"])
def test_required_overlay_refuses_before_first_yield(importer, monkeypatch, media_only, failure):
    _, overlay = sources(importer, media_only=media_only)
    if failure == "missing":
        overlay.unlink()
    elif failure == "unreadable":
        read = Path.read_bytes
        def blocked(path):
            if path == overlay:
                raise PermissionError("fixture unreadable")
            return read(path)
        monkeypatch.setattr(Path, "read_bytes", blocked)
    elif failure == "columns":
        overlay.write_text("compound\twrong_cas\n" + NAME + "\t" + OLD + "\n")
    elif failure == "malformed":
        overlay.write_text(overlay.read_text().rsplit("\t", 1)[0] + "\n")
    else:
        row = dict(OVERLAY_ROW)
        if failure == "omitted":
            row["compound"] = "Different compound"
        elif failure == "changed":
            row["correct_cas"] = OLD
        elif failure == "form":
            row["correct_form"] = "free base"
        elif failure == "evidence":
            row["evidence"] = "uncorroborated proposal"
        rows = [row]
        if failure in {"duplicate", "conflict"}:
            rows.append(row | ({"correct_cas": OLD} if failure == "conflict" else {}))
        write_rows(overlay, rows, "\t")
    with pytest.raises(ValueError, match="correction preflight failed"):
        next(iter(importer.src_culturebotht()))
    assert list(importer.MAPPED_DIR.iterdir()) == []


@pytest.mark.parametrize("media_only", [False, True])
def test_apply_max_cannot_hide_late_preflight_failure(importer, monkeypatch, media_only):
    sources(importer, media_only=media_only, overlay=False)
    monkeypatch.setattr(sys, "argv", ["import", "--source", "culturebotht", "--apply", "--max", "1"])
    monkeypatch.setattr(importer.Resolver, "resolve", lambda *a: pytest.fail("Resolution before source preflight"))
    with pytest.raises(ValueError, match="correction preflight failed"):
        importer.main()
    assert not list(importer.MAPPED_DIR.iterdir()) and not list(importer.UNMAPPED_DIR.iterdir())
    assert not importer.WORKSPACE.exists()


@pytest.mark.parametrize("name,cas,expected", [
    (" " + NAME + " ", " " + OLD + " ", CORRECT),
    (NAME.lower(), OLD, OLD), ("Carnitine  (Dl) Hydrochloride", OLD, OLD),
    (NAME, OLD + "/fixture-other", OLD), (NAME, OLD + " fixture-other", OLD),
    (NAME, CORRECT, CORRECT), ("Phenethylamine Hydrochloride", "64-04-0", "64-04-0"),
    ("Glycyrrhizic Acid, Ammonium Salt", "1405-86-3", "1405-86-3"),
    ("Dimethylsulfoniopropionate hydrochloride", "7314-30-9", "7314-30-9"),
])
def test_exact_raw_tuple_boundary_and_no_unrelated_overlay_dependency(importer, name, cas, expected):
    correction_needed = name.strip() == NAME and cas.strip() == OLD
    sources(importer, names=[(name, cas)], overlay=correction_needed)
    candidate, = importer.src_culturebotht()
    assert candidate.cas == expected
    assert bool(candidate.source_correction) is correction_needed


def test_missing_sources_remain_empty_without_overlay(importer):
    assert list(importer.src_culturebotht()) == []


@pytest.mark.parametrize("media_only", [False, True])
def test_captured_bytes_and_source_locator_survive_both_emitters(importer, monkeypatch, media_only):
    source, overlay = sources(importer, names=[(NAME, OLD)], media_only=media_only)
    source_bytes, overlay_bytes = source.read_bytes(), overlay.read_bytes()
    # Change files only after their captured bytes have been read, before first yield.
    original_reference = importer._overlay_reference
    def changed(path, captured):
        source.write_bytes(b"later source replacement")
        overlay.write_bytes(b"later overlay replacement")
        return original_reference(path, captured)
    monkeypatch.setattr(importer, "_overlay_reference", changed)
    c, = importer.src_culturebotht()
    evidence = c.source_correction
    assert evidence["source_sha256"] == hashlib.sha256(source_bytes).hexdigest()
    assert evidence["overlay_sha256"] == hashlib.sha256(overlay_bytes).hexdigest()
    assert evidence["original_cas"] == OLD and evidence["corrected_cas"] == CORRECT
    assert evidence["source_row"]["cas_number" if media_only else "CAS"] == OLD
    assert evidence["source_locator"] == ({"medium": "Fixture medium", "ingredient_index": 0}
                                          if media_only else {"csv_line": 2})
    assert evidence["overlay_reference"] == "sha256:" + evidence["overlay_sha256"]
    assert "1f27c43b" in evidence["reviewed_entry_reference"]
    mapped = importer.MAPPED_DIR / "mapped.yaml"
    importer.emit_mapped_yaml(mapped, c, importer.ResolveResult("cas:" + CORRECT, NAME, "cas-fallback", "FALLBACK_REGISTRY"), "culturebotht")
    c.rejected_proposals.append({"ontology_id": AMIDE, "reason": "fixture rejection"})
    unmapped = importer.UNMAPPED_DIR / "unmapped.yaml"
    importer.emit_unmapped_yaml(unmapped, c, "UNMAPPED_9999", "culturebotht")
    for path in (mapped, unmapped):
        record = yaml.safe_load(path.read_text())
        notes = record["curation_history"][0]["changes"]
        assert json.loads(notes.split(" Evidence: ", 1)[1])["source_correction"] == evidence
        assert OLD in notes and CORRECT in notes and evidence["overlay_sha256"] in notes
    assert "Reviewed identity rejection" in yaml.safe_load(unmapped.read_text())["notes"]
    assert "no CAS-RN" not in unmapped.read_text()


def test_actual_overlay_git_revision_is_bound_only_to_matching_blob(importer):
    _, overlay = sources(importer, names=[(NAME, OLD)])
    root = importer.CULTUREBOT_ROOT
    for args in (["init", "-q"], ["add", "data/curated/compound_cas_corrections.tsv"],
                 ["-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid", "commit", "-qm", "fixture"]):
        subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)
    revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
    candidate, = importer.src_culturebotht()
    assert candidate.source_correction["overlay_revision"] == revision
    assert candidate.source_correction["overlay_reference"].startswith("git:" + revision + ":")
    # Unrelated overlay additions do not alter the one reviewed tuple's approval.
    write_rows(overlay, [OVERLAY_ROW, OVERLAY_ROW | {"compound": "Unrelated", "evidence": "unrelated update"}], "\t")
    candidate, = importer.src_culturebotht()
    assert candidate.cas == CORRECT
    assert candidate.source_correction["checkout_revision"] == revision
    assert candidate.source_correction["overlay_revision"] is None
    assert candidate.source_correction["overlay_reference"].startswith("sha256:")


@pytest.mark.parametrize("outcome", ["name_skip", "cas_skip", "mapped", "unmapped"])
@pytest.mark.parametrize("apply", [False, True])
def test_full_run_retains_correction_including_skips_and_dry_run(importer, monkeypatch, outcome, apply):
    source, _ = sources(importer, names=[(NAME, OLD)])
    original = source.read_bytes()
    if outcome.endswith("skip"):
        record = {"preferred_term": NAME if outcome == "name_skip" else "Other existing name",
                  "chemical_properties": {"cas_rn": CORRECT if outcome == "cas_skip" else ""}}
        existing = importer.MAPPED_DIR / "existing.yaml"
        existing.write_text(yaml.safe_dump(record))
        existing_bytes = existing.read_bytes()
    monkeypatch.setattr(importer, "ols_search_by_name", lambda *a: None)
    if outcome == "unmapped":
        monkeypatch.setattr(importer, "oak_cas_lookup", lambda *a: AMIDE)
    monkeypatch.setattr(sys, "argv", ["import", "--source", "culturebotht", "--no-pubchem", "--no-sync"]
                        + (["--apply"] if apply else []))
    importer.main()
    summary = (importer.WORKSPACE / "reports/import_summary_culturebotht.md").read_text()
    diagnostic, = json.loads(summary.split("```json\n", 1)[1].split("\n```", 1)[0])
    assert diagnostic["source_correction"]["original_cas"] == OLD
    assert diagnostic["source_correction"]["corrected_cas"] == CORRECT
    assert source.read_bytes() == original
    if outcome.endswith("skip"):
        assert existing.read_bytes() == existing_bytes
        assert diagnostic["outcome"] == "skipped_existing_" + ("name" if outcome == "name_skip" else "cas")
        assert len(list(importer.MAPPED_DIR.iterdir())) == 1
        assert not list(importer.UNMAPPED_DIR.iterdir())
    elif outcome == "unmapped":
        assert diagnostic["rejected_proposals"][0]["ontology_id"] == AMIDE
        assert not list(importer.MAPPED_DIR.iterdir())
        assert bool(list(importer.UNMAPPED_DIR.iterdir())) is apply
    else:
        assert bool(list(importer.MAPPED_DIR.iterdir())) is apply
