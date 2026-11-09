"""Which claw checkout configures the fleet, however the package is installed (#480, #486).

Every `kg-microbe-*` console script took `Path(__file__).parents[2]` as claw's
root. That is claw only in a source tree; installed from a wheel it is a
directory inside the virtualenv, so claw's `.env` was never read and a
configured fleet reported every Mech as not configured.

The replacement must also not err the other way: finding *some* directory and
treating its `.env` as claw's, or measuring it as claw (#486). Each test below
is driven by a layout in which the candidate answers differ.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

import kg_microbe_fleet.roots as roots
from kg_microbe_fleet.roots import (
    NO_CLAW_CHECKOUT,
    claw_root,
    is_claw_checkout,
    resolve_mech_root,
)

ROOT = Path(__file__).resolve().parents[1]


def _claw_like(path: Path) -> Path:
    (path / "src" / "kg_microbe_fleet").mkdir(parents=True)
    (path / "src" / "kg_microbe_fleet" / "fleet.yaml").write_text("version: 1\n")
    (path / "pyproject.toml").write_text("[project]\nname = 'kg-microbe-orchestration'\n")
    return path


def _mech_like(path: Path) -> Path:
    """A Python project that is not claw -- what every Mech checkout looks
    like -- so `is_claw_checkout` must tell the two apart (#500)."""
    path.mkdir(parents=True, exist_ok=True)
    (path / "pyproject.toml").write_text("[project]\nname = 'some-mech'\n")
    (path / "src" / "somemech").mkdir(parents=True)
    return path


def _installed(monkeypatch, venv: Path) -> Path:
    """Make this module look as it does in a wheel installed into `venv`."""
    site = venv / "lib" / "python3.13" / "site-packages" / "kg_microbe_fleet"
    site.mkdir(parents=True)
    monkeypatch.setattr(roots, "__file__", str(site / "roots.py"))
    monkeypatch.setattr(roots.sys, "prefix", str(venv))
    return site.parent.parent  # what parents[2] of roots.py now is


def test_a_mech_checkout_is_not_claw(tmp_path):
    """Both markers, not either: every Mech is a Python project too (#500)."""
    assert is_claw_checkout(_claw_like(tmp_path / "claw"))
    assert not is_claw_checkout(_mech_like(tmp_path / "mech"))
    fleet_only = tmp_path / "fleet-only"
    (fleet_only / "src" / "kg_microbe_fleet").mkdir(parents=True)
    (fleet_only / "src" / "kg_microbe_fleet" / "fleet.yaml").write_text("version: 1\n")
    assert not is_claw_checkout(fleet_only)


# --------------------------------------------------------------------------
# A source checkout
# --------------------------------------------------------------------------


def test_a_source_checkout_is_its_own_root():
    assert claw_root() == ROOT


def test_a_source_checkout_wins_over_the_checkout_it_is_run_from(monkeypatch, tmp_path):
    """The editable install from one claw checkout, run inside another (a PR
    worktree without a `.env`), keeps reading the installed checkout's `.env`
    -- as it always did (#487)."""
    other = _claw_like(tmp_path / "other-claw")
    monkeypatch.chdir(other)
    assert claw_root() == ROOT
    assert claw_root(other) == ROOT


# --------------------------------------------------------------------------
# An installed package
# --------------------------------------------------------------------------


def test_an_installed_command_finds_the_checkout_it_is_run_from(monkeypatch, tmp_path):
    """The call installed CLIs make: no argument, the working directory."""
    _installed(monkeypatch, tmp_path / "venv")
    claw = _claw_like(tmp_path / "work" / "claw")
    (claw / "scripts").mkdir()

    monkeypatch.chdir(claw / "scripts")
    assert claw_root() == claw


def test_a_virtualenv_inside_claw_belongs_to_that_checkout(monkeypatch, tmp_path):
    """`uv sync --no-editable` in claw A, run inside claw B: the venv says
    whose install it is, over the working directory (#500)."""
    claw_a = _claw_like(tmp_path / "claw-a")
    claw_b = _claw_like(tmp_path / "claw-b")
    _installed(monkeypatch, claw_a / ".venv")
    monkeypatch.chdir(claw_b)
    assert claw_root() == claw_a


def test_outside_any_checkout_it_answers_with_a_path_that_holds_no_env(monkeypatch, tmp_path):
    """Not the working directory -- a Mech here, with a `.env` of its own,
    would be read as claw (#486)."""
    packaged = _installed(monkeypatch, tmp_path / "venv")
    mech = _mech_like(tmp_path / "some-mech")
    (mech / ".env").write_text(f"TRAITMECH_ROOT={tmp_path / 'stale'}\n")
    monkeypatch.chdir(mech)

    assert claw_root() == packaged / NO_CLAW_CHECKOUT
    assert not claw_root().exists()


def test_a_target_install_does_not_read_its_parent_directorys_env(monkeypatch, tmp_path):
    """`pip install --target DIR`: the package location's parents[2] is DIR's
    parent, an ordinary directory whose `.env` the old fallback read (#502)."""
    project = tmp_path / "project"
    target = project / "vendor" / "kg_microbe_fleet"
    target.mkdir(parents=True)
    (project / ".env").write_text(f"TRAITMECH_ROOT={tmp_path / 'wrong'}\n")
    monkeypatch.setattr(roots, "__file__", str(target / "roots.py"))
    monkeypatch.setattr(roots.sys, "prefix", str(tmp_path / "python"))
    monkeypatch.chdir(tmp_path)

    root = claw_root()
    assert root != project and not (root / ".env").exists()


def test_a_deleted_working_directory_does_not_break_the_command(monkeypatch, tmp_path):
    packaged = _installed(monkeypatch, tmp_path / "venv")

    def gone() -> Path:
        raise FileNotFoundError("the working directory was deleted")

    monkeypatch.setattr(roots.Path, "cwd", staticmethod(gone))
    assert claw_root() == packaged / NO_CLAW_CHECKOUT


def test_an_installed_command_reads_the_checkouts_env(monkeypatch, tmp_path):
    """The failure itself: a root configured only in claw's `.env`."""
    _installed(monkeypatch, tmp_path / "venv")
    claw = _claw_like(tmp_path / "claw")
    trait = tmp_path / "mechs" / "TraitMech"
    (trait / "src" / "traitmech").mkdir(parents=True)
    (claw / ".env").write_text(f"TRAITMECH_ROOT={trait}\n")
    monkeypatch.chdir(claw)

    assert resolve_mech_root("traitmech", claw_root=claw_root(), environ={}) == trait


def test_health_refuses_to_measure_a_repository_that_is_not_claw(monkeypatch, tmp_path, capsys):
    """Before #480 this refused; the first fallback measured whatever git
    repository the user stood in and labelled it claw (#486)."""
    import subprocess

    import kg_microbe_health.__main__ as health

    other = _mech_like(tmp_path / "some-mech")
    subprocess.run(["git", "init", "-q", str(other)], check=True)
    monkeypatch.setattr(health, "CLAW_ROOT", other)
    assert health.main(["report", "--mech", "claw"]) == 2
    assert "is not a claw checkout" in capsys.readouterr().err

    monkeypatch.setattr(health, "CLAW_ROOT", ROOT)
    assert health.main(["report", "--mech", "claw", "--largest", "1"]) == 0
    assert json.loads(capsys.readouterr().out)["mech"] == "claw"


# --------------------------------------------------------------------------
# Adoption
# --------------------------------------------------------------------------


@pytest.mark.parametrize("path", sorted((ROOT / "src").glob("kg_microbe_*/__main__.py")),
                         ids=lambda p: p.parent.name)
def test_no_console_script_derives_claws_root_from_its_own_file(path):
    text = path.read_text(encoding="utf-8")
    assert not re.search(r"CLAW_ROOT\s*=\s*Path\(__file__\)", text), (
        f"{path.parent.name}: use kg_microbe_fleet.roots.claw_root()"
    )
