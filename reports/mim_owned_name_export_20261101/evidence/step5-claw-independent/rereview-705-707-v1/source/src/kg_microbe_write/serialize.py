"""Per-Mech record serialization (standardization Phase 3 item 4).

A shared write transaction takes pre-serialized text, so the caller chooses the
style -- and choosing wrongly is not a cosmetic mistake. CultureMech#141
measured it: writing records back at `width=120` re-wrapped every long string,
turning a two-field edit into 47 added lines, 24 of them pure noise.

The options come from the packaged manifest, and only where they were measured
to round-trip that Mech's real corpus byte-for-byte. Two Mechs have no such
option set (#187), so this refuses rather than guessing: reformatting someone
else's corpus is worse than declining to write it.
"""

from __future__ import annotations

from typing import Any

import yaml

from kg_microbe_fleet import FleetManifest, load_fleet_manifest

from .transaction import WriteError


class SerializationUnavailable(WriteError):
    """No verified emit options exist for this Mech, so nothing is serialized."""


def emit_options(
    mech_key: str, *, manifest: FleetManifest | None = None
) -> dict[str, Any]:
    """The verified emit options for `mech_key`, or a refusal."""
    manifest = manifest or load_fleet_manifest()
    mech = manifest.mechs.get(mech_key)
    if mech is None:
        raise SerializationUnavailable(
            f"unknown Mech {mech_key!r}; the manifest declares "
            f"{', '.join(sorted(manifest.mechs))}"
        )
    profile = mech.serialization
    if profile is None:
        raise SerializationUnavailable(
            f"{mech_key} declares no serialization profile; add one to the "
            f"manifest and verify it round-trips the corpus"
        )
    if not profile.verified:
        raise SerializationUnavailable(
            f"{mech_key} has no verified emit options: {profile.reason} "
            f"Writing a record back would reformat it, so this refuses rather "
            f"than guessing."
        )
    return dict(profile.options)


def dump_record(
    mech_key: str, record: Any, *, manifest: FleetManifest | None = None
) -> str:
    """Serialize `record` the way `mech_key` writes its own records."""
    return yaml.safe_dump(record, **emit_options(mech_key, manifest=manifest))
