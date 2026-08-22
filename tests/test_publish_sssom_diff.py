"""Row-set diff behind the publish-sssom truncation guard (MediaIngredientMech#416).

The guard used to compare row counts, which reports churn as one net number: on
2026-08-21 a 155-out/102-in difference -- 88 of which were the same records under
a re-spelled subject -- surfaced only as "-53", indistinguishable from a
truncation. These tests pin the distinction the count could not make.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_SPEC = importlib.util.spec_from_file_location(
    "publish_sssom", Path(__file__).resolve().parents[1] / "scripts" / "publish_sssom.py"
)
publish_sssom = importlib.util.module_from_spec(_SPEC)
# Register before exec: @dataclass resolves annotations via
# sys.modules[cls.__module__], which is None for an unregistered module.
sys.modules[_SPEC.name] = publish_sssom
_SPEC.loader.exec_module(publish_sssom)

diff_rows = publish_sssom.diff_rows
_spelling_key = publish_sssom._spelling_key


def row(subject, obj, predicate="skos:exactMatch"):
    return {"subject_id": subject, "object_id": obj, "predicate_id": predicate}


def test_identical_row_sets_produce_an_empty_diff():
    rows = [row("MIM:Glucose", "CHEBI:17234"), row("MIM:Edta_Stock", "CHEBI:4735")]

    diff = diff_rows(rows, list(rows))

    assert diff.is_empty
    assert diff.same_key_and_predicate == 2


def test_a_genuinely_removed_row_is_reported_as_removed():
    prev = [row("MIM:Glucose", "CHEBI:17234"), row("MIM:Dropped", "CHEBI:99999")]
    new = [row("MIM:Glucose", "CHEBI:17234")]

    diff = diff_rows(prev, new)

    assert diff.removed == [("MIM:Dropped", "CHEBI:99999")]
    assert diff.added == []
    assert diff.respelled == []


def test_a_new_row_is_reported_as_added():
    prev = [row("MIM:Glucose", "CHEBI:17234")]
    new = [row("MIM:Glucose", "CHEBI:17234"), row("MIM:Fresh", "CHEBI:12345")]

    diff = diff_rows(prev, new)

    assert diff.added == [("MIM:Fresh", "CHEBI:12345")]
    assert diff.removed == []


@pytest.mark.parametrize(
    ("published", "rebuilt"),
    [
        # Letter case -- the capitalize() scar from MediaIngredientMech#147.
        ("MIM:EDTA_Stock", "MIM:Edta_Stock"),
        ("MIM:ATCC_Wolfes_mineral_mix", "MIM:ATCC_Wolfes_Mineral_Mix"),
        ("MIM:BG-11_Trace_Metals_Solution", "MIM:Bg-11_Trace_Metals_Solution"),
        # ~HEX escaping -- the published side carries literal parens, which
        # MIM's own _CURIE_RE rejects.
        ("MIM:(R)-lactate", "MIM:~28R~29-lactate"),
        ("MIM:Calcium(2)", "MIM:Calcium~282~29"),
        ("MIM:Tryptoneyeastbeef_(tyb)", "MIM:Tryptoneyeastbeef_~28tyb~29"),
    ],
)
def test_subject_respellings_are_not_removals(published, rebuilt):
    diff = diff_rows([row(published, "CHEBI:17234")], [row(rebuilt, "CHEBI:17234")])

    assert diff.removed == [], "a re-spelled subject must not read as a truncation"
    assert diff.added == []
    assert diff.respelled == [(published, rebuilt, "CHEBI:17234")]


@pytest.mark.parametrize(
    ("published", "rebuilt"),
    [
        # An older naming rule *stripped* the parens instead of escaping them,
        # so the stem itself differs -- not recoverable by normalisation.
        ("MIM:Synthetic_Sea_Salts_sss", "MIM:Synthetic_Sea_Salts_~28sss~29"),
        ("MIM:Sodium", "MIM:Sodium~28~29"),
        # A genuine relabel (MediaIngredientMech#236).
        ("MIM:2-phenylethylamine", "MIM:Phenethylamine_Hydrochloride"),
    ],
)
def test_a_changed_stem_is_not_silently_paired_as_a_respelling(published, rebuilt):
    """Only case and `~HEX` escaping are treated as spelling.

    Anything else -- a stripped character, a relabel -- is reported for a human
    to confirm. Pairing them automatically would need a lossy normalisation that
    could collapse two genuinely distinct records onto one key, and a guard that
    guesses is the failure mode this whole change exists to remove.
    """
    diff = diff_rows([row(published, "CHEBI:17234")], [row(rebuilt, "CHEBI:17234")])

    assert diff.respelled == []
    assert diff.removed == [(published, "CHEBI:17234")]
    assert diff.added == [(rebuilt, "CHEBI:17234")]


def test_a_respelling_onto_a_different_object_is_not_a_respelling():
    """Same record, different target, is a real mapping change -- gate it."""
    diff = diff_rows(
        [row("MIM:EDTA_Stock", "CHEBI:4735")],
        [row("MIM:Edta_Stock", "CHEBI:64755")],
    )

    assert diff.respelled == []
    assert diff.removed == [("MIM:EDTA_Stock", "CHEBI:4735")]
    assert diff.added == [("MIM:Edta_Stock", "CHEBI:64755")]


def test_predicate_flip_on_a_shared_key_is_reported_and_not_counted_unchanged():
    diff = diff_rows(
        [row("MIM:Glucose", "CHEBI:17234", "skos:exactMatch")],
        [row("MIM:Glucose", "CHEBI:17234", "skos:narrowMatch")],
    )

    assert diff.flipped == [
        ("MIM:Glucose", "CHEBI:17234", "skos:exactMatch", "skos:narrowMatch")
    ]
    assert diff.same_key_and_predicate == 0
    assert diff.removed == []


@pytest.mark.parametrize(
    "new_predicate",
    ["skos:closeMatch", "skos:narrowMatch", "skos:broadMatch", "skos:relatedMatch"],
)
def test_a_flip_away_from_exact_match_is_a_widening_flip(new_predicate):
    """#112: nothing gated on `flipped` before this -- a rebuild that flipped
    every exactMatch to closeMatch printed a count and exited 0."""
    diff = diff_rows(
        [row("MIM:Glucose", "CHEBI:17234", "skos:exactMatch")],
        [row("MIM:Glucose", "CHEBI:17234", new_predicate)],
    )

    assert diff.widening_flips == [
        ("MIM:Glucose", "CHEBI:17234", "skos:exactMatch", new_predicate)
    ]


@pytest.mark.parametrize("old_predicate", ["skos:closeMatch", "skos:narrowMatch", "skos:relatedMatch"])
def test_a_flip_tightened_to_exact_match_is_not_widening(old_predicate):
    """The normal outcome of curation -- a provisional mapping proven exact --
    must not trip the same gate as a rebuild regression."""
    diff = diff_rows(
        [row("MIM:Glucose", "CHEBI:17234", old_predicate)],
        [row("MIM:Glucose", "CHEBI:17234", "skos:exactMatch")],
    )

    assert diff.flipped == [("MIM:Glucose", "CHEBI:17234", old_predicate, "skos:exactMatch")]
    assert diff.widening_flips == []


def test_a_lateral_flip_between_non_exact_predicates_is_not_widening():
    """Scope is deliberately narrow: exact-vs-not, not a full precision
    ordering across the weaker predicates."""
    diff = diff_rows(
        [row("MIM:Glucose", "CHEBI:17234", "skos:narrowMatch")],
        [row("MIM:Glucose", "CHEBI:17234", "skos:broadMatch")],
    )

    assert diff.flipped == [
        ("MIM:Glucose", "CHEBI:17234", "skos:narrowMatch", "skos:broadMatch")
    ]
    assert diff.widening_flips == []


def test_widening_flipped_is_included_in_the_diff_payload(tmp_path):
    diff = diff_rows(
        [row("MIM:Glucose", "CHEBI:17234", "skos:exactMatch")],
        [row("MIM:Glucose", "CHEBI:17234", "skos:closeMatch")],
    )

    out = publish_sssom._write_diff_report(diff, tmp_path / "d.json")
    payload = json.loads(out.read_text())

    assert payload["widening_flipped"] == [
        ["MIM:Glucose", "CHEBI:17234", "skos:exactMatch", "skos:closeMatch"]
    ]


def test_a_respelled_row_with_a_predicate_downgrade_is_not_silently_absorbed():
    """A respelling changes the (subject, object) key, so this pair is never
    in `shared` and never reaches `flipped` -- before the fix, an exactMatch
    -> closeMatch downgrade riding along with a respelling was completely
    invisible in every diff artifact, and --allow-widening-flips 0 did not
    refuse the promotion. Reproduces the case found reviewing this PR."""
    diff = diff_rows(
        [row("MIM:Foo", "CHEBI:1", "skos:exactMatch")],
        [row("MIM:foo", "CHEBI:1", "skos:closeMatch")],
    )

    assert diff.flipped == [], "the key changed -- this must not show up as a flip"
    assert diff.respelled == [("MIM:Foo", "MIM:foo", "CHEBI:1")]
    assert diff.respelled_widening == [
        ("MIM:Foo", "MIM:foo", "CHEBI:1", "skos:exactMatch", "skos:closeMatch")
    ]
    assert diff.all_widening == diff.respelled_widening


def test_a_plain_respelling_with_no_predicate_change_has_no_widening():
    diff = diff_rows(
        [row("MIM:EDTA_Stock", "CHEBI:4735", "skos:exactMatch")],
        [row("MIM:Edta_Stock", "CHEBI:4735", "skos:exactMatch")],
    )

    assert diff.respelled == [("MIM:EDTA_Stock", "MIM:Edta_Stock", "CHEBI:4735")]
    assert diff.respelled_widening == []
    assert diff.all_widening == []


def test_all_widening_unions_flips_and_respelled_widening():
    diff = diff_rows(
        [
            row("MIM:Glucose", "CHEBI:17234", "skos:exactMatch"),  # flips in place
            row("MIM:Foo", "CHEBI:1", "skos:exactMatch"),          # respells + widens
        ],
        [
            row("MIM:Glucose", "CHEBI:17234", "skos:closeMatch"),
            row("MIM:foo", "CHEBI:1", "skos:closeMatch"),
        ],
    )

    assert len(diff.widening_flips) == 1
    assert len(diff.respelled_widening) == 1
    assert len(diff.all_widening) == 2


def test_churn_is_separated_rather_than_netted_out():
    """The shape the count guard could not see: rows out AND rows in."""
    prev = [
        row("MIM:EDTA_Stock", "CHEBI:4735"),          # re-spelled below
        row("MIM:(R)-lactate", "CHEBI:16004"),        # re-spelled below
        row("MIM:Retired", "kgmicrobe.compound:retired"),  # genuinely gone
    ]
    new = [
        row("MIM:Edta_Stock", "CHEBI:4735"),
        row("MIM:~28R~29-lactate", "CHEBI:16004"),
        row("MIM:Brand_New", "CHEBI:12345"),
    ]

    diff = diff_rows(prev, new)

    # A count guard sees 3 -> 3 and waves this through; a naive set diff sees
    # 3 out / 3 in and blocks. Only one row actually left the mapping set.
    assert len(diff.respelled) == 2
    assert diff.removed == [("MIM:Retired", "kgmicrobe.compound:retired")]
    assert diff.added == [("MIM:Brand_New", "CHEBI:12345")]


def test_spelling_key_is_idempotent_on_an_already_escaped_subject():
    """`~` is safe, so normalising an escaped subject twice is a fixed point."""
    once = _spelling_key("MIM:~28R~29-lactate")

    assert _spelling_key(once) == once


def test_spelling_key_does_not_collapse_distinct_records():
    assert _spelling_key("MIM:Glucose") != _spelling_key("MIM:Galactose")


def test_spelling_key_tolerates_a_subject_without_a_prefix():
    assert _spelling_key("bare_subject") == "bare_subject"


def test_duplicate_subject_object_pairs_are_counted_not_swallowed():
    """Keying on (subject, object) drops repeats -- the diff must admit it."""
    prev = [
        row("MIM:Glucose", "CHEBI:17234", "skos:exactMatch"),
        row("MIM:Glucose", "CHEBI:17234", "skos:closeMatch"),
    ]
    new = [row("MIM:Glucose", "CHEBI:17234", "skos:exactMatch")]

    diff = diff_rows(prev, new)

    assert diff.collapsed_prev == 1
    assert diff.collapsed_new == 0


def test_no_duplicates_reports_no_collapse():
    diff = diff_rows([row("MIM:Glucose", "CHEBI:17234")], [row("MIM:Glucose", "CHEBI:17234")])

    assert diff.collapsed_prev == 0
    assert diff.collapsed_new == 0


def test_respelling_choice_is_deterministic_across_orderings():
    """Two added rows can share a spelling key; the pairing must not vary."""
    prev = [row("MIM:FOO_BAR", "CHEBI:1")]
    variants = [row("MIM:Foo_Bar", "CHEBI:1"), row("MIM:foo_bar", "CHEBI:1")]

    forward = diff_rows(prev, list(variants))
    reversed_ = diff_rows(prev, list(reversed(variants)))

    assert forward.respelled == reversed_.respelled
    assert forward.added == reversed_.added


def test_columns_outside_the_key_are_counted_not_ignored():
    """#115: keying on (subject, object, predicate) alone would let a rebuild
    rewrite every object_label and still report the rows as unchanged."""
    prev = [{"subject_id": "MIM:Glucose", "object_id": "CHEBI:17234",
             "predicate_id": "skos:exactMatch", "object_label": "D-glucose",
             "confidence": "0.95"}]
    new = [{"subject_id": "MIM:Glucose", "object_id": "CHEBI:17234",
            "predicate_id": "skos:exactMatch", "object_label": "glucose",
            "confidence": "0.99"}]

    diff = diff_rows(prev, new)

    assert diff.same_key_and_predicate == 1, "the key and predicate did survive"
    assert diff.column_changes == {"object_label": 1, "confidence": 1}
    assert diff.is_empty, "column drift is reported, not gated"


def test_column_changes_is_empty_when_rows_are_identical():
    rows = [{"subject_id": "MIM:Glucose", "object_id": "CHEBI:17234",
             "predicate_id": "skos:exactMatch", "object_label": "D-glucose"}]

    assert diff_rows(rows, [dict(r) for r in rows]).column_changes == {}


def test_a_column_present_on_only_one_side_counts_as_changed():
    """A dropped or added column is drift too -- `.keys() |` not `.keys() &`."""
    prev = [{"subject_id": "MIM:X", "object_id": "CHEBI:1",
             "predicate_id": "skos:exactMatch", "confidence": "0.9"}]
    new = [{"subject_id": "MIM:X", "object_id": "CHEBI:1",
            "predicate_id": "skos:exactMatch"}]

    assert diff_rows(prev, new).column_changes == {"confidence": 1}


def test_diff_report_is_written_with_every_entry(tmp_path):
    """#116: stdout shows EXAMPLES_SHOWN per category; the rest must be readable
    somewhere on a dry run, not only in the apply-path audit log."""
    prev = [row(f"MIM:Gone{i}", f"CHEBI:{i}") for i in range(30)]
    diff = diff_rows(prev, [])

    out = publish_sssom._write_diff_report(diff, tmp_path / "d.json")
    payload = json.loads(out.read_text())

    assert len(payload["removed"]) == 30 > publish_sssom.EXAMPLES_SHOWN
    assert payload["same_key_and_predicate"] == 0
    assert "column_changes" in payload


def test_read_rows_skips_the_yaml_preamble(tmp_path):
    path = tmp_path / "m.sssom.tsv"
    path.write_text(
        "# curie_map:\n"
        '#   CHEBI: "http://purl.obolibrary.org/obo/CHEBI_"\n'
        "subject_id\tpredicate_id\tobject_id\n"
        "MIM:Glucose\tskos:exactMatch\tCHEBI:17234\n"
    )

    rows = publish_sssom._read_rows(path)

    assert rows == [
        {
            "subject_id": "MIM:Glucose",
            "predicate_id": "skos:exactMatch",
            "object_id": "CHEBI:17234",
        }
    ]


def test_read_rows_on_a_missing_file_is_empty_not_an_error(tmp_path):
    assert publish_sssom._read_rows(tmp_path / "absent.tsv") == []


def _write_sssom_tsv(path, rows):
    """Minimal SSSOM TSV (header + rows) for main()-level tests.

    rows: iterable of (subject_id, predicate_id, object_id).
    """
    lines = ["subject_id\tpredicate_id\tobject_id\n"]
    lines += [f"{s}\t{p}\t{o}\n" for s, p, o in rows]
    path.write_text("".join(lines))


def _patch_diff_report_default(monkeypatch, tmp_path):
    """_write_diff_report's `path` default is bound to the real DIFF_REPORT
    at module-def time, so monkeypatching the DIFF_REPORT *name* alone does
    not redirect it -- without patching the default itself, a main()-level
    test would write into this repo's real workspace/ directory."""
    monkeypatch.setattr(
        publish_sssom._write_diff_report, "__defaults__",
        (tmp_path / "diff_report.json",),
    )


