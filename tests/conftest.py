"""Test project source, even when a timestamp-valid bytecode cache exists.

A same-size mutation with the same integer mtime can otherwise execute old code
(#380). Disabling bytecode writes alone does not disable reading existing pycs.
This hook covers normal imports and explicit spec/exec_module loaders, including
scripts imported by another script. Dependency caches remain untouched.
"""
from __future__ import annotations

from importlib.machinery import SourceFileLoader
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = tuple(ROOT / name for name in ("scripts", "src", "cli", "plugins", "pipelines"))


def pytest_configure(config):
    original = SourceFileLoader.get_code
    patch = pytest.MonkeyPatch()

    def source_code(loader, fullname):
        filename = loader.get_filename(fullname)
        path = Path(filename).resolve()
        if any(path.is_relative_to(root) for root in SOURCE_ROOTS):
            return loader.source_to_code(loader.get_data(filename), filename)
        return original(loader, fullname)

    patch.setattr(SourceFileLoader, "get_code", source_code)
    config.add_cleanup(patch.undo)
