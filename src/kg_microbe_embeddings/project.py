"""Build immutable, independently loadable map assets from registered vectors."""

from __future__ import annotations

import importlib.metadata
import os
import shutil
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .registry import (
    EmbeddingError,
    canonical,
    digest,
    load_registry,
    local_path,
    read_json,
    validate_set,
)


def verify_inputs(item: dict, root: Path) -> tuple[Path, Path]:
    paths = []
    for key in ("ids", "vectors"):
        path = local_path(root, item[key]["path"])
        if not path.is_file() or digest(path) != item[key]["sha256"]:
            raise EmbeddingError(f"{item['id']}: missing or changed {key} artifact")
        paths.append(path)
    return paths[0], paths[1]


def read_vectors(item: dict, root: Path):
    import numpy as np

    ids_path, vector_path = verify_inputs(item, root)
    ids = read_json(ids_path)
    if (
        not isinstance(ids, list)
        or not ids
        or any(not isinstance(key, str) or not key.strip() for key in ids)
    ):
        raise EmbeddingError(f"{item['id']}: ids must be a nonempty list of strings")
    if len(set(ids)) != len(ids):
        raise EmbeddingError(f"{item['id']}: duplicate entity IDs")
    try:
        vectors = np.load(vector_path, allow_pickle=False, mmap_mode="r")
    except (ValueError, OSError) as exc:
        raise EmbeddingError(f"{item['id']}: invalid NumPy vector artifact: {exc}") from exc
    if (
        not isinstance(vectors, np.ndarray)
        or vectors.ndim != 2
        or vectors.shape != (len(ids), item["encoder"]["dimension"])
        or vectors.dtype.kind not in "fiu"
    ):
        raise EmbeddingError(f"{item['id']}: vector shape/type does not match IDs and encoder")
    if len(ids) > item["coverage"]["eligible"]:
        raise EmbeddingError(f"{item['id']}: embedded count exceeds eligible coverage")
    # Bound validation memory even when the corpus has millions of rows.
    for start in range(0, len(ids), 8192):
        block = vectors[start : start + 8192]
        if not np.isfinite(block).all() or np.any(np.all(block == 0, axis=1)):
            raise EmbeddingError(f"{item['id']}: vectors must be finite and nonzero")
    return ids, vectors


def project_set(item: dict, root: Path) -> dict:
    """Project exactly one space. Cross-space nearest neighbours are undefined."""
    import numpy as np

    validate_set(item)
    if item["status"] != "ready":
        raise EmbeddingError("only a ready vector set can be projected")
    ids, vectors = read_vectors(item, root)
    config = item["projection"]
    count = len(ids)
    selected = np.arange(count)
    maximum = config["max_points"]
    if maximum and maximum < count:
        selected = np.sort(
            np.random.default_rng(config["seed"]).choice(count, maximum, replace=False)
        )
    if len(selected) < 10:
        raise EmbeddingError(
            f"{item['id']}: at least 10 embedded entities are required by the fleet "
            "projection policy; retain a blocked plan for smaller cohorts"
        )
    matrix = np.array(vectors[selected], dtype=np.float32, copy=True)
    if not np.isfinite(matrix).all():
        raise EmbeddingError(f"{item['id']}: vectors overflow float32")
    if config["preprocessing"] == "center_l2":
        matrix -= matrix.mean(axis=0, keepdims=True, dtype=np.float64).astype(np.float32)
    if config["preprocessing"] in {"l2", "center_l2"}:
        norms = np.linalg.norm(matrix.astype(np.float64), axis=1, keepdims=True)
        if np.any(norms == 0) or not np.isfinite(norms).all():
            raise EmbeddingError(f"{item['id']}: preprocessing produced invalid/zero rows")
        matrix = (matrix / norms).astype(np.float32)
    if not np.any(np.ptp(matrix, axis=0) > 0):
        raise EmbeddingError(f"{item['id']}: all prepared vectors are identical")
    # Keep enough distinct candidates for both near and further pairs. A
    # requested neighbour count is a fixed request, never an auto-scaling floor.
    neighbors = min(config["neighbors"], int((len(selected) - 1) / (1 + config["FP_ratio"])))
    if neighbors < 2 or any(
        not 1 <= round(neighbors * config[key]) <= len(selected) - 1
        for key in ("MN_ratio", "FP_ratio")
    ):
        raise EmbeddingError(f"{item['id']}: pair settings cannot fit the selected cohort")
    try:
        import pacmap
    except ImportError as exc:
        raise EmbeddingError(
            "projection requires the embeddings extra: uv sync --extra embeddings"
        ) from exc
    reducer = pacmap.PaCMAP(
        n_components=2,
        n_neighbors=neighbors,
        MN_ratio=config["MN_ratio"],
        FP_ratio=config["FP_ratio"],
        random_state=config["seed"],
        apply_pca=config["apply_pca"],
        distance="euclidean",
        knn_backend="faiss",
        lr=1.0,
        num_iters=(100, 100, 250),
    )
    coords = np.asarray(reducer.fit_transform(matrix, init=config["init"]), dtype=float)
    if coords.shape != (len(selected), 2) or not np.isfinite(coords).all():
        raise EmbeddingError(f"{item['id']}: PaCMAP returned invalid coordinates")
    verify_inputs(item, root)
    return {
        "format_version": 1,
        "set_id": item["id"],
        "label": item["label"],
        "modality": item["modality"],
        "entity_type": item["entity_type"],
        "encoder": item["encoder"],
        "source": item["source"],
        "inputs": {key: item[key] for key in ("ids", "vectors")},
        "coverage": {
            **item["coverage"],
            "embedded": count,
            "shown": len(selected),
            "sampling": "uniform_without_replacement" if len(selected) < count else "all",
        },
        "projection": {
            **config,
            "dimensions": 2,
            "implementation": "pacmap.PaCMAP",
            "effective_neighbors": int(reducer.n_neighbors),
            "effective_mid_near_pairs": int(reducer.n_MN),
            "effective_further_pairs": int(reducer.n_FP),
            "distance": "euclidean",
            "knn_backend": "faiss",
            "learning_rate": 1.0,
            "iterations": [100, 100, 250],
            "library_versions": {
                name: importlib.metadata.version(name)
                for name in ("pacmap", "numpy", "numba", "scikit-learn", "faiss-cpu")
            },
        },
        "points": [
            [ids[int(i)], float(xy[0]), float(xy[1])]
            for i, xy in zip(selected, coords, strict=True)
        ],
    }


