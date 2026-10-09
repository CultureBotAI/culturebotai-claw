"""Strict, lightweight registry validation; projection dependencies are optional."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path, PurePosixPath
from typing import Any

from kg_microbe_fleet import load_fleet_manifest

STATUSES = frozenset({"ready", "planned", "blocked"})
PREPROCESSING = frozenset({"none", "l2", "center_l2"})


class EmbeddingError(ValueError):
    """The input or artifact does not meet the embedding-set contract."""


def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise EmbeddingError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
    except (OSError, ValueError, UnicodeError) as exc:
        raise EmbeddingError(f"{path}: {exc}") from exc


def canonical(value: Any) -> bytes:
    return (
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
        ).encode("utf-8")
        + b"\n"
    )


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fields(value: Any, required: set[str], optional: set[str], where: str) -> dict:
    if not isinstance(value, dict):
        raise EmbeddingError(f"{where} must be an object")
    missing, extra = required - value.keys(), value.keys() - required - optional
    if missing or extra:
        raise EmbeddingError(f"{where}: missing {sorted(missing)}, unknown {sorted(extra)}")
    return value


def nonblank(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EmbeddingError(f"{where} must be a nonempty string")
    return value


def integer(value: Any, where: str, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise EmbeddingError(f"{where} must be an integer >= {minimum}")
    return value


def choice(value: Any, allowed: set | frozenset, where: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise EmbeddingError(f"{where} must be one of {sorted(allowed)}")
    return value


def identifier(value: Any, where: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{0,79}", value):
        raise EmbeddingError(f"{where} must be a lowercase identifier")
    return value


def hexadecimal(value: Any, length: int, where: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(rf"[a-f0-9]{{{length}}}", value):
        raise EmbeddingError(f"{where} must be a {length}-character lowercase hex digest")
    return value


def local_path(root: Path, value: Any) -> Path:
    nonblank(value, "artifact path")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or ".." in path.parts
        or path.as_posix() != value
        or "\\" in value
        or ":" in value
        or any(ord(c) < 32 for c in value)
        or value == "."
    ):
        raise EmbeddingError(f"artifact path must be relative and contained: {value!r}")
    resolved = (root / value).resolve()
    if not resolved.is_relative_to(root.resolve()):
        raise EmbeddingError(f"artifact path escapes registry directory: {value!r}")
    return resolved


def projection_config(value: Any) -> dict:
    fields(
        value,
        {
            "method",
            "neighbors",
            "MN_ratio",
            "FP_ratio",
            "seed",
            "init",
            "apply_pca",
            "preprocessing",
            "max_points",
        },
        set(),
        "projection",
    )
    if value["method"] != "pacmap" or value["init"] != "pca":
        raise EmbeddingError("primary projection must be pacmap with pca initialization")
    integer(value["neighbors"], "projection.neighbors", 2)
    integer(value["seed"], "projection.seed")
    if value["seed"] > 2**32 - 1:
        raise EmbeddingError("projection.seed exceeds the random-state range")
    integer(value["max_points"], "projection.max_points")
    if 0 < value["max_points"] < 10:
        raise EmbeddingError("projection.max_points must be zero (all) or at least 10")
    for key in ("MN_ratio", "FP_ratio"):
        number = value[key]
        if type(number) not in (float, int) or not math.isfinite(number) or number <= 0:
            raise EmbeddingError(f"projection.{key} must be a positive finite number")
    if type(value["apply_pca"]) is not bool:
        raise EmbeddingError("invalid apply_pca or preprocessing")
    choice(value["preprocessing"], PREPROCESSING, "projection.preprocessing")
    return value


def validate_set(item: Any) -> None:
    base = {"id", "label", "modality", "entity_type", "status"}
    ready = {"encoder", "source", "ids", "vectors", "coverage", "projection"}
    optional = {"representation"}
    fields(item, base, ready | optional | {"reason"}, "embedding set")
    identifier(item["id"], "set.id")
    for key in ("label", "entity_type"):
        nonblank(item[key], f"set.{key}")
    # Modality describes the input space; it does not select an encoder or
    # reducer. New domains can register dense vectors without a code change.
    identifier(item["modality"], "set.modality")
    if "representation" in item:
        identifier(item["representation"], "set.representation")
    choice(item["status"], STATUSES, "set.status")
    if item["status"] != "ready":
        fields(item, base | {"reason"}, optional, item["id"])
        nonblank(item["reason"], "set.reason")
        return
    fields(item, base | ready, optional, item["id"])
    encoder = fields(
        item["encoder"],
        {"name", "revision", "dimension", "input_recipe", "parameters", "library_versions"},
        set(),
        "encoder",
    )
    for key in ("name", "revision", "input_recipe"):
        nonblank(encoder[key], f"encoder.{key}")
    if encoder["revision"].strip().lower() in {
        "main",
        "master",
        "latest",
        "unknown",
        "unversioned",
    }:
        raise EmbeddingError("encoder.revision must identify an immutable model/feature release")
    integer(encoder["dimension"], "encoder.dimension", 2)
    for key in ("parameters", "library_versions"):
        if not isinstance(encoder[key], dict) or not encoder[key]:
            raise EmbeddingError(f"encoder.{key} must be a nonempty object")
        for name in encoder[key]:
            nonblank(name, f"encoder.{key} key")
    for name, value in encoder["library_versions"].items():
        nonblank(value, f"encoder.library_versions.{name}")
    source = fields(item["source"], {"revision", "input_sha256"}, set(), "source")
    hexadecimal(source["revision"], 40, "source.revision")
    hexadecimal(source["input_sha256"], 64, "source.input_sha256")
    for key in ("ids", "vectors"):
        artifact = fields(item[key], {"path", "sha256"}, set(), key)
        nonblank(artifact["path"], f"{key}.path")
        hexadecimal(artifact["sha256"], 64, f"{key}.sha256")
    coverage = fields(item["coverage"], {"total", "eligible"}, set(), "coverage")
    integer(coverage["total"], "coverage.total")
    integer(coverage["eligible"], "coverage.eligible")
    if coverage["eligible"] > coverage["total"]:
        raise EmbeddingError("coverage.eligible exceeds total")
    projection_config(item["projection"])


def load_registry(path: Path) -> dict:
    doc = fields(
        read_json(path), {"format_version", "repository", "default_set", "sets"}, set(), "registry"
    )
    if type(doc["format_version"]) is not int or doc["format_version"] != 1:
        raise EmbeddingError("unsupported registry format_version")
    repositories = {m.github for m in load_fleet_manifest().mechs.values()}
    choice(doc["repository"], repositories, "registry.repository")
    if not isinstance(doc["sets"], list) or not doc["sets"]:
        raise EmbeddingError("registry.sets must be a nonempty list")
    seen: set[str] = set()
    artifact_paths: set[Path] = set()
    for item in doc["sets"]:
        validate_set(item)
        if item["id"] in seen:
            raise EmbeddingError(f"duplicate embedding set: {item['id']}")
        seen.add(item["id"])
        if item["status"] == "ready":
            # Sharing identifiers across spaces is fine. Sharing vector files
            # would hide a model/representation collision, so require isolation.
            ids_path = local_path(path.parent, item["ids"]["path"])
            vector_path = local_path(path.parent, item["vectors"]["path"])
            if ids_path == vector_path or vector_path in artifact_paths:
                raise EmbeddingError("each ready set needs an independent vector artifact")
            artifact_paths.add(vector_path)
    choice(doc["default_set"], seen, "default_set")
    available = {item["id"] for item in doc["sets"] if item["status"] == "ready"}
    if available and doc["default_set"] not in available:
        raise EmbeddingError("default_set must be ready when ready sets exist")
    try:
        canonical(doc)
    except (TypeError, ValueError) as exc:
        raise EmbeddingError("registry must contain finite JSON values") from exc
    return doc
