"""Pure native-Rule-K ownership and deterministic suppression evidence (#701)."""

from __future__ import annotations

import copy
import csv
import io
import itertools
import json
from dataclasses import FrozenInstanceError, replace

import pytest

from kg_microbe_utils.owned_name_policy import (
    SIDECAR_COLUMNS,
    AliasCandidate,
    Suppression,
    build_owner_index,
    filter_owned_aliases,
    render_suppressed_aliases,
)

POLICY = "https://github.com/CultureBotAI/MediaIngredientMech/issues/669"


def record(name, identifier="CHEBI:1", status="MAPPED", **extra):
    return {"preferred_term": name, "identifier": identifier,
            "mapping_status": status, **extra}


def alias(text, surface="mim_yaml", source="record.yaml#/synonyms/0", evidence=POLICY):
    return AliasCandidate(text, surface, (source,), (evidence,))


def event(**changes):
    base = Suppression("MIM:Child", "Parent", frozenset({"MIM:Parent"}),
                       "mim_yaml", ("child.yaml#/synonyms/0",), (POLICY,))
    return replace(base, **changes)


def rows(data):
    return list(csv.DictReader(io.StringIO(data.decode("utf-8")), delimiter="\t"))


@pytest.mark.parametrize("status", ["MAPPED", "AMBIGUOUS", "UNMAPPED", "", None, "pending"])
def test_every_nonrejected_record_owns_its_name_without_emitting_a_row(status):
    data = {"MIM:Owner": record(" Owned ", status=status,
                               ontology_mapping={"ontology_id": "unsupported:1"})}
    assert build_owner_index(data) == {"owned": frozenset({"MIM:Owner"})}
    kept, events = filter_owned_aliases("MIM:Other", [alias("OWNED")], build_owner_index(data))
    assert kept == ()
    assert events[0].owner_subject_ids == frozenset({"MIM:Owner"})


def test_casefold_without_punctuation_internal_space_or_unicode_normalization():
    owners = build_owner_index({
        "MIM:Street": record(" Straße "),
        "MIM:Spaces": record("Parent  name"),
        "MIM:Stereo": record("(S)-malate"),
        "MIM:Accent": record("é"),
    })
    assert "strasse" in owners and "straße" not in owners
    candidates = [alias(x) for x in ["STRASSE", "Parent name", "S-malate", "e\u0301"]]
    kept, events = filter_owned_aliases("MIM:Other", candidates, owners)
    assert kept == tuple(candidates[1:])
    assert [x.token for x in events] == ["STRASSE"]


def test_distinct_live_subjects_sharing_an_identifier_do_not_inherit_each_others_names():
    owners = build_owner_index({"MIM:A": record("Alpha"), "MIM:B": record("Beta")})
    kept, events = filter_owned_aliases("MIM:A", [alias("Beta")], owners)
    assert kept == ()
    assert events[0].owner_subject_ids == frozenset({"MIM:B"})


def test_tombstone_credits_all_live_identifier_holders_and_keeps_current_owner():
    owners = build_owner_index({
        "MIM:Z": record("Z", status="AMBIGUOUS"),
        "MIM:A": record("A"),
        "MIM:Dead": record("Old name", status=" rejected "),
    })
    assert owners["old name"] == frozenset({"MIM:A", "MIM:Z"})
    candidate = alias("Old name")
    assert filter_owned_aliases("MIM:Z", [candidate], owners) == ((candidate,), ())
    assert filter_owned_aliases("MIM:A", [candidate], owners) == ((candidate,), ())
    kept, events = filter_owned_aliases("MIM:Stranger", [candidate], owners)
    assert not kept and events[0].owner_subject_ids == frozenset({"MIM:A", "MIM:Z"})


def test_explicit_representative_wins_over_retained_wrong_identifier():
    owners = build_owner_index({
        "MIM:Old": record("Old", "CHEBI:1"),
        "MIM:Corrected": record("Corrected", "CHEBI:2"),
        "MIM:Tomb": record("Merged name", "CHEBI:1", "REJECTED",
                           representative=" CHEBI:2 "),
    })
    assert owners["merged name"] == frozenset({"MIM:Corrected"})
    assert filter_owned_aliases("MIM:Old", [alias("Merged name")], owners)[1]
    assert not filter_owned_aliases("MIM:Corrected", [alias("Merged name")], owners)[1]


