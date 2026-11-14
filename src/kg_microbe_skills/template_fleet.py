"""Read-only baseline adoption/drift coverage for the existing maintenance cycle."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_fleet.roots import MechRootError, resolve_mech_root
from kg_microbe_skills.catalogue import CatalogueError
from kg_microbe_skills.template import TemplateError, plan_repository


def collect_template_drift(claw_root: Path) -> dict[str, Any]:
    """Keep unconfigured and unadopted consumers visible without inventing adoption."""
    rows: list[dict[str, Any]] = []
    for key in sorted(load_fleet_manifest().mechs):
        try:
            root = resolve_mech_root(key, claw_root=claw_root)
        except MechRootError as exc:
            rows.append({"repository": key, "status": "not_configured", "detail": str(exc)})
            continue
        config = root / "workflow/mech-template.json"
        if not config.exists() and not config.is_symlink():
            rows.append({"repository": key, "status": "not_adopted"})
            continue
        try:
            plan = plan_repository(root, source_root=claw_root)
            rows.append(plan.report)
        except (TemplateError, CatalogueError, OSError, ValueError) as exc:
            rows.append({"repository": key, "status": "error", "detail": str(exc)})
    return {
        "scope": "public_manifest",
        "private_consumers": "Run their explicit policy-bound template check separately.",
        "repositories": rows,
        "ok": all(row["status"] in {"current", "not_configured", "not_adopted"} for row in rows),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claw-root", type=Path, required=True)
    args = parser.parse_args(argv)
    report = collect_template_drift(args.claw_root.resolve())
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
