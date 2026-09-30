"""Graph receipts describe actual source bytes and complete new output sets."""

import copy
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest

SOURCE = (
    Path(__file__).resolve().parents[1]
    / "src/kg_microbe_governance/artifacts/scripts/graph_embedding_receipts.py"
)
SPEC = importlib.util.spec_from_file_location("tested_graph_receipts", SOURCE)
receipts = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(receipts)


def source_file(path, rows):
    path.write_bytes(gzip.compress(("node\td1\td2\n" + "".join(rows)).encode(), mtime=0))
    return path


def test_source_hash_is_the_actual_compressed_stream_and_selection_is_explicit(tmp_path):
    path = source_file(
        tmp_path / "graph.tsv.gz", ["CHEBI:1\t1\t2\n", "CHEBI:2\t2\t3\n", "NCBITaxon:3\t3\t4\n"]
    )
    reader = receipts.GraphSource(path, ["CHEBI"], node_ids={"CHEBI:2"})
    assert list(reader) == [("CHEBI:2", [2.0, 3.0])]
    assert reader.receipt["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert reader.receipt["bytes"] == path.stat().st_size
    assert reader.receipt["selected_nodes"] == 1
    assert reader.receipt["selection"] == "explicit-node-ids"


def test_same_name_size_and_mtime_never_reuse_old_vectors(tmp_path):
    path = source_file(tmp_path / "graph.tsv.gz", ["CHEBI:1\t1\t2\n"])
    before = path.stat()
    first = receipts.GraphSource(path, ["CHEBI"])
    assert list(first)[0][1] == [1.0, 2.0]
    source_file(path, ["CHEBI:1\t3\t4\n"])
    assert path.stat().st_size == before.st_size
    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    second = receipts.GraphSource(path, ["CHEBI"])
    assert list(second)[0][1] == [3.0, 4.0]
    assert second.receipt["sha256"] != first.receipt["sha256"]


@pytest.mark.parametrize(
    "rows",
    [
        ["CHEBI:1\t1\t2\n", "CHEBI:1\t3\t4\n"],
        ["CHEBI:1\t1\t2\n", "CHEBI:2\t1\t2\t3\n"],
        ["CHEBI:1\tnan\t2\n"],
        ["CHEBI:1\t0\t0\n"],
        ["CHEBI:1\tnot-numeric\t2\n"],
    ],
)
def test_invalid_selected_source_rows_fail_without_a_receipt(tmp_path, rows):
    source = receipts.GraphSource(source_file(tmp_path / "bad.tsv.gz", rows), ["CHEBI"])
    with pytest.raises(ValueError):
        list(source)
    assert source.receipt is None


def test_partial_read_never_has_a_complete_receipt(tmp_path):
    source = receipts.GraphSource(
        source_file(tmp_path / "source.tsv.gz", ["CHEBI:1\t1\t2\n", "CHEBI:2\t2\t3\n"]), ["CHEBI"]
    )
    iterator = iter(source)
    next(iterator)
    iterator.close()
    assert source.receipt is None


def test_middle_corpus_file_change_and_row_order_change_are_detected(tmp_path):
    paths = []
    for index in range(7):
        path = tmp_path / f"{index}.yaml"
        path.write_text(f"id: {index}\n")
        paths.append(path)
    before = receipts.corpus_receipt(paths, tmp_path)
    paths[3].write_text("id: changed\n")
    assert receipts.corpus_receipt(paths, tmp_path)["sha256"] != before["sha256"]
    matrix = [[1, 2], [3, 4], [5, 6]]
    receipt = receipts.matrix_receipt(matrix, ["a", "b", "c"])
    assert (
        receipt["sha256"]
        != receipts.matrix_receipt(list(reversed(matrix)), ["c", "b", "a"])["sha256"]
    )
    assert (
        receipt["row_ids_sha256"]
        != receipts.matrix_receipt(matrix, ["c", "b", "a"])["row_ids_sha256"]
    )


def fixture_receipt(tmp_path):
    path = source_file(tmp_path / "source.tsv.gz", [f"CHEBI:{i}\t{i + 1}\t2\n" for i in range(3)])
    source = receipts.GraphSource(path, ["CHEBI"])
    vectors = dict(source)
    corpus = tmp_path / "record.yaml"
    corpus.write_text("id: 1\n")
    return receipts.make_receipt(
        source=source.receipt,
        corpus=receipts.corpus_receipt([corpus], tmp_path),
        ledger=[
            {"identifier": name, "source_nodes": [name], "status": "projected"} for name in vectors
        ],
        matrix=receipts.matrix_receipt(vectors.values(), vectors),
        projection={
            "method": "pacmap",
            "implementation": "pacmap.PaCMAP",
            "normalization": "l2",
            "parameters": {},
            "library_versions": {"fixture": "1"},
            "effective_pairs": {"neighbors": 1, "mid_near": 0, "further": 1},
        },
        coverage={"eligible": 3, "projected": 3},
    )


def test_publish_binds_new_bytes_and_rolls_back_on_partial_promotion(tmp_path, monkeypatch):
    receipt = fixture_receipt(tmp_path)
    staged = tmp_path / "staged.json"
    staged.write_text("[1,2,3]")
    output = tmp_path / "map.json"
    output.write_text("previous map")
    sidecar = tmp_path / "map.metadata.json"
    sidecar.write_text("previous receipt")
    original = receipts.os.replace

    def fail_receipt(src, dst):
        if Path(dst) == sidecar and Path(src).name.startswith(".graph-publish-"):
            raise OSError("receipt promotion failure")
        return original(src, dst)

    with monkeypatch.context() as patch:
        patch.setattr(receipts.os, "replace", fail_receipt)
        with pytest.raises(OSError, match="receipt promotion"):
            receipts.publish_artifacts({output: staged}, sidecar, receipt)
    assert output.read_text() == "previous map" and sidecar.read_text() == "previous receipt"
    result = receipts.publish_artifacts({output: staged}, sidecar, receipt)
    assert json.loads(sidecar.read_text()) == result
    receipts.validate_receipt(result, {"map.json": output})
    output.write_text("changed map")
    with pytest.raises(ValueError, match="checksum"):
        receipts.validate_receipt(result, {"map.json": output})


def test_legacy_source_cannot_be_blessed(tmp_path):
    with pytest.raises(ValueError, match="freshly parsed"):
        receipts.make_receipt(
            source={"filename": "old.pkl"},
            corpus={},
            ledger=[],
            matrix={},
            projection={},
            coverage={},
        )


@pytest.mark.parametrize("damage", ["coverage", "ledger", "corpus", "matrix", "reducer"])
def test_receipt_rejects_internally_inconsistent_claims(tmp_path, damage):
    value = copy.deepcopy(fixture_receipt(tmp_path))
    if damage == "coverage":
        value["coverage"]["eligible"] += 1
    elif damage == "ledger":
        value["matching"]["rows"][1]["source_nodes"] = []
        value["matching"]["sha256"] = hashlib.sha256(
            receipts.canonical(value["matching"]["rows"])
        ).hexdigest()
    elif damage == "corpus":
        value["corpus"]["files"][0]["sha256"] = "0" * 64
    elif damage == "matrix":
        value["matrix"]["row_ids"].reverse()
    else:
        value["projection"].pop("effective_pairs")
    with pytest.raises(ValueError):
        receipts._validate_core(value)


def test_publication_requires_sibling_outputs_and_refuses_receipt_symlinks(tmp_path):
    receipt = fixture_receipt(tmp_path)
    staged = tmp_path / "staged.json"
    staged.write_text("[]")
    with pytest.raises(ValueError, match="sibling"):
        receipts.publish_artifacts(
            {tmp_path / "elsewhere" / "map.json": staged}, tmp_path / "map.metadata.json", receipt
        )
    target = tmp_path / "real.json"
    target.write_text("old")
    link = tmp_path / "map.metadata.json"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="sibling"):
        receipts.publish_artifacts({tmp_path / "map.json": staged}, link, receipt)
    assert target.read_text() == "old"


