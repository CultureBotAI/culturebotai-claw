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

import importlib.util
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


def write_cohort(root: Path, cohort: str, rows, *, kind="classes", template=None):
    directory = root / "proposals" / cohort
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"metpo_proposal_{kind}_robot.tsv"
    lines = ["\t".join(HEADER), "\t".join(template or TEMPLATE)]
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


def test_a_repeated_id_and_label_keeps_the_first_cohort_deterministically():
    """Two cohorts can carry the same id and label with different supporting
    columns. Dedup has to pick one, and which one must not depend on read
    order or the aggregate changes between runs for no reason.

    The first version of this file asserted additivity with two *different*
    IDs, so every dedup policy passed it -- the fixture agreed with itself.
    Here the rows share an identity and differ in `definition`, which is the
    only input where first-wins and last-wins diverge.
    """
    first = {"proposed_id": "METPO:1007001", "label": "same", "definition": "from v1",
             "parent": "METPO:1", "_mech": "t", "_cohort": "v1", "_source": "a"}
    later = {**first, "definition": "from v2", "_cohort": "v2", "_source": "b"}

    merged = fma.merged_rows([first, later], tuple(HEADER))
    assert len(merged) == 1
    assert merged[0]["definition"] == "from v1"


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
    assert "every identifier means one thing across the fleet" in rendered


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


def test_a_clean_fleet_exits_zero(monkeypatch, tmp_path):
    root = tmp_path / "m"
    write_cohort(root, "v1", [row("METPO:1007001", "a"), row("METPO:1007002", "b")])
    monkeypatch.setattr(fma, "resolve_mech_root", lambda key, claw_root: root)
    monkeypatch.setattr(fma, "load_fleet_manifest", lambda: _manifest(m="enabled"))

    assert fma.main(["--check"]) == 0


def test_check_writes_nothing(monkeypatch, tmp_path):
    root, out = tmp_path / "m", tmp_path / "out"
    write_cohort(root, "v1", [row("METPO:1007001", "a")])
    monkeypatch.setattr(fma, "resolve_mech_root", lambda key, claw_root: root)
    monkeypatch.setattr(fma, "load_fleet_manifest", lambda: _manifest(m="enabled"))

    assert fma.main(["--check", "--out", str(out)]) == 0
    assert not out.exists()


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
    assert any("equally common" in msg for msg in data["errors"].values())
