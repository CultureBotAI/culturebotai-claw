#!/usr/bin/env python3
"""Snapshot the Biolink terms the KGX exporter maps to (#539).

    uv run python scripts/snapshot_biolink.py 4.3.6

Fetches biolink-model.yaml at the tag and writes
src/kg_microbe_kgx/data/biolink_<version>.json: every class as a
`biolink:CamelCase` category, every slot usable as an edge predicate as a
`biolink:snake_case` predicate, and each predicate's exact and narrow
mappings, so an RO or BFO predicate_id can be translated from the model's own
mappings instead of a hand-written table. The exporter and its tests read only
the snapshot; nothing fetches at run time.
"""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

import yaml

URL = "https://raw.githubusercontent.com/biolink/biolink-model/v{version}/biolink-model.yaml"
OUT = Path(__file__).resolve().parents[1] / "src" / "kg_microbe_kgx" / "data"


def camel(name: str) -> str:
    return "".join(part[:1].upper() + part[1:] for part in re.split(r"[ _]", name))


def is_predicate(name: str, slots: dict, seen: set[str] | None = None) -> bool:
    """A slot descends from `related to`, the root of Biolink's predicates."""
    seen = seen or set()
    if name == "related to":
        return True
    if name in seen or name not in slots:
        return False
    seen.add(name)
    parent = (slots[name] or {}).get("is_a")
    return bool(parent) and is_predicate(parent, slots, seen)


def main(argv: list[str]) -> int:
    version = argv[1] if len(argv) > 1 else "4.3.6"
    with urllib.request.urlopen(URL.format(version=version), timeout=60) as response:
        model = yaml.safe_load(response.read())
    classes = sorted(f"biolink:{camel(name)}" for name in model["classes"])
    slots = model["slots"]
    predicates: dict[str, list[str]] = {}
    for name, body in slots.items():
        if not is_predicate(name, slots):
            continue
        body = body or {}
        mapped = sorted({*body.get("exact_mappings", []), *body.get("narrow_mappings", [])})
        predicates[f"biolink:{name.replace(' ', '_')}"] = mapped
    OUT.mkdir(parents=True, exist_ok=True)
    target = OUT / f"biolink_{version.replace('.', '_')}.json"
    target.write_text(
        json.dumps({"version": version, "categories": classes, "predicates": predicates},
                   indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"{target.name}: {len(classes)} categories, {len(predicates)} predicates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
