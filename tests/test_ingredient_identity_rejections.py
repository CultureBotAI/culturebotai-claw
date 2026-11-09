"""Bounded identity exclusions, including their installed-package boundary."""
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from kg_microbe_utils.ingredient_identity_rejections import rejection_reason

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("name", ["Carnitine Hydrochloride", "Carnitine (Dl) Hydrochloride",
                                 "  CARNITINE\t(DL)  hydrochloride\n"])
@pytest.mark.parametrize("cas", [None, "", "461-06-3", "461-05-2"])
def test_reviewed_names_reject_amide_independently_of_cas(name, cas):
    reason = rejection_reason(ontology_id="CHEBI:48601", cas=cas, name=name)
    assert reason and "distinct amide" in reason
    assert "issues/1004" in reason and "compound/5970" in reason


@pytest.mark.parametrize("cas", ["461-05-2", " 461-05-2 ", "CAS:461-05-2"])
def test_reviewed_exact_cas_pair_rejects_without_any_name(cas):
    assert rejection_reason(ontology_id=" chebi:48601 ", cas=cas)


@pytest.mark.parametrize("name,cas", [
    ("carnitinamide chloride", "5080-50-2"), ("DL-carnitine", "461-06-3"),
    ("L-carnitine hydrochloride", "10018-58-7"), ("Unrelated hydrochloride", "1-00-0"),
    ("Carnitine Hydrochloride solution", None), ("Carnitine (L) Hydrochloride", None),
    ("Carnitine ( Dl ) Hydrochloride", None), (None, None),
])
def test_no_global_amide_ban_or_broader_name_inference(name, cas):
    assert rejection_reason(ontology_id="CHEBI:48601", cas=cas, name=name) is None


@pytest.mark.parametrize("ontology_id", ["NCIT:C216679", "CHEBI:17126", "CHEBI_48601", ""])
def test_policy_does_not_reject_or_assign_other_targets(ontology_id):
    assert rejection_reason(ontology_id=ontology_id, cas="461-05-2",
                            name="Carnitine Hydrochloride") is None


def test_policy_is_available_from_installed_wheel_without_checkout(tmp_path):
    """Use the real package discovery config; install only into an external target."""
    project = tmp_path / "project"
    project.mkdir()
    for name in ("pyproject.toml", "README.md"):
        shutil.copyfile(ROOT / name, project / name)
    shutil.copytree(ROOT / "src/kg_microbe_utils", project / "src/kg_microbe_utils",
                    ignore=shutil.ignore_patterns("__pycache__"))
    wheels = tmp_path / "wheels"
    wheels.mkdir()
    env = {**os.environ, "PYTHONPYCACHEPREFIX": str(tmp_path / "pycache"),
           "PIP_CACHE_DIR": str(tmp_path / "pip-cache"), "PIP_NO_INDEX": "1"}
    build = subprocess.run(
        [sys.executable, "-c", "from setuptools.build_meta import build_wheel; "
         "import sys; build_wheel(sys.argv[1])", str(wheels)],
        cwd=project, env=env, capture_output=True, text=True,
    )
    assert build.returncode == 0, build.stdout + build.stderr
    wheel, = wheels.glob("*.whl")
    installed = tmp_path / "installed"
    install = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-deps", "--no-index",
         "--no-compile", "--target", str(installed), str(wheel)],
        cwd=tmp_path, env=env, capture_output=True, text=True,
    )
    assert install.returncode == 0, install.stdout + install.stderr
    probe = subprocess.run(
        [sys.executable, "-I", "-S", "-c",
         "import sys; from pathlib import Path; sys.path.insert(0, sys.argv[1]); "
         "import kg_microbe_utils.ingredient_identity_rejections as policy; "
         "assert Path(policy.__file__).is_relative_to(Path(sys.argv[1])); "
         "assert policy.rejection_reason(ontology_id='CHEBI:48601', cas='461-05-2')",
         str(installed)], cwd=tmp_path, env=env, capture_output=True, text=True,
    )
    assert probe.returncode == 0, probe.stdout + probe.stderr