def test_main_refuses_to_promote_a_widening_flip_by_default(tmp_path, monkeypatch):
    """#112 end-to-end: the CLI gate must actually fire, not just the
    diff-level classification tested above."""
    working_copy = tmp_path / "working.sssom.tsv"
    published = tmp_path / "published.sssom.tsv"
    _write_sssom_tsv(published, [("MIM:Glucose", "skos:exactMatch", "CHEBI:17234")])
    _write_sssom_tsv(working_copy, [("MIM:Glucose", "skos:closeMatch", "CHEBI:17234")])

    monkeypatch.setattr(publish_sssom, "WORKING_COPY", working_copy)
    monkeypatch.setattr(publish_sssom, "PUBLISHED", published)
    _patch_diff_report_default(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "argv", ["publish_sssom.py", "--dry-run"])

    with pytest.raises(SystemExit) as excinfo:
        publish_sssom.main()

    assert excinfo.value.code == 2


def test_main_apply_writes_a_pointer_and_counts_not_the_full_diff(tmp_path, monkeypatch):
    """#113 end-to-end: the JSONL audit line must not embed the full diff,
    and the sibling archive file it points to must actually exist and hold
    the full diff."""
    working_copy = tmp_path / "working.sssom.tsv"
    published = tmp_path / "published.sssom.tsv"
    _write_sssom_tsv(published, [("MIM:Old", "skos:exactMatch", "CHEBI:1")])
    _write_sssom_tsv(working_copy, [
        ("MIM:Old", "skos:exactMatch", "CHEBI:1"),
        ("MIM:New", "skos:exactMatch", "CHEBI:2"),
    ])
    audit_log = tmp_path / "status" / "sssom_promotions.jsonl"

    monkeypatch.setattr(publish_sssom, "WORKING_COPY", working_copy)
    monkeypatch.setattr(publish_sssom, "PUBLISHED", published)
    monkeypatch.setattr(publish_sssom, "AUDIT_LOG", audit_log)
    monkeypatch.setattr(publish_sssom, "LOCKS_DIR", tmp_path / "locks")
    # _load_lock_manager() resolves plugins/lock_manager.py via CLAW_ROOT --
    # a real checkout root, not necessarily this test file's grandparent, but
    # the two coincide in every environment this suite runs in (worktree or
    # CI checkout), and CLAW_ROOT is hardcoded to the PR author's own machine
    # path otherwise -- unpatched, this passes locally and fails on CI.
    monkeypatch.setattr(publish_sssom, "CLAW_ROOT", Path(__file__).resolve().parents[1])
    monkeypatch.setattr(publish_sssom, "_validate", lambda path: [])
    _patch_diff_report_default(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "argv", ["publish_sssom.py", "--apply"])

    publish_sssom.main()

    lines = audit_log.read_text().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert "diff" not in entry, "the full diff must not be embedded inline (#113)"
    assert entry["diff_counts"] == {
        "added": 1, "removed": 0, "respelled": 0, "flipped": 0,
        "widening_flipped": 0, "respelled_widening": 0, "total_widening": 0,
    }
    diff_file = Path(entry["diff_file"])
    assert diff_file.exists(), "diff_file must point at a file that actually exists"
    archived = json.loads(diff_file.read_text())
    assert archived["added"] == [["MIM:New", "CHEBI:2"]]
    assert published.read_bytes() == working_copy.read_bytes()


