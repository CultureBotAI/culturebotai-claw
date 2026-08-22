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


def test_bare_gap_assertions_are_rejected():
    for s in (
        "Knowledge gaps remain.",
        "However, many unanswered questions persist.",
        "To date, critical research gaps exist!",
    ):
        assert is_contentless(s), s


def test_a_specific_gap_is_not_mistaken_for_boilerplate():
    s = (
        "Knowledge gaps about how c-di-GMP levels control biofilm formation "
        "under starvation persist in the literature."
    )
    assert not is_contentless(s)
    assert len(extract_gap_signals(s, topic_terms=TOPIC)) == 1


def test_content_before_the_assertion_is_not_boilerplate():
    """#77: the stop-list is anchored at BOTH ends. An end-only anchor killed
    specific gaps that merely close with 'knowledge gaps remain', and an
    unanchored pattern killed any sentence containing the identify-phrase.
    This deliberately reverses this PR's own first draft, which rejected the
    topic-prefixed third shape below."""
    survivors = (
        "Despite decades of work on the role of c-di-GMP in biofilm dispersal, "
        "major knowledge gaps remain.",
        "This review identifies challenges and knowledge gaps in biofilm "
        "dispersal under flow, specifically the role of c-di-GMP.",
        "For biofilm formation, however, critical knowledge gaps remain.",
    )
    for s in survivors:
        assert not is_contentless(s), s
    assert len(extract_gap_signals(survivors[0], topic_terms=["biofilm dispersal"])) == 1


def test_terms_with_non_word_edges_can_still_match():
    """#75: \\b outside a paren or plus demands an adjacent word character that
    prose never supplies, so Fe3+ and (-)-anisomycin could never match."""
    assert sentence_mentions_topic(
        "Reduction of Fe3+ in these sediments remains poorly understood.", ["Fe3+"]
    )
    assert sentence_mentions_topic(
        "The mode of action of (-)-anisomycin is largely unknown.", ["(-)-anisomycin"]
    )
    assert not sentence_mentions_topic(
        "Ferrous iron cycling is well studied.", ["Fe3+"]
    )


def test_hyphen_and_space_spellings_cross_match():
    """#78: `gut-associated` labels vs "Gut associated" prose, and back."""
    assert sentence_mentions_topic(
        "Gut associated microbial communities remain poorly understood.", ["gut-associated"]
    )
    assert sentence_mentions_topic(
        "Free-living amoebae remain poorly understood.", ["free living"]
    )


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


def test_existing_discussion_outside_offset_window_blocks_cross_run_duplicate(
    tmp_path, monkeypatch
):
    """#72: dedup must index the complete corpus, not only this run's window.

    The existing filing is deliberately outside ``--offset 1 --limit 1``.
    A per-run index would therefore miss it and file the same sentence under
    the second record on the next nightly window.
    """
    shared = (
        "The role of commensalism in gut associated communities "
        "remains poorly understood."
    )
    monkeypatch.setattr(scan_mod, "europepmc_search", lambda *a, **k: [
        {"pmid": "123", "title": "A paper", "abstractText": shared}
    ])
    cfg = _write_corpus(tmp_path)
    first = tmp_path / "data" / "commensalism.yaml"
    doc = yaml.safe_load(first.read_text())
    doc["discussions"] = [
        {
            "discussion_id": "kgscan-existing",
            "prompt": f"Knowledge gap for commensalism: {shared}",
            "evidence": [{"snippet": shared}],
        }
    ]
    first.write_text(yaml.dump(doc, sort_keys=False))

    out_json = tmp_path / "packet.json"
    monkeypatch.setattr(sys, "argv", [
        "prog", "--config", str(cfg), "--min-score", "1",
        "--offset", "1", "--limit", "1",
        "--output-json", str(out_json),
        "--output-md", str(tmp_path / "packet.md"),
    ])
    assert kgscan_main.main() == 0
    packet = json.loads(out_json.read_text())
    assert packet["records_scanned"] == 1
    assert packet["proposed"] == 0
    assert packet["duplicates_dropped"] == 1
    assert packet["results"][0]["write_status"] == (
        "cross_record_duplicate_of:trait:commensalism"
    )


def test_existing_discussion_in_same_record_is_not_reproposed(tmp_path, monkeypatch):
    """An idempotent later scan reports an existing filing, even in dry-run."""
    sentence = "Commensalism remains poorly understood."
    monkeypatch.setattr(scan_mod, "europepmc_search", lambda *a, **k: [
        {"pmid": "123", "title": "A paper", "abstractText": sentence}
    ])
    cfg = _write_corpus(tmp_path)
    first = tmp_path / "data" / "commensalism.yaml"
    doc = yaml.safe_load(first.read_text())
    doc["discussions"] = [
        {
            "discussion_id": "kgscan-existing",
            "prompt": f"Knowledge gap for commensalism: {sentence}",
            "evidence": [{"snippet": sentence}],
        }
    ]
    first.write_text(yaml.dump(doc, sort_keys=False))

    out_json = tmp_path / "packet.json"
    monkeypatch.setattr(sys, "argv", [
        "prog", "--config", str(cfg), "--min-score", "1", "--limit", "1",
        "--output-json", str(out_json),
        "--output-md", str(tmp_path / "packet.md"),
    ])
    assert kgscan_main.main() == 0
    packet = json.loads(out_json.read_text())
    assert packet["proposed"] == 0
    assert packet["existing_skipped"] == 1
    assert packet["duplicates_dropped"] == 0
    assert packet["results"][0]["write_status"] == (
        "already_present_in:trait:commensalism"
    )


