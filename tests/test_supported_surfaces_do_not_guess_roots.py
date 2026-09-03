"""#131 item 2, from the other side: keep the guess out of supported code.

`test_scripts_verify_mech_roots` governs `scripts/`, where the conventional
sibling fallback is deliberate -- a module-level plain path keeps importing a
script from requiring a checkout (#147), and `require_mech_roots` verifies it
at the top of `main()`.

Nothing said the same pattern may not appear in `cli/`, `plugins/`,
`pipelines/` or `src/`. Those surfaces are supported: CLAUDE.md requires them
to consume `RepositorySettings` or `resolve_mech_root`, which verify a guessed
root against the manifest before trusting it. They are clean today. This is
what keeps them that way, in the spirit of the contract tests #130 added for
reintroduced Mech lists.

The occurrence in `kg_microbe_fleet.roots` is a docstring quoting the
anti-pattern it exists to replace. A grep cannot tell that from a live
fallback; parsing can, and the difference is the whole reason this reads the
syntax tree.

What this does not catch: a checkout name held in a variable rather than
written as a literal. `roots.py` itself is written that way, legitimately --
it resolves whatever the manifest names. So this rejects the idiom as all
sixty-five scripts actually write it, which is how it would come back, and it
is not a proof that no supported module can reach a sibling path.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from kg_microbe_fleet import load_fleet_manifest

ROOT = Path(__file__).resolve().parents[1]
SUPPORTED = ("cli", "plugins", "pipelines", "src")

# From the manifest, so a newly admitted Mech is covered without an edit here.
# kg-microbe is not a Mech and has no manifest row, but the same guessed
# sibling path reaches it, so it is named alongside.
CHECKOUT_NAMES = frozenset(
    {mech.display_name for mech in load_fleet_manifest().mechs.values()}
    | {"kg-microbe"}
)


def sibling_guesses(source: str) -> list[str]:
    """Checkout names reached by a `<something>.parent / "Name"` expression.

    Parsed, not matched: the same characters inside a docstring are prose about
    the pattern rather than a use of it, and this module's whole point is that
    supported code contains the former and not the latter.
    """
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Div):
            continue
        right = node.right
        if not isinstance(right, ast.Constant) or right.value not in CHECKOUT_NAMES:
            continue
        if any(
            isinstance(inner, ast.Attribute) and inner.attr == "parent"
            for inner in ast.walk(node.left)
        ):
            found.append(right.value)
    return sorted(found)


def _supported_modules() -> list[Path]:
    return sorted(
        path
        for directory in SUPPORTED
        for path in (ROOT / directory).rglob("*.py")
        if "__pycache__" not in path.parts
    )


MODULES = _supported_modules()


def test_there_are_modules_to_check():
    """Guards the parametrization: an empty list would assert nothing."""
    assert len(MODULES) >= 20, f"only {len(MODULES)} modules found"


@pytest.mark.parametrize("path", MODULES, ids=lambda p: str(p.relative_to(ROOT)))
def test_a_supported_module_does_not_guess_a_checkout_path(path):
    guesses = sibling_guesses(path.read_text(encoding="utf-8"))
    assert not guesses, (
        f"{path.relative_to(ROOT)} resolves {', '.join(guesses)} from the "
        f"conventional sibling path. Supported surfaces go through "
        f"RepositorySettings or resolve_mech_root, which check a guessed root "
        f"against the manifest before working on it (#131)."
    )


def test_the_detector_finds_the_pattern_it_is_looking_for():
    """`scripts/` is full of the real thing by design, so it is the honest
    positive control: a detector that found nothing there would pass the whole
    suite above while detecting nothing at all."""
    hits = {
        path.name: found
        for path in sorted((ROOT / "scripts").glob("*.py"))
        if (found := sibling_guesses(path.read_text(encoding="utf-8")))
    }
    assert len(hits) >= 20, f"detector found the pattern in only {len(hits)} scripts"


def test_prose_about_the_pattern_is_not_a_use_of_it():
    """The distinction a grep cannot make. Same characters, both files."""
    live = 'ROOT = Path(os.environ.get("X", REPO_ROOT.parent / "CultureMech"))'
    quoted = '"""Nineteen scripts did:\n\n    REPO_ROOT.parent / "CultureMech"\n"""\n'
    assert sibling_guesses(live) == ["CultureMech"]
    assert sibling_guesses(quoted) == []


def test_a_name_that_is_not_a_checkout_is_not_a_finding():
    """`self.root.parent / "data"` is an ordinary path join."""
    assert sibling_guesses('p = base.parent / "data"') == []
    assert sibling_guesses('p = base.parent / "CultureMech"') == ["CultureMech"]


def test_a_join_that_does_not_climb_is_not_a_finding():
    """Naming a Mech under a root you were given is not guessing at a sibling."""
    assert sibling_guesses('p = workspace / "CultureMech"') == []
    assert sibling_guesses('p = workspace.parent / "CultureMech"') == ["CultureMech"]


def test_the_checkout_names_come_from_the_manifest():
    """A ledger. Restated as a literal, this list would go stale the next time
    a Mech is admitted -- which is the drift #131 exists to remove."""
    manifest = {m.display_name for m in load_fleet_manifest().mechs.values()}
    assert manifest < CHECKOUT_NAMES
    assert CHECKOUT_NAMES - manifest == {"kg-microbe"}
