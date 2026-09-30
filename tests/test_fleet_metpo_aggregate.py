"""Guards for the METPO aggregate, aimed at where merging can mislead.

The aggregate's value is not the merged file, it is the answer to "does one
identifier mean one thing across the fleet?". So the tests that matter are the
ones about disagreement, and each fixture below is built so the two sides
*differ*:

* two cohorts proposing the same ID for different terms;
* two cohorts proposing different IDs for the same term;
* a cohort whose ROBOT template row disagrees with the fleet's;
* an unreadable Mech that must not silently vanish from the denominator.

A fixture where every cohort agrees would pass whatever the merge did, which is
the failure #286 names. The live corpus these were written against carries
eight real ID collisions, all CommunityMech's, so the collision path is the
common case rather than the exotic one.
"""

from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "fleet_metpo_aggregate", ROOT / "scripts" / "fleet_metpo_aggregate.py"
)
assert SPEC and SPEC.loader
fma = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(fma)

HEADER = ["proposed_id", "label", "definition", "parent"]
TEMPLATE = ["ID", "LABEL", "A IAO:0000115", "SC %"]


def write_cohort(
    root: Path, cohort: str, rows, *, kind="classes", header=None, template=None
):
    directory = root / "proposals" / cohort
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"metpo_proposal_{kind}_robot.tsv"
    lines = ["\t".join(header or HEADER), "\t".join(template or TEMPLATE)]
    lines += ["\t".join(row) for row in rows]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def row(proposed_id, label, definition="d", parent="METPO:1"):
    return [proposed_id, label, definition, parent]


# --------------------------------------------------------------------------
# reading a ROBOT template
# --------------------------------------------------------------------------


def test_the_template_row_is_not_read_as_a_proposed_class(tmp_path):
    """A ROBOT template's second line carries the OWL mapping for each column.
    Treating it as data emits a class whose label is literally `LABEL`, which
    only fails once it reaches the ontology."""
    path = write_cohort(tmp_path, "c1", [row("METPO:1007001", "real term")])
    header, template, data = fma.read_template(path)

    assert header == tuple(HEADER)
    assert template == tuple(TEMPLATE)
    assert [item["label"] for item in data] == ["real term"]


def test_a_short_row_is_padded_rather_than_misaligned(tmp_path):
    """A row with fewer cells than the header would otherwise zip short and
    silently shift every later column's meaning."""
    directory = tmp_path / "proposals" / "c1"
    directory.mkdir(parents=True)
    path = directory / "metpo_proposal_classes_robot.tsv"
    path.write_text(
        "\t".join(HEADER) + "\n" + "\t".join(TEMPLATE) + "\n"
        + "METPO:1007001\tterm\n",
        encoding="utf-8",
    )
    _header, _template, data = fma.read_template(path)
    assert data[0]["label"] == "term"
    assert data[0]["parent"] == ""


def test_a_file_with_no_template_row_is_refused(tmp_path):
    directory = tmp_path / "proposals" / "c1"
    directory.mkdir(parents=True)
    path = directory / "metpo_proposal_classes_robot.tsv"
    path.write_text("\t".join(HEADER) + "\n", encoding="utf-8")
    with pytest.raises(fma.AggregateError, match="ROBOT template row"):
        fma.read_template(path)


@pytest.mark.parametrize(
    "header,template,values",
    [
        (["proposed_id", "label", "label", "parent"], TEMPLATE,
         row("METPO:1007001", "term")),
        (["identifier", "label", "definition", "parent"], TEMPLATE,
         row("METPO:1007001", "term")),
        (["proposed_id", "name", "definition", "parent"], TEMPLATE,
         row("METPO:1007001", "term")),
        (HEADER, TEMPLATE, row("METPO:1007001", "term") + ["silently lost"]),
        (HEADER, ["ID", "LABEL", "A IAO:0000115"], row("METPO:1007001", "term")),
        (HEADER, ["LABEL", "ID", "A IAO:0000115", "SC %"],
         row("METPO:1007001", "term")),
        (HEADER, row("METPO:1007000", "accidental data"),
         row("METPO:1007001", "term")),
        (HEADER, TEMPLATE, row(" ", "term")),
        (HEADER, TEMPLATE, row("METPO:1007001", " ")),
    ],
    ids=[
        "duplicate-header", "missing-id-header", "missing-label-header",
        "excess-data-columns", "short-template", "swapped-identity-mapping",
        "data-in-template-row", "blank-id", "blank-label",
    ],
)
def test_malformed_templates_cannot_silently_lose_or_reinterpret_assertions(
    tmp_path, header, template, values
):
    path = write_cohort(tmp_path, "v1", [values], header=header, template=template)

    with pytest.raises(fma.AggregateError):
        fma.read_template(path)


