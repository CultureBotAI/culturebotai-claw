"""No script may hardcode a path that only exists on one machine.

#193. `generate_kgm_xref_patches.py` hardcoded an absolute workspace path, so
it only ran on one developer's laptop and, run from a git worktree, wrote its
output into a *different* checkout. Fifty-four scripts shared the shape.

`test_scripts_verify_mech_roots.py` could not see any of them: it finds scripts
by the honest `REPO_ROOT.parent` idiom and asks whether they verify. A script
with a literal absolute path never resolves a root at all, so the guard that
exists for exactly this class of bug structurally skips the worst offenders.

These two lists were burn-down ledgers (#198). Both are empty: all 52 scripts
now derive their paths from the file's own location with the fleet's
environment variables as overrides, and all 54 shebangs name `python3` rather
than one Homebrew install. They stay in the file as the mechanism that keeps
them empty -- a new script cannot be added to either without a deliberate edit
here, and the tests fail in both directions.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

# Scripts that still embed a home-directory path. Shrink this; never grow it.
HARDCODED_PATHS: set[str] = set()

# Scripts whose shebang names an interpreter by absolute path. Same ledger,
# different symptom: `#!/usr/bin/env /opt/homebrew/bin/python3.13` is a Mac
# with Homebrew and that exact Python.
ABSOLUTE_INTERPRETER: set[str] = set()


def _scripts():
    return sorted(SCRIPTS.glob("*.py"))


def _has_home_path(path: Path) -> bool:
    source = path.read_text(encoding="utf-8")
    return "/Users/" in source or "/home/" in source


def test_there_are_scripts_to_check():
    """Guards the parametrization: an empty glob would pass everything."""
    assert len(_scripts()) >= 100, f"only {len(_scripts())} scripts found"


@pytest.mark.parametrize("path", _scripts(), ids=lambda p: p.name)
def test_no_new_script_hardcodes_a_home_directory_path(path):
    if path.name in HARDCODED_PATHS:
        pytest.skip("known offender; tracked in #198")
    assert not _has_home_path(path), (
        f"{path.name} embeds a home-directory path, so it runs on one machine "
        f"and writes wherever that literal points rather than into the "
        f"checkout it was invoked from. Derive paths from "
        f"Path(__file__).resolve().parent.parent and resolve Mech roots with "
        f"require_mech_roots"
    )


@pytest.mark.parametrize("path", _scripts(), ids=lambda p: p.name)
def test_no_new_script_pins_an_absolute_interpreter(path):
    if path.name in ABSOLUTE_INTERPRETER:
        pytest.skip("known offender; tracked in #198")
    first = path.read_text(encoding="utf-8").split("\n", 1)[0]
    assert not first.startswith("#!/usr/bin/env /"), (
        f"{path.name} pins {first[len('#!/usr/bin/env '):]}; use "
        f"#!/usr/bin/env python3 so the active environment decides"
    )


@pytest.mark.parametrize("name", sorted(HARDCODED_PATHS))
def test_a_fixed_script_leaves_the_path_ledger(name):
    """A cleaned-up script must be removed from the list, or the ledger stops
    describing anything and the burn-down cannot be read."""
    path = SCRIPTS / name
    assert path.is_file(), f"{name} is listed but does not exist; remove it"
    assert _has_home_path(path), (
        f"{name} no longer hardcodes a home path -- remove it from "
        f"HARDCODED_PATHS so the remaining count stays honest"
    )


@pytest.mark.parametrize("name", sorted(ABSOLUTE_INTERPRETER))
def test_a_fixed_script_leaves_the_interpreter_ledger(name):
    path = SCRIPTS / name
    assert path.is_file(), f"{name} is listed but does not exist; remove it"
    assert path.read_text(encoding="utf-8").startswith("#!/usr/bin/env /"), (
        f"{name} no longer pins an absolute interpreter -- remove it from "
        f"ABSOLUTE_INTERPRETER"
    )


# --------------------------------------------------------------------------
# #205: --help must not need a checkout, and a module-level downstream import
#       makes it need one
# --------------------------------------------------------------------------

# Scripts that import a module from a downstream checkout at module level, so
# `--help` fails without that checkout. Shrink this; never grow it.
DOWNSTREAM_IMPORT_AT_MODULE_LEVEL = {
    "resolve_label_plausibility_defects.py",
    "resolve_mediadive_backlog.py",
    "resolve_residual_defects.py",
    "review_p44_synonym_enrichment.py",
    "sweep_kg_microbe_rules.py",
}

# Path variables that name a checkout other than this one.
_DOWNSTREAM_VARIABLES = {
    "MIM_ROOT",
    "CM",
    "CULTUREMECH_ROOT_PATH",
    "COMMUNITYMECH_ROOT_PATH",
    "KGM_ROOT_PATH",
    "CULTUREBOTHT_ROOT_PATH",
}


def _imports_from_a_downstream_path(path: Path) -> bool:
    """A top-level import that follows a sys.path.insert of a downstream root.

    Static rather than a subprocess sweep: running `--help` on sixty scripts
    is a minute of test time, and this reads the same fact off the AST.
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    inserted = False
    for node in tree.body:
        if (
            isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and "sys.path.insert" in ast.unparse(node.value.func)
        ):
            names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
            if names & _DOWNSTREAM_VARIABLES:
                inserted = True
        elif isinstance(node, (ast.Import, ast.ImportFrom)) and inserted:
            return True
    return False


