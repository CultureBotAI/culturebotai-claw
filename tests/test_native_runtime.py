"""Actual isolated venv/import tests; all release evidence is synthetic offline data."""

from __future__ import annotations

import hashlib
import json
import sys
import venv
from pathlib import Path

import pytest
from test_goal_freshness import git, isolated_git  # noqa: F401
from test_native_freshness import reference

from kg_microbe_workflows import native_runtime as runtime
from kg_microbe_workflows.native_boundary_adapter import run_cli
from kg_microbe_workflows.native_freshness import NativeFreshnessError


@pytest.fixture
def installed(tmp_path):
    source = tmp_path / "released-source"
    source.mkdir()
    git(source, "init", "--initial-branch=main")
    git(source, "remote", "add", "origin", "https://github.com/CultureBotAI/culturebotai-claw.git")
    (source / ".gitignore").write_text("__pycache__/\n")
    policy = source / "src/kg_microbe_workflows/templates/repository-freshness-v1.yaml"
    policy.parent.mkdir(parents=True)
    policy.write_bytes(runtime.CONTRACT_PATH.read_bytes())
    git(source, "add", "--all")
    git(source, "commit", "-m", "Offline base freshness dependency")
    base_commit = git(source, "rev-parse", "HEAD")
    base_tree = git(source, "rev-parse", "HEAD^{tree}")
    for name in runtime.PACKAGES:
        location = source / name if name == "plugins" else source / "src" / name
        location.mkdir(parents=True, exist_ok=True)
        (location / "__init__.py").write_text("")
    for relative in runtime.REQUIRED:
        (source / relative).write_text("# Fixture source bound by the release tree.\n")
    (source / "src/kg_microbe_workflows/freshness_cli.py").write_text(
        'import json\nprint(json.dumps({"marker":"reviewed-installed-runner"}))\n'
    )
    (source / "src/kg_microbe_fleet/retained.py").write_text(
        'MARKER = "reviewed-transitive-source"\n'
    )
    git(source, "add", "--all")
    git(source, "commit", "-m", "Offline native runner fixture")
    commit = git(source, "rev-parse", "HEAD")
    tree = git(source, "rev-parse", "HEAD^{tree}")
    prefix = tmp_path / "release-venv"
    venv.EnvBuilder(with_pip=False, symlinks=True).create(prefix)
    executable = prefix / "bin/python"
    target = executable.resolve()
    purelib = (
        prefix
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages"
    )
    (purelib / "fixture-native-release.pth").write_text(
        str(source / "src") + "\n" + str(source) + "\n"
    )
    audit = reference(
        tmp_path / "audit.json",
        {
            "schema_version": "1.0.0",
            "kind": "verified_freshness_release_source",
            "source_commit": commit,
            "source_tree": tree,
            "declaration": {"repository": runtime.REPOSITORY, "tag": "fixture-only-release"},
        },
    )
    publication = reference(
        tmp_path / "publication.json",
        {
            "status": "verified",
            "source_commit": commit,
            "tag": "fixture-only-release",
            "audit_sha256": audit["sha256"],
        },
    )
    base_audit = reference(
        tmp_path / "base-audit.json",
        {
            "kind": "verified_freshness_release_source",
            "source_commit": base_commit,
            "source_tree": base_tree,
            "declaration": {
                "repository": runtime.REPOSITORY,
                "tag": "repository-freshness-v1.0.0",
                "source_pr": 1128,
            },
        },
    )
    base_publication = reference(
        tmp_path / "base-publication.json",
        {
            "status": "verified",
            "source_commit": base_commit,
            "tag": "repository-freshness-v1.0.0",
            "audit_sha256": base_audit["sha256"],
        },
    )
    record = {
        "base_release_proof": base_audit,
        "base_publication_proof": base_publication,
        "python": str(executable),
        "python_target": str(target),
        "python_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "venv_prefix": str(prefix),
        "venv_config_sha256": hashlib.sha256((prefix / "pyvenv.cfg").read_bytes()).hexdigest(),
        "source_root": str(source),
        "canonical_release_commit": commit,
        "release_proof": audit,
        "publication_proof": publication,
        "cache_directory": str(tmp_path / "runtime-caches"),
    }
    return record, source, commit, purelib


def test_real_installed_runner_preserves_virtualenv_symlink(installed):
    record, source, commit, purelib = installed
    assert Path(record["python"]).is_symlink()
    executable = runtime.verify_runtime(record, expected_release=commit)
    assert executable == Path(record["python"]) and executable != Path(record["python_target"])
    with runtime.uncached_command(
        executable, ["-m", "kg_microbe_workflows.freshness_cli"], Path(record["cache_directory"])
    ) as command:
        result = run_cli(command, timeout=15)
    assert result == {"marker": "reviewed-installed-runner"}
    # Running the installed source may create ignored bytecode, never dirtiness.
    assert runtime.verify_runtime(record, expected_release=commit) == executable