@pytest.mark.parametrize("values", [HEADER, TEMPLATE], ids=["header", "template"])
def test_concatenated_template_headers_are_not_proposed_entities(tmp_path, values):
    path = write_cohort(tmp_path, "v1", [row("METPO:1007001", "term"), values])

    with pytest.raises(fma.AggregateError):
        fma.read_template(path)


def test_valid_quoted_multiline_assertions_are_preserved(tmp_path):
    definition = 'First line with a "quotation".\nSecond line\twith a tab.'
    path = write_cohort(tmp_path, "v1", [])
    with path.open("a", encoding="utf-8", newline="") as handle:
        csv.writer(handle, delimiter="\t").writerow(
            row("METPO:1007001", "term", definition)
        )

    _header, _template, data = fma.read_template(path)

    assert len(data) == 1
    assert data[0]["definition"] == definition


# --------------------------------------------------------------------------
# collisions -- the reason this exists
# --------------------------------------------------------------------------


def test_one_id_meaning_two_things_is_reported():
    """The live defect: METPO:1007214 is both `interspecies electron transfer`
    and `direct interspecies electron transfer community`, in two CommunityMech
    cohorts. Submitting both hands METPO contradictory definitions."""
    rows = [
        {"proposed_id": "METPO:1007214", "label": "interspecies electron transfer",
         "_mech": "communitymech", "_cohort": "interaction_v1", "_source": "a"},
        {"proposed_id": "METPO:1007214",
         "label": "direct interspecies electron transfer community",
         "_mech": "communitymech", "_cohort": "v1", "_source": "b"},
    ]
    found = fma.find_collisions(rows)
    assert found["id_means_two_things"] == {
        "METPO:1007214": [
            "direct interspecies electron transfer community",
            "interspecies electron transfer",
        ]
    }
    assert found["label_has_two_ids"] == {}


def test_one_thing_with_two_ids_is_reported_separately():
    """The opposite defect, and not the same one: downstream data splits across
    two identifiers that will never be reconciled."""
    rows = [
        {"proposed_id": "METPO:1007300", "label": "syntrophy",
         "_mech": "traitmech", "_cohort": "v1", "_source": "a"},
        {"proposed_id": "METPO:1008300", "label": "syntrophy",
         "_mech": "communitymech", "_cohort": "v1", "_source": "b"},
    ]
    found = fma.find_collisions(rows)
    assert found["label_has_two_ids"] == {
        "syntrophy": ["METPO:1007300", "METPO:1008300"]
    }
    assert found["id_means_two_things"] == {}


def test_the_same_row_in_two_cohorts_is_not_a_collision():
    """Identical ID and label proposed twice is a duplicate to merge, not a
    contradiction to refuse. Treating it as a collision would make the common
    re-proposal case fail."""
    rows = [
        {"proposed_id": "METPO:1007001", "label": "same",
         "_mech": "traitmech", "_cohort": "v1", "_source": "a"},
        {"proposed_id": "METPO:1007001", "label": "same",
         "_mech": "traitmech", "_cohort": "v2", "_source": "b"},
    ]
    found = fma.find_collisions(rows)
    assert found["id_means_two_things"] == {}
    assert found["label_has_two_ids"] == {}
    assert list(found["repeated_identical_rows"]) == ["METPO:1007001 same"]


def test_a_clean_fleet_reports_no_collision():
    rows = [
        {"proposed_id": "METPO:1007001", "label": "a", "_mech": "m",
         "_cohort": "v1", "_source": "s"},
        {"proposed_id": "METPO:1007002", "label": "b", "_mech": "m",
         "_cohort": "v1", "_source": "s"},
    ]
    found = fma.find_collisions(rows)
    assert not found["id_means_two_things"] and not found["label_has_two_ids"]


# --------------------------------------------------------------------------
# merging
# --------------------------------------------------------------------------


