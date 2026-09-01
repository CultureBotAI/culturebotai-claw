"""OAKQuery resolves a verified checkout, and does not report a bad one as OAK.

#283. The plugin read `MEDIAINGREDIENTMECH_ROOT` with `os.getenv` and checked
only that it was *set* -- not that the directory existed, and not that it was
MediaIngredientMech. The value then went onto `sys.path` and was imported from,
so a stale or wrong path ran code out of the wrong tree. CLAUDE.md's rule that
repository-aware plugins consume the resolver exists for exactly this.

The second half matters more. Every failure was caught and reported as
"OntologyClient unavailable (OAK compatibility issue)" -- an unset variable, a
missing directory, a typo in the module. A misconfigured deployment and a
working one produced the same logs and the same return value, and nothing
failed. That is the fail-open shape #131 item 1 removed from
cross-repo-validation.yaml and #280 removed from the completeness guard.
"""

from __future__ import annotations

import sys

import pytest

from kg_microbe_fleet.roots import MechRootError
from plugins.oak_query import OAKQueryPlugin


@pytest.fixture
def plugin(tmp_path):
    return OAKQueryPlugin({"cache_dir": str(tmp_path / "ws")})


def test_an_unset_root_raises_rather_than_reporting_an_oak_problem(plugin, monkeypatch):
    """It is a configuration error. Calling it an OAK incompatibility is how a
    misconfigured deployment looks identical to a working one."""
    monkeypatch.delenv("MEDIAINGREDIENTMECH_ROOT", raising=False)
    monkeypatch.setattr(
        "plugins.oak_query.resolve_mech_root",
        lambda *a, **k: (_ for _ in ()).throw(MechRootError("not set")),
    )

    with pytest.raises(MechRootError):
        plugin._get_client()


def test_a_root_pointing_nowhere_raises(plugin, tmp_path, monkeypatch):
    """The old check accepted any non-empty string, so a path that does not
    exist reached sys.path."""
    monkeypatch.setenv("MEDIAINGREDIENTMECH_ROOT", str(tmp_path / "absent"))

    with pytest.raises(MechRootError, match="not a directory"):
        plugin._get_client()


def test_a_directory_that_is_not_the_mech_is_refused(plugin, tmp_path, monkeypatch):
    """An unrelated directory at the conventional path was previously used
    without any check that it was MediaIngredientMech."""
    stranger = tmp_path / "not-mim"
    stranger.mkdir()
    monkeypatch.delenv("MEDIAINGREDIENTMECH_ROOT", raising=False)
    monkeypatch.setattr("plugins.oak_query.CLAW_ROOT", tmp_path / "claw")

    with pytest.raises(MechRootError):
        plugin._get_client()


def test_an_import_failure_still_degrades_to_delegation(plugin, tmp_path, monkeypatch):
    """The one case the handler was written for. A real OAK incompatibility
    should not take the pipeline down."""
    root = tmp_path / "MediaIngredientMech"
    (root / "src").mkdir(parents=True)
    monkeypatch.setenv("MEDIAINGREDIENTMECH_ROOT", str(root))

    # Nothing to import from the staged src/, so the import raises ImportError.
    assert plugin._get_client() is None
    assert plugin._client == "UNAVAILABLE"


def test_a_resolved_root_reaches_sys_path(plugin, tmp_path, monkeypatch):
    """The resolver's answer is what gets imported from, not the raw variable."""
    root = tmp_path / "MediaIngredientMech"
    (root / "src").mkdir(parents=True)
    monkeypatch.setenv("MEDIAINGREDIENTMECH_ROOT", str(root))

    plugin._get_client()

    assert str(root.resolve() / "src") in sys.path


def test_a_non_import_failure_is_not_reported_as_an_oak_problem(
    plugin, tmp_path, monkeypatch
):
    """Construction failing is a real fault. Swallowing it into the same
    sentinel as an import failure is what made every fault look alike."""
    root = tmp_path / "MediaIngredientMech"
    (root / "src").mkdir(parents=True)
    monkeypatch.setenv("MEDIAINGREDIENTMECH_ROOT", str(root))

    def explode(*args, **kwargs):
        raise RuntimeError("ontology backend refused the connection")

    module = type(sys)("mediaingredientmech.utils.ontology_client")
    module.OntologyClient = explode
    monkeypatch.setitem(sys.modules, "mediaingredientmech", type(sys)("mediaingredientmech"))
    monkeypatch.setitem(sys.modules, "mediaingredientmech.utils", type(sys)("mediaingredientmech.utils"))
    monkeypatch.setitem(sys.modules, "mediaingredientmech.utils.ontology_client", module)

    with pytest.raises(RuntimeError, match="refused the connection"):
        plugin._get_client()