def test_wrong_installed_package_is_rejected_before_import(installed, tmp_path):
    record, source, commit, purelib = installed
    shadow = tmp_path / "wrong-package"
    package = shadow / "kg_microbe_workflows"
    package.mkdir(parents=True)
    marker = tmp_path / "wrong-package-imported"
    (package / "__init__.py").write_text(
        f'from pathlib import Path\nPath({str(marker)!r}).write_text("bad import")\n'
    )
    (purelib / "fixture-native-release.pth").write_text(
        str(shadow) + "\n" + str(source / "src") + "\n" + str(source) + "\n"
    )
    with pytest.raises(NativeFreshnessError, match="outside the reviewed release"):
        runtime.verify_runtime(record, expected_release=commit)
    assert not marker.exists()


def test_correct_python_with_different_released_source_is_rejected(installed):
    record, source, commit, purelib = installed
    changed = dict(record)
    changed["canonical_release_commit"] = "0" * 40
    with pytest.raises(NativeFreshnessError, match="release differs"):
        runtime.verify_runtime(changed, expected_release=commit)


def test_changed_installed_entrypoint_cannot_use_old_proof(installed):
    record, source, commit, purelib = installed
    (source / "src/kg_microbe_workflows/freshness_cli.py").write_text(
        'raise SystemExit("wrong code")\n'
    )
    with pytest.raises(NativeFreshnessError, match="not clean|bytes differ"):
        runtime.verify_runtime(record, expected_release=commit)


def test_publication_proof_must_bind_exact_source_audit(installed, tmp_path):
    record, source, commit, purelib = installed
    published = json.loads(Path(record["publication_proof"]["path"]).read_text())
    published["audit_sha256"] = "0" * 64
    changed = {
        **record,
        "publication_proof": reference(tmp_path / "wrong-publication.json", published),
    }
    with pytest.raises(NativeFreshnessError, match="publication proof differs"):
        runtime.verify_runtime(changed, expected_release=commit)


def test_changed_virtualenv_configuration_holds(installed):
    record, source, commit, purelib = installed
    prefix = Path(record["venv_prefix"])
    (prefix / "pyvenv.cfg").write_text("home = /not-the-approved-runtime\n")
    with pytest.raises(NativeFreshnessError, match="configuration changed"):
        runtime.verify_runtime(record, expected_release=commit)