@pytest.mark.parametrize("target", [None, "", "  ", "CHEBI:missing", "chebi:1"])
def test_explicit_empty_or_unresolved_representative_never_uses_old_identifier(target):
    owners = build_owner_index({
        "MIM:Old": record("Old"),
        "MIM:Tomb": record("Merged name", status="REJECTED", representative=target),
    })
    assert owners["merged name"] == frozenset({"MIM:Tomb"})
    assert filter_owned_aliases("MIM:Old", [alias("Merged name")], owners)[1]


def test_rejected_record_without_any_live_target_keeps_ownership():
    owners = build_owner_index({
        "MIM:Dead1": record("Retired", status="REJECTED"),
        "MIM:Dead2": record("Other retired", status="REJECTED"),
    })
    assert owners["retired"] == frozenset({"MIM:Dead1"})
    assert owners["other retired"] == frozenset({"MIM:Dead2"})


def test_preferred_name_collisions_union_live_and_unresolved_tombstone_owners():
    owners = build_owner_index({
        "MIM:Live": record("Shared"),
        "MIM:Dead": record("SHARED", "CHEBI:missing", "REJECTED"),
    })
    assert owners["shared"] == frozenset({"MIM:Live", "MIM:Dead"})


def test_empty_preferred_names_do_not_erase_identifier_membership():
    owners = build_owner_index({
        "MIM:NoName": record("  "),
        "MIM:Tomb": record("Legacy name", status="REJECTED"),
        "MIM:None": record(None, ""),
    })
    assert owners == {"legacy name": frozenset({"MIM:NoName"})}


def test_escaped_subject_keys_are_not_decoded_reescaped_or_lowercased():
    subject = "MIM:~3911~7E_special"
    owners = build_owner_index({subject: record("Greek name")})
    candidate = alias("Greek name")
    assert owners == {"greek name": frozenset({subject})}
    assert filter_owned_aliases(subject, [candidate], owners) == ((candidate,), ())
    assert filter_owned_aliases(subject.lower(), [candidate], owners)[1]


def test_owner_index_is_fresh_and_input_permutations_do_not_change_decisions():
    entries = [("MIM:A", record("A")), ("MIM:B", record("B")),
               ("MIM:T", record("Old name", status="REJECTED"))]
    snapshots = [build_owner_index(dict(order)) for order in itertools.permutations(entries)]
    assert all(index == snapshots[0] for index in snapshots)
    assert snapshots[0]["old name"] == frozenset({"MIM:A", "MIM:B"})
    other_worktree = build_owner_index({"MIM:New": record("Old name")})
    assert other_worktree["old name"] == frozenset({"MIM:New"})
    assert snapshots[0]["old name"] == frozenset({"MIM:A", "MIM:B"})


def test_filter_keeps_object_identity_and_order_without_deduplicating_or_capping():
    candidates = [alias(" unknown "), alias("Parent"), alias("unknown"), alias("   ")]
    owners = {"parent": frozenset({"MIM:Parent"})}
    kept, events = filter_owned_aliases(" MIM:Child ", iter(candidates), owners)
    assert kept == (candidates[0], candidates[2], candidates[3])
    assert all(a is b for a, b in zip(kept, (candidates[0], candidates[2], candidates[3]), strict=True))
    assert len(events) == 1 and events[0].subject_id == "MIM:Child"


@pytest.mark.parametrize("text", ["Parent|unknown", "unknown|Parent", "|", " Parent | Other "])
def test_pipe_lists_refuse_even_when_the_unsplit_text_has_no_owner(text):
    with pytest.raises(ValueError, match="Split pipe-delimited"):
        filter_owned_aliases("MIM:Child", [alias(text)], {})


def test_records_candidates_and_owner_index_are_not_mutated():
    records = {"MIM:Parent": record("Parent", synonyms=[{"synonym_text": "One"}])}
    before = copy.deepcopy(records)
    owners = build_owner_index(records)
    prior_owners = copy.deepcopy(owners)
    candidates = [alias(" parent ")]
    kept, events = filter_owned_aliases("MIM:Child", candidates, owners)
    render_suppressed_aliases(events)
    assert records == before and owners == prior_owners
    assert candidates == [alias(" parent ")] and kept == ()
    with pytest.raises(FrozenInstanceError):
        candidates[0].text = "changed"
    with pytest.raises(FrozenInstanceError):
        events[0].token = "changed"