def test_every_cohort_contributes_because_cohorts_are_additive():
    """TraitMech's v1..v11 are separate batches, not revisions: measured on the
    live corpus the union of IDs equals the sum of per-cohort counts. Keeping
    only the newest cohort would drop 145 of its 160 classes."""
    rows = [
        {"proposed_id": "METPO:1007001", "label": "from v1", "_mech": "t",
         "_cohort": "v1", "_source": "a"},
        {"proposed_id": "METPO:1007002", "label": "from v11", "_mech": "t",
         "_cohort": "v11", "_source": "b"},
    ]
    merged = fma.merged_rows(rows, tuple(HEADER))
    assert [item["label"] for item in merged] == ["from v1", "from v11"]


@pytest.mark.parametrize("difference", [{"definition": "from v2"}, {"parent": "METPO:2"}])
def test_disagreeing_assertions_are_preserved_and_reported(difference):
    """An ID and label do not make different OWL assertions interchangeable."""
    first = {"proposed_id": "METPO:1007001", "label": "same", "definition": "from v1",
             "parent": "METPO:1", "_mech": "t", "_cohort": "v1", "_source": "a"}
    later = {**first, **difference, "_cohort": "v2", "_source": "b"}

    merged = fma.merged_rows([first, later], tuple(HEADER))
    assert len(merged) == 2
    assert merged == fma.merged_rows([later, first], tuple(HEADER))
    assert {tuple(item[name] for name in HEADER) for item in merged} == {
        tuple(item[name] for name in HEADER) for item in (first, later)
    }
    found = fma.find_collisions([first, later])
    assert "METPO:1007001 same" in found["conflicting_rows"]
    assert not found["repeated_identical_rows"]
    assert not found["id_means_two_things"]
    assert not found["label_has_two_ids"]


def test_only_complete_identical_rows_are_deduplicated():
    first = dict(zip(HEADER, row("METPO:1007001", "same")))
    rows = [
        {**first, "_mech": "m", "_cohort": "v1", "_source": "a"},
        {**first, "_mech": "n", "_cohort": "v2", "_source": "b"},
    ]

    assert fma.merged_rows(rows, tuple(HEADER)) == [first]
    found = fma.find_collisions(rows)
    assert not found["conflicting_rows"]
    assert found["repeated_identical_rows"]["METPO:1007001 same"] == ["m:v1", "n:v2"]


def test_merged_rows_are_ordered_by_id_so_two_runs_diff():
    rows = [
        {"proposed_id": "METPO:1007009", "label": "late", "_mech": "t",
         "_cohort": "v1", "_source": "a"},
        {"proposed_id": "METPO:1007001", "label": "early", "_mech": "t",
         "_cohort": "v2", "_source": "b"},
    ]
    merged = fma.merged_rows(rows, tuple(HEADER))
    assert [item["proposed_id"] for item in merged] == [
        "METPO:1007001", "METPO:1007009"
    ]


def test_the_aggregate_carries_the_template_row_exactly_once(tmp_path):
    """ROBOT reads line two as the template. A second copy further down would
    be interpreted as a class."""
    data = {
        "mechs_declaring": ["t"], "mechs_read": ["t"],
        "cohorts": {"t": ["v1", "v2"]},
        "rows": {
            "classes": [
                {"proposed_id": "METPO:1007001", "label": "a", "definition": "d",
                 "parent": "METPO:1", "_mech": "t", "_cohort": "v1", "_source": "x"},
                {"proposed_id": "METPO:1007002", "label": "b", "definition": "d",
                 "parent": "METPO:1", "_mech": "t", "_cohort": "v2", "_source": "y"},
            ],
            "properties": [],
        },
        "shape": {"classes": {"header": tuple(HEADER), "template": tuple(TEMPLATE)}},
        "errors": {},
    }
    written = fma.write_aggregate(data, tmp_path)
    aggregate = next(p for p in written if p.name.endswith("classes_robot.tsv"))
    lines = aggregate.read_text(encoding="utf-8").splitlines()

    assert lines[0].split("\t") == HEADER
    assert lines[1].split("\t") == TEMPLATE
    assert sum(1 for line in lines if line.split("\t") == TEMPLATE) == 1
    assert len(lines) == 4