def test_receipt_loader_checks_every_artifact_in_generation(tmp_path):
    receipt = fixture_receipt(tmp_path)
    a, b = tmp_path / "new-map", tmp_path / "new-neighbors"
    a.write_text("map")
    b.write_text("neighbors")
    sidecar = tmp_path / "map.metadata.json"
    receipts.publish_artifacts(
        {tmp_path / "map.json": a, tmp_path / "neighbors.json": b}, sidecar, receipt
    )
    assert receipts.load_receipt(sidecar)["coverage"]["projected"] == 3
    (tmp_path / "neighbors.json").write_text("stale neighbors")
    with pytest.raises(ValueError, match="checksum"):
        receipts.load_receipt(sidecar)


def test_named_proxy_filter_selects_only_candidates_and_reader_cannot_restart(tmp_path):
    source = receipts.GraphSource(
        source_file(tmp_path / "graph.tsv.gz", ["CHEBI:1\t1\t2\n", "CHEBI:2\t2\t3\n"]),
        ["CHEBI"],
        node_filter=lambda node: node.endswith(":2"),
        filter_name="fixture-parent-proxy-v1",
    )
    assert dict(source) == {"CHEBI:2": [2.0, 3.0]}
    assert source.receipt["filter_policy"] == "fixture-parent-proxy-v1"
    with pytest.raises(ValueError, match="single-use"):
        list(source)


def test_receipt_destination_alias_is_refused_before_any_output_changes(tmp_path):
    receipt = fixture_receipt(tmp_path)
    (tmp_path / "sub").mkdir()
    staged = tmp_path / "staged.json"
    staged.write_text("new artifact")
    sidecar = tmp_path / "map.metadata.json"
    sidecar.write_text("previous receipt")
    ordinary = tmp_path / "map.json"
    ordinary.write_text("previous graph")
    alias = tmp_path / "sub" / ".." / "map.metadata.json"
    with pytest.raises(ValueError, match="sibling"):
        receipts.publish_artifacts({ordinary: staged, alias: staged}, sidecar, receipt)
    assert ordinary.read_text() == "previous graph"
    assert sidecar.read_text() == "previous receipt"
    assert not list(tmp_path.glob(".graph-recovery-*"))


@pytest.mark.parametrize("payload", ["[]", '"not a receipt"'])
def test_receipt_loader_requires_a_json_object(tmp_path, payload):
    path = tmp_path / "map.metadata.json"
    path.write_text(payload)
    with pytest.raises(ValueError, match="JSON object"):
        receipts.load_receipt(path)