def test_main_refuses_to_promote_a_respelled_widening_flip(tmp_path, monkeypatch):
    """The exact bug this PR fixes, exercised through the CLI: before the
    fix, a row that was both re-spelled AND downgraded from skos:exactMatch
    was invisible to `flipped` (the key changed) and `respelled` (no
    predicate_id), so `main()`'s gate -- checking only `widening_flips` --
    would not have fired here. This must go through `all_widening`, not
    `widening_flips` alone, or this test would still pass on the bug."""
    working_copy = tmp_path / "working.sssom.tsv"
    published = tmp_path / "published.sssom.tsv"
    _write_sssom_tsv(published, [("MIM:Foo", "skos:exactMatch", "CHEBI:1")])
    _write_sssom_tsv(working_copy, [("MIM:foo", "skos:closeMatch", "CHEBI:1")])

    monkeypatch.setattr(publish_sssom, "WORKING_COPY", working_copy)
    monkeypatch.setattr(publish_sssom, "PUBLISHED", published)
    _patch_diff_report_default(monkeypatch, tmp_path)
    monkeypatch.setattr(sys, "argv", ["publish_sssom.py", "--dry-run"])

    with pytest.raises(SystemExit) as excinfo:
        publish_sssom.main()

    assert excinfo.value.code == 2


def test_main_proceeds_past_the_widening_gate_when_explicitly_overridden(tmp_path, monkeypatch):
    """The gate's only purpose is to be overridable with justification -- a
    boundary regression (e.g. `>=` instead of `>`, or the flag silently not
    being read) would otherwise go undetected by the refusal-path tests
    alone, since those never exercise a nonzero --allow-widening-flips."""
    working_copy = tmp_path / "working.sssom.tsv"
    published = tmp_path / "published.sssom.tsv"
    _write_sssom_tsv(published, [("MIM:Glucose", "skos:exactMatch", "CHEBI:17234")])
    _write_sssom_tsv(working_copy, [("MIM:Glucose", "skos:closeMatch", "CHEBI:17234")])

    monkeypatch.setattr(publish_sssom, "WORKING_COPY", working_copy)
    monkeypatch.setattr(publish_sssom, "PUBLISHED", published)
    _patch_diff_report_default(monkeypatch, tmp_path)
    monkeypatch.setattr(
        sys, "argv", ["publish_sssom.py", "--dry-run", "--allow-widening-flips", "1"]
    )

    publish_sssom.main()  # must not raise SystemExit -- 1 widening flip, limit 1
