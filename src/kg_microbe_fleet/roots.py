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
from io import StringIO
from pathlib import Path

from dotenv import dotenv_values  # type: ignore[import-untyped]

from . import FleetManifest, load_fleet_manifest


class MechRootError(RuntimeError):
    """A Mech checkout root could not be resolved, or is not that Mech."""


def sibling_default(mech_display_name: str, claw_root: Path) -> Path:
    """The conventional sibling checkout path, as a last-resort guess.

    It was the layout every script assumed, and it is no longer the layout on
    the machine this fleet is developed on: the Mech checkouts moved out from
    beside claw on 2026-09-07 (#364). The guess is kept because it costs
    nothing -- `looks_like` refuses a directory that is not that Mech, so a
    stale convention produces a refusal rather than work on the wrong tree --
    but it is a guess, not the convention, and the configured variable or
    claw's own `.env` should answer first.
    """
    return Path(claw_root).resolve().parent / mech_display_name


def dotenv_value(claw_root: Path, variable: str) -> str:
    """One named variable from claw's own `.env`, or "".

    General by construction -- it returns whatever key it is asked for -- but
    the resolvers here only ever ask for a root variable the manifest or this
    module declares. It is not a way to load `.env` into the environment, and
    nothing here mutates `os.environ`.

    `openclaw-cli` reads `.env` through `RepositorySettings`; every
    `kg-microbe-*` console script read the bare process environment, so a
    fleet configured exactly as CLAUDE.md prescribes still refused every
    command that did not separately export it (#364). This reads the same
    file for the one variable being resolved.

    Interpolation is off for the reason `merged_repository_environment` gives:
    letting python-dotenv expand turns an unknown variable into an empty
    string, so `${MISSING}/repo` silently becomes `/repo` -- a path that could
    redirect an operation to an unintended checkout. A malformed or
    unreadable file yields "" and the caller falls through to the guess, which
    is validated; it can never yield a root that was not checked.
    """
    path = Path(claw_root) / ".env"
    try:
        if path.is_symlink() or not path.is_file():
            return ""
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return ""
    try:
        loaded = dotenv_values(stream=StringIO(text), verbose=False, interpolate=False)
    except Exception:  # pragma: no cover - python-dotenv is lenient by design
        return ""
    value = loaded.get(variable)
    return value.strip() if isinstance(value, str) else ""


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
    if not configured:
        # The same reason `resolve_mech_root` reads it (#364, #373): a fleet
        # configured in claw's `.env` is invisible to every console script
        # that reads only the process environment, and this resolver returns
        # None rather than raising, so the corpus would be reported absent.
        configured = dotenv_value(claw_root, KG_MICROBE_VARIABLE)
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
    explicit: Path | str | None = None,
) -> Path:
    """The checkout root for Mech `key`, or a clear refusal.

    Order: a path the caller was given explicitly, then the manifest's
    environment variable, then that variable in claw's own `.env`, then the
    conventional sibling path *if it looks like that Mech*. A guess that fails
    the check raises rather than being used, because operating on the wrong
    tree is worse than stopping.

    `explicit` is what the command actually parsed -- the value behind its own
    `--...-root` flag. Without it this verified the *default* location and
    refused whenever that was absent, even though the caller had named a real
    checkout on the command line and the work would never have touched the
    path being checked (#368). A caller passes it so the check covers the path
    the work will use. It is trusted exactly as a configured variable is:
    someone naming a path has made a decision, but it must exist.
    """
    manifest = manifest or load_fleet_manifest()
    if key not in manifest.mechs:
        raise MechRootError(
            f"unknown Mech {key!r}; the manifest declares "
            f"{', '.join(sorted(manifest.mechs))}"
        )
    mech = manifest.mechs[key]
    env = os.environ if environ is None else environ

    if explicit is not None and str(explicit).strip():
        root = Path(str(explicit)).expanduser()
        if not root.is_dir():
            raise MechRootError(
                f"the {mech.display_name} path given on the command line is not "
                f"a directory: {root}"
            )
        return root.resolve()

    configured = (env.get(mech.environment_variable) or "").strip()
    source = f"{mech.environment_variable} is set to"
    if not configured:
        configured = dotenv_value(claw_root, mech.environment_variable)
        source = f"{mech.environment_variable} in {claw_root}/.env is"
    if configured:
        root = Path(configured).expanduser()
        if not root.is_dir():
            raise MechRootError(f"{source} {root}, which is not a directory")
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
    explicit: Mapping[str, Path | str | None] | None = None,
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

    `explicit` maps a Mech key to the path the command parsed from its own
    flag, so the check covers the path the work will use rather than the
    default it will not (#368). A key absent from the mapping, or mapped to
    None, resolves the usual way.
    """
    given = explicit or {}
    unknown = sorted(set(given) - set(keys))
    if unknown:
        raise MechRootError(
            f"explicit paths given for {unknown}, which "
            f"{'is' if len(unknown) == 1 else 'are'} not being verified; "
            f"pass the same keys to require_mech_roots"
        )
    resolved: dict[str, Path] = {}
    for key in keys:
        resolved[key] = resolve_mech_root(
            key,
            claw_root=claw_root,
            environ=environ,
            manifest=manifest,
            explicit=given.get(key),
        )
    return resolved