def test_provenance_records_every_cohort_a_row_came_from(tmp_path):
    """The merged file loses which cohort proposed what; without provenance a
    collision cannot be traced back to a repository to fix."""
    data = {
        "mechs_declaring": ["t"], "mechs_read": ["t"], "cohorts": {"t": ["v1", "v2"]},
        "rows": {"classes": [
            {"proposed_id": "METPO:1007001", "label": "a", "_mech": "t",
             "_cohort": "v1", "_source": "proposals/v1/x.tsv"},
            {"proposed_id": "METPO:1007001", "label": "a", "_mech": "t",
             "_cohort": "v2", "_source": "proposals/v2/x.tsv"},
        ], "properties": []},
        "shape": {"classes": {"header": tuple(HEADER), "template": tuple(TEMPLATE)}},
        "errors": {},
    }
    written = fma.write_aggregate(data, tmp_path)
    provenance = next(p for p in written if p.name.endswith("provenance.tsv"))
    body = provenance.read_text(encoding="utf-8").splitlines()

    assert body[0].split("\t") == list(fma.PROVENANCE_COLUMNS)
    assert len(body) == 3, "both cohorts must appear even though they merge to one row"


# --------------------------------------------------------------------------
# collect: membership, template disagreement, and the denominator
# --------------------------------------------------------------------------


class _Mech:
    def __init__(self, status, settings=None):
        self.status = status
        self.settings = settings or {}
        self.reason_claims = None


class _Manifest:
    def __init__(self, mechs):
        self.mechs = mechs


def _manifest(**statuses):
    return _Manifest({
        key: type("M", (), {"capabilities": {fma.CAPABILITY: _Mech(status)}})()
        for key, status in statuses.items()
    })


def test_only_mechs_the_manifest_enables_are_read(monkeypatch, tmp_path):
    """Membership is the manifest's to decide. A list in the script would be
    the drift #131 exists to remove."""
    enabled, disabled = tmp_path / "on", tmp_path / "off"
    for root in (enabled, disabled):
        write_cohort(root, "v1", [row("METPO:1007001", "term")])
    monkeypatch.setattr(
        fma, "resolve_mech_root",
        lambda key, claw_root: enabled if key == "on" else disabled,
    )
    data = fma.collect(_manifest(on="enabled", off="disabled"), claw_root=tmp_path)

    assert data["mechs_declaring"] == ["on"]
    assert data["mechs_read"] == ["on"]
    assert len(data["rows"]["classes"]) == 1


def test_legacy_synonyms_and_extended_class_templates_merge_without_shape_errors(
    monkeypatch, tmp_path
):
    """The eleven-column template and its related-synonym extension coexist.

    A single extended cohort must not be dropped as a minority schema, and
    adding its optional column must not change the meaning of exact synonyms.
    """
    root = tmp_path / "m"
    header = HEADER + [
        "synonyms", "examples", "source", "comment", "creator", "date", "subsets"
    ]
    template = TEMPLATE + [
        "A oboInOwl:hasExactSynonym SPLIT=|", "A IAO:0000112", "A dcterms:source",
        "A rdfs:comment", "A dcterms:creator", "A dcterms:date", "A oboInOwl:inSubset",
    ]
    assert len(header) == 11
    write_cohort(
        root, "legacy", [row("METPO:1007001", "legacy term") + ["exact old"] + [""] * 6],
        header=header, template=template,
    )
    extended_header = ["exact_synonyms" if name == "synonyms" else name for name in header]
    extended_header.append("related_synonyms")
    write_cohort(
        root, "extended",
        [row("METPO:1007002", "extended term") + ["exact new"] + [""] * 6 + ["related new"]],
        header=extended_header,
        template=template + ["A oboInOwl:hasRelatedSynonym SPLIT=|"],
    )
    monkeypatch.setattr(fma, "resolve_mech_root", lambda key, claw_root: root)

    data = fma.collect(_manifest(m="enabled"), claw_root=tmp_path)

    assert not data["errors"]
    assert data["shape"]["classes"]["header"] == tuple(extended_header)
    by_label = {item["label"]: item for item in data["rows"]["classes"]}
    assert set(by_label) == {"legacy term", "extended term"}
    assert by_label["legacy term"]["exact_synonyms"] == "exact old"
    assert by_label["legacy term"]["related_synonyms"] == ""
    assert by_label["extended term"]["exact_synonyms"] == "exact new"
    assert by_label["extended term"]["related_synonyms"] == "related new"


