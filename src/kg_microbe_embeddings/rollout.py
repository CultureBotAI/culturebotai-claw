"""All current fleet members must have a concrete PaCMAP adoption disposition."""

from __future__ import annotations

from pathlib import Path

import yaml

from kg_microbe_fleet import UniqueKeySafeLoader, load_fleet_manifest

from .registry import MODALITIES, EmbeddingError, choice, fields, hexadecimal, identifier, nonblank


def load_rollout(path: Path | None = None) -> dict:
    path = path or Path(__file__).with_name("rollout.yaml")
    doc = yaml.load(path.read_text(encoding="utf-8"), Loader=UniqueKeySafeLoader)
    fields(
        doc,
        {"version", "checked_on", "reference", "coordination", "policy", "mechs", "acceptance"},
        set(),
        "rollout",
    )
    if type(doc["version"]) is not int or doc["version"] != 1:
        raise EmbeddingError("unsupported rollout version")
    policy = doc["policy"]
    if policy != {
        "primary_projection": "pacmap",
        "multiple_sets": True,
        "registry_adoption": "planned",
    }:
        raise EmbeddingError("fleet policy must require PaCMAP and independent embedding sets")
    if not isinstance(doc["acceptance"], list) or not doc["acceptance"]:
        raise EmbeddingError("rollout needs shared acceptance gates")
    for rule in doc["acceptance"]:
        nonblank(rule, "acceptance rule")
    manifest = load_fleet_manifest()
    if not isinstance(doc["mechs"], dict) or set(doc["mechs"]) != set(manifest.keys):
        raise EmbeddingError("rollout must cover exactly the canonical fleet; update new members")
    for key, plan in doc["mechs"].items():
        fields(plan, {"revision", "native", "evidence", "sets", "actions", "tracking"}, set(), key)
        hexadecimal(plan["revision"], 40, f"{key}.revision")
        choice(plan["native"], {"pacmap", "pca", "no_pipeline_in_audited_source"}, "native")
        for name in ("evidence", "actions", "tracking"):
            if not isinstance(plan[name], list) or not plan[name]:
                raise EmbeddingError(f"{key}.{name} must be nonempty")
            for value in plan[name]:
                nonblank(value, f"{key}.{name}")
        if not isinstance(plan["sets"], dict) or not plan["sets"]:
            raise EmbeddingError(f"{key}: declare intended embedding sets")
        modalities = set()
        for name, item in plan["sets"].items():
            identifier(name, "planned set ID")
            fields(item, {"modality", "entity_type", "state", "notes"}, set(), f"{key}.{name}")
            choice(item["modality"], MODALITIES, "modality")
            choice(item["state"], {"native", "planned", "conditional"}, "state")
            nonblank(item["entity_type"], "entity_type")
            nonblank(item["notes"], "notes")
            modalities.add(item["modality"])
        if not {"text", "protein_language_model"} <= modalities:
            raise EmbeddingError(
                f"{key}: explicitly disposition text and protein-language-model sets"
            )
    return doc
