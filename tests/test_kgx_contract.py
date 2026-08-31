"""The shared KGX contract, and the two corrections measuring forced.

Proved against artifacts nobody wrote for it: CommunityMech's own
`output/kgx/{nodes,edges}.tsv` and the 1 GB kg-microbe merged edge file vendored
at `app/kgm/merged-kg_edges.tsv`. Both fail, differently, which is why a shared
validator was worth building from one implementation when a shared exporter was
not.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kg_microbe_fleet.roots import MechRootError, resolve_mech_root
from kg_microbe_kgx import (
    EDGE_REQUIRED,
    NODE_REQUIRED,
    KgxProfile,
    check_edges,
    check_graph,
    check_nodes,
    read_table,
    summarise,
)

CLAW_ROOT = Path(__file__).resolve().parents[1]
NODE_HEADER = "id\tcategory\tname\tdescription\tprovided_by"
EDGE_HEADER = "id\tsubject\tpredicate\tobject"


def write(tmp_path: Path, name: str, text: str, newline: str = "\n") -> Path:
    path = tmp_path / name
    path.write_bytes(text.replace("\n", newline).encode("utf-8"))
    return path


def codes(findings) -> list[str]:
    return [f.code for f in findings]


def test_a_well_formed_graph_reports_nothing(tmp_path: Path):
    nodes = write(tmp_path, "nodes.tsv", NODE_HEADER + "\nX:1\tbiolink:Thing\tn\td\tinfores:x\n")
    edges = write(tmp_path, "edges.tsv", EDGE_HEADER + "\ne1\tX:1\tbiolink:related_to\tX:1\n")
    assert check_graph(nodes, edges) == []


# -- the two corrections measuring forced -----------------------------------


def test_crlf_line_endings_are_a_line_ending_not_a_defect(tmp_path: Path):
    """CommunityMech's exports are CRLF throughout -- 999 CR, 999 CRLF, none
    bare. The first version of this module reported every row of a healthy file,
    which is the failure that makes a checker ignorable."""
    nodes = write(
        tmp_path,
        "nodes.tsv",
        NODE_HEADER + "\nX:1\tbiolink:Thing\tn\td\tinfores:x\n",
        newline="\r\n",
    )
    table = read_table(nodes)
    assert table.header_has_cr is False
    assert table.rows_with_cr == 0
    assert check_nodes(table) == []


def test_a_bare_carriage_return_in_the_header_is_reported(tmp_path: Path):
    """kg-microbe's merged edge file carries one in its header, right after a
    duplicated `agent_type`. awk sees eleven columns; Python's text mode ends
    the line at the CR and sees seven, so every field past it misaligns without
    any error being raised."""
    header = "id\tsubject\tpredicate\tobject\tagent_type\ragent_type"
    edges = write(tmp_path, "edges.tsv", header + "\ne\tX:1\tbiolink:r\tX:1\ta\ta\n")
    findings = check_edges(read_table(edges))
    assert "CARRIAGE_RETURN_IN_HEADER" in codes(findings)


def test_a_fragment_of_a_broken_row_is_not_judged_as_a_row(tmp_path: Path):
    """A literal newline inside a description splits one record across two
    physical lines. Judging the fragments reports the same structural break
    again as a bad id and a bad category, in language that suggests three
    separate defects."""
    text = (
        NODE_HEADER
        + "\nX:1\tbiolink:Thing\tname\tfirst half\n"
        + "second half\tinfores:x\n"
    )
    findings = check_nodes(read_table(write(tmp_path, "nodes.tsv", text)))
    assert codes(findings) == ["NEWLINE_IN_FIELD"]


def test_the_two_readers_must_agree(tmp_path: Path):
    """A quote character opens a field for the csv module and does not for
    anything that splits on newlines, so the file means two different things."""
    text = (
        NODE_HEADER
        + '\nX:1\tbiolink:Thing\tn\t"opens a quote\td\n'
        + "X:2\tbiolink:Thing\tn\tstill inside it"\
        + '\td\n'
    )
    assert "READERS_DISAGREE" in codes(
        check_nodes(read_table(write(tmp_path, "nodes.tsv", text)))
    )


# -- shape ------------------------------------------------------------------


def test_required_columns_are_a_subset_not_an_exact_list(tmp_path: Path):
    """CommunityMech writes five node columns and kg-microbe's merged graph
    writes ten. Both are valid KGX, which is why CommunityMech's own validator
    -- which matches the list exactly -- cannot check the merged file."""
    assert NODE_REQUIRED == ("id", "category")
    assert EDGE_REQUIRED == ("subject", "predicate", "object")
    wide = NODE_HEADER + "\textra\nX:1\tbiolink:Thing\tn\td\tinfores:x\tv\n"
    assert check_nodes(read_table(write(tmp_path, "nodes.tsv", wide))) == []


def test_a_missing_required_column_is_reported(tmp_path: Path):
    text = "id\tname\nX:1\tn\n"
    findings = check_nodes(read_table(write(tmp_path, "nodes.tsv", text)))
    assert "MISSING_REQUIRED_COLUMN" in codes(findings)
    assert "category" in str(findings[0])


def test_a_repeated_column_name_is_reported(tmp_path: Path):
    text = "id\tcategory\tagent_type\tagent_type\nX:1\tbiolink:T\ta\ta\n"
    assert "DUPLICATE_COLUMN" in codes(
        check_nodes(read_table(write(tmp_path, "nodes.tsv", text)))
    )


def test_an_empty_file_says_so(tmp_path: Path):
    assert codes(check_nodes(read_table(write(tmp_path, "n.tsv", "")))) == ["EMPTY_FILE"]


# -- rows -------------------------------------------------------------------


def test_an_empty_or_non_curie_identifier_is_reported(tmp_path: Path):
    text = NODE_HEADER + "\n\tbiolink:T\tn\td\tx\nnot a curie\tbiolink:T\tn\td\tx\n"
    found = codes(check_nodes(read_table(write(tmp_path, "n.tsv", text))))
    assert "EMPTY_IDENTIFIER" in found and "NOT_A_CURIE" in found


def test_a_repeated_node_id_is_reported(tmp_path: Path):
    text = NODE_HEADER + "\nX:1\tbiolink:T\tn\td\tx\nX:1\tbiolink:T\tn\td\tx\n"
    assert "DUPLICATE_NODE_ID" in codes(
        check_nodes(read_table(write(tmp_path, "n.tsv", text)))
    )


def test_an_edge_naming_an_undefined_node_is_dangling(tmp_path: Path):
    nodes = write(tmp_path, "n.tsv", NODE_HEADER + "\nX:1\tbiolink:T\tn\td\tx\n")
    edges = write(tmp_path, "e.tsv", EDGE_HEADER + "\ne\tX:1\tbiolink:r\tX:9\n")
    assert "DANGLING_EDGE" in codes(check_graph(nodes, edges))


def test_a_category_outside_biolink_is_reported_unless_declared(tmp_path: Path):
    """kg-microbe's merged graph carries METPO predicates alongside biolink
    ones. A Mech that contributes those declares them rather than being told
    it is wrong."""
    text = NODE_HEADER + "\nX:1\tMETPO:1\tn\td\tx\n"
    table = read_table(write(tmp_path, "n.tsv", text))
    assert "UNEXPECTED_CATEGORY" in codes(check_nodes(table))
    assert check_nodes(table, KgxProfile(extra_prefixes=("METPO",))) == []
    assert check_nodes(table, KgxProfile(require_biolink=False)) == []


def test_a_predicate_outside_biolink_is_reported_unless_declared(tmp_path: Path):
    """The edge half of the same rule, and the one the node test does not cover:
    kg-microbe's merged graph carries METPO predicates on 6.1M edges."""
    text = EDGE_HEADER + "\ne\tX:1\tMETPO:1\tX:1\n"
    table = read_table(write(tmp_path, "e.tsv", text))
    assert "UNEXPECTED_PREDICATE" in codes(check_edges(table))
    assert check_edges(table, profile=KgxProfile(extra_prefixes=("METPO",))) == []