def test_real_generic_and_form_examples_suppress_without_chemical_inference():
    records = {
        "MIM:L-asparagine": record("L-Asparagine", "CHEBI:17196"),
        "MIM:Asparagine": record("Asparagine", "CHEBI:22653"),
        "MIM:Magnesium_Chloride": record("Magnesium chloride", "CHEBI:86345"),
        "MIM:Mgcl2_X_6_H2o": record("MgCl2 x 6 H2O", "CHEBI:86345"),
    }
    owners = build_owner_index(records)
    for subject, token, expected in [
        ("MIM:L-asparagine", "ASPARAGINE", "MIM:Asparagine"),
        ("MIM:Magnesium_Chloride", "MgCl2 x 6 H2O", "MIM:Mgcl2_X_6_H2o"),
    ]:
        kept, events = filter_owned_aliases(subject, [alias(token)], owners)
        assert not kept and events[0].owner_subject_ids == frozenset({expected})
        assert rows(render_suppressed_aliases(events))[0]["disposition"] == "SUPPRESS"


def test_repeated_pair_aggregates_every_origin_and_owner_in_one_deterministic_row():
    events = [
        event(token=" parent ", owner_subject_ids=frozenset({"MIM:Z", "MIM:Parent"})),
        event(token="PARENT", input_surface="kg_target", source_refs=("nodes.tsv#CHEBI:1",),
              evidence_refs=("ontology-source", POLICY)),
        event(token="Parent", input_surface="registry_cas", source_refs=("child.yaml#/cas",)),
        event(token="Parent"),
    ]
    expected = render_suppressed_aliases(events)
    assert all(render_suppressed_aliases(order) == expected for order in itertools.permutations(events))
    parsed = rows(expected)
    assert len(parsed) == 1
    row = parsed[0]
    assert row["subject_id"] == "MIM:Child" and row["token_key"] == "parent"
    assert row["token"] == "PARENT" and row["disposition"] == "SUPPRESS"
    assert json.loads(row["owner_subject_ids"]) == ["MIM:Parent", "MIM:Z"]
    assert json.loads(row["input_surfaces"]) == ["kg_target", "mim_yaml", "registry_cas"]
    assert json.loads(row["source_refs"]) == [
        "child.yaml#/cas", "child.yaml#/synonyms/0", "nodes.tsv#CHEBI:1",
    ]
    assert json.loads(row["evidence_refs"]) == sorted([POLICY, "ontology-source"])
    assert b"\r\n" not in expected


def test_pair_key_keeps_subjects_distinct_and_sorts_tokens_by_casefolded_key():
    parsed = rows(render_suppressed_aliases([
        event(subject_id="MIM:Z", token="Alpha"),
        event(subject_id="MIM:A", token="Zulu"),
        event(subject_id="MIM:A", token="alpha"),
        event(subject_id="MIM:A", token="ALPHA"),
    ]))
    assert [(row["subject_id"], row["token_key"]) for row in parsed] == [
        ("MIM:A", "alpha"), ("MIM:A", "zulu"), ("MIM:Z", "alpha"),
    ]


def test_sidecar_quotes_tabs_quotes_and_unicode_without_losing_provenance():
    text = 'Straße\t"name"'
    data = render_suppressed_aliases([event(token=text, source_refs=('path#"quoted"',))])
    row = rows(data)[0]
    assert row["token"] == text and row["token_key"] == text.casefold()
    assert json.loads(row["source_refs"]) == ['path#"quoted"']
    assert "Straße".encode() in data


def test_empty_sidecar_is_exact_header_only_not_stale_rows():
    expected = ("\t".join(SIDECAR_COLUMNS) + "\n").encode()
    assert render_suppressed_aliases(iter(())) == expected
    assert rows(expected) == []


@pytest.mark.parametrize("changes", [
    {"subject_id": ""}, {"token": "  "}, {"token": "Parent|Other"},
    {"owner_subject_ids": frozenset()}, {"owner_subject_ids": frozenset({"MIM:Child"})},
    {"owner_subject_ids": frozenset({""})}, {"owner_subject_ids": frozenset({" MIM:Parent "})},
    {"input_surface": " "}, {"source_refs": ()}, {"evidence_refs": ()},
    {"source_refs": (" ",)}, {"evidence_refs": ("",)},
    {"source_refs": "not-a-tuple"}, {"owner_subject_ids": "not-a-set"},
])
def test_unverifiable_or_false_suppression_cannot_be_rendered(changes):
    with pytest.raises(ValueError):
        render_suppressed_aliases([event(**changes)])


@pytest.mark.parametrize("records", [{"MIM:Broken": None}, {"": {}}, {" MIM:Bad ": {}}])
def test_incomplete_or_unkeyed_record_snapshots_refuse(records):
    with pytest.raises(ValueError):
        build_owner_index(records)
