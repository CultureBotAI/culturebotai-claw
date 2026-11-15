"""Reproducible, inert infrastructure composition from existing CLAW authorities.

This owns skill managed regions and parent snapshots, never scientific records,
native profiles, governed payloads/pins, or runtime activation. Native commands
are evidence/configuration, not commands this module executes.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from importlib.metadata import distribution
from importlib.resources import files
from pathlib import Path, PurePosixPath
from typing import Any

from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_skills.catalogue import canonical_regions, render_adapter, render_identity_adapter
from kg_microbe_write import ValidatedWriteTransaction
from plugins.lock_manager import LockManager
from plugins.repository_settings import RepositoryTarget

BASELINE_PATH = "src/kg_microbe_skills/template_baseline.json"
CONFIG_PATH = "workflow/mech-template.json"
RECEIPT_PATH = "workflow/mech-template-lock.json"
AUTHORITY_GROUPS = {
    "kg_microbe_skills": ("skills.yaml", "canonical/*.md"),
    "kg_microbe_workflows": ("templates/*.yaml", "schema/*.yaml"),
    "kg_microbe_governance": ("vendored_artifacts.json", "artifacts/**/*", "private_audit/scaleup-v1.json"),
    "kg_microbe_fleet": ("fleet.yaml",),
}
PARENT_SOURCES = {
    "workflow/parent/mech-cycle.yaml": "src/kg_microbe_workflows/templates/mech-cycle.yaml",
    "workflow/parent/workflow.yaml": "src/kg_microbe_workflows/schema/workflow.yaml",
}
SHA = re.compile(r"[0-9a-f]{40}\Z")
DIGEST = re.compile(r"[0-9a-f]{64}\Z")
SKILL_TARGET = re.compile(r"\.claude/skills/[a-z][a-z0-9-]*/SKILL\.md\Z")


class TemplateError(ValueError):
    """An incomplete, conflicting, or unauthenticated composition was refused."""


def digest(content: bytes | str) -> str:
    return hashlib.sha256(content.encode() if isinstance(content, str) else content).hexdigest()


def encode(value: Any) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _json(raw: str) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise TemplateError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=unique)
    if not isinstance(value, dict):
        raise TemplateError("expected a JSON object")
    return value


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=30)
    if proc.returncode:
        raise TemplateError(f"git {args[0]} failed")
    return proc.stdout.rstrip("\n")


def _relative(value: Any) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise TemplateError("expected a relative POSIX path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or str(path) != value:
        raise TemplateError(f"unsafe path: {value}")
    return value


def _safe_path(root: Path, relative: str) -> Path:
    relative = _relative(relative)
    current = root
    for piece in PurePosixPath(relative).parts:
        current = current / piece
        if current.is_symlink():
            raise TemplateError(f"symlink refused: {relative}")
    return current


def _read(root: Path, relative: str) -> str | None:
    path = _safe_path(root, relative)
    if not path.exists():
        return None
    if not path.is_file():
        raise TemplateError(f"not a regular file: {relative}")
    return path.read_text(encoding="utf-8")


def _package_root(package: str, source_root: Path | None) -> Path:
    return source_root / "src" / package if source_root else Path(str(files(package)))


def source_inventory(source_root: Path | None = None) -> dict[str, str]:
    """Inventory disk contents, including ignored files, under authority globs."""
    result = {}
    for package, patterns in AUTHORITY_GROUPS.items():
        root = _package_root(package, source_root)
        for pattern in patterns:
            for path in sorted(root.glob(pattern)):
                relative = path.relative_to(root).as_posix()
                if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
                    continue
                _safe_path(root, relative)
                if path.is_file():
                    result[f"src/{package}/{relative}"] = digest(path.read_bytes())
    return dict(sorted(result.items()))


def _source_text(relative: str, source_root: Path | None) -> str:
    _, package, tail = relative.split("/", 2)
    raw = _read(_package_root(package, source_root), tail)
    if raw is None:
        raise TemplateError(f"missing authority: {relative}")
    return raw


def baseline_document(source_root: Path | None = None) -> dict[str, Any]:
    raw = _source_text(BASELINE_PATH, source_root)
    baseline = _json(raw)
    if set(baseline) != {"schema_version", "baseline_version", "source_ref", "sources"}:
        raise TemplateError("invalid baseline fields")
    if baseline["schema_version"] != 1 or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", baseline["baseline_version"]):
        raise TemplateError("invalid baseline version")
    if not SHA.fullmatch(baseline["source_ref"]):
        raise TemplateError("baseline source_ref must be an immutable SHA")
    sources = baseline["sources"]
    if not isinstance(sources, dict) or not sources:
        raise TemplateError("baseline sources must be nonempty")
    for path, value in sources.items():
        _relative(path)
        if not isinstance(value, str) or not DIGEST.fullmatch(value):
            raise TemplateError(f"invalid source digest: {path}")
    return baseline


def check_baseline(source_root: Path | None = None) -> dict[str, Any]:
    baseline = baseline_document(source_root)
    actual = source_inventory(source_root)
    expected = baseline["sources"]
    differences = sorted(path for path in actual.keys() | expected.keys() if actual.get(path) != expected.get(path))
    if differences:
        raise TemplateError("canonical baseline drift: " + ", ".join(differences))
    if source_root:
        _verify_source_objects(source_root, baseline["source_ref"], expected, inventory=True)
    return baseline


def _verify_source_objects(root: Path, ref: str, sources: dict[str, str], *, inventory: bool = False) -> None:
    if inventory:
        names = _git(root, "ls-tree", "-r", "--name-only", ref, "--", "src").splitlines()
        committed = set()
        for name in names:
            if "__pycache__" in PurePosixPath(name).parts or Path(name).suffix in {".pyc", ".pyo"}:
                continue
            for package, patterns in AUTHORITY_GROUPS.items():
                prefix = f"src/{package}/"
                if not name.startswith(prefix):
                    continue
                tail = name.removeprefix(prefix)
                for pattern in patterns:
                    expression = re.escape(pattern).replace(r"\*\*/", "(?:.*/)?").replace(r"\*", "[^/]*")
                    if re.fullmatch(expression, tail):
                        committed.add(name)
        if committed != set(sources):
            raise TemplateError("source revision authority inventory differs from baseline: " + ", ".join(sorted(committed ^ set(sources))))
    for path, expected in sources.items():
        proc = subprocess.run(["git", "-C", str(root), "show", f"{ref}:{path}"], capture_output=True, timeout=30)
        if proc.returncode or digest(proc.stdout) != expected:
            raise TemplateError(f"source revision does not authenticate bytes: {path}")


def refresh_baseline(source_root: Path, *, version: str | None = None, apply: bool = False) -> dict[str, Any]:
    source_root = source_root.resolve(strict=True)
    RepositoryTarget("claw", source_root, "CultureBotAI/culturebotai-claw").open()
    previous = baseline_document(source_root) if _read(source_root, BASELINE_PATH) is not None else None
    version = version or (previous["baseline_version"] if previous else "1.0.0")
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", version):
        raise TemplateError("invalid baseline version")
    ref = _git(source_root, "rev-parse", "HEAD")
    sources = source_inventory(source_root)
    # Only authority bytes must match the named commit; other development edits
    # are allowed. A newly added ignored authority is also checked here.
    _verify_source_objects(source_root, ref, sources, inventory=True)
    if previous and previous["baseline_version"] == version and previous["sources"] == sources:
        _verify_source_objects(source_root, previous["source_ref"], sources, inventory=True)
        return previous
    baseline = {"schema_version": 1, "baseline_version": version, "source_ref": ref, "sources": sources}
    tx = ValidatedWriteTransaction(source_root)
    tx.stage(BASELINE_PATH, encode(baseline))
    tx.commit(apply=apply)
    return baseline


def component_names(baseline: dict[str, Any]) -> list[str]:
    prefix = "src/kg_microbe_skills/canonical/"
    return sorted(["workflow:parent", *(
        "skill:" + Path(path).stem for path in baseline["sources"] if path.startswith(prefix)
    )])


def _identity(key: str) -> dict[str, Any]:
    manifest = load_fleet_manifest()
    if key in manifest.mechs:
        mech = manifest.mechs[key]
        return {"key": key, "github": mech.github, "private": False, "values": {
            "mech_key": key, "display_name": mech.display_name, "github": mech.github,
            "environment_variable": mech.environment_variable, "package_path": mech.package_path,
            "schema_paths": ", ".join(f"`{p}`" for p in mech.schema_paths),
            "record_globs": ", ".join(f"`{p}`" for p in mech.record_globs),
        }}
    if key == "scaleupmech":
        policy = _json(files("kg_microbe_governance").joinpath("private_audit/scaleup-v1.json").read_text())
        schema = next(item["target"] for item in policy["artifacts"] if item["id"] == "shared_mech_schema")
        package = str(PurePosixPath(schema).parent.parent)
        return {"key": key, "github": policy["repository"], "private": True, "values": {
            "mech_key": key, "display_name": "ScaleupMech", "github": policy["repository"],
            "environment_variable": "SCALEUPMECH_ROOT", "package_path": package,
            "schema_paths": "consumer configuration required", "record_globs": "consumer configuration required",
        }}
    raise TemplateError(f"unknown repository: {key}")


def _implementation_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _verify_implementation(ref: str, source_root: Path | None) -> None:
    if not isinstance(ref, str) or not SHA.fullmatch(ref):
        raise TemplateError("source_ref must be an immutable implementation SHA")
    if source_root:
        if source_root != _implementation_root():
            raise TemplateError("source-root is not the executing implementation checkout")
        payloads = {}
        for path in sorted((source_root / "src/kg_microbe_skills").glob("*.py")):
            relative = path.relative_to(source_root).as_posix()
            _safe_path(source_root, relative)
            payloads[relative] = digest(path.read_bytes())
        baseline = _read(source_root, BASELINE_PATH)
        if baseline is None:
            raise TemplateError("implementation baseline lock is absent")
        payloads[BASELINE_PATH] = digest(baseline)
        pinned = {
            path for path in _git(source_root, "ls-tree", "-r", "--name-only", ref, "--", "src/kg_microbe_skills").splitlines()
            if path == BASELINE_PATH or (
                PurePosixPath(path).parent == PurePosixPath("src/kg_microbe_skills") and path.endswith(".py")
            )
        }
        if pinned != set(payloads):
            raise TemplateError("implementation revision inventory differs from configured source_ref")
        _verify_source_objects(source_root, ref, payloads)
        # An unrelated commit or squash merge does not change the pinned bundle.
        # Dirty, added and deleted implementation files or a changed baseline do.
        return
    else:
        direct = distribution("kg-microbe-orchestration").read_text("direct_url.json")
        metadata = _json(direct) if direct else {}
        observed = metadata.get("vcs_info", {}).get("commit_id")
        if not observed:
            raise TemplateError("installed package needs immutable Git direct_url provenance or --source-root")
    if observed != ref:
        raise TemplateError("implementation revision differs from config source_ref")


def _validate_config(config: dict[str, Any], names: list[str]) -> None:
    if set(config) - {"native_identity"} != {"schema_version", "repository", "source_ref", "components", "native_checks", "extensions"}:
        raise TemplateError("invalid config fields")
    if config["schema_version"] != 1 or not isinstance(config["repository"], str):
        raise TemplateError("invalid config identity/version")
    components = config["components"]
    if not isinstance(components, dict) or set(components) != set(names):
        raise TemplateError("config must explicitly decide every baseline component")
    targets = []
    for name, decision in components.items():
        if not isinstance(decision, dict) or set(decision) - {"action", "reason", "evidence", "target"}:
            raise TemplateError(f"invalid component decision: {name}")
        if decision.get("action") not in {"adopt", "defer", "not_applicable"}:
            raise TemplateError(f"invalid component action: {name}")
        if not isinstance(decision.get("reason"), str) or not decision["reason"].strip():
            raise TemplateError(f"component needs a measured reason: {name}")
        evidence = decision.get("evidence")
        if not isinstance(evidence, list) or not evidence or not all(isinstance(item, str) and item.strip() for item in evidence):
            raise TemplateError(f"component needs evidence: {name}")
        if "target" in decision and (not name.startswith("skill:") or decision["action"] != "adopt"):
            raise TemplateError("only adopted skills may customize their target")
        if name.startswith("skill:") and decision["action"] == "adopt":
            target = decision.get("target", f".claude/skills/{name[6:]}/SKILL.md")
            if not isinstance(target, str) or not SKILL_TARGET.fullmatch(target):
                raise TemplateError(f"invalid skill target: {target}")
            targets.append(target)
    if len(targets) != len(set(targets)):
        raise TemplateError("component target collision")
    checks = config["native_checks"]
    if not isinstance(checks, list) or not checks or not all(
        isinstance(check, list) and check and all(isinstance(arg, str) and arg.strip() for arg in check) for check in checks
    ):
        raise TemplateError("native_checks must record nonempty argv arrays (never executed)")
    extensions = config["extensions"]
    if not isinstance(extensions, list):
        raise TemplateError("extensions must be paths")
    for path in extensions:
        _relative(path)
        if any(path == target or target.startswith(path + "/") for target in targets):
            raise TemplateError("consumer extension overlaps a managed target")


def _managed_hashes(text: str) -> dict[str, str]:
    regions = canonical_regions(text)
    return {name: digest(value) for name, value in regions.items()} if regions else {"file": digest(text)}


def _validate_layout(root: Path) -> None:
    if _read(root, "AGENTS.md") is None:
        raise TemplateError("required layout: real AGENTS.md is absent")
    skills = _safe_path(root, ".claude/skills")
    if not skills.is_dir():
        raise TemplateError("required layout: .claude/skills must be a real directory")
    _safe_path(root, ".agents")
    for relative, destination in (("CLAUDE.md", "AGENTS.md"), (".agents/skills", "../.claude/skills")):
        path = root / relative
        if not path.is_symlink() or os.readlink(path) != destination:
            raise TemplateError(f"required layout: {relative} must link relatively to {destination}")


@dataclass
class TemplatePlan:
    root: Path
    identity: dict[str, Any]
    report: dict[str, Any]
    outputs: dict[str, str]
    expected: dict[str, str | None]


def plan_repository(target_root: Path, *, config_path: Path | None = None,
                    source_root: Path | None = None) -> TemplatePlan:
    root = target_root.resolve(strict=True)
    if source_root:
        source_root = source_root.resolve(strict=True)
    baseline = check_baseline(source_root)
    config_path = config_path or root / CONFIG_PATH
    if not config_path.is_absolute():
        config_path = root / config_path
    try:
        config_relative = config_path.relative_to(root).as_posix()
    except ValueError as exc:
        raise TemplateError("config must be inside target repository") from exc
    raw = _read(root, config_relative)
    if raw is None:
        raise TemplateError("consumer has no template config; not adopted")
    config = _json(raw)
    _validate_config(config, component_names(baseline))
    _verify_implementation(config["source_ref"], source_root)
    identity = _identity(config["repository"])
    RepositoryTarget(identity["key"], root, identity["github"]).open()
    _validate_layout(root)
    native = config.get("native_identity")
    if identity["private"]:
        if not isinstance(native, dict) or set(native) != {"schema_paths", "record_globs"}:
            raise TemplateError("private consumer requires measured native_identity schema_paths/record_globs")
        for key in ("schema_paths", "record_globs"):
            values = native[key]
            if not isinstance(values, list) or not values:
                raise TemplateError(f"private native_identity needs {key}")
            for value in values:
                _relative(value)
                if key == "schema_paths" and not _safe_path(root, value).is_file():
                    raise TemplateError(f"private native schema absent: {value}")
            identity["values"][key] = ", ".join(f"`{value}`" for value in values)
    elif native is not None:
        raise TemplateError("public identity must come from fleet manifest")
    for extension in config["extensions"]:
        if not _safe_path(root, extension).exists():
            raise TemplateError(f"declared consumer extension is absent: {extension}")
    old_receipt_raw = _read(root, RECEIPT_PATH)
    old = _json(old_receipt_raw) if old_receipt_raw else {}
    if old and (old.get("schema_version") != 1 or old.get("repository") != config["repository"]):
        raise TemplateError("receipt identity/version mismatch")
    previous = old.get("files", {})
    if not isinstance(previous, dict):
        raise TemplateError("invalid receipt files")
    outputs: dict[str, str] = {}
    expected = {config_relative: raw, RECEIPT_PATH: old_receipt_raw}
    records = {}
    for component, decision in sorted(config["components"].items()):
        if decision["action"] != "adopt":
            continue
        if component == "workflow:parent":
            desired = {target: _source_text(source, source_root) for target, source in PARENT_SOURCES.items()}
        else:
            name = component[6:]
            target = decision.get("target", f".claude/skills/{name}/SKILL.md")
            template = _source_text(f"src/kg_microbe_skills/canonical/{name}.md", source_root)
            rendered = (render_identity_adapter(template, identity["values"]) if identity["private"]
                        else render_adapter(template, identity["key"]))
            desired = {target: rendered}
        for target, rendered in desired.items():
            current = _read(root, target)
            expected[target] = current
            prior = previous.get(target)
            if current is not None:
                if prior:
                    observed = _managed_hashes(current) if component.startswith("skill:") else {"file": digest(current)}
                    if observed != prior.get("managed"):
                        raise TemplateError(f"managed content changed locally: {target}")
                elif _managed_hashes(current) != _managed_hashes(rendered):
                    raise TemplateError(f"unmanaged existing target; adopt markers through review first: {target}")
                if component.startswith("skill:") and canonical_regions(rendered):
                    rendered = render_identity_adapter(template, identity["values"], existing=current)
            outputs[target] = rendered
            records[target] = {"component": component, "managed": (
                _managed_hashes(rendered) if component.startswith("skill:") else {"file": digest(rendered)}
            )}
    if set(previous) - set(records):
        raise TemplateError("previously adopted components cannot be silently removed or relocated")
    receipt = {
        "schema_version": 1, "repository": config["repository"], "status": "candidate",
        "source_ref": config["source_ref"], "canonical_source_ref": baseline["source_ref"],
        "baseline_version": baseline["baseline_version"], "baseline_sha256": digest(encode(baseline)),
        "config_sha256": digest(raw), "files": records,
    }
    outputs[RECEIPT_PATH] = encode(receipt)
    changed = sorted(path for path, content in outputs.items() if expected.get(path) != content)
    pin = _read(root, "scripts/.vendored_canon_ref")
    report = {
        "repository": config["repository"], "status": "drift" if changed else "current",
        "changed_paths": changed, "components": config["components"],
        "source_ref": config["source_ref"], "baseline_sha256": receipt["baseline_sha256"],
        "native_checks": config["native_checks"], "extensions": config["extensions"],
        "governance": {"status": "separate_validation_required", "observed_pin": pin.strip() if pin else None,
                       "private_policy": identity["private"], "writes": False},
        "runtime_activation": False,
    }
    return TemplatePlan(root, identity, report, outputs, expected)


def apply_plan(plan: TemplatePlan, *, apply: bool = False) -> dict[str, Any]:
    def execute() -> dict[str, Any]:
        if any(path != RECEIPT_PATH and path not in PARENT_SOURCES and not SKILL_TARGET.fullmatch(path) for path in plan.outputs):
            raise TemplateError("template plan contains an unmanaged output path")
        RepositoryTarget(plan.identity["key"], plan.root, plan.identity["github"]).open()
        _validate_layout(plan.root)
        for path, expected in plan.expected.items():
            if _read(plan.root, path) != expected:
                raise TemplateError(f"target changed after planning: {path}")
        if not plan.report["changed_paths"]:
            return {**plan.report, "applied": False, "journal": None}
        journal = Path(_git(plan.root, "rev-parse", "--git-path", "mech-template-journals"))
        if not journal.is_absolute():
            journal = plan.root / journal
        def validate(path: Path, text: str) -> None:
            relative = path.relative_to(plan.root).as_posix()
            if relative not in plan.outputs or text != plan.outputs[relative]:
                raise TemplateError("unexpected staged template output")
            # Validate the complete optimistic snapshot before each staged write.
            for original, expected in plan.expected.items():
                if _read(plan.root, original) != expected:
                    raise TemplateError(f"target changed during staging: {original}")
        tx = ValidatedWriteTransaction(plan.root, validator=validate, journal_dir=journal)
        for path, content in plan.outputs.items():
            tx.stage(path, content)
        result = tx.commit(apply=apply)
        return {**plan.report, **result.as_dict()}
    if not apply:
        return execute()
    with LockManager().lock(plan.identity["key"], "mech-template-adoption"):
        return execute()