def check_inputs(registry: Path) -> dict:
    """Check ready artifacts, including their rows, without importing PaCMAP."""
    doc = load_registry(registry)
    for item in doc["sets"]:
        if item["status"] == "ready":
            read_vectors(item, registry.parent)
    return doc


def build(registry: Path, output: Path) -> dict:
    """Build all ready sets as one release, then publish the local directory.

    The output is a new versioned directory. Existing outputs are never edited;
    the caller decides whether/when its site should adopt a completed release.
    """
    if os.path.lexists(output):
        raise EmbeddingError(f"output already exists; use a new release directory: {output}")
    before = digest(registry)
    doc = check_inputs(registry)
    if not any(item["status"] == "ready" for item in doc["sets"]):
        raise EmbeddingError("registry has no ready embedding sets to project")
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".embedding-build-", dir=output.parent))
    try:
        entries = []
        for item in doc["sets"]:
            entry = {key: item[key] for key in ("id", "label", "modality", "entity_type", "status")}
            if item["status"] == "ready":
                payload = project_set(item, registry.parent)
                relative = f"sets/{item['id']}.json"
                artifact = stage / relative
                artifact.parent.mkdir(exist_ok=True)
                artifact.write_bytes(canonical(payload))
                entry.update(
                    {
                        "path": relative,
                        "sha256": digest(artifact),
                        "encoder": payload["encoder"],
                        "coverage": payload["coverage"],
                        "projection": payload["projection"],
                    }
                )
            else:
                entry["reason"] = item["reason"]
            entries.append(entry)
        if digest(registry) != before:
            raise EmbeddingError("registry changed while building; rerun")
        # A later set can take long enough for an earlier set's inputs to drift.
        for item in doc["sets"]:
            if item["status"] == "ready":
                verify_inputs(item, registry.parent)
        index = {
            "format_version": 1,
            "repository": doc["repository"],
            "default_set": doc["default_set"],
            "registry_sha256": before,
            "generated_at_utc": datetime.now(timezone.utc).isoformat(),
            "sets": entries,
        }
        (stage / "index.json").write_bytes(canonical(index))
        if os.path.lexists(output):
            raise EmbeddingError(f"output appeared while building: {output}")
        os.rename(stage, output)
        return index
    finally:
        if stage.exists():
            shutil.rmtree(stage)