# -- against the real artifacts ---------------------------------------------


def _communitymech() -> Path:
    try:
        return resolve_mech_root("communitymech", claw_root=CLAW_ROOT)
    except MechRootError as exc:  # pragma: no cover - depends on the machine
        pytest.skip(f"needs a communitymech checkout: {exc}")


def test_communitymechs_own_export_reports_what_was_measured():
    """Two findings, one root cause: nine node descriptions contain a literal
    newline, some quoted and some not."""
    root = _communitymech()
    nodes = root / "output/kgx/nodes.tsv"
    edges = root / "output/kgx/edges.tsv"
    if not nodes.is_file():
        pytest.skip("no KGX export here")
    assert summarise(check_graph(nodes, edges)) == {
        "READERS_DISAGREE": 1,
        "NEWLINE_IN_FIELD": 1,
    }


def test_the_merged_graph_header_is_the_case_this_was_built_for():
    """1 GB, 190,506 bare carriage returns and zero CRLF -- so they are not line
    endings -- plus a duplicated column name, one of the CRs sitting in the
    header itself."""
    root = _communitymech()
    path = root / "app/kgm/merged-kg_edges.tsv"
    if not path.is_file():
        pytest.skip("no vendored merged graph here")
    table = read_table(path)
    assert len(table.columns) == 11
    assert table.header_has_cr is True
    found = summarise(check_edges(table, profile=KgxProfile(extra_prefixes=("METPO",))))
    assert found["DUPLICATE_COLUMN"] == 1
    assert found["CARRIAGE_RETURN_IN_HEADER"] == 1
    assert found["READERS_DISAGREE"] == 1