def test_ambiguous_legacy_and_new_synonym_columns_are_refused(tmp_path):
    path = write_cohort(
        tmp_path, "v1", [row("METPO:1007001", "term") + ["one", "two"]],
        header=HEADER + ["synonyms", "exact_synonyms"],
        template=TEMPLATE + ["A oboInOwl:hasExactSynonym SPLIT=|"] * 2,
    )

    with pytest.raises(fma.AggregateError):
        fma.read_template(path)


def test_enabled_proposer_with_no_templates_is_incomplete(monkeypatch, tmp_path):
    root = tmp_path / "m"
    root.mkdir()
    monkeypatch.setattr(fma, "resolve_mech_root", lambda key, claw_root: root)
    monkeypatch.setattr(fma, "load_fleet_manifest", lambda: _manifest(m="enabled"))

    data = fma.collect(claw_root=tmp_path)

    assert data["mechs_declaring"] == ["m"]
    assert "m" in data["errors"]
    assert not any(data["rows"].values())
    assert fma.main(["--check"]) == 1


def test_a_cohort_whose_template_row_disagrees_is_refused_not_merged(
    monkeypatch, tmp_path
):
    """Merging templates that disagree would misalign columns: the aggregate
    would look fine and mean something else. Driven by a second cohort whose
    template differs in exactly one cell."""
    root = tmp_path / "m"
    # `bad` sorts before both `good` cohorts, so a first-file-wins rule would
    # crown the deviation and refuse the majority. That is what the first
    # version of collect() did.
    write_cohort(root, "good1", [row("METPO:1007001", "kept")])
    write_cohort(root, "good2", [row("METPO:1007003", "kept too")])
    write_cohort(
        root, "bad", [row("METPO:1007002", "dropped")],
        template=["ID", "LABEL", "A IAO:0000115", "SC PARENT"],
    )
    monkeypatch.setattr(fma, "resolve_mech_root", lambda key, claw_root: root)
    data = fma.collect(_manifest(m="enabled"), claw_root=tmp_path)

    labels = sorted(item["label"] for item in data["rows"]["classes"])
    assert labels == ["kept", "kept too"], "the majority shape must survive"
    assert any("template shape differs" in msg for msg in data["errors"].values())


def test_an_unresolvable_mech_is_named_and_the_result_marked_incomplete(
    monkeypatch, tmp_path
):
    """A repository that could not be read must not read as a repository with
    no proposals; that is the denominator failure every fleet report here is
    shaped around."""
    def explode(key, claw_root):
        raise fma.MechRootError(f"{key} is not configured")

    monkeypatch.setattr(fma, "resolve_mech_root", explode)
    data = fma.collect(_manifest(m="enabled"), claw_root=tmp_path)

    assert "m" in data["errors"]
    assert data["mechs_read"] == []
    rendered = fma.render(data, {kind: fma.find_collisions([]) for kind in fma.KINDS})
    assert "INCOMPLETE" in rendered
    assert "lower bound" in rendered


def test_render_names_a_clean_fleet_explicitly():
    """Silence must not be the way "no collisions" is communicated."""
    data = {
        "mechs_declaring": ["m"], "mechs_read": ["m"], "cohorts": {"m": ["v1"]},
        "rows": {"classes": [
            {"proposed_id": "METPO:1007001", "label": "a", "_mech": "m",
             "_cohort": "v1", "_source": "s"}], "properties": []},
        "shape": {}, "errors": {},
    }
    rendered = fma.render(
        data, {kind: fma.find_collisions(data["rows"][kind]) for kind in fma.KINDS}
    )
    assert "none in the rows read" in rendered


# --------------------------------------------------------------------------
# exit codes
# --------------------------------------------------------------------------


def test_a_collision_exits_nonzero(monkeypatch, tmp_path):
    """A merged file nobody should submit must not report success."""
    root = tmp_path / "m"
    write_cohort(root, "v1", [row("METPO:1007214", "one thing")])
    write_cohort(root, "v2", [row("METPO:1007214", "another thing")])
    monkeypatch.setattr(fma, "resolve_mech_root", lambda key, claw_root: root)
    monkeypatch.setattr(fma, "load_fleet_manifest", lambda: _manifest(m="enabled"))

    assert fma.main(["--check"]) == 1