def test_timestamp_valid_ignored_bytecode_cannot_override_released_source(installed):
    import os
    import py_compile
    import subprocess

    record, source, commit, purelib = installed
    module = source / "src/kg_microbe_workflows/freshness_cli.py"
    approved = module.read_bytes()
    metadata = module.stat()
    altered = approved.replace(b"reviewed-installed-runner", b"altered!-installed-runner")
    assert len(altered) == len(approved)
    module.write_bytes(altered)
    os.utime(module, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
    cache = (
        module.parent / "__pycache__" / (module.stem + "." + sys.implementation.cache_tag + ".pyc")
    )
    cache.parent.mkdir(exist_ok=True)
    py_compile.compile(
        str(module),
        cfile=str(cache),
        doraise=True,
        invalidation_mode=py_compile.PycInvalidationMode.TIMESTAMP,
    )
    module.write_bytes(approved)
    os.utime(module, ns=(metadata.st_atime_ns, metadata.st_mtime_ns))
    old = subprocess.run(
        [record["python"], "-I", "-B", "-m", "kg_microbe_workflows.freshness_cli"],
        check=True,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert json.loads(old.stdout)["marker"] == "altered!-installed-runner"
    executable = runtime.verify_runtime(record, expected_release=commit)
    with runtime.uncached_command(
        executable, ["-m", "kg_microbe_workflows.freshness_cli"], Path(record["cache_directory"])
    ) as command:
        result = run_cli(command, timeout=15)
    assert result["marker"] == "reviewed-installed-runner"
    assert module.read_bytes() == approved
    assert list(Path(record["cache_directory"]).iterdir()) == []


def test_base_release_cannot_be_substituted_by_native_candidate(installed, tmp_path):
    record, source, commit, purelib = installed
    changed = {
        **record,
        "base_release_proof": record["release_proof"],
        "base_publication_proof": record["publication_proof"],
    }
    with pytest.raises(NativeFreshnessError, match="base release dependency"):
        runtime.verify_runtime(changed, expected_release=commit)


def test_base_publication_must_bind_its_own_audit(installed, tmp_path):
    record, source, commit, purelib = installed
    changed = {**record, "base_publication_proof": record["publication_proof"]}
    with pytest.raises(NativeFreshnessError, match="base release dependency"):
        runtime.verify_runtime(changed, expected_release=commit)


@pytest.mark.parametrize("tag", [None, "", "repository-freshness-v1.0.0", "invalid tag"])
def test_future_release_requires_its_own_nonempty_valid_tag(installed, tmp_path, tag):
    record, source, commit, purelib = installed
    audit = json.loads(Path(record["release_proof"]["path"]).read_text())
    published = json.loads(Path(record["publication_proof"]["path"]).read_text())
    if tag is None:
        audit["declaration"].pop("tag")
        published.pop("tag")
    else:
        audit["declaration"]["tag"] = tag
        published["tag"] = tag
    audit_ref = reference(tmp_path / "altered-future-audit.json", audit)
    published["audit_sha256"] = audit_ref["sha256"]
    changed = {
        **record,
        "release_proof": audit_ref,
        "publication_proof": reference(tmp_path / "altered-future-publication.json", published),
    }
    with pytest.raises(NativeFreshnessError):
        runtime.verify_runtime(changed, expected_release=commit)


@pytest.mark.parametrize("module", ["kg_microbe_workflows.freshness_cli", "kg_microbe_fleet.retained"])
def test_ignored_package_cannot_shadow_reviewed_entrypoint_or_dependency(installed, module):
    record, source, commit, purelib = installed
    executable = runtime.verify_runtime(record, expected_release=commit)
    relative = "src/" + module.replace(".", "/")
    reviewed = source / (relative + ".py")
    before = reviewed.read_bytes()
    shadow = source / relative
    shadow.mkdir()
    (shadow / "__init__.py").write_text('MARKER = "ignored-unreviewed-package"\n')
    (source / ".git/info/exclude").write_text(relative + "/\n")
    assert git(source, "status", "--porcelain=v1", "--untracked-files=all") == ""
    assert reviewed.read_bytes() == before
    # This real installed import demonstrates why tracked hashes/top-level origins
    # alone are insufficient, even with the existing fresh cache namespace.
    command_text = (
        f"import importlib,json; print(json.dumps({{\"marker\": "
        f"importlib.import_module({module!r}).MARKER}}))"
    )
    with runtime.uncached_command(
        executable, ["-c", command_text], Path(record["cache_directory"])
    ) as command:
        assert run_cli(command, timeout=15) == {"marker": "ignored-unreviewed-package"}
    with pytest.raises(NativeFreshnessError, match="unreviewed package descendant"):
        runtime.verify_runtime(record, expected_release=commit)
    assert reviewed.read_bytes() == before and (shadow / "__init__.py").is_file()


@pytest.mark.parametrize("name", ["extra.py", "extra.so", "extra.pyd", "notes.txt"])
def test_unknown_ignored_package_file_holds_and_is_preserved(installed, name):
    record, source, commit, purelib = installed
    relative = "src/kg_microbe_fleet/" + name
    unknown = source / relative
    unknown.write_bytes(b"unreviewed artifact")
    (source / ".git/info/exclude").write_text(relative + "\n")
    assert git(source, "status", "--porcelain=v1", "--untracked-files=all") == ""
    with pytest.raises(NativeFreshnessError, match="unreviewed package descendant"):
        runtime.verify_runtime(record, expected_release=commit)
    assert unknown.read_bytes() == b"unreviewed artifact"


@pytest.mark.parametrize("name", ["__init__.py", "orphan.pyc", "retained.invalid.pyc"])
def test_unreviewed_cache_descendants_are_not_a_package_bypass(installed, name):
    record, source, commit, purelib = installed
    cache = source / "src/kg_microbe_fleet/__pycache__"
    cache.mkdir()
    item = cache / name
    if name == "retained.invalid.pyc":
        item.symlink_to(source / "src/kg_microbe_fleet/retained.py")
    else:
        item.write_bytes(b"unreviewed executable descendant")
    assert git(source, "status", "--porcelain=v1", "--untracked-files=all") == ""
    with pytest.raises(NativeFreshnessError, match="unreviewed cache descendant"):
        runtime.verify_runtime(record, expected_release=commit)
    assert item.exists()


def test_ignored_evidence_outside_executable_packages_is_preserved(installed):
    record, source, commit, purelib = installed
    evidence = source / "operator-evidence"
    evidence.mkdir()
    item = evidence / "notes.txt"
    item.write_text("unique retained evidence")
    (source / ".git/info/exclude").write_text("operator-evidence/\n")
    assert runtime.verify_runtime(record, expected_release=commit) == Path(record["python"])
    assert item.read_text() == "unique retained evidence"