@pytest.mark.parametrize("path", _scripts(), ids=lambda p: p.name)
def test_help_does_not_require_a_downstream_checkout(path):
    """#179 again, through a door the AST guard could not see.

    That guard checks `require_mech_roots` runs after `parse_args`, which these
    scripts do. It cannot see an import that fails before `main()` is ever
    reached -- and `--help` is how a reader discovers which variable to set, so
    needing the checkout to print it is circular.
    """
    if path.name in DOWNSTREAM_IMPORT_AT_MODULE_LEVEL:
        pytest.skip("known offender; tracked in #205")
    assert not _imports_from_a_downstream_path(path), (
        f"{path.name} imports from a downstream checkout at module level, so "
        f"--help fails without it; import inside the function that uses it"
    )


@pytest.mark.parametrize("name", sorted(DOWNSTREAM_IMPORT_AT_MODULE_LEVEL))
def test_a_fixed_script_leaves_the_downstream_import_ledger(name):
    path = SCRIPTS / name
    assert path.is_file(), f"{name} is listed but does not exist; remove it"
    assert _imports_from_a_downstream_path(path), (
        f"{name} no longer imports from a downstream checkout at module level "
        f"-- remove it from DOWNSTREAM_IMPORT_AT_MODULE_LEVEL"
    )


# --------------------------------------------------------------------------
# #207 review: adding a parser must not reject arguments a script already took
# --------------------------------------------------------------------------


@pytest.mark.parametrize("path", _scripts(), ids=lambda p: p.name)
def test_a_script_that_reads_argv_declares_what_it_reads(path):
    """#198 gave twenty scripts an argument parser so `--help` would work.
    A bare parser rejects every positional -- and `chebi_semantic_audit` had
    always taken its destination as `sys.argv[1]`, so parsing silently turned
    a working invocation into `error: unrecognized arguments`.
    """
    source = path.read_text(encoding="utf-8")
    if "parse_args" not in source or "sys.argv" not in source:
        return

    tree = ast.parse(source)
    indexed = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Subscript)
        and ast.unparse(node.value) == "sys.argv"
    ]
    if not indexed:
        return

    declared = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and getattr(node.func, "attr", "") == "add_argument"
    ]
    assert declared, (
        f"{path.name} indexes sys.argv and also parses arguments, but declares "
        f"none; the parser will reject what the indexing expects"
    )