@pytest.mark.parametrize("difference", [{"definition": "changed"}, {"parent": "METPO:2"}])
def test_conflicting_assertions_alone_block_main(monkeypatch, tmp_path, difference):
    root = tmp_path / "m"
    first = dict(zip(HEADER, row("METPO:1007001", "same")))
    later = {**first, **difference}
    write_cohort(root, "v1", [[first[name] for name in HEADER]])
    write_cohort(root, "v2", [[later[name] for name in HEADER]])
    monkeypatch.setattr(fma, "resolve_mech_root", lambda key, claw_root: root)
    monkeypatch.setattr(fma, "load_fleet_manifest", lambda: _manifest(m="enabled"))

    assert fma.main(["--check"]) == 1


def test_a_shared_id_across_classes_and_properties_blocks_main(monkeypatch, tmp_path):
    root = tmp_path / "m"
    for kind in ("classes", "properties"):
        write_cohort(root, "v1", [row("METPO:1007001", "same")], kind=kind)
    monkeypatch.setattr(fma, "resolve_mech_root", lambda key, claw_root: root)
    monkeypatch.setattr(fma, "load_fleet_manifest", lambda: _manifest(m="enabled"))

    data = fma.collect(claw_root=tmp_path)

    assert not data["errors"]
    assert "METPO:1007001" in fma.find_kind_collisions(data)
    assert fma.main(["--check"]) == 1


def test_a_clean_fleet_exits_zero(monkeypatch, tmp_path):
    root = tmp_path / "m"
    write_cohort(root, "v1", [row("METPO:1007001", "a"), row("METPO:1007002", "b")])
    monkeypatch.setattr(fma, "resolve_mech_root", lambda key, claw_root: root)
    monkeypatch.setattr(fma, "load_fleet_manifest", lambda: _manifest(m="enabled"))

    assert fma.main(["--check"]) == 0


@pytest.mark.parametrize("failure", ["unterminated-quote", "oversized-field"])
def test_csv_failure_replaces_previous_clean_report_with_incomplete_result(
    monkeypatch, tmp_path, capsys, failure
):
    root, out = tmp_path / "m", tmp_path / "out"
    path = write_cohort(root, "v1", [row("METPO:1007001", "term")])
    monkeypatch.setattr(fma, "resolve_mech_root", lambda key, claw_root: root)
    monkeypatch.setattr(fma, "load_fleet_manifest", lambda: _manifest(m="enabled"))
    assert fma.main(["--out", str(out)]) == 0
    report_path = out / "metpo_fleet_aggregate_report.json"
    assert json.loads(report_path.read_text())["merge_status"] == "clean"
    capsys.readouterr()
    if failure == "unterminated-quote":
        # A permissive CSV reader absorbs the second proposal into the first
        # definition and reports one accepted proposal instead of two.
        invalid_rows = (
            'METPO:1007001\tterm\t"unfinished definition\tMETPO:1\n'
            'METPO:1007002\tsecond term\tother definition\tMETPO:1\n'
        )
    else:
        invalid_rows = "\t".join(
            row("METPO:1007001", "term", "x" * (csv.field_size_limit() + 1))
        ) + "\n"
    path.write_text(
        "\t".join(HEADER) + "\n" + "\t".join(TEMPLATE) + "\n" + invalid_rows,
        encoding="utf-8",
    )

    assert fma.main(["--json", "--out", str(out)]) == 1

    report = json.loads(capsys.readouterr().out)
    assert report == json.loads(report_path.read_text())
    assert report["merge_status"] == "blocked"
    assert "invalid TSV" in report["errors"]["m:v1:classes"]
    assert report["counts"]["classes"] == 0
    assert not report["sources"]
    assert "INCOMPLETE" in (out / "proposal.md").read_text()
    assert not (out / "metpo_fleet_aggregate_classes_robot.tsv").exists()


@pytest.mark.parametrize("source_column", ["_mech", "_cohort", "_source", "_custom"])
def test_reserved_source_columns_cannot_hide_conflicting_assertions(
    monkeypatch, tmp_path, capsys, source_column
):
    root, out = tmp_path / "m", tmp_path / "out"
    for cohort, assertion in (("v1", "first assertion"), ("v2", "different assertion")):
        write_cohort(
            root, cohort, [row("METPO:1007001", "same term") + [assertion]],
            header=HEADER + [source_column], template=TEMPLATE + ["A rdfs:comment"],
        )
    monkeypatch.setattr(fma, "resolve_mech_root", lambda key, claw_root: root)
    monkeypatch.setattr(fma, "load_fleet_manifest", lambda: _manifest(m="enabled"))

    assert fma.main(["--json", "--out", str(out)]) == 1

    report = json.loads(capsys.readouterr().out)
    assert report["merge_status"] == "blocked"
    assert set(report["errors"]) == {"m:v1:classes", "m:v2:classes"}
    assert all("reserved" in error for error in report["errors"].values())
    assert report["counts"]["classes"] == 0
    assert not (out / "metpo_fleet_aggregate_classes_robot.tsv").exists()


