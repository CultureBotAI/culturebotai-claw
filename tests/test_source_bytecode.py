"""Exercise the actual pytest harness against genuinely valid stale pycs."""
from __future__ import annotations

import importlib.util
import os
import py_compile
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("mode", ["import", "spec"])
@pytest.mark.parametrize("cached", [False, True])
def test_project_imports_execute_current_source(tmp_path, mode, cached):
    project = tmp_path / "project"
    tests = project / "tests"
    tests.mkdir(parents=True)
    shutil.copyfile(ROOT / "tests" / "conftest.py", tests / "conftest.py")
    scripts = project / "scripts"
    scripts.mkdir()
    package = project / "src" / "bytecode_probe_dependency"
    package.mkdir(parents=True)
    (project / "pytest.ini").write_text("[pytest]\npythonpath = scripts src\n")
    # The script imports a package too: fixing only spec-loader callers would
    # leave this transitive import, and ordinary imports, vulnerable.
    sources = {
        scripts / "bytecode_probe.py": (
            'import bytecode_probe_dependency\nVALUE = "before"\n'
        ),
        package / "__init__.py": 'VALUE = "before"\n',
    }
    caches = {}
    for path, source in sources.items():
        path.write_text(source)
        stat = path.stat()
        cache = Path(importlib.util.cache_from_source(str(path)))
        if cached:
            py_compile.compile(str(path), doraise=True,
                               invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP)
            caches[cache] = cache.read_bytes()
        mutation = source.replace('"before"', '"after!"')
        assert len(mutation.encode()) == stat.st_size
        path.write_text(mutation)
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        assert path.stat().st_mtime_ns == stat.st_mtime_ns

    if mode == "import":
        load = "import bytecode_probe as module"
    else:
        load = '''import importlib.util
from pathlib import Path
spec = importlib.util.spec_from_file_location(
    "bytecode_probe", Path(__file__).parents[1] / "scripts" / "bytecode_probe.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)'''
    (tests / "test_probe.py").write_text(load + '''

def test_source():
    assert module.VALUE == "after!"
    assert module.bytecode_probe_dependency.VALUE == "after!"
''')
    env = dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    # Even -B is intentionally set: reverting our loader to only suppress
    # writes must still fail for the timestamp-valid caches prepared above.
    result = subprocess.run(
        [sys.executable, "-B", "-m", "pytest", "-q", "tests/test_probe.py"],
        cwd=project, env=env, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    for path in sources:
        cache = Path(importlib.util.cache_from_source(str(path)))
        if cached:
            assert cache.read_bytes() == caches[cache], "existing caches must remain untouched"
        else:
            assert not cache.exists(), "source imports must not create a new cache"


def test_embedded_pytest_restores_the_loader_after_each_session(tmp_path):
    tests = tmp_path / "tests"
    tests.mkdir()
    shutil.copyfile(ROOT / "tests" / "conftest.py", tests / "conftest.py")
    (tests / "test_probe.py").write_text('''
from importlib.machinery import SourceFileLoader
from __main__ import original

def test_hook_is_active():
    assert SourceFileLoader.get_code is not original
''')
    runner = '''
from importlib.machinery import SourceFileLoader
import pytest
original = SourceFileLoader.get_code
for _ in range(2):
    assert pytest.main(["-q", "tests/test_probe.py"]) == 0
    assert SourceFileLoader.get_code is original
'''
    result = subprocess.run(
        [sys.executable, "-B", "-c", runner], cwd=tmp_path,
        env=dict(os.environ, PYTEST_DISABLE_PLUGIN_AUTOLOAD="1"),
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