def test_malformed_existing_discussions_do_not_crash_or_create_an_empty_key(tmp_path):
    records = [
        (
            tmp_path / "one.yaml",
            {
                "identifier": "trait:one",
                "discussions": [
                    None,
                    {},
                    "bad",
                    {"evidence": "not-a-list"},
                    {"evidence": [None, "bad", {"snippet": 42}]},
                ],
            },
        ),
        (tmp_path / "two.yaml", {"identifier": "trait:two", "discussions": {"not": "a list"}}),
    ]
    assert kgscan_main._existing_prompt_owners(
        records, {"id_field": "identifier"}, "discussions"
    ) == {}


def test_existing_index_reads_every_evidence_snippet(tmp_path):
    records = [
        (
            tmp_path / "one.yaml",
            {
                "identifier": "trait:one",
                "discussions": [
                    {
                        "evidence": [
                            {"snippet": "First gap sentence."},
                            {"snippet": "A later duplicate sentence."},
                        ]
                    }
                ],
            },
        )
    ]
    assert kgscan_main._existing_prompt_owners(
        records, {"id_field": "identifier"}, "discussions"
    ) == {
        "first gap sentence.": ("trait:one",),
        "a later duplicate sentence.": ("trait:one",),
    }


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


def test_dedup_keeps_the_best_scored_filing_regardless_of_scan_order(tmp_path, monkeypatch):
    """#76: glob order used to win, and --offset rotation changed the winner
    between runs. Now the highest-scored filing wins deterministically, and the
    loser is named in the Markdown, not just counted."""
    shared = ("The role of commensalism in gut associated communities "
              "remains poorly understood.")
    extra = "How gut associated taxa resist invasion is largely unknown."

    def fake_search(query, **kwargs):
        # The low-scoring record (glob-first) retrieves only the shared
        # sentence; the high-scoring one also gets a second on-topic signal.
        abstract = shared if "commensalism" in query else f"{shared} {extra}"
        return [{"pmid": "123", "title": "A paper", "abstractText": abstract}]

    monkeypatch.setattr(scan_mod, "europepmc_search", fake_search)
    conf = tmp_path / "conf"
    data = tmp_path / "data"
    conf.mkdir()
    data.mkdir()
    (data / "aaa_low.yaml").write_text(yaml.dump(
        {"identifier": "trait:aaa_low", "label": "commensalism", "synonyms": []}))
    (data / "zzz_high.yaml").write_text(yaml.dump(
        {"identifier": "trait:zzz_high", "label": "gut associated", "synonyms": []}))
    cfg = conf / "kgscan_config.yaml"
    cfg.write_text(yaml.dump({
        "repo_name": "fixture", "record_glob": "../data/*.yaml",
        "name_fields": ["label"], "synonym_field": "synonyms",
        "id_field": "identifier", "min_score": 1,
    }))
    for offset in ("0", "1"):  # rotation must not change the winner
        out_json = tmp_path / f"packet{offset}.json"
        out_md = tmp_path / f"packet{offset}.md"
        monkeypatch.setattr(sys, "argv", [
            "prog", "--config", str(cfg), "--min-score", "1", "--offset", offset,
            "--output-json", str(out_json), "--output-md", str(out_md)])
        assert kgscan_main.main() == 0
        packet = json.loads(out_json.read_text())
        kept = [r for r in packet["results"] if r.get("discussion")]
        dropped = [r for r in packet["results"] if not r.get("discussion")]
        assert [r["record_id"] for r in kept] == ["trait:zzz_high"], f"offset {offset}"
        assert dropped[0]["write_status"] == "cross_record_duplicate_of:trait:zzz_high"
        md = out_md.read_text()
        assert "Dropped cross-record duplicates" in md
        assert "trait:aaa_low" in md, "the loser must be visible in the Markdown"


def test_require_topic_in_sentence_false_in_the_config_restores_recall(tmp_path, monkeypatch):
    """#79 escape hatch, plumbed through a real config file: an off-topic gap
    sentence is filed again when the Mech opts out of the gate."""
    monkeypatch.setattr(scan_mod, "europepmc_search", lambda *a, **k: [
        {"pmid": "9", "title": "Review", "abstractText":
         "Prokaryotes of marine plastispheres remain poorly understood."}])
    conf = tmp_path / "conf"
    data = tmp_path / "data"
    conf.mkdir()
    data.mkdir()
    (data / "commensalism.yaml").write_text(yaml.dump(
        {"identifier": "trait:commensalism", "label": "commensalism", "synonyms": []}))
    cfg = conf / "kgscan_config.yaml"
    cfg.write_text(yaml.dump({
        "repo_name": "fixture", "record_glob": "../data/*.yaml",
        "name_fields": ["label"], "synonym_field": "synonyms",
        "id_field": "identifier", "min_score": 1,
        "require_topic_in_sentence": False,
    }))
    out_json = tmp_path / "packet.json"
    monkeypatch.setattr(sys, "argv", [
        "prog", "--config", str(cfg), "--min-score", "1",
        "--output-json", str(out_json), "--output-md", str(tmp_path / "packet.md")])
    assert kgscan_main.main() == 0
    assert json.loads(out_json.read_text())["proposed"] == 1