def test_check_writes_nothing(monkeypatch, tmp_path):
    root, out = tmp_path / "m", tmp_path / "out"
    write_cohort(root, "v1", [row("METPO:1007001", "a")])
    monkeypatch.setattr(fma, "resolve_mech_root", lambda key, claw_root: root)
    monkeypatch.setattr(fma, "load_fleet_manifest", lambda: _manifest(m="enabled"))

    assert fma.main(["--check", "--out", str(out)]) == 0
    assert not out.exists()


@pytest.mark.parametrize("blocked", [False, True], ids=["clean", "blocked"])
def test_check_does_not_modify_existing_outputs(monkeypatch, tmp_path, blocked):
    root, out = tmp_path / "m", tmp_path / "out"
    write_cohort(root, "v1", [row("METPO:1007001", "a")])
    if blocked:
        write_cohort(root, "v2", [row("METPO:1007001", "different")])
    out.mkdir()
    for name in (
        "metpo_fleet_aggregate_report.json", "proposal.md",
        "metpo_fleet_aggregate_classes_robot.tsv",
        "metpo_fleet_aggregate_properties_robot.tsv",
    ):
        (out / name).write_text("previous output\n", encoding="utf-8")
    before = {path.name: path.read_bytes() for path in out.iterdir()}
    monkeypatch.setattr(fma, "resolve_mech_root", lambda key, claw_root: root)
    monkeypatch.setattr(fma, "load_fleet_manifest", lambda: _manifest(m="enabled"))

    assert fma.main(["--check", "--json", "--out", str(out)]) == int(blocked)
    assert {path.name: path.read_bytes() for path in out.iterdir()} == before


@pytest.mark.parametrize("case", ["clean", "conflict", "invalid", "empty"])
def test_main_persists_review_reports_even_when_inputs_block_the_merge(
    monkeypatch, tmp_path, case
):
    root, out = tmp_path / "m", tmp_path / "out"
    root.mkdir()
    if case != "empty":
        write_cohort(root, "v1", [row("METPO:1007001", "term")])
    if case == "conflict":
        write_cohort(root, "v2", [row("METPO:1007001", "term", "different definition")])
    elif case == "invalid":
        write_cohort(root, "v1", [row("", "term")])
    monkeypatch.setattr(fma, "resolve_mech_root", lambda key, claw_root: root)
    monkeypatch.setattr(fma, "load_fleet_manifest", lambda: _manifest(m="enabled"))

    assert fma.main(["--out", str(out)]) == (0 if case == "clean" else 1)

    reports = list(out.glob("*.json"))
    assert len(reports) == 1
    report = json.loads(reports[0].read_text(encoding="utf-8"))
    narrative = (out / "proposal.md").read_text(encoding="utf-8")
    assert narrative.strip()
    assert report["mechs_declaring"] == ["m"]
    if case in ("invalid", "empty"):
        assert report["errors"]
        assert "INCOMPLETE" in narrative
    elif case == "conflict":
        assert "METPO:1007001 term" in report["collisions"]["classes"]["conflicting_rows"]
        assert "METPO:1007001" in narrative
        aggregate = out / "metpo_fleet_aggregate_classes_robot.tsv"
        _header, _template, rows = fma.read_template(aggregate)
        assert {item["definition"] for item in rows} == {"d", "different definition"}
    else:
        assert not report["errors"]


