"""Commands verify their Mech checkout before working, but not at import.

#176 / #131 item 2. Two contracts had to hold at once:

* importing a script must not require a checkout (#147) -- five scripts import
  `classify_ingredient_type` for its regexes alone; and
* a command must not operate on a directory it never confirmed is the
  repository it wanted (#131 item 2).

Resolving at module level satisfies the second and breaks the first, which is
what the reverted mechanical rewrite in #177 demonstrated. The split is:
module-level roots stay plain paths, and `require_mech_roots` runs at the top
of `main()`.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from kg_microbe_fleet import load_fleet_manifest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

# Tolerates absent roots by design: it reports per-source coverage instead,
# because a partial inventory is a real answer there (#161).
EXEMPT = {"inventory_unmapped_ingredients.py"}

# Read from the manifest, not restated here. This list is what decides which
# scripts the guard below even looks at, so a Mech missing from it is a Mech
# whose guessed roots nothing checks. It was written as a literal five while the
# fleet had five, and CellStructureMech's admission silently made it four-fifths
# of the answer -- the exact drift #131 exists to remove, in the test enforcing
# #131.
MECH_VARIABLES = tuple(
    sorted(mech.environment_variable for mech in load_fleet_manifest().mechs.values())
)


def _guessing_scripts() -> list[Path]:
    """Scripts that resolve a Mech root from the conventional sibling path."""
    return [
        path
        for path in sorted(SCRIPTS.glob("*.py"))
        if "REPO_ROOT.parent" in path.read_text(encoding="utf-8")
        and any(v in path.read_text(encoding="utf-8") for v in MECH_VARIABLES)
    ]


GUESSING = _guessing_scripts()
REQUIRED = [p for p in GUESSING if p.name not in EXEMPT]


def test_there_are_scripts_to_check():
    """Guards the parametrization: an empty list would skip everything."""
    assert len(REQUIRED) >= 10, f"only {len(REQUIRED)} scripts found"


@pytest.mark.parametrize("path", REQUIRED, ids=lambda p: p.name)
def test_a_command_verifies_its_checkout_before_working(path):
    source = path.read_text(encoding="utf-8")

    assert "require_mech_roots(" in source, (
        f"{path.name} resolves a Mech root from the conventional sibling path "
        f"without verifying it; call require_mech_roots at the top of main()"
    )


@pytest.mark.parametrize("path", REQUIRED, ids=lambda p: p.name)
def test_the_verification_happens_inside_main_not_at_import(path):
    """At module level it would break the import-safety contract (#147)."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    main = next(
        (n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main"),
        None,
    )
    assert main is not None, f"{path.name} has no main()"

    inside = [
        node
        for node in ast.walk(main)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", "") == "require_mech_roots"
    ]
    at_module_level = [
        node
        for node in tree.body
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and getattr(node.value.func, "id", "") == "require_mech_roots"
    ]

    assert inside, f"{path.name} does not verify inside main()"
    assert not at_module_level, (
        f"{path.name} verifies at import time, which breaks the contract that "
        f"importing a script does not require a checkout"
    )


@pytest.mark.parametrize("path", REQUIRED, ids=lambda p: p.name)
def test_a_command_verifies_every_mech_root_it_resolves(path):
    """Verifying one root while silently guessing another is the same bug."""
    source = path.read_text(encoding="utf-8")
    expected = {
        variable.split("_ROOT")[0].lower() for variable in MECH_VARIABLES
        if variable in source
    }
    tree = ast.parse(source)
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")
    verified = {
        arg.value
        for node in ast.walk(main)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", "") == "require_mech_roots"
        for arg in node.args
        if isinstance(arg, ast.Constant)
    }

    assert expected, f"{path.name} names no Mech root variable"
    assert expected <= verified, (
        f"{path.name} resolves {sorted(expected - verified)} without verifying"
    )


def test_the_exempt_script_is_exempt_for_a_recorded_reason():
    """An exemption must be a decision, not an omission."""
    for name in EXEMPT:
        path = SCRIPTS / name
        assert path.is_file(), name
        assert "require_mech_roots(" not in path.read_text(encoding="utf-8"), (
            f"{name} is listed as exempt but verifies anyway; remove the exemption"
        )


# --------------------------------------------------------------------------
# #179: --help must work without a checkout
# --------------------------------------------------------------------------


@pytest.mark.parametrize("path", REQUIRED, ids=lambda p: p.name)
def test_verification_happens_after_argument_parsing(path):
    """#179: inserted as the first statement of main(), it ran before
    parse_args, so `--help` failed without a checkout -- and `--help` is how
    someone discovers which variable to set. Refusing to print it because that
    variable is unset is circular.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    main = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "main")

    parse_lines = [
        node.lineno
        for node in ast.walk(main)
        if isinstance(node, ast.Call) and "parse_args" in ast.unparse(node.func)
    ]
    verify_lines = [
        node.lineno
        for node in ast.walk(main)
        if isinstance(node, ast.Call)
        and getattr(node.func, "id", "") == "require_mech_roots"
    ]

    assert parse_lines, f"{path.name} never parses arguments"
    assert verify_lines, f"{path.name} never verifies"
    assert min(verify_lines) > max(parse_lines), (
        f"{path.name} verifies at line {min(verify_lines)}, before arguments are "
        f"parsed at line {max(parse_lines)}; --help would fail without a checkout"
    )


def test_the_variable_list_is_the_manifest_and_not_a_copy_of_it():
    """The guard's own coverage is derived, so admitting a Mech extends it.

    Asserting the derivation rather than the values: a literal list here would
    reintroduce exactly the drift this checks for. The failure it prevents is
    quiet -- a script guessing a root for an undeclared Mech is not reported as
    unverified, it is simply never examined.
    """
    manifest = load_fleet_manifest()
    assert set(MECH_VARIABLES) == {
        mech.environment_variable for mech in manifest.mechs.values()
    }
    assert len(MECH_VARIABLES) == len(manifest.mechs)
    # The value the old literal omitted, named so the regression is legible.
    assert "CELLSTRUCTUREMECH_ROOT" in MECH_VARIABLES
