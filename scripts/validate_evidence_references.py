#!/usr/bin/env python3
"""Compatibility entry point for the shared, offline evidence quote gate.

The default Mech is mediaingredientmech. CLI flags and report formats come from
kg_microbe_evidence; reports belong to the exact validated Mech checkout.
load_cache and normalize remain available to apply_evidence_proposals.py.
No import-time root resolution, source fetching or repair is performed.
"""
from __future__ import annotations

import re
import sys
from collections.abc import Sequence
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(REPO_ROOT / "src"), str(REPO_ROOT)]

from kg_microbe_evidence import (  # noqa: E402
    CAPABILITY,
    CachedSource,
    EvidenceConfig,
    EvidenceError,
    EvidenceValidator,
    normalize as normalize,
)

# Explicit bindings retained for the old downstream adapter. None means resolve
# through RepositorySettings when called; it never means a guessed sibling.
MIM_ROOT: Path | None = None
CACHE_DIR: Path | None = None
INGREDIENTS: Path | None = None
OUT_DIR: Path | None = None
OUT_TSV: Path | None = None
OUT_MD: Path | None = None


def _cache_validator() -> EvidenceValidator:
    if CACHE_DIR is not None:
        # An intentional import-API override, used by existing adapters/tests.
        # Keep the cache's final component unresolved so symlinks stay visible
        # to the shared parser's rejection rules.
        cache = Path(CACHE_DIR).expanduser().absolute()
        return EvidenceValidator(cache.parent, EvidenceConfig(cache.name))

    from kg_microbe_fleet import load_fleet_manifest
    from kg_microbe_fleet.roots import claw_root
    from plugins.repository_settings import (
        RepositorySettings,
        RepositoryTarget,
        merged_repository_environment,
    )

    manifest = load_fleet_manifest()
    mech = manifest.mechs["mediaingredientmech"]
    capability = mech.capability(CAPABILITY)
    if capability is None or not capability.is_enabled:
        raise EvidenceError("mediaingredientmech evidence validation is not enabled")
    config = EvidenceConfig.from_settings(capability.settings)
    if MIM_ROOT is not None:
        target = RepositoryTarget(mech.key, Path(MIM_ROOT).expanduser().resolve(), mech.github)
    else:
        dotenv = claw_root() / ".env"
        environment = merged_repository_environment(dotenv if dotenv.exists() else None)
        target = RepositorySettings.from_environment(environ=environment, manifest=manifest).get_target(mech.key)
    target.open()
    return EvidenceValidator(target.path, config)


def load_cache(pmid: str) -> str | None:
    """Return the identified abstract body, never metadata or curator notes.

    Missing, malformed, wrongly identified and symlinked cache files return
    None, preserving the import API's refusal to accept that candidate. Root
    configuration errors still raise instead of silently selecting a checkout.
    """
    if not isinstance(pmid, str) or re.fullmatch(r"[0-9]+", pmid) is None:
        return None
    source = _cache_validator()._source(pmid)
    return source.body if isinstance(source, CachedSource) else None


def main(argv: Sequence[str] | None = None) -> int:
    from kg_microbe_evidence.__main__ import main as shared_main

    arguments = ["--mech", "mediaingredientmech"]
    if MIM_ROOT is not None:
        arguments.extend(["--root", str(MIM_ROOT)])
    arguments.extend(sys.argv[1:] if argv is None else argv)
    return shared_main(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
