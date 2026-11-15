"""Read-only native runner provenance, preserving a release virtualenv path."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from plugins.repository_settings import RepositoryTarget

from .freshness import FreshnessError, Git
from .freshness import identity as git_identity
from .freshness_contract import CONTRACT_PATH
from .native_freshness import (
    NativeFreshnessError,
    path,
    read_reference,
    read_regular,
    require,
    sha,
    shape,
    text,
)

REPOSITORY = "CultureBotAI/culturebotai-claw"
PACKAGES = (
    "kg_microbe_workflows",
    "kg_microbe_fleet",
    "kg_microbe_governance",
    "kg_microbe_write",
    "plugins",
)
REQUIRED = (
    "src/kg_microbe_workflows/freshness_cli.py",
    "src/kg_microbe_workflows/freshness.py",
    "src/kg_microbe_workflows/native_freshness.py",
    "src/kg_microbe_workflows/native_boundary_adapter.py",
    "src/kg_microbe_workflows/native_runtime.py",
)
PROBE = """import importlib.util,json,sys
names=json.loads(sys.argv[1])
result={"prefix":sys.prefix,"executable":sys.executable,"packages":{}}
for name in names:
 spec=importlib.util.find_spec(name)
 result["packages"][name]=None if spec is None else {"origin":spec.origin,"locations":list(spec.submodule_search_locations or [])}
