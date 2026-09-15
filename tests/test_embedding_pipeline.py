"""End-to-end contracts for streaming inputs, incremental caches and publication.

Every encoder/projector in this file is a small deterministic test double.
Tests never load model weights, install optional dependencies or call services.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import math
import random
import sqlite3
from html.parser import HTMLParser
from pathlib import Path

import pytest

SOURCE = (Path(__file__).resolve().parents[1] / "src" / "kg_microbe_governance"
          / "artifacts" / "scripts" / "embedding_pipeline.py")
SPEC = importlib.util.spec_from_file_location("tested_embedding_pipeline", SOURCE)
pipeline = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pipeline)


def document(index: int, *, text: str | None = None, **changes) -> dict:
    text = f"Biological description for record {index}." if text is None else text
    return {
        "identifier": f"test:{index}", "label": f"Record {index}",
        "category": f"category-{index % 3}", "page": f"records/{index}.html",
        "source_path": f"data/records/{index}.yaml", "text": text,
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "adapter_version": "test-adapter-v1", **changes,
    }


def write_inputs(path: Path, rows: list[dict]) -> Path:
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                    encoding="utf-8")
    return path


@pytest.fixture
def profile() -> dict:
    return {
        **pipeline.encoder_profile(library_versions={"test-encoder": "1.0"}),
        "model": "tests/three-dimensional-encoder", "dimension": 3,
    }


class Encoder:
    def __init__(self):
        self.calls: list[list[str]] = []

    def __call__(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(list(texts))
        result = []
        for text in texts:
            values = [1 + value for value in hashlib.sha256(text.encode()).digest()[:3]]
            norm = math.sqrt(sum(value * value for value in values))
            result.append([value / norm for value in values])
        return result

    @property
    def texts(self):
        return [text for call in self.calls for text in call]


@pytest.fixture
def populated(tmp_path, profile):
    rows = [document(index) for index in range(17)]
    source = write_inputs(tmp_path / "input.jsonl", rows)
    cache = tmp_path / "cache.sqlite"
    encoder = Encoder()
    pipeline.populate_cache(source, cache, profile, encoder, batch_size=4)
    return source, cache, rows


def project(matrix, *, seed, neighbors):
    # A deterministic stand-in for the expensive PaCMAP operation.
    assert seed == 42
    assert 1 <= neighbors < len(matrix)
    return matrix[:, :2]


def publish(source, cache, output, profile, **options):
    return pipeline.build_map(
        source, cache, output, profile, projector=project,
        projection_versions={"test-projector": "1.0"}, **options,
    )


def test_inspection_reads_streams_and_hashes_every_middle_record(tmp_path, monkeypatch):
    rows = [document(index) for index in range(1001)]
    source = write_inputs(tmp_path / "input.jsonl", rows)
    original_open = Path.open
    reads = []

    class BoundedReader:
        def __init__(self, stream):
            self.stream = stream

        def __enter__(self):
            self.stream.__enter__()
            return self

        def __exit__(self, *args):
            return self.stream.__exit__(*args)

        def __iter__(self):
            return iter(self.stream)

        def read(self, size=-1):
            assert 0 < size <= 1024 * 1024, "input was read without a bounded chunk size"
            reads.append(size)
            return self.stream.read(size)

    def bounded_open(path, *args, **kwargs):
        stream = original_open(path, *args, **kwargs)
        return BoundedReader(stream) if path == source else stream

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", bounded_open)
        initial = pipeline.inspect_inputs(source)
    assert reads
    assert initial["count"] == 1001
    assert sum(initial["categories"].values()) == 1001
    rows[500] = document(500, text="An edited middle record with new biological meaning.")
    write_inputs(source, rows)
    changed = pipeline.inspect_inputs(source)
    assert changed["corpus_sha256"] != initial["corpus_sha256"]
    assert changed["records_sha256"] != initial["records_sha256"]
    assert changed["input_sha256"] != initial["input_sha256"]


def test_display_change_keeps_content_identity_but_invalidates_display_identity(tmp_path):
    rows = [document(index) for index in range(5)]
    source = write_inputs(tmp_path / "input.jsonl", rows)
    before = pipeline.inspect_inputs(source)
    rows[2]["label"] = "Revised display label"
    write_inputs(source, rows)
    after = pipeline.inspect_inputs(source)
    assert after["corpus_sha256"] == before["corpus_sha256"]
    assert after["records_sha256"] != before["records_sha256"]
    write_inputs(source, list(reversed(rows)))
    assert pipeline.inspect_inputs(source)["corpus_sha256"] != after["corpus_sha256"]


def test_duplicate_at_end_of_stream_is_rejected_before_encoder_or_cache(tmp_path, profile):
    rows = [document(index) for index in range(101)] + [document(0)]
    source = write_inputs(tmp_path / "input.jsonl", rows)
    encoder = Encoder()
    cache = tmp_path / "cache.sqlite"
    with pytest.raises(pipeline.ContractError, match="duplicate"):
        pipeline.populate_cache(source, cache, profile, encoder)
    assert not encoder.calls
    assert not cache.exists()


@pytest.mark.parametrize("rows", [[], [document(1), document(2, adapter_version="other")],
                                  [document(1, text_sha256="0" * 64)]])
def test_invalid_input_identity_is_rejected(tmp_path, rows):
    source = write_inputs(tmp_path / "input.jsonl", rows)
    with pytest.raises(pipeline.ContractError):
        pipeline.inspect_inputs(source)


@pytest.mark.parametrize("page", ["https://example.org/x", "//example.org/x", "/absolute",
                                  "../private", "%2e%2e/private", "dir/%2e%2e/private",
                                  "dir\\private", "javascript:alert(1)", "x\ny"])
def test_record_links_cannot_escape_the_site(tmp_path, page):
    source = write_inputs(tmp_path / "input.jsonl", [document(1, page=page)])
    with pytest.raises(pipeline.ContractError):
        pipeline.inspect_inputs(source)


def test_unchanged_cache_reuses_all_rows_and_middle_edit_encodes_only_one(populated, profile):
    source, cache, rows = populated
    encoder = Encoder()
    repeated = pipeline.populate_cache(source, cache, profile, encoder, batch_size=3)
    assert (repeated["encoded"], repeated["reused"]) == (0, len(rows))
    assert not encoder.calls
    rows[8] = document(8, text="Different middle-record meaning")
    write_inputs(source, rows)
    changed = pipeline.populate_cache(source, cache, profile, encoder, batch_size=3)
    assert (changed["encoded"], changed["reused"]) == (1, len(rows) - 1)
    assert encoder.texts == [rows[8]["text"]]
    assert changed["corpus_sha256"] != repeated["corpus_sha256"]
    rows[9]["label"] = "Only the label changed"
    write_inputs(source, rows)
    encoder.calls.clear()
    display = pipeline.populate_cache(source, cache, profile, encoder)
    assert (display["encoded"], display["reused"]) == (0, len(rows))
    assert not encoder.calls


@pytest.mark.parametrize("change", [{"revision": "a" * 40}, {"max_seq_length": 128},
                                    {"library_versions": {"test-encoder": "2.0"}}])
def test_encoder_profile_changes_never_reuse_other_profile_vectors(populated, profile, change):
    source, cache, rows = populated
    encoder = Encoder()
    result = pipeline.populate_cache(source, cache, {**profile, **change}, encoder)
    assert (result["encoded"], result["reused"]) == (len(rows), 0)
    assert encoder.texts == [row["text"] for row in rows]


@pytest.mark.parametrize("change", [{"revision": "main"}, {"revision": "abc123"},
                                    {"dimension": True}, {"dimension": 1},
                                    {"normalized": 1}, {"normalized": False},
                                    {"dtype": "object"}, {"max_seq_length": 0},
                                    {"max_seq_length": True}, {"model": ""}])
def test_invalid_profiles_fail_before_encoder(tmp_path, profile, change):
    source = write_inputs(tmp_path / "input.jsonl", [document(1)])
    encoder = Encoder()
    with pytest.raises(pipeline.ContractError):
        pipeline.populate_cache(source, tmp_path / "cache.sqlite", {**profile, **change}, encoder)
    assert not encoder.calls


@pytest.mark.parametrize("bad_vector", [[1, 0], [0, 0, 0], [1, 1, 1],
                                        [float("nan"), 0, 0], [float("inf"), 0, 0]])
def test_bad_vector_rejects_whole_batch_before_any_row_is_committed(tmp_path, profile, bad_vector):
    source = write_inputs(tmp_path / "input.jsonl", [document(1), document(2)])
    cache = tmp_path / "cache.sqlite"
    with pytest.raises(pipeline.ContractError):
        pipeline.populate_cache(source, cache, profile, lambda texts: [[1, 0, 0], bad_vector])
    encoder = Encoder()
    recovered = pipeline.populate_cache(source, cache, profile, encoder)
    assert (recovered["encoded"], recovered["reused"]) == (2, 0)


def test_encoder_wrong_row_count_is_not_a_partial_success(tmp_path, profile):
    source = write_inputs(tmp_path / "input.jsonl", [document(1), document(2)])
    cache = tmp_path / "cache.sqlite"
    with pytest.raises(pipeline.ContractError, match="number of vectors"):
        pipeline.populate_cache(source, cache, profile, lambda texts: [[1, 0, 0]])
    result = pipeline.populate_cache(source, cache, profile, Encoder())
    assert result["encoded"] == 2


def test_database_failure_rolls_back_all_rows_in_the_failed_batch(tmp_path, profile):
    rows = [document(index) for index in range(5)]
    source = write_inputs(tmp_path / "input.jsonl", rows[:1])
    cache = tmp_path / "cache.sqlite"
    pipeline.populate_cache(source, cache, profile, Encoder())
    with sqlite3.connect(cache) as db:
        db.execute("""CREATE TRIGGER fail_later_row BEFORE INSERT ON vectors
                   WHEN NEW.identifier = 'test:3'
                   BEGIN SELECT RAISE(ABORT, 'simulated storage failure'); END""")
    write_inputs(source, rows)
    with pytest.raises(sqlite3.Error, match="simulated storage failure"):
        pipeline.populate_cache(source, cache, profile, Encoder(), batch_size=4)
    with sqlite3.connect(cache) as db:
        assert db.execute("SELECT identifier FROM vectors").fetchall() == [("test:0",)]
        db.execute("DROP TRIGGER fail_later_row")
    encoder = Encoder()
    recovered = pipeline.populate_cache(source, cache, profile, encoder)
    assert (recovered["encoded"], recovered["reused"]) == (4, 1)
    assert encoder.texts == [row["text"] for row in rows[1:]]


def test_failed_later_batch_preserves_previous_verified_batch(tmp_path, profile):
    rows = [document(index) for index in range(5)]
    source = write_inputs(tmp_path / "input.jsonl", rows)
    cache = tmp_path / "cache.sqlite"
    good = Encoder()

    def fail_second_batch(texts):
        if len(good.calls) == 1:
            raise RuntimeError("simulated encoder interruption")
        return good(texts)

    with pytest.raises(RuntimeError, match="interruption"):
        pipeline.populate_cache(source, cache, profile, fail_second_batch, batch_size=2)
    recovered = pipeline.populate_cache(source, cache, profile, Encoder(), batch_size=2)
    assert (recovered["encoded"], recovered["reused"]) == (3, 2)


def test_modified_input_during_encoding_is_reported(tmp_path, profile):
    rows = [document(index) for index in range(4)]
    source = write_inputs(tmp_path / "input.jsonl", rows)
    good = Encoder()

    def edit_input_then_encode(texts):
        write_inputs(source, [*rows[:-1], document(3, text="Edited concurrently")])
        return good(texts)

    with pytest.raises(pipeline.ContractError, match="changed"):
        pipeline.populate_cache(source, tmp_path / "cache.sqlite", profile, edit_input_then_encode)


def test_corrupted_cached_vector_cannot_be_reused(populated, profile):
    source, cache, _ = populated
    with sqlite3.connect(cache) as db:
        db.execute("UPDATE vectors SET vector = ? WHERE identifier = ?", (b"corrupt", "test:3"))
    encoder = Encoder()
    with pytest.raises(pipeline.ContractError, match="checksum"):
        pipeline.populate_cache(source, cache, profile, encoder)
    assert not encoder.calls


def test_selection_is_bounded_deterministic_and_input_order_independent(tmp_path):
    rows = [document(index) for index in range(100)]
    source = write_inputs(tmp_path / "input.jsonl", rows)
    first = pipeline.select_records(source, 7, 42)
    assert len(first) == 7
    assert first == pipeline.select_records(source, 7, 42)
    random.Random(812).shuffle(rows)
    write_inputs(source, rows)
    assert first == pipeline.select_records(source, 7, 42)
    assert first == pipeline.select_records(source, 9, 42)[:7]
    assert first != pipeline.select_records(source, 7, 43)


def test_bundle_reports_complete_coverage_and_a_bounded_display(populated, tmp_path, profile):
    source, cache, rows = populated
    output = tmp_path / "site"
    captured = []

    def bounded_projector(matrix, **kwargs):
        captured.append((matrix.shape, matrix.dtype.str, kwargs))
        return project(matrix, **kwargs)

    result = pipeline.build_map(
        source, cache, output, profile, maximum=5, projector=bounded_projector,
        projection_versions={"test-projector": "1.0"},
    )
    active = pipeline.current_bundle(output)
    assert Path(result["bundle"]) == active
    manifest = pipeline.validate_bundle(active, input_path=source)
    assert captured == [((5, 3), "<f4", {"seed": 42, "neighbors": 4})]
    assert manifest["coverage"] == {
        "total": len(rows), "eligible": len(rows), "displayed": 5, "omitted": len(rows) - 5,
        "selection": "bottom-k-sha256(seed,identifier)", "maximum": 5,
    }
    assert manifest["source_vectors"]["shape"] == [5, 3]
    points = json.loads((active / "points.json").read_text())
    assert len(points) == 5
    assert all("text" not in point for point in points)
    assert "Showing 5 of 17 input records" in (active / "index.html").read_text()
    assert manifest["inputs"] == pipeline.inspect_inputs(source)


def test_unshown_records_still_require_verified_cache_coverage(populated, tmp_path, profile):
    source, cache, rows = populated
    displayed = {row["identifier"] for row in pipeline.select_records(source, 5, 42)}
    omitted = next(row["identifier"] for row in rows if row["identifier"] not in displayed)
    with sqlite3.connect(cache) as db:
        db.execute("DELETE FROM vectors WHERE identifier = ?", (omitted,))
    with pytest.raises(pipeline.ContractError, match="missing verified embedding"):
        publish(source, cache, tmp_path / "site", profile, maximum=5)
    assert not (tmp_path / "site" / "current.json").exists()


@pytest.mark.parametrize("failure", ["projector", "rename", "pointer"])
def test_interrupted_publication_preserves_previous_active_bundle(
    populated, tmp_path, profile, monkeypatch, failure,
):
    source, cache, _ = populated
    output = tmp_path / "site"
    publish(source, cache, output, profile, maximum=5)
    previous = pipeline.current_bundle(output)
    pointer = (output / "current.json").read_bytes()
    options = {}

    def fail(*args, **kwargs):
        raise OSError("simulated publication interruption")

    if failure == "projector":
        options["projector"] = fail
    elif failure == "rename":
        monkeypatch.setattr(pipeline.os, "rename", fail)
    else:
        original_replace = pipeline.os.replace

        def fail_pointer(source_path, destination):
            if Path(destination) == output / "current.json":
                return fail()
            return original_replace(source_path, destination)

        monkeypatch.setattr(pipeline.os, "replace", fail_pointer)
    with pytest.raises(OSError, match="interruption"):
        pipeline.build_map(
            source, cache, output, profile, maximum=7,
            projector=options.get("projector", project),
            projection_versions={"test-projector": "1.0"},
        )
    assert (output / "current.json").read_bytes() == pointer
    assert pipeline.current_bundle(output) == previous
    pipeline.validate_bundle(previous, input_path=source)
    assert not list(output.glob(".building-*"))


@pytest.mark.parametrize("coordinates", [[[0, 0]], [[0, 0], [0, 0], [float("nan"), 0]],
                                         [[0, 0], [0, 0], [0, float("inf")]]])
def test_invalid_projection_cannot_publish(populated, tmp_path, profile, coordinates):
    source, cache, _ = populated
    output = tmp_path / "site"
    with pytest.raises(pipeline.ContractError, match="coordinates"):
        pipeline.build_map(source, cache, output, profile, maximum=3,
                           projector=lambda matrix, **kwargs: coordinates)
    assert not (output / "current.json").exists()


def test_current_pointer_and_artifact_tampering_are_rejected(populated, tmp_path, profile):
    source, cache, _ = populated
    output = tmp_path / "site"
    publish(source, cache, output, profile)
    active = pipeline.current_bundle(output)
    points_path = active / "points.json"
    original_points = points_path.read_bytes()
    points_path.write_bytes(original_points + b" ")
    with pytest.raises(pipeline.ContractError, match="checksum"):
        pipeline.validate_bundle(active, input_path=source)
    points_path.write_bytes(original_points)
    manifest_path = active / "manifest.json"
    original_manifest = manifest_path.read_bytes()
    manifest_path.write_bytes(original_manifest + b" ")
    with pytest.raises(pipeline.ContractError, match="checksum"):
        pipeline.current_bundle(output)
    manifest_path.write_bytes(original_manifest)
    pointer = json.loads((output / "current.json").read_text())
    (output / "current.json").write_text(json.dumps({**pointer, "bundle": "../outside"}))
    with pytest.raises(pipeline.ContractError):
        pipeline.current_bundle(output)


@pytest.mark.parametrize("field", ["text", "label", "category", "adapter_version"])
def test_offline_validation_rejects_stale_semantics_or_display(populated, tmp_path, profile, field):
    source, cache, rows = populated
    output = tmp_path / "site"
    publish(source, cache, output, profile)
    active = pipeline.current_bundle(output)
    if field == "text":
        rows[8] = document(8, text="New meaning in the middle")
    elif field == "adapter_version":
        rows = [{**row, field: "test-adapter-v2"} for row in rows]
    else:
        rows[8][field] = "changed"
    write_inputs(source, rows)
    with pytest.raises(pipeline.ContractError, match="stale"):
        pipeline.validate_bundle(active, input_path=source)


class ParsedHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags = []
        self.point_payload = []
        self.in_points = False

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))
        self.in_points = tag == "script" and dict(attrs).get("id") == "points"

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_points = False

    def handle_data(self, data):
        if self.in_points:
            self.point_payload.append(data)


def test_html_escapes_title_and_record_payload_without_changing_labels(tmp_path, profile):
    injection = '</script><img src=x onerror="alert(1)"><script>'
    rows = [document(index, label=injection, text=f"Safe biological text {index}")
            for index in range(3)]
    source = write_inputs(tmp_path / "input.jsonl", rows)
    cache = tmp_path / "cache.sqlite"
    pipeline.populate_cache(source, cache, profile, Encoder())
    output = tmp_path / "site"
    publish(source, cache, output, profile, title=injection)
    html = (pipeline.current_bundle(output) / "index.html").read_text()
    parsed = ParsedHTML()
    parsed.feed(html)
    assert all(tag != "img" for tag, _ in parsed.tags)
    assert sum(tag == "script" for tag, _ in parsed.tags) == 2
    payload = json.loads("".join(parsed.point_payload))
    assert [row["label"] for row in payload] == [injection] * 3
    assert "&lt;/script&gt;" in html
    assert "\\u003c/script>" in html


def test_inspect_cli_does_not_load_model_or_write_cache(tmp_path, monkeypatch, capsys):
    source = write_inputs(tmp_path / "input.jsonl", [document(1), document(2), document(3)])

    def forbidden(*args, **kwargs):
        pytest.fail("read-only inspect loaded a model")

    monkeypatch.setattr(pipeline, "local_encoder", forbidden)
    assert pipeline.main(["inspect", "--input", str(source)]) == 0
    assert json.loads(capsys.readouterr().out)["count"] == 3
    assert set(tmp_path.iterdir()) == {source}


@pytest.mark.parametrize("field,value", [
    ("identifier", "not-in-the-current-corpus"),
    ("label", "A label belonging to a different record"),
    ("text_sha256", "0" * 64),
    ("category", "not-the-input-category"),
    ("source_path", "../outside.yaml"),
])
def test_bundle_points_are_bound_to_actual_adapter_records(
    populated, tmp_path, profile, field, value,
):
    """A checksum-consistent artifact must still describe the checked inputs.

    This reproduces a generator/mapping defect, not only a truncated file:
    recomputing the point-file checksum cannot bless a wrong record binding.
    """
    source, cache, _ = populated
    output = tmp_path / "site"
    publish(source, cache, output, profile, maximum=5)
    active = pipeline.current_bundle(output)
    points = json.loads((active / "points.json").read_text())
    points[0][field] = value
    (active / "points.json").write_text(json.dumps(points))
    manifest = json.loads((active / "manifest.json").read_text())
    manifest["files"]["points.json"] = hashlib.sha256((active / "points.json").read_bytes()).hexdigest()
    (active / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(pipeline.ContractError):
        pipeline.validate_bundle(active, input_path=source)


@pytest.mark.parametrize("section,key,value", [
    ("projection", "method", "umap"),
    ("projection", "dimensions", 3),
    ("coverage", "maximum", 3),
])
def test_bundle_rejects_inconsistent_projection_or_selection_contract(
    populated, tmp_path, profile, section, key, value,
):
    source, cache, _ = populated
    output = tmp_path / "site"
    publish(source, cache, output, profile, maximum=5)
    active = pipeline.current_bundle(output)
    manifest = json.loads((active / "manifest.json").read_text())
    manifest[section][key] = value
    (active / "manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(pipeline.ContractError):
        pipeline.validate_bundle(active, input_path=source)


def test_cached_source_vector_receipt_is_verified_against_actual_bytes(populated, tmp_path, profile):
    import struct

    source, cache, _ = populated
    output = tmp_path / "site"
    publish(source, cache, output, profile, maximum=5)
    active = pipeline.current_bundle(output)
    pipeline.validate_bundle(active, input_path=source, cache_path=cache)
    point = json.loads((active / "points.json").read_text())[0]
    replacement = struct.pack("<fff", 1.0, 0.0, 0.0)
    with sqlite3.connect(cache) as db:
        # Internally valid vector/checksum, but different from the map's receipt.
        db.execute("UPDATE vectors SET vector = ?, vector_sha256 = ? WHERE identifier = ?",
                   (replacement, hashlib.sha256(replacement).hexdigest(), point["identifier"]))
    with pytest.raises(pipeline.ContractError, match="source vector receipt"):
        pipeline.validate_bundle(active, input_path=source, cache_path=cache)


@pytest.mark.parametrize("missing", ["format_version", "pooling", "truncation",
                                    "query_instruction", "library_versions",
                                    "inference_device", "weight_dtype"])
def test_truncated_encoder_profile_cannot_be_treated_as_complete_provenance(
    tmp_path, profile, missing,
):
    source = write_inputs(tmp_path / "input.jsonl", [document(1)])
    incomplete = {key: value for key, value in profile.items() if key != missing}
    encoder = Encoder()
    with pytest.raises(pipeline.ContractError):
        pipeline.populate_cache(source, tmp_path / "cache.sqlite", incomplete, encoder)
    assert not encoder.calls


def test_unsupported_encoder_profile_format_is_rejected(tmp_path, profile):
    source = write_inputs(tmp_path / "input.jsonl", [document(1)])
    with pytest.raises(pipeline.ContractError):
        pipeline.populate_cache(source, tmp_path / "cache.sqlite",
                                {**profile, "format_version": 999}, Encoder())


def test_in_place_projector_cannot_rewrite_source_vector_receipt(populated, tmp_path, profile):
    source, cache, _ = populated
    output = tmp_path / "site"

    def in_place_projector(matrix, **kwargs):
        # Some numerical reducers center or rescale the caller's input array.
        matrix[:] = matrix[:, ::-1]
        return matrix[:, :2]

    pipeline.build_map(source, cache, output, profile, maximum=5,
                       projector=in_place_projector,
                       projection_versions={"test-projector": "1.0"})
    pipeline.validate_bundle(pipeline.current_bundle(output), input_path=source, cache_path=cache)


def test_local_encoder_applies_the_recorded_revision_and_window(monkeypatch):
    import sys
    from types import SimpleNamespace

    calls = {}

    class FakeModel:
        max_seq_length = None

        def __init__(self, name, **kwargs):
            calls["name"] = name
            calls["constructor"] = kwargs
            self.device = kwargs["device"]
            self.tokenizer = SimpleNamespace(truncation_side="left")

        def parameters(self):
            yield SimpleNamespace(dtype="torch.float32")

        def get_sentence_embedding_dimension(self):
            return 1024

        def encode(self, texts, **kwargs):
            calls["window"] = self.max_seq_length
            calls["texts"] = texts
            calls["encode"] = kwargs
            calls["truncation_side"] = self.tokenizer.truncation_side
            return "test-vector-placeholder"

    monkeypatch.setitem(sys.modules, "sentence_transformers",
                        SimpleNamespace(SentenceTransformer=FakeModel))
    monkeypatch.setattr(pipeline, "versions", lambda names: dict.fromkeys(names, "test-version"))
    profile, encoder = pipeline.local_encoder("cpu")
    assert encoder(["A biological description"]) == "test-vector-placeholder"
    assert calls["name"] == profile["model"] == "BAAI/bge-large-en-v1.5"
    assert calls["constructor"]["revision"] == profile["revision"] == (
        "d4aa6901d3a41ba39fb536a557fa166f842b0e09"
    )
    assert calls["constructor"]["trust_remote_code"] is False
    assert calls["constructor"]["device"] == "cpu"
    assert profile["inference_device"] == "cpu"
    assert profile["weight_dtype"] == "torch.float32"
    assert calls["truncation_side"] == "right"
    assert calls["window"] == profile["max_seq_length"] == 512
    assert calls["encode"]["normalize_embeddings"] is profile["normalized"] is True
    assert calls["texts"] == ["A biological description"]


def test_check_cli_needs_no_model_or_numerical_imports(populated, tmp_path, profile, monkeypatch, capsys):
    import builtins

    source, cache, _ = populated
    output = tmp_path / "site"
    publish(source, cache, output, profile, maximum=5)
    original_import = builtins.__import__

    def without_heavy_modules(name, *args, **kwargs):
        if name.split(".", 1)[0] in {"numpy", "torch", "sentence_transformers", "pacmap"}:
            pytest.fail(f"offline check imported {name}")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", without_heavy_modules)
    assert pipeline.main(["check", "--output", str(output), "--input", str(source),
                          "--cache", str(cache)]) == 0
    assert json.loads(capsys.readouterr().out)["coverage"]["displayed"] == 5


def test_actual_reducer_pair_counts_replace_requested_counts(populated, tmp_path, profile, monkeypatch):
    import sys
    from types import SimpleNamespace

    class AdjustingReducer:
        def __init__(self, **kwargs):
            assert kwargs["n_neighbors"] == 12
            assert kwargs["knn_backend"] == "faiss"

        def fit_transform(self, matrix, *, init):
            assert init == "pca"
            self.n_neighbors, self.n_MN, self.n_FP = 3, 1, 7
            return matrix[:, :2]

    monkeypatch.setitem(sys.modules, "pacmap", SimpleNamespace(PaCMAP=AdjustingReducer))
    monkeypatch.setattr(pipeline, "versions", lambda names: dict.fromkeys(names, "test-version"))
    source, cache, _ = populated
    output = tmp_path / "site"
    pipeline.build_map(source, cache, output, profile, maximum=13)
    manifest = pipeline.validate_bundle(pipeline.current_bundle(output), input_path=source)
    assert manifest["projection"]["requested_neighbors"] == 15
    assert manifest["projection"]["neighbors"] == 3
    assert manifest["projection"]["effective_pairs"] == {"neighbors": 3, "mid_near": 1, "further": 7}


def test_input_byte_receipt_cannot_describe_different_inspected_records(tmp_path, monkeypatch):
    source = write_inputs(tmp_path / "input.jsonl", [document(1), document(2)])
    original_records = pipeline.records

    def edited_after_read(path, **kwargs):
        yield from original_records(path, **kwargs)
        write_inputs(path, [document(1), document(2, text="Concurrent new text")])

    monkeypatch.setattr(pipeline, "records", edited_after_read)
    with pytest.raises(pipeline.ContractError, match="changed while inspecting"):
        pipeline.inspect_inputs(source)


@pytest.fixture
def deployable_bundle(populated, tmp_path, profile, monkeypatch):
    import sys
    from types import SimpleNamespace

    class Reducer:
        def __init__(self, **kwargs):
            pass

        def fit_transform(self, matrix, *, init):
            self.n_neighbors, self.n_MN, self.n_FP = 3, 2, 6
            return matrix[:, :2]

    monkeypatch.setitem(sys.modules, "pacmap", SimpleNamespace(PaCMAP=Reducer))
    monkeypatch.setattr(pipeline, "versions", lambda names: dict.fromkeys(names, "test-version"))
    source, cache, rows = populated
    output = tmp_path / "map-artifacts"
    pipeline.build_map(source, cache, output, profile)
    return source, output, rows


def test_site_staging_verifies_and_replaces_complete_old_directory(deployable_bundle, tmp_path):
    source, output, _ = deployable_bundle
    destination = tmp_path / "pages/text-map"
    destination.mkdir(parents=True)
    (destination / "obsolete.txt").write_text("old generation")
    manifest = pipeline.stage_map(output, destination, input_path=source)
    assert set(p.name for p in destination.iterdir()) == {"index.html", "points.json", "manifest.json"}
    assert manifest == pipeline.validate_bundle(destination, input_path=source)
    assert manifest == pipeline.validate_bundle(pipeline.current_bundle(output), input_path=source)


@pytest.mark.parametrize("failure", ["copy", "promotion"])
def test_site_staging_failure_preserves_the_previous_site(
    deployable_bundle, tmp_path, monkeypatch, failure,
):
    source, output, _ = deployable_bundle
    destination = tmp_path / "pages/text-map"
    destination.mkdir(parents=True)
    old = destination / "old-generation.html"
    old.write_bytes(b"previous verified site")
    if failure == "copy":
        original = pipeline.shutil.copyfile

        def fail_copy(src, dst):
            if Path(src).name == "points.json":
                raise OSError("interrupted copy")
            return original(src, dst)

        monkeypatch.setattr(pipeline.shutil, "copyfile", fail_copy)
    else:
        original = pipeline.os.rename

        def fail_promotion(src, dst):
            if Path(src).name.startswith(".text-map-stage-"):
                raise OSError("interrupted promotion")
            return original(src, dst)

        monkeypatch.setattr(pipeline.os, "rename", fail_promotion)
    with pytest.raises(OSError, match="interrupted"):
        pipeline.stage_map(output, destination, input_path=source)
    assert old.read_bytes() == b"previous verified site"
    assert set(p.name for p in destination.iterdir()) == {"old-generation.html"}
    assert not list(destination.parent.glob(".text-map-stage-*"))
    assert not list(destination.parent.glob(".text-map-recovery-*"))


def test_stale_bundle_never_replaces_the_previous_site(deployable_bundle, tmp_path):
    source, output, rows = deployable_bundle
    destination = tmp_path / "pages/text-map"
    destination.mkdir(parents=True)
    old = destination / "old-generation.html"
    old.write_bytes(b"previous verified site")
    rows[8] = document(8, text="New biological meaning")
    write_inputs(source, rows)
    with pytest.raises(pipeline.ContractError, match="stale"):
        pipeline.stage_map(output, destination, input_path=source)
    assert old.read_bytes() == b"previous verified site"


def test_injected_test_projector_cannot_be_staged_as_a_real_map(populated, tmp_path, profile):
    source, cache, _ = populated
    output = tmp_path / "map-artifacts"
    publish(source, cache, output, profile)
    destination = tmp_path / "pages/text-map"
    with pytest.raises(pipeline.ContractError, match="actual PaCMAP"):
        pipeline.stage_map(output, destination, input_path=source)
    assert not destination.exists()


def alternate_generation(output, *, preserve_generation_name=False):
    """Create a valid alternate-profile bundle, including updated checksums."""
    import shutil

    previous = pipeline.current_bundle(output)
    manifest = pipeline.validate_bundle(previous)
    manifest["encoder"]["model"] = "tests/alternate-valid-encoder"
    manifest["encoder_profile_sha256"] = pipeline.profile_id(manifest["encoder"])
    generation = hashlib.sha256(pipeline.canonical(manifest)).hexdigest()
    destination = previous if preserve_generation_name else output / generation
    if destination != previous:
        shutil.copytree(previous, destination)
    pipeline.atomic_json(destination / "manifest.json", manifest)
    pipeline.atomic_json(output / "current.json", {
        "bundle": destination.name,
        "manifest_sha256": pipeline.digest_file(destination / "manifest.json"),
    })
    assert pipeline.validate_bundle(destination) == manifest
    return destination


@pytest.mark.parametrize("existing_site", [False, True])
def test_preflight_generation_swap_never_writes_site(
    deployable_bundle, tmp_path, existing_site,
):
    source, output, _ = deployable_bundle
    approved = pipeline.current_bundle(output).name
    alternate = alternate_generation(output)
    assert alternate.name != approved
    destination = tmp_path / "pages/text-map"
    if existing_site:
        destination.mkdir(parents=True)
        (destination / "old.html").write_bytes(b"previous verified site")
    with pytest.raises(pipeline.ContractError, match="changed after site preflight"):
        pipeline.stage_map(output, destination, input_path=source, expected_bundle=approved)
    if existing_site:
        assert {p.name: p.read_bytes() for p in destination.iterdir()} == {
            "old.html": b"previous verified site",
        }
        assert list(destination.parent.iterdir()) == [destination]
    else:
        assert not destination.parent.exists()


def test_preflight_same_name_content_substitution_never_writes_site(deployable_bundle, tmp_path):
    source, output, _ = deployable_bundle
    approved = pipeline.current_bundle(output).name
    alternate_generation(output, preserve_generation_name=True)
    destination = tmp_path / "pages/text-map"
    with pytest.raises(pipeline.ContractError, match="immutable generation identity"):
        pipeline.stage_map(output, destination, input_path=source, expected_bundle=approved)
    assert not destination.parent.exists()


def test_preflight_unchanged_generation_can_be_staged(deployable_bundle, tmp_path):
    source, output, _ = deployable_bundle
    approved = pipeline.current_bundle(output)
    destination = tmp_path / "pages/text-map"
    manifest = pipeline.stage_map(output, destination, input_path=source,
                                  expected_bundle=approved.name)
    assert manifest == pipeline.validate_bundle(approved, input_path=source)
    assert manifest == pipeline.validate_bundle(destination, input_path=source)
