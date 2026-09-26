"""Which claw checkout configures the fleet, however the package is installed (#480).

Every `kg-microbe-*` console script took `Path(__file__).parents[2]` as claw's
root. That is claw only in a source tree; installed from a wheel it is a
directory inside the virtualenv, so claw's `.env` was never read and a
configured fleet reported every Mech as not configured.
"""

from __future__ import annotations

import re
from pathlib import Path

import kg_microbe_fleet.roots as roots
from kg_microbe_fleet.roots import claw_root, resolve_mech_root

ROOT = Path(__file__).resolve().parents[1]


def _claw_like(path: Path) -> Path:
    (path / "src" / "kg_microbe_fleet").mkdir(parents=True)
    (path / "src" / "kg_microbe_fleet" / "fleet.yaml").write_text("version: 1\n")
    (path / "pyproject.toml").write_text("[project]\nname = 'kg-microbe-orchestration'\n")
    return path


def _installed(monkeypatch, tmp_path: Path) -> None:
    """Make this module look as it does inside a wheel install."""
    site = tmp_path / "venv" / "lib" / "python3.13" / "site-packages" / "kg_microbe_fleet"
    site.mkdir(parents=True)
    monkeypatch.setattr(roots, "__file__", str(site / "roots.py"))


def test_a_source_checkout_is_its_own_root():
    assert claw_root() == ROOT


def test_an_installed_package_finds_the_checkout_it_is_run_from(monkeypatch, tmp_path):
    _installed(monkeypatch, tmp_path)
    claw = _claw_like(tmp_path / "work" / "claw")
    (claw / "scripts").mkdir()

    assert claw_root(claw) == claw
    assert claw_root(claw / "scripts") == claw


def test_outside_any_checkout_it_falls_back_to_where_it_was_run(monkeypatch, tmp_path):
    _installed(monkeypatch, tmp_path)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    assert claw_root(elsewhere) == elsewhere.resolve()


def test_an_installed_command_reads_the_checkouts_env(monkeypatch, tmp_path):
    """The failure itself: a root configured only in claw's `.env`."""
    _installed(monkeypatch, tmp_path)
    claw = _claw_like(tmp_path / "claw")
    trait = tmp_path / "mechs" / "TraitMech"
    (trait / "src" / "traitmech").mkdir(parents=True)
    (claw / ".env").write_text(f"TRAITMECH_ROOT={trait}\n")

    assert resolve_mech_root("traitmech", claw_root=claw_root(claw), environ={}) == trait


def test_no_console_script_derives_claws_root_from_its_own_file():
    offenders = [
        path.relative_to(ROOT).as_posix()
        for path in sorted((ROOT / "src").glob("kg_microbe_*/__main__.py"))
        if re.search(r"CLAW_ROOT\s*=\s*Path\(__file__\)", path.read_text(encoding="utf-8"))
    ]
    assert offenders == [], f"use kg_microbe_fleet.roots.claw_root(): {offenders}"
