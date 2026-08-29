"""Resolve a Mech checkout root, verifying it before trusting a guess.

Nineteen scripts carried this shape:

    MIM_ROOT = Path(os.environ.get(
        "MEDIAINGREDIENTMECH_ROOT",
        REPO_ROOT.parent / "MediaIngredientMech",
    ))

The environment variable is authoritative and fine. The *fallback* is a guess:
if the variable is unset and a directory happens to sit at that sibling path,
the script operates on it without ever checking it is the repository it wanted.
A wrong or empty directory there produces a silent no-op or a write into the
wrong tree, which is the failure #161 documented for the inventory and #156 for
the classifier.

This resolves the same paths and adds the missing step: a guessed root is
accepted only when it looks like the Mech the manifest describes. An explicit
environment variable is trusted as before -- an operator naming a path has made
a decision, and second-guessing it would break legitimate layouts -- but it must
at least exist.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from . import FleetManifest, load_fleet_manifest


class MechRootError(RuntimeError):
    """A Mech checkout root could not be resolved, or is not that Mech."""


def sibling_default(mech_display_name: str, claw_root: Path) -> Path:
    """The conventional sibling checkout path this fleet has always used."""
    return Path(claw_root).resolve().parent / mech_display_name


def looks_like(root: Path, package_path: str) -> bool:
    """Whether `root` carries the package the manifest says this Mech has.

    Cheap and offline. It does not prove the checkout is the right *clone* --
    only `RepositorySettings` does that, by checking the Git origin -- but it
    is enough to reject an unrelated or empty directory sitting at the
    conventional path, which is what the bare fallback could not do.
    """
    return (Path(root) / package_path).is_dir()


def resolve_mech_root(
    key: str,
    *,
    claw_root: Path,
    environ: Mapping[str, str] | None = None,
    manifest: FleetManifest | None = None,
) -> Path:
    """The checkout root for Mech `key`, or a clear refusal.

    Order: the manifest's environment variable, then the conventional sibling
    path *if it looks like that Mech*. A guess that fails the check raises
    rather than being used, because operating on the wrong tree is worse than
    stopping.
    """
    manifest = manifest or load_fleet_manifest()
    if key not in manifest.mechs:
        raise MechRootError(
            f"unknown Mech {key!r}; the manifest declares "
            f"{', '.join(sorted(manifest.mechs))}"
        )
    mech = manifest.mechs[key]
    env = os.environ if environ is None else environ

    configured = (env.get(mech.environment_variable) or "").strip()
    if configured:
        root = Path(configured).expanduser()
        if not root.is_dir():
            raise MechRootError(
                f"{mech.environment_variable} is set to {root}, which is not a "
                f"directory"
            )
        return root.resolve()

    guess = sibling_default(mech.display_name, claw_root)
    package_path = getattr(mech, "package_path", None)
    if not guess.is_dir():
        raise MechRootError(
            f"{mech.environment_variable} is not set and no checkout is at the "
            f"conventional path {guess}. Set {mech.environment_variable}."
        )
    if package_path and not looks_like(guess, package_path):
        raise MechRootError(
            f"{mech.environment_variable} is not set and {guess} does not look "
            f"like {mech.display_name}: it has no {package_path}/. Refusing to "
            f"guess -- set {mech.environment_variable} to the right checkout."
        )
    return guess.resolve()