@pytest.mark.parametrize("remaining_kind", ["classes", "properties", None])
def test_new_run_removes_only_stale_generated_templates(
    monkeypatch, tmp_path, remaining_kind
):
    root, out = tmp_path / "m", tmp_path / "out"
    sources = {
        kind: write_cohort(root, "v1", [row(proposed_id, label)], kind=kind)
        for kind, proposed_id, label in (
            ("classes", "METPO:1007001", "term"),
            ("properties", "METPO:2007001", "relation"),
        )
    }
    monkeypatch.setattr(fma, "resolve_mech_root", lambda key, claw_root: root)
    monkeypatch.setattr(fma, "load_fleet_manifest", lambda: _manifest(m="enabled"))
    assert fma.main(["--out", str(out)]) == 0
    generated = {
        kind: out / f"metpo_fleet_aggregate_{kind}_robot.tsv" for kind in sources
    }
    assert all(path.exists() for path in generated.values())
    unrelated = out / "reviewer-notes.md"
    unrelated.write_text("Keep the curator's notes.\n", encoding="utf-8")
    for kind, source in sources.items():
        if kind != remaining_kind:
            source.unlink()

    assert fma.main(["--out", str(out)]) == (1 if remaining_kind is None else 0)

    for kind, path in generated.items():
        assert path.exists() == (kind == remaining_kind)
    assert unrelated.read_text(encoding="utf-8") == "Keep the curator's notes.\n"
    report = json.loads(next(out.glob("*.json")).read_text(encoding="utf-8"))
    assert report["counts"] == {
        kind: int(kind == remaining_kind) for kind in sources
    }
    assert (out / "proposal.md").is_file()


def test_no_majority_shape_refuses_rather_than_picking_one(monkeypatch, tmp_path):
    """Two shapes, one cohort each. There is no basis for calling either the
    deviation, so choosing would be arbitrary and silently wrong."""
    root = tmp_path / "m"
    write_cohort(root, "a", [row("METPO:1007001", "one")])
    write_cohort(
        root, "b", [row("METPO:1007002", "two")],
        template=["ID", "LABEL", "A IAO:0000115", "SC PARENT"],
    )
    monkeypatch.setattr(fma, "resolve_mech_root", lambda key, claw_root: root)
    data = fma.collect(_manifest(m="enabled"), claw_root=tmp_path)

    assert data["rows"]["classes"] == []
    assert "classes:shape" in data["errors"]


def test_a_plurality_of_template_shapes_is_not_a_strict_majority(monkeypatch, tmp_path):
    """Two of four agreeing cohorts cannot dictate the other two's semantics."""
    root = tmp_path / "m"
    write_cohort(root, "a", [row("METPO:1007001", "first")])
    write_cohort(root, "b", [row("METPO:1007002", "second")])
    write_cohort(
        root, "c", [row("METPO:1007003", "third")],
        template=["ID", "LABEL", "A IAO:0000115", "SC PARENT"],
    )
    write_cohort(
        root, "d", [row("METPO:1007004", "fourth")],
        template=["ID", "LABEL", "A IAO:0000115", "SC SOME %"],
    )
    monkeypatch.setattr(fma, "resolve_mech_root", lambda key, claw_root: root)

    data = fma.collect(_manifest(m="enabled"), claw_root=tmp_path)

    assert "classes:shape" in data["errors"]
    assert not data["rows"]["classes"]
    assert "classes" not in data["shape"]


def test_failed_report_write_cannot_leave_a_stale_clean_verdict(monkeypatch, tmp_path):
    root, out = tmp_path / "m", tmp_path / "out"
    write_cohort(root, "v1", [row("METPO:1007001", "term")])
    monkeypatch.setattr(fma, "resolve_mech_root", lambda key, claw_root: root)
    monkeypatch.setattr(fma, "load_fleet_manifest", lambda: _manifest(m="enabled"))
    assert fma.main(["--out", str(out)]) == 0
    report_path = out / "metpo_fleet_aggregate_report.json"
    assert json.loads(report_path.read_text())["merge_status"] == "clean"
    write_cohort(root, "v2", [row("METPO:1007001", "conflicting term")])
    original = Path.write_text

    def fail_report(path, *args, **kwargs):
        if path == report_path:
            raise PermissionError("report unavailable")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_report)
    assert fma.main(["--out", str(out)]) == 2
    assert not report_path.exists()


def test_cross_kind_collision_does_not_print_a_clean_verdict():
    data = {
        "rows": {kind: [{"proposed_id": "METPO:1007001", "label": "term",
                         "_mech": "m", "_cohort": "v1", "_source": "s"}]
                 for kind in fma.KINDS},
        "cohorts": {"m": ["v1"]}, "errors": {},
        "mechs_declaring": ["m"], "mechs_read": ["m"],
    }
    rendered = fma.render(data, {kind: fma.find_collisions(rows)
                                 for kind, rows in data["rows"].items()})
    assert "CLASS/PROPERTY ID REUSE" in rendered
    assert "none in the rows read" not in rendered
