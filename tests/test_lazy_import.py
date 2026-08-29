"""LazyModule defers a downstream import without hiding what went wrong.

#205. Five scripts imported from a Mech checkout at module level, so `--help`
failed before `main()` was reached. The proxy moves the import to first use.

Deferring an import is easy; the risk is what it says when the import fails.
A proxy that turns every failure into "set the root variable" would be worse
than the eager import it replaced, because the reader would go and set a
variable that was never the problem.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from _lazy_import import LazyModule  # noqa: E402


@pytest.fixture
def module_dir(tmp_path):
    directory = tmp_path / "elsewhere"
    directory.mkdir()
    return directory


def test_nothing_is_imported_until_an_attribute_is_read(module_dir):
    (module_dir / "_probe_a.py").write_text("VALUE = 1\n", encoding="utf-8")
    proxy = LazyModule("_probe_a", lambda: (module_dir,))

    assert "_probe_a" not in sys.modules, "constructing the proxy must not import"
    assert proxy.VALUE == 1
    assert "_probe_a" in sys.modules


def test_the_search_path_is_added_only_when_the_import_happens(module_dir):
    (module_dir / "_probe_b.py").write_text("VALUE = 2\n", encoding="utf-8")
    proxy = LazyModule("_probe_b", lambda: (module_dir,))

    assert str(module_dir) not in sys.path
    assert proxy.VALUE == 2
    assert str(module_dir) in sys.path


def test_an_absent_module_refuses_with_the_paths_and_the_hint(module_dir):
    proxy = LazyModule(
        "_probe_absent", lambda: (module_dir,), hint="Set CULTUREMECH_ROOT."
    )

    with pytest.raises(SystemExit) as raised:
        proxy.anything

    message = str(raised.value)
    assert "_probe_absent could not be imported" in message
    assert str(module_dir) in message, "say where it looked"
    assert "Set CULTUREMECH_ROOT." in message, "say what to do about it"


def test_a_dependency_missing_inside_the_module_is_not_reported_as_the_module(
    module_dir,
):
    """The failure that made this worth testing. `except ModuleNotFoundError`
    catches a miss anywhere in the import, so a package absent *inside* the
    target was reported as the target itself being unreachable -- sending the
    reader to set a root variable that was never the problem."""
    (module_dir / "_probe_c.py").write_text(
        "import a_package_that_does_not_exist\n", encoding="utf-8"
    )
    proxy = LazyModule("_probe_c", lambda: (module_dir,), hint="Set CULTUREMECH_ROOT.")

    with pytest.raises(ModuleNotFoundError) as raised:
        proxy.anything

    assert raised.value.name == "a_package_that_does_not_exist"


def test_an_error_raised_inside_the_module_surfaces_unchanged(module_dir):
    (module_dir / "_probe_d.py").write_text(
        "raise ValueError('inner failure')\n", encoding="utf-8"
    )
    proxy = LazyModule("_probe_d", lambda: (module_dir,))

    with pytest.raises(ValueError, match="inner failure"):
        proxy.anything


def test_the_module_is_imported_once(module_dir):
    (module_dir / "_probe_e.py").write_text(
        "import itertools\nCOUNT = next(itertools.count())\nVALUE = object()\n",
        encoding="utf-8",
    )
    proxy = LazyModule("_probe_e", lambda: (module_dir,))

    assert proxy.VALUE is proxy.VALUE


def test_a_dunder_attribute_does_not_trigger_the_import(module_dir):
    """copy, pickle and inspect probe for dunders. Importing a Mech because
    something looked for __deepcopy__ would defeat the point."""
    proxy = LazyModule("_probe_never", lambda: (module_dir,))

    with pytest.raises(AttributeError):
        proxy.__deepcopy__

    assert "not yet imported" in repr(proxy)