print(json.dumps(result,sort_keys=True))"""


@contextmanager
def uncached_command(executable: Path, arguments: list[str], cache_directory: Path):
    """Fresh empty cache namespace: -B alone still reads timestamp-valid pyc."""
    cache_directory = path(str(cache_directory))
    cache_directory.mkdir(parents=True, exist_ok=True)
    require(cache_directory.resolve() == cache_directory, "runtime cache directory changed")
    cache = cache_directory / ("native-python-" + uuid.uuid4().hex)
    cache.mkdir(mode=0o700)
    try:
        yield [str(executable), "-I", "-B", "-X", "pycache_prefix=" + str(cache), *arguments]
    finally:
        # Never delete unknown content or another invocation's state.
        if cache.is_dir() and not cache.is_symlink() and not any(cache.iterdir()):
            cache.rmdir()
        else:
            raise NativeFreshnessError("runtime cache namespace changed; preserve it")


def probe_python(executable: Path, cache_directory: Path) -> dict[str, Any]:
    # No target package is imported: find_spec for top-level names establishes
    # resolution before the freshness entrypoint runs. -I ignores cwd/PYTHONPATH.
    try:
        with uncached_command(
            executable, ["-c", PROBE, json.dumps(PACKAGES)], cache_directory
        ) as command:
            result = subprocess.run(
                command,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
    except (OSError, subprocess.SubprocessError) as exc:
        raise NativeFreshnessError("native release package probe unavailable") from exc
    require(
        result.returncode == 0 and len(result.stdout.encode()) <= 65536,
        "native release package probe failed or exceeded bound",
    )
    try:
        value = json.loads(result.stdout)
    except ValueError as exc:
        raise NativeFreshnessError("native release package probe is malformed") from exc
    return shape(value, {"prefix", "executable", "packages"}, "native release probe fields differ")


def _python(runtime: dict) -> Path:
    raw = runtime["python"]
    require(isinstance(raw, str), "native runner executable path must be text")
    executable = Path(raw)
    # The final executable may be a normal venv symlink; parents may not alias.
    require(
        executable.is_absolute()
        and executable.parent.resolve() == executable.parent
        and ".." not in executable.parts,
        "native runner executable path aliases another directory",
    )
    target = path(runtime["python_target"])
    require(executable.resolve(strict=True) == target, "native runner symlink target changed")
    info = executable.lstat()
    require(
        stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode),
        "native runner is not a regular executable or venv symlink",
    )
    require(
        hashlib.sha256(read_regular(target, limit=100_000_000)).hexdigest()
        == sha(runtime["python_sha256"]),
        "native runner binary digest changed",
    )
    require(os.access(executable, os.X_OK), "native runner executable is not executable")
    prefix = path(runtime["venv_prefix"])
    require(
        executable.parent == prefix / "bin",
        "native runner is not the declared virtualenv executable",
    )
    require(
        hashlib.sha256(read_regular(prefix / "pyvenv.cfg")).hexdigest()
        == sha(runtime["venv_config_sha256"]),
        "native runner virtualenv configuration changed",
    )
    return executable


def verify_future_release_tag(declaration: dict, published: dict, git: Git) -> None:
    """Two absent tags are not evidence of a published native release."""
    tag = text(declaration.get("tag"))
    require(
        published.get("tag") == tag and tag != "repository-freshness-v1.0.0",
        "native release tag must be distinct from its base dependency",
    )
    try:
        git.run("check-ref-format", "refs/tags/" + tag)
    except FreshnessError as exc:
        raise NativeFreshnessError("native release tag is not a valid Git reference") from exc



def verify_package_filesystem(root: Path, prefixes: list[str], tracked: set[str]) -> None:
    """Inspect ignored descendants too; only unused conventional caches may differ.

    Unknown files are preserved and hold execution, including non-code resources:
    reviewed Python may consume those resources. Evidence outside these executable
    package roots is unaffected. Fresh pycache namespaces make the narrowly admitted
    regular cache files unusable by the runner.
    """
    directories = set(prefixes)
    for name in tracked:
        parent = Path(name).parent
        while str(parent) not in directories:
            require(parent != Path("."), "native package source is outside package roots")
            directories.add(str(parent))
            parent = parent.parent
    count = 0

    def entries(relative: str):
        nonlocal count
        location = root / relative
        require(
            stat.S_ISDIR(location.lstat().st_mode),
            "native runtime package directory is not a regular directory",
        )
        with os.scandir(location) as items:
            for item in items:
                count += 1
                require(count <= 100_000, "native runtime package inventory exceeds bound")
                yield item, str(Path(relative) / item.name)

    try:
        pending = list(prefixes)
        while pending:
            relative = pending.pop()
            for item, name in entries(relative):
                mode = item.stat(follow_symlinks=False).st_mode
                if name in tracked:
                    require(stat.S_ISREG(mode), "native runtime package source is not regular")
                elif name in directories:
                    require(stat.S_ISDIR(mode), "native runtime package directory is not regular")
                    pending.append(name)
                elif item.name == "__pycache__" and stat.S_ISDIR(mode):
                    for cached, cached_name in entries(name):
                        match = re.fullmatch(
                            r"([^.]+)\.([A-Za-z0-9_-]+)(?:\.opt-[12])?\.pyc", cached.name
                        )
                        require(
                            match is not None
                            and str(Path(relative) / (match.group(1) + ".py")) in tracked
                            and stat.S_ISREG(cached.stat(follow_symlinks=False).st_mode),
                            "native runtime has an unreviewed cache descendant: " + cached_name,
                        )
                else:
                    raise NativeFreshnessError(
                        "native runtime has an unreviewed package descendant: " + name
                    )
    except OSError as exc:
        raise NativeFreshnessError("native runtime package inventory is unreadable") from exc

def verify_runtime(runtime: Any, *, expected_release: str) -> Path:
    """Bind actual Python import resolution to the exact approved release tree.

    The supplied source/publication records are pinned operator evidence, not
    fresh GitHub API observations. No tag, pin, interpreter or Git ref is changed.
    Existing release source proof does not itself authorize native adoption.
    """
    shape(
        runtime,
        {
            "python",
            "python_target",
            "python_sha256",
            "venv_prefix",
            "venv_config_sha256",
            "source_root",
            "canonical_release_commit",
            "release_proof",
            "publication_proof",
            "base_release_proof",
            "base_publication_proof",
            "cache_directory",
        },
        "native release runtime fields differ",
    )
    require(
        runtime["canonical_release_commit"] == sha(expected_release, 40),
        "native runtime release differs",
    )
    source = read_reference(runtime["release_proof"])
    published = read_reference(runtime["publication_proof"])
    declaration = source.get("declaration")
    if not isinstance(declaration, dict):
        raise NativeFreshnessError("native release declaration shape differs")
    require(
        source.get("kind") == "verified_freshness_release_source"
        and source.get("source_commit") == expected_release
        and declaration.get("repository") == REPOSITORY,
        "native runtime lacks reviewed release source proof",
    )
    require(
        published.get("status") == "verified"
        and published.get("source_commit") == expected_release
        and published.get("audit_sha256") == runtime["release_proof"]["sha256"]
        and published.get("tag") == declaration.get("tag"),
        "native runtime publication proof differs from source audit",
    )
    root = path(runtime["source_root"])
    target = RepositoryTarget("claw", root, REPOSITORY)
    git = Git(root, timeout=30)
    git_identity(git, target)
    verify_future_release_tag(declaration, published, git)
    require(
        git.run("rev-parse", "HEAD") == expected_release
        and git.run("rev-parse", expected_release + "^{tree}") == source.get("source_tree"),
        "native runtime source HEAD/tree differs from released proof",
    )
    require(
        not git.run("status", "--porcelain=v1", "--untracked-files=all"),
        "native runtime source checkout is not clean",
    )
    base = read_reference(runtime["base_release_proof"])
    base_published = read_reference(runtime["base_publication_proof"])
    base_declaration = base.get("declaration", {})
    require(isinstance(base_declaration, dict), "base freshness declaration shape differs")
    base_commit = sha(base.get("source_commit"), 40)
    require(
        base.get("kind") == "verified_freshness_release_source"
        and base_declaration.get("repository") == REPOSITORY
        and base_declaration.get("tag") == "repository-freshness-v1.0.0"
        and base_declaration.get("source_pr") == 1128
        and base_published.get("status") == "verified"
        and base_published.get("tag") == base_declaration.get("tag")
        and base_published.get("source_commit") == base_commit
        and base_published.get("audit_sha256") == runtime["base_release_proof"]["sha256"]
        and base_commit != expected_release,
        "native runtime base release dependency differs",
    )
    require(
        git.run("rev-parse", base_commit + "^{tree}") == base.get("source_tree"),
        "base freshness release tree differs",
    )
    git.run("merge-base", "--is-ancestor", base_commit, expected_release)
    base_policy = read_regular(CONTRACT_PATH)
    policy_blob = hashlib.sha1(
        b"blob " + str(len(base_policy)).encode() + b"\0" + base_policy
    ).hexdigest()
    require(
        git.run(
            "rev-parse",
            base_commit + ":src/kg_microbe_workflows/templates/repository-freshness-v1.yaml",
        )
        == policy_blob,
        "base freshness release contract differs",
    )
    executable = _python(runtime)
    cache_directory = path(runtime["cache_directory"])
    require(
        not cache_directory.is_relative_to(root), "runtime caches must stay outside released source"
    )
    prefixes = [
        package if package == "plugins" else "src/" + package for package in PACKAGES
    ]
    listing = git.run("ls-tree", "-r", "-z", expected_release, "--", *prefixes)
    seen = set()
    total = 0
    for row in filter(None, listing.split("\0")):
        metadata, name = row.split("\t", 1)
        mode, kind, oid = metadata.split()
        require(
            kind == "blob" and mode in {"100644", "100755"},
            "native runtime source has an unsupported Git mode",
        )
        location = path(str(root / name))
        require(location.is_relative_to(root), "native runtime source escapes release root")
        raw = read_regular(location, limit=32_000_000)
        total += len(raw)
        require(total <= 128_000_000, "native runtime source exceeds verification bound")
        actual = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        require(actual == oid, "native runtime package bytes differ from released tree")
        seen.add(name)
    require(set(REQUIRED) <= seen, "release lacks the native-compatible shared entrypoints")
    verify_package_filesystem(root, prefixes, seen)
    probe = probe_python(executable, cache_directory)
    require(
        probe["prefix"] == runtime["venv_prefix"] and probe["executable"] == str(executable),
        "native runner lost declared virtualenv context",
    )
    shape(probe["packages"], set(PACKAGES), "native runner package set differs")
    for package, prefix in zip(PACKAGES, prefixes, strict=True):
        package_root = root / prefix
        require(
            probe["packages"][package]
            == {"origin": str(package_root / "__init__.py"), "locations": [str(package_root)]},
            "native runner resolves a package outside the reviewed release",
        )
    verify_package_filesystem(root, prefixes, seen)
    # Retain venv path, never return its resolved base interpreter.
    require(
        _python(runtime) == executable and git.run("rev-parse", "HEAD") == expected_release,
        "native runtime changed during verification",
    )
    return executable
