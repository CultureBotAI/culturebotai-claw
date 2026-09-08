"""Where a Mech root may come from, and which source wins (#364, #368).

Two defects, one resolution order.

#368: `require_mech_roots` verified the *default* root, never the one the
command parsed. A `--culturemech-root` naming a real checkout was refused
whenever the default location happened to be absent -- refusing a more
specific answer than the one it checked, and naming a variable the caller had
already worked around.

#364: `openclaw-cli` reads claw's `.env` through `RepositorySettings`; every
`kg-microbe-*` console script read the bare process environment. A fleet
configured exactly as CLAUDE.md prescribes got "not set" from every command
that did not separately export it.

Each test below is driven by a fixture where the sources *disagree* -- the
explicit path exists and the default does not, the exported value and the
dotenv value point at different directories -- so a resolver that ignored the
new source, or took them in the wrong order, goes red. A fixture with one root
in one place would pass either way, which is the failure #286 names.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_fleet.roots import (
    MechRootError,
    dotenv_variable,
    require_mech_roots,
    resolve_mech_root,
)

MECH = "culturemech"
MANIFEST = load_fleet_manifest()
VARIABLE = MANIFEST.mechs[MECH].environment_variable
PACKAGE = MANIFEST.mechs[MECH].package_path
DISPLAY = MANIFEST.mechs[MECH].display_name


def make_checkout(base: Path, name: str) -> Path:
    root = base / name
    (root / PACKAGE).mkdir(parents=True)
    return root


def write_dotenv(claw_root: Path, body: str) -> None:
    claw_root.mkdir(parents=True, exist_ok=True)
    (claw_root / ".env").write_text(body, encoding="utf-8")


# --------------------------------------------------------------------------
# #368: the path the command parsed
# --------------------------------------------------------------------------


def test_an_explicit_path_is_used_when_the_default_location_is_absent(tmp_path):
    """The #368 regression. Nothing sits at the sibling path and no variable
    is set, so a resolver that checks only the default refuses."""
    claw = tmp_path / "elsewhere" / "claw"
    claw.mkdir(parents=True)
    named = make_checkout(tmp_path / "unusual", "CultureMech")

    assert not (claw.parent / DISPLAY).exists()
    assert (
        resolve_mech_root(MECH, claw_root=claw, environ={}, explicit=named)
        == named.resolve()
    )


def test_an_explicit_path_outranks_a_variable_pointing_somewhere_else(tmp_path):
    """Both resolve; they must not resolve to the same place, or the order is
    untested."""
    claw = tmp_path / "claw"
    claw.mkdir()
    configured = make_checkout(tmp_path, "from-variable")
    named = make_checkout(tmp_path, "from-command-line")

    assert configured != named
    assert (
        resolve_mech_root(
            MECH,
            claw_root=claw,
            environ={VARIABLE: str(configured)},
            explicit=named,
        )
        == named.resolve()
    )


def test_an_explicit_path_that_does_not_exist_is_refused_as_a_command_line_path(
    tmp_path,
):
    """The message must name the command line, not a variable the caller did
    not use -- that wording is what made the old refusal circular."""
    claw = tmp_path / "claw"
    claw.mkdir()
    with pytest.raises(MechRootError) as excinfo:
        resolve_mech_root(
            MECH, claw_root=claw, environ={}, explicit=tmp_path / "absent"
        )
    message = str(excinfo.value)
    assert "command line" in message
    assert VARIABLE not in message


@pytest.mark.parametrize("empty", [None, "", "   "])
def test_an_absent_explicit_path_falls_through_to_the_usual_order(tmp_path, empty):
    """A flag left at its default must not shadow the variable."""
    claw = tmp_path / "claw"
    claw.mkdir()
    configured = make_checkout(tmp_path, "configured")
    assert (
        resolve_mech_root(
            MECH,
            claw_root=claw,
            environ={VARIABLE: str(configured)},
            explicit=empty,
        )
        == configured.resolve()
    )


def test_require_mech_roots_passes_each_explicit_path_to_its_own_key(tmp_path):
    claw = tmp_path / "claw"
    claw.mkdir()
    cm = make_checkout(tmp_path, "cm-named")
    mim_key = "mediaingredientmech"
    mim_pkg = MANIFEST.mechs[mim_key].package_path
    mim = tmp_path / "mim-named"
    (mim / mim_pkg).mkdir(parents=True)

    resolved = require_mech_roots(
        MECH,
        mim_key,
        claw_root=claw,
        environ={},
        explicit={MECH: cm, mim_key: mim},
    )
    assert resolved == {MECH: cm.resolve(), mim_key: mim.resolve()}


def test_an_explicit_path_for_a_key_that_is_not_verified_is_refused(tmp_path):
    """Silently ignoring it would verify one root while the work used another."""
    claw = tmp_path / "claw"
    claw.mkdir()
    cm = make_checkout(tmp_path, "cm")
    with pytest.raises(MechRootError, match="not being verified"):
        require_mech_roots(
            MECH,
            claw_root=claw,
            environ={},
            explicit={MECH: cm, "traitmech": tmp_path / "tm"},
        )


# --------------------------------------------------------------------------
# #364: claw's own .env
# --------------------------------------------------------------------------


def test_the_variable_is_read_from_claws_dotenv_when_it_is_not_exported(tmp_path):
    """The #364 regression. The checkout is not beside claw, so only the
    dotenv file can answer."""
    claw = tmp_path / "claw"
    root = make_checkout(tmp_path / "far" / "away", "CultureMech")
    write_dotenv(claw, f"{VARIABLE}={root}\n")

    assert not (claw.parent / DISPLAY).exists()
    assert resolve_mech_root(MECH, claw_root=claw, environ={}) == root.resolve()


def test_an_exported_value_wins_over_the_dotenv_file(tmp_path):
    """Both are readable and they point at different checkouts, so a resolver
    that preferred the file would resolve to the wrong one."""
    claw = tmp_path / "claw"
    exported = make_checkout(tmp_path, "exported")
    from_file = make_checkout(tmp_path, "from-file")
    write_dotenv(claw, f"{VARIABLE}={from_file}\n")

    assert exported != from_file
    assert (
        resolve_mech_root(MECH, claw_root=claw, environ={VARIABLE: str(exported)})
        == exported.resolve()
    )


def test_a_dotenv_value_wins_over_the_sibling_guess(tmp_path):
    """A checkout *does* sit at the conventional path, so a resolver that
    skipped the file would find something plausible and use it."""
    claw = tmp_path / "claw"
    claw.mkdir()
    beside = make_checkout(tmp_path, DISPLAY)
    named = make_checkout(tmp_path / "named", "CultureMech")
    write_dotenv(claw, f"{VARIABLE}={named}\n")

    assert beside.is_dir()
    assert resolve_mech_root(MECH, claw_root=claw, environ={}) == named.resolve()


def test_a_dotenv_path_that_does_not_exist_is_refused_naming_the_file(tmp_path):
    """Reporting it as an unset variable would send someone to fix the wrong
    thing."""
    claw = tmp_path / "claw"
    write_dotenv(claw, f"{VARIABLE}={tmp_path / 'absent'}\n")
    with pytest.raises(MechRootError, match=r"\.env"):
        resolve_mech_root(MECH, claw_root=claw, environ={})


def test_an_unexpanded_reference_is_not_silently_turned_into_a_shorter_path(tmp_path):
    """Interpolation turns an unknown variable into an empty string, so
    `${MISSING}<path>` becomes `<path>` -- a *different, existing* checkout
    that the operator never named.

    The fixture puts a real checkout exactly where the expansion would land,
    so interpolation resolves successfully and only the literal reading
    refuses. Written against a path that does not exist either way, this test
    passed with interpolation on or off and proved nothing.
    """
    claw = tmp_path / "claw"
    would_land_on = make_checkout(tmp_path, "expanded")
    write_dotenv(claw, f"{VARIABLE}=${{MISSING}}{would_land_on}\n")

    assert would_land_on.is_dir()
    with pytest.raises(MechRootError):
        resolve_mech_root(MECH, claw_root=claw, environ={})


def test_a_symlinked_dotenv_is_ignored(tmp_path):
    """`RepositorySettings` refuses one; this must not quietly accept what the
    orchestration layer rejects."""
    claw = tmp_path / "claw"
    claw.mkdir()
    real = tmp_path / "elsewhere.env"
    root = make_checkout(tmp_path, "target")
    real.write_text(f"{VARIABLE}={root}\n", encoding="utf-8")
    (claw / ".env").symlink_to(real)

    assert dotenv_variable(claw, VARIABLE) == ""


def test_a_missing_dotenv_is_not_an_error(tmp_path):
    assert dotenv_variable(tmp_path, VARIABLE) == ""


def test_the_dotenv_reader_returns_only_the_variable_asked_for(tmp_path):
    """It must not become a general environment loader: a command reading one
    root should not pick up an unrelated credential from the same file."""
    claw = tmp_path / "claw"
    write_dotenv(claw, f"{VARIABLE}=/somewhere\nOPENAI_API_KEY=secret\n")
    assert dotenv_variable(claw, VARIABLE) == "/somewhere"
    assert dotenv_variable(claw, "OPENAI_API_KEY") == "secret"
    # ...but resolving a root never consults an unrelated key.
    with pytest.raises(MechRootError):
        resolve_mech_root(MECH, claw_root=claw, environ={})
