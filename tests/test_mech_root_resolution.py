"""Resolving a Mech checkout root verifies a guess before trusting it.

#131 item 2. Nineteen scripts resolved a root as
`os.environ.get(VAR, REPO_ROOT.parent / "Name")`. The variable is authoritative
and fine; the fallback is a guess that was never checked, so an unrelated or
empty directory at the conventional path was used silently.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kg_microbe_fleet import (
    MechRootError,
    load_fleet_manifest,
    looks_like,
    resolve_mech_root,
    sibling_default,
)

MANIFEST = load_fleet_manifest()
MECH = "mediaingredientmech"
VARIABLE = MANIFEST.mechs[MECH].environment_variable
PACKAGE = MANIFEST.mechs[MECH].package_path


def _checkout(base: Path, name: str, *, complete: bool = True) -> Path:
    root = base / name
    if complete:
        (root / PACKAGE).mkdir(parents=True)
    else:
        root.mkdir(parents=True)
    return root


def test_an_explicit_variable_is_trusted(tmp_path):
    """An operator naming a path has made a decision; second-guessing it would
    break legitimate layouts."""
    root = _checkout(tmp_path, "elsewhere")

    resolved = resolve_mech_root(
        MECH, claw_root=tmp_path / "claw", environ={VARIABLE: str(root)}
    )

    assert resolved == root.resolve()


def test_an_explicit_variable_pointing_nowhere_is_refused(tmp_path):
    """Trusted, but it must at least exist."""
    with pytest.raises(MechRootError, match="not a directory"):
        resolve_mech_root(
            MECH, claw_root=tmp_path, environ={VARIABLE: str(tmp_path / "absent")}
        )


def test_the_conventional_sibling_is_used_when_it_looks_right(tmp_path):
    claw = tmp_path / "culturebotai-claw"
    claw.mkdir()
    root = _checkout(tmp_path, MANIFEST.mechs[MECH].display_name)

    assert resolve_mech_root(MECH, claw_root=claw, environ={}) == root.resolve()


def test_a_sibling_that_is_not_that_mech_is_refused(tmp_path):
    """The missing step. A directory at the conventional path was used without
    ever checking it is the repository the script wanted."""
    claw = tmp_path / "culturebotai-claw"
    claw.mkdir()
    _checkout(tmp_path, MANIFEST.mechs[MECH].display_name, complete=False)

    with pytest.raises(MechRootError, match="does not look like"):
        resolve_mech_root(MECH, claw_root=claw, environ={})


def test_an_absent_sibling_names_the_variable_to_set(tmp_path):
    claw = tmp_path / "culturebotai-claw"
    claw.mkdir()

    with pytest.raises(MechRootError) as excinfo:
        resolve_mech_root(MECH, claw_root=claw, environ={})

    assert VARIABLE in str(excinfo.value)


def test_an_unknown_mech_lists_the_declared_ones(tmp_path):
    with pytest.raises(MechRootError, match="unknown Mech"):
        resolve_mech_root("nosuchmech", claw_root=tmp_path, environ={})


@pytest.mark.parametrize("key", sorted(MANIFEST.mechs))
def test_every_mech_resolves_through_its_declared_variable(key, tmp_path):
    """The resolver reads the manifest rather than a hard-coded name per Mech."""
    mech = MANIFEST.mechs[key]
    root = tmp_path / key
    (root / mech.package_path).mkdir(parents=True)

    resolved = resolve_mech_root(
        key, claw_root=tmp_path, environ={mech.environment_variable: str(root)}
    )

    assert resolved == root.resolve()


def test_the_sibling_default_matches_the_convention_the_scripts_used(tmp_path):
    """`REPO_ROOT.parent / "MediaIngredientMech"` is the shape being replaced."""
    claw = tmp_path / "culturebotai-claw"

    assert sibling_default("MediaIngredientMech", claw) == (
        tmp_path / "MediaIngredientMech"
    )


def test_looks_like_rejects_an_empty_directory(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()

    assert looks_like(empty, PACKAGE) is False


def test_looks_like_accepts_the_declared_package(tmp_path):
    root = _checkout(tmp_path, "mim")

    assert looks_like(root, PACKAGE) is True
