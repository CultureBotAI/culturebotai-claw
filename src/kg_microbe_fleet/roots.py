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


# kg-microbe is a corpus this fleet reads, not a Mech, so the manifest has no
# row for it and `resolve_mech_root` cannot answer for it. The resolution is
# the same shape, so it lives here rather than being re-implemented by each
# caller (#131).
KG_MICROBE_VARIABLE = "KGMICROBE_ROOT"
KG_MICROBE_DIRECTORY = "kg-microbe"
KG_MICROBE_PACKAGE = "kg_microbe"


def resolve_kg_microbe_root(
    *,
    claw_root: Path,
    environ: Mapping[str, str] | None = None,
) -> Path | None:
    """kg-microbe's checkout, or None when it cannot be resolved.

    Returns rather than raises: every caller so far treats an absent corpus as
    something to report, not as a reason to stop.

    An explicit KGMICROBE_ROOT is trusted, as `resolve_mech_root` trusts a
    configured variable -- an operator naming a path has made a decision. The
    conventional sibling path is a *guess*, and is accepted only if it carries
    the `kg_microbe` package: the same check `looks_like` makes for a Mech.
    Without it, any directory sitting at ../kg-microbe was treated as the
    corpus, and anything checked against it got a verdict about the wrong
    repository.
    """
    env = os.environ if environ is None else environ
    configured = (env.get(KG_MICROBE_VARIABLE) or "").strip()
    if configured:
        root = Path(configured).expanduser()
        return root.resolve() if root.is_dir() else None

    guess = Path(claw_root).resolve().parent / KG_MICROBE_DIRECTORY
    if not (guess / KG_MICROBE_PACKAGE).is_dir():
        return None
    # .resolve() to match resolve_mech_root, which resolves its guess too. The
    # parent components are already resolved; this is the final `kg-microbe`
    # component, which can be a symlink -- and two functions of the same shape
    # handing back different paths for one checkout is how a caller ends up
    # with two roots where there is one (#330).
    return guess.resolve()


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


def require_mech_roots(
    *keys: str,
    claw_root: Path,
    environ: Mapping[str, str] | None = None,
    manifest: FleetManifest | None = None,
) -> dict[str, Path]:
    """Verify each Mech checkout before work begins, raising on the first bad one.

    Meant to be called at the top of a command, not at import. Module-level
    constants stay plain paths so importing a script for its helpers never
    requires a checkout -- five scripts import `classify_ingredient_type` for
    its regexes alone, and #147 pinned that. Verification belongs where the
    work is, which is the split #176 describes.

    A command that legitimately tolerates an absent root must NOT call this:
    `inventory_unmapped_ingredients` reports per-source coverage instead,
    because a partial inventory is a real answer there (#161).
    """
    resolved: dict[str, Path] = {}
    for key in keys:
        resolved[key] = resolve_mech_root(
            key, claw_root=claw_root, environ=environ, manifest=manifest
        )
    return resolved
