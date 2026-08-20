"""Tests for the kgscan precision fixes (#69, TraitMech#411).

The defect these pin: the Europe PMC query anchors the PAPER to the topic, but
nothing anchored the SENTENCE, so any hedged sentence in a topically adjacent
abstract got promoted into a Discussion filed under the wrong record. All ten
of TraitMech's scanned gaps came out misfiled that way — two duplicate pairs
and two contentless boilerplate assertions among them. Each of those failure
modes gets a test here, several quoting the actual sentences that got through.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import kg_microbe_kgscan.__main__ as kgscan_main  # noqa: E402
import kg_microbe_kgscan.scan as scan_mod  # noqa: E402
from kg_microbe_kgscan.scan import (  # noqa: E402
    build_discussion,
    extract_gap_signals,
    is_contentless,
    prompt_key,
    sentence_mentions_topic,
)

TOPIC = ["biofilm formation", "biofilm"]


# --- the sentence-level topic gate ---


def test_gap_sentence_about_something_else_is_dropped():
    """The misfiling that motivated the fix: a gut-mucosa sentence retrieved
    for a biofilm query must not become a biofilm gap."""
    text = (
        "Biofilm formation is common in chronic infections. "
        "The mechanisms of immune homeostasis at the gut mucosa remain poorly understood."
    )
    sigs = extract_gap_signals(text, topic_terms=TOPIC)
    assert len(sigs) == 0


def test_gap_sentence_naming_the_topic_survives():
    text = "The regulation of biofilm formation under flow conditions remains poorly understood."
    sigs = extract_gap_signals(text, topic_terms=TOPIC)
    assert len(sigs) == 1
    assert "biofilm" in sigs[0]["sentence"].casefold()


def test_synonyms_anchor_too():
    text = "How the sessile community disperses is largely unknown."
    assert extract_gap_signals(text, topic_terms=TOPIC) == []
    assert len(extract_gap_signals(text, topic_terms=TOPIC + ["sessile community"])) == 1


def test_slug_underscores_match_spaced_prose():
    assert sentence_mentions_topic(
        "Biofilm formation in this species is poorly understood.", ["biofilm_formation"]
    )


def test_topic_match_respects_word_boundaries():
    """#71: `aerobic` inside "anaerobic" must not pass the gate -- a spurious
    pass silently reproduces the misfiling the gate exists to stop."""
    assert not sentence_mentions_topic(
        "Anaerobic digestion of sludge remains poorly understood.", ["aerobic"]
    )
    assert sentence_mentions_topic(
        "Aerobic growth at depth remains poorly understood.", ["aerobic"]
    )


def test_gate_can_be_disabled_and_without_topic_terms_is_inert():
    text = "The mechanisms of coral growth anomalies remain poorly understood."
    assert len(extract_gap_signals(text, topic_terms=TOPIC, require_topic=False)) == 1
    assert len(extract_gap_signals(text, topic_terms=())) == 1


# --- contentless boilerplate ---


def test_the_actual_boilerplate_that_got_filed_twice_is_rejected():
    """Filed verbatim under both biosafety_level and biosafety_level_3."""
    s = "It identifies ongoing challenges and critical knowledge gaps for future research."
    assert is_contentless(s)
    assert extract_gap_signals(s, topic_terms=(), require_topic=False) == []


def test_contentless_is_rejected_even_when_it_names_the_topic():
    """Naming the trait does not make 'gaps remain' curatable."""
    s = "For biofilm formation, however, critical knowledge gaps remain."
    assert is_contentless(s)
    assert extract_gap_signals(s, topic_terms=TOPIC) == []


def test_a_specific_gap_is_not_mistaken_for_boilerplate():
    s = (
        "Knowledge gaps about how c-di-GMP levels control biofilm formation "
        "under starvation persist in the literature."
    )
    assert not is_contentless(s)
    assert len(extract_gap_signals(s, topic_terms=TOPIC)) == 1


# --- cross-record dedup key ---


def test_prompt_key_ignores_record_name_case_and_whitespace():
    a = build_discussion("trait:a", {"name": "commensalism", "matches": [
        {"reference": "PMID:1", "score": 3,
         "signals": [{"categories": ["unclear_unknown"],
                      "sentence": "Plant-derived xenomiRs remain poorly understood."}]}]})
    b = build_discussion("trait:b", {"name": "gut_associated", "matches": [
        {"reference": "PMID:2", "score": 3,
         "signals": [{"categories": ["unclear_unknown"],
                      "sentence": "  plant-derived xenomiRs remain POORLY understood.  "}]}]})
    assert a["discussion_id"] != b["discussion_id"], "ids can never collide across records"
    assert prompt_key(a) == prompt_key(b), "the sentence identity must"


# --- end to end through main(), Europe PMC mocked ---


def _write_corpus(tmp_path: Path) -> Path:
    conf = tmp_path / "conf"
    data = tmp_path / "data"
    conf.mkdir()
    data.mkdir()
    for slug, label in [("commensalism", "commensalism"), ("gut_associated", "gut associated")]:
        (data / f"{slug}.yaml").write_text(yaml.dump(
            {"identifier": f"trait:{slug}", "label": label, "synonyms": []}))
    cfg = conf / "kgscan_config.yaml"
    cfg.write_text(yaml.dump({
        "repo_name": "fixture", "record_glob": "../data/*.yaml",
        "name_fields": ["label"], "synonym_field": "synonyms",
        "id_field": "identifier", "min_score": 1,
    }))
    return cfg


def test_main_drops_the_second_filing_of_the_same_sentence(tmp_path, monkeypatch, capsys):
    """Both records retrieve the same paper; its one on-topic gap sentence may
    be filed once. The second filing is reported as a duplicate, not written."""
    shared = ("The role of commensalism in gut associated communities "
              "remains poorly understood.")
    monkeypatch.setattr(scan_mod, "europepmc_search", lambda *a, **k: [
        {"pmid": "123", "title": "A paper", "abstractText": shared}])
    cfg = _write_corpus(tmp_path)
    out_json = tmp_path / "packet.json"
    monkeypatch.setattr(sys, "argv", [
        "prog", "--config", str(cfg), "--min-score", "1",
        "--output-json", str(out_json), "--output-md", str(tmp_path / "packet.md")])
    assert kgscan_main.main() == 0
    packet = json.loads(out_json.read_text())
    assert packet["proposed"] == 1
    assert packet["duplicates_dropped"] == 1
    statuses = [r["write_status"] for r in packet["results"]]
    assert any(s.startswith("cross_record_duplicate_of:trait:") for s in statuses)


def test_main_files_nothing_when_the_only_gap_sentence_is_off_topic(tmp_path, monkeypatch):
    """A topically adjacent paper whose hedged sentence is about something else
    entirely — the shape of all ten TraitMech misfilings — produces zero
    proposals rather than a misfiled one."""
    monkeypatch.setattr(scan_mod, "europepmc_search", lambda *a, **k: [
        {"pmid": "9", "title": "Plastisphere review", "abstractText":
         "Prokaryotes of marine plastispheres remain poorly understood."}])
    cfg = _write_corpus(tmp_path)
    out_json = tmp_path / "packet.json"
    monkeypatch.setattr(sys, "argv", [
        "prog", "--config", str(cfg), "--min-score", "1",
        "--output-json", str(out_json), "--output-md", str(tmp_path / "packet.md")])
    assert kgscan_main.main() == 0
    assert json.loads(out_json.read_text())["proposed"] == 0
