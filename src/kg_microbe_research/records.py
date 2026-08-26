"""Strict, provider-free persistence for deep-research result records.

The LinkML schema governs the serialised shape.  This module enforces the
cross-field invariants that a schema cannot express: lifecycle consistency,
reference closure, policy facts, safe paths, and byte-level checksums.  Saved
plans are audit snapshots only; nothing here reconstructs execution authority
or contacts a provider.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import importlib
import math
import os
import re
import secrets
import stat
import threading
from collections import defaultdict
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from importlib.resources import files
from pathlib import Path, PurePosixPath
from typing import Any

import yaml
from linkml.validator import Validator
from linkml.validator.plugins import JsonschemaValidationPlugin

from .policy import authorize, plan_stage
from .profile import ProfileError, ResearchProfile, load_profile_bytes
from .providers import (
    COST_VALUE,
    DEEPER_MED_STUB_REASON,
    KNOWN_BLOCKED,
    MOCK_STUB_REASON,
    MOCK_UNAVAILABLE_REASON,
    PROVIDER_CATALOGUE_SHA256,
    PROVIDER_CATALOGUE_VERSION,
    PROVIDERS,
    TRIAGE_CONTRACT_SHA256,
    TRIAGE_CONTRACT_VERSION,
    AvailabilityEvidence,
    LocalProbe,
    canonical_provider,
)
from .triage import rank_stage

RESEARCH_VERSION = 1
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
WINDOWS_DRIVE_PATTERN = re.compile(r"^[A-Za-z]:")
SUPPORTED_RESULT_STATUSES = frozenset(
    {"DRY_RUN", "COMPLETED", "PARTIAL", "FAILED", "UNUSABLE"}
)
EVIDENCE_BEARING_SUPPORT = frozenset({"SUPPORT", "REFUTE", "PARTIAL", "WRONG_STATEMENT"})
TERMINAL_LIVE_STATUSES = frozenset({"COMPLETED", "FAILED", "UNUSABLE"})
STABLE_REFERENCE_PATTERN = re.compile(
    r"^(?:https://[^\s]+|[A-Za-z][A-Za-z0-9._-]*:[^\s:][^\s]*)$"
)
RESULT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SUPPORTED_PROVIDER_CATALOGUES = frozenset(
    {(PROVIDER_CATALOGUE_VERSION, PROVIDER_CATALOGUE_SHA256)}
)
SUPPORTED_TRIAGE_CONTRACTS = frozenset(
    {(TRIAGE_CONTRACT_VERSION, TRIAGE_CONTRACT_SHA256)}
)
ASSESSMENT_ADDITION_ARTIFACT_ROLES = frozenset(
    {
        "SOURCE_SNAPSHOT",
        "REFERENCE_VALIDATION",
        "EVIDENCE_ASSESSMENT",
        "TARGET_SNAPSHOT",
        "PATCH",
        "DOMAIN_SCHEMA",
        "DOMAIN_VALIDATION",
    }
)
RAW_FORBIDDEN_ARTIFACT_ROLES = frozenset(
    {"EVIDENCE_ASSESSMENT", "PATCH", "DOMAIN_SCHEMA", "DOMAIN_VALIDATION"}
)


class _PureLinkMLYamlLoader(yaml.SafeLoader):
    """Pure-Python LinkML loader insulated from PyYAML C import-order damage.

    Coverage's dotted-source discovery can import ``yaml.cyaml`` recursively
    while coverage is starting. PyYAML 6.0.3 then leaves ``CSafeLoader``
    producing nodes with null tags for the lifetime of the process. LinkML's
    default duplicate-check loader inherits that C parser, so even packaged
    ``linkml:types`` cannot load. The pure safe loader has the same duplicate
    rejection needed here and is also isolated from foreign path resolvers.
    """

    yaml_path_resolvers: dict[Any, Any] = {}

    def construct_mapping(self, node: yaml.MappingNode, deep: bool = False) -> dict[Any, Any]:
        self.flatten_mapping(node)
        mapping: dict[Any, Any] = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            try:
                duplicate = key in mapping
            except TypeError as exc:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    "found an unhashable key",
                    key_node.start_mark,
                ) from exc
            if duplicate:
                raise yaml.constructor.ConstructorError(
                    "while constructing a mapping",
                    node.start_mark,
                    f"found duplicate key {key!r}",
                    key_node.start_mark,
                )
            mapping[key] = self.construct_object(value_node, deep=deep)
        return mapping


_linkml_yaml_loader = importlib.import_module("linkml_runtime.loaders.yaml_loader")
_LINKML_LOADER_LOCK = threading.RLock()


@contextmanager
def _pure_linkml_loader() -> Iterator[None]:
    """Scope the pure parser to this package's LinkML operation."""

    with _LINKML_LOADER_LOCK:
        original = getattr(_linkml_yaml_loader, "DupCheckYamlLoader")
        setattr(_linkml_yaml_loader, "DupCheckYamlLoader", _PureLinkMLYamlLoader)
        try:
            yield
        finally:
            setattr(_linkml_yaml_loader, "DupCheckYamlLoader", original)


class ResearchRecordError(ValueError):
    """A research result is malformed, inconsistent, or unsafe to persist."""


class _StrictResultLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects aliases, anchors, tags, and duplicate keys."""

    # ISO timestamps are record strings, not Python datetime objects.  Keeping
    # them as text makes quoted and unquoted YAML behave identically and lets
    # LinkML's date-time format check see the serialised representation.
    yaml_implicit_resolvers = {
        key: [
            item
            for item in resolvers
            if item[0] != "tag:yaml.org,2002:timestamp"
        ]
        for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }
    # Do not inherit process-global path resolvers installed by unrelated YAML
    # consumers. A resolver returning ``None`` can otherwise produce untyped
    # MappingNodes and make LinkML fail depending on test/import order.
    yaml_path_resolvers: dict[Any, Any] = {}

    def compose_node(self, parent: yaml.Node | None, index: Any) -> yaml.Node:
        if self.check_event(yaml.AliasEvent):
            event = self.peek_event()
            raise yaml.constructor.ConstructorError(
                None,
                None,
                "YAML aliases are not permitted in research results",
                event.start_mark,
            )
        event = self.peek_event()
        if getattr(event, "anchor", None) is not None:
            raise yaml.constructor.ConstructorError(
                None,
                None,
                "YAML anchors are not permitted in research results",
                event.start_mark,
            )
        if getattr(event, "tag", None) is not None:
            raise yaml.constructor.ConstructorError(
                None,
                None,
                "explicit YAML tags are not permitted in research results",
                event.start_mark,
            )
        return super().compose_node(parent, index)


def _construct_unique_mapping(
    loader: _StrictResultLoader,
    node: yaml.MappingNode,
    deep: bool = False,
) -> dict[Any, Any]:
    mapping: dict[Any, Any] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found an unhashable mapping key {key!r}",
                key_node.start_mark,
            ) from exc
        if duplicate:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate mapping key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


_StrictResultLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def default_research_schema_path() -> Path:
    """Return the LinkML schema shipped with ``kg_microbe_research``."""

    return Path(str(files("kg_microbe_research").joinpath("schema/research.yaml")))


@lru_cache(maxsize=1)
def _linkml_validator() -> Validator:
    schema = default_research_schema_path()
    if not schema.is_file():
        raise ResearchRecordError(
            "packaged research schema is missing: "
            "kg_microbe_research/schema/research.yaml"
        )
    try:
        schema_document = yaml.load(schema.read_text(encoding="utf-8"), Loader=_StrictResultLoader)
    except (OSError, UnicodeError, yaml.YAMLError) as exc:
        raise ResearchRecordError(f"packaged research schema is not strict YAML: {exc}") from exc
    if not isinstance(schema_document, dict):
        raise ResearchRecordError("packaged research schema must be a YAML mapping")
    with _pure_linkml_loader():
        return Validator(
            schema_document,
            validation_plugins=[JsonschemaValidationPlugin(closed=True)],
            strict=True,
        )


def sha256_bytes(value: bytes) -> str:
    """Return the lowercase SHA-256 digest of exact bytes."""

    return hashlib.sha256(value).hexdigest()


def sha256_text(value: str) -> str:
    """Return the SHA-256 digest of a string's exact UTF-8 encoding."""

    return sha256_bytes(value.encode("utf-8"))


def _nonblank(value: Any, where: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ResearchRecordError(f"{where} must be a non-empty string")
    return value


def _sha256(value: Any, where: str) -> str:
    if not isinstance(value, str) or SHA256_PATTERN.fullmatch(value) is None:
        raise ResearchRecordError(f"{where} must be a lowercase SHA-256 digest")
    return value


def _integer(value: Any, where: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ResearchRecordError(f"{where} must be an integer >= {minimum}")
    return value


def _number(value: Any, where: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ResearchRecordError(f"{where} must be a finite number >= {minimum}")
    number = float(value)
    if not math.isfinite(number) or number < minimum:
        raise ResearchRecordError(f"{where} must be a finite number >= {minimum}")
    return number


def _timestamp(value: Any, where: str) -> datetime:
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ResearchRecordError(f"{where} must be a timezone-aware ISO-8601 string")
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            raise ValueError("timezone missing")
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError) as exc:
        raise ResearchRecordError(
            f"{where} must be a timezone-aware ISO-8601 string"
        ) from exc


def _relative_path(value: Any, where: str) -> PurePosixPath:
    text = _nonblank(value, where)
    if (
        "\x00" in text
        or "\\" in text
        or "://" in text
        or WINDOWS_DRIVE_PATTERN.match(text)
    ):
        raise ResearchRecordError(f"{where} must be a normalized repository-relative path")
    path = PurePosixPath(text)
    if (
        path.is_absolute()
        or path.as_posix() != text
        or text in {".", ".."}
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ResearchRecordError(f"{where} must be a normalized repository-relative path")
    return path


def _root_directory(repository_root: Path) -> Path:
    try:
        root = Path(repository_root).resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ResearchRecordError(
            f"repository root does not exist: {repository_root}"
        ) from exc
    if not root.is_dir():
        raise ResearchRecordError(f"repository root is not a directory: {root}")
    return root


def _open_root_descriptor(root: Path, flags: int) -> int:
    """Open the resolved repository root without following or swapping it."""

    nofollow = getattr(os, "O_NOFOLLOW", 0)
    try:
        expected = os.stat(root, follow_symlinks=False)
        if not stat.S_ISDIR(expected.st_mode):
            raise OSError("repository root is not a physical directory")
        descriptor = os.open(root, flags | nofollow)
        observed = os.fstat(descriptor)
        if (observed.st_dev, observed.st_ino) != (expected.st_dev, expected.st_ino):
            os.close(descriptor)
            raise OSError("repository root changed while it was being opened")
        return descriptor
    except OSError as exc:
        raise ResearchRecordError(
            f"repository root cannot be opened without following a replacement: {root}: {exc}"
        ) from exc


def _read_repository_file(repository_root: Path, value: str, where: str) -> bytes:
    """Read a regular file without following repository-internal symlinks.

    On POSIX, every path component is opened relative to an already-open
    directory descriptor with ``O_NOFOLLOW``. This closes the resolve/read race
    where an attacker could replace a checked directory with a symlink before
    the file was opened. The conservative fallback retains containment checks
    for platforms without ``dir_fd`` support.
    """

    root = _root_directory(repository_root)
    relative = _relative_path(value, where)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    cloexec = getattr(os, "O_CLOEXEC", 0)
    if os.open in getattr(os, "supports_dir_fd", set()) and nofollow:
        opened: list[int] = []
        file_descriptor: int | None = None
        try:
            current = _open_root_descriptor(
                root, os.O_RDONLY | directory | cloexec
            )
            opened.append(current)
            for part in relative.parts[:-1]:
                current = os.open(
                    part,
                    os.O_RDONLY | directory | nofollow | cloexec,
                    dir_fd=current,
                )
                opened.append(current)
            file_descriptor = os.open(
                relative.parts[-1],
                os.O_RDONLY | nofollow | cloexec,
                dir_fd=current,
            )
            if not stat.S_ISREG(os.fstat(file_descriptor).st_mode):
                raise ResearchRecordError(f"{where} is not a regular file: {value}")
            with os.fdopen(file_descriptor, "rb") as handle:
                file_descriptor = None
                return handle.read()
        except ResearchRecordError:
            raise
        except OSError as exc:
            raise ResearchRecordError(
                f"{where} does not resolve to a regular file inside repository root {root}: {exc}"
            ) from exc
        finally:
            if file_descriptor is not None:
                os.close(file_descriptor)
            for descriptor in reversed(opened):
                os.close(descriptor)

    candidate = root.joinpath(*relative.parts)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(root)
        if not resolved.is_file():
            raise OSError("not a regular file")
        return resolved.read_bytes()
    except (OSError, RuntimeError, ValueError) as exc:
        raise ResearchRecordError(
            f"{where} does not resolve to a regular file inside repository root {root}: {exc}"
        ) from exc


def _check_file(
    repository_root: Path,
    path: str,
    expected_sha256: str,
    where: str,
    *,
    expected_size: int | None = None,
) -> bytes:
    content = _read_repository_file(repository_root, path, f"{where}.path")
    actual = sha256_bytes(content)
    if actual != expected_sha256:
        raise ResearchRecordError(
            f"{where}.sha256 does not match {path}: expected {expected_sha256}, got {actual}"
        )
    if expected_size is not None and len(content) != expected_size:
        raise ResearchRecordError(
            f"{where}.size_bytes does not match {path}: "
            f"expected {expected_size}, got {len(content)}"
        )
    return content


def _repository_path_exists(repository_root: Path, value: str, where: str) -> bool:
    """Check path existence without following a repository-internal symlink."""

    root = _root_directory(repository_root)
    relative = _relative_path(value, where)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    cloexec = getattr(os, "O_CLOEXEC", 0)
    if os.open in getattr(os, "supports_dir_fd", set()) and nofollow:
        opened: list[int] = []
        try:
            current = _open_root_descriptor(
                root, os.O_RDONLY | directory | cloexec
            )
            opened.append(current)
            for part in relative.parts[:-1]:
                try:
                    current = os.open(
                        part,
                        os.O_RDONLY | directory | nofollow | cloexec,
                        dir_fd=current,
                    )
                except FileNotFoundError:
                    return False
                opened.append(current)
            try:
                os.stat(relative.parts[-1], dir_fd=current, follow_symlinks=False)
            except FileNotFoundError:
                return False
            return True
        except OSError as exc:
            raise ResearchRecordError(
                f"{where} cannot be checked safely inside repository root {root}: {exc}"
            ) from exc
        finally:
            for descriptor in reversed(opened):
                os.close(descriptor)

    candidate = root.joinpath(*relative.parts)
    try:
        candidate.parent.resolve(strict=False).relative_to(root)
        candidate.lstat()
        return True
    except FileNotFoundError:
        return False
    except (OSError, RuntimeError, ValueError) as exc:
        raise ResearchRecordError(
            f"{where} cannot be checked safely inside repository root {root}: {exc}"
        ) from exc


def _unique_ids(record: Mapping[str, Any]) -> None:
    result_id = _nonblank(record["result_id"], "result_id")
    if RESULT_ID_PATTERN.fullmatch(result_id) is None:
        raise ResearchRecordError(
            "result_id must contain only letters, digits, dot, dash, and underscore"
        )
    entries: list[tuple[str, str]] = [
        ("result_id", result_id),
        ("plan.plan_id", _nonblank(record["plan"]["plan_id"], "plan.plan_id")),
        (
            "plan.question.question_id",
            _nonblank(
                record["plan"]["question"]["question_id"],
                "plan.question.question_id",
            ),
        ),
    ]
    for collection, key in (
        ("runs", "run_id"),
        ("citations", "citation_id"),
        ("artifacts", "artifact_id"),
        ("evidence", "evidence_id"),
        ("findings", "finding_id"),
        ("proposed_changes", "change_id"),
    ):
        for index, item in enumerate(record.get(collection, [])):
            entries.append(
                (
                    f"{collection}[{index}].{key}",
                    _nonblank(item[key], f"{collection}[{index}].{key}"),
                )
            )
    seen: dict[str, str] = {}
    for where, identifier in entries:
        if identifier in seen:
            raise ResearchRecordError(
                f"{where} duplicates identifier {identifier!r} from {seen[identifier]}"
            )
        seen[identifier] = where


def _canonical_provider_name(provider_name: str, where: str) -> str:
    if (
        not isinstance(provider_name, str)
        or canonical_provider(provider_name) != provider_name
        or provider_name not in PROVIDERS
    ):
        raise ResearchRecordError(f"{where} must be a canonical provider name")
    return provider_name


def _validate_catalogue_facts(item: Mapping[str, Any], where: str) -> None:
    """Bind copied cost and billing facts to the retained catalogue contract."""

    provider_name = _canonical_provider_name(item["provider"], f"{where}.provider")
    provider = PROVIDERS[provider_name]
    expected_gate = provider.billing != "free"
    if (
        item["relative_cost"] != provider.cost
        or item["billing"] != provider.billing
        or item["usage_authorization_required"] is not expected_gate
    ):
        raise ResearchRecordError(
            f"{where} cost/billing facts contradict the versioned provider catalogue"
        )


def _validate_plan(record: Mapping[str, Any]) -> dict[str, list[Mapping[str, Any]]]:
    plan = record["plan"]
    if plan["authority"] != "audit_only":
        raise ResearchRecordError("plan.authority must be audit_only")
    catalogue_contract = (
        plan["provider_catalogue_version"],
        plan["provider_catalogue_sha256"],
    )
    if catalogue_contract not in SUPPORTED_PROVIDER_CATALOGUES:
        raise ResearchRecordError(
            "plan provider catalogue version/digest is unsupported"
        )
    triage_contract = (
        plan["triage_contract_version"],
        plan["triage_contract_sha256"],
    )
    if triage_contract not in SUPPORTED_TRIAGE_CONTRACTS:
        raise ResearchRecordError(
            "plan triage contract version/digest is unsupported"
        )
    _sha256(plan["profile_sha256"], "plan.profile_sha256")
    _relative_path(plan["profile_path"], "plan.profile_path")
    _nonblank(plan["focus"], "plan.focus")
    _nonblank(plan["evidence_policy"], "plan.evidence_policy")

    allowlist = plan.get("provider_allowlist", [])
    if "provider_allowlist" in plan and not allowlist:
        raise ResearchRecordError(
            "plan.provider_allowlist must be absent rather than an empty unrestricted list"
        )
    if len(allowlist) != len(set(allowlist)):
        raise ResearchRecordError("plan.provider_allowlist contains duplicate providers")
    for index, provider_name in enumerate(allowlist):
        _canonical_provider_name(provider_name, f"plan.provider_allowlist[{index}]")

    target = plan["question"]["target"]
    for field in ("target_id", "target_label", "target_type"):
        _nonblank(target[field], f"plan.question.target.{field}")
    _nonblank(plan["question"]["text"], "plan.question.text")
    _relative_path(target["target_path"], "plan.question.target.target_path")
    _sha256(target["target_sha256"], "plan.question.target.target_sha256")

    evaluations: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    evaluation_stage_order: list[str] = []
    for index, evaluation in enumerate(plan["provider_evaluations"]):
        where = f"plan.provider_evaluations[{index}]"
        stage = _nonblank(evaluation["stage"], f"{where}.stage")
        _integer(evaluation["ordinal"], f"{where}.ordinal", minimum=1)
        _integer(evaluation["fit"], f"{where}.fit")
        if evaluation["fit"] > 100:
            raise ResearchRecordError(f"{where}.fit must be <= 100")
        _validate_catalogue_facts(evaluation, where)
        _nonblank(evaluation["provider_status_reason"], f"{where}.provider_status_reason")
        provider_name = evaluation["provider"]
        observed_status = (
            evaluation["provider_status"],
            evaluation["provider_status_reason"],
        )
        if provider_name in KNOWN_BLOCKED and observed_status != (
            "blocked",
            KNOWN_BLOCKED[provider_name],
        ):
            raise ResearchRecordError(
                f"{where} contradicts the versioned blocked-provider policy"
            )
        if provider_name == "deeper_med" and observed_status != (
            "stub",
            DEEPER_MED_STUB_REASON,
        ):
            raise ResearchRecordError(
                f"{where} contradicts the catalogue-only stub policy"
            )
        if provider_name == "mock" and observed_status not in {
            (
                "unavailable",
                MOCK_UNAVAILABLE_REASON,
            ),
            ("stub", MOCK_STUB_REASON),
        }:
            raise ResearchRecordError(
                f"{where} contradicts the catalogue-only mock policy"
            )
        if (
            provider_name not in {"mock", "deeper_med"}
            and evaluation["provider_status"] == "stub"
        ):
            raise ResearchRecordError(
                f"{where}.provider_status cannot label an executable catalogue row as stub"
            )
        if stage not in evaluations:
            evaluation_stage_order.append(stage)
        elif evaluation_stage_order[-1] != stage:
            raise ResearchRecordError(
                f"{where}.stage must be grouped with the other {stage!r} evaluations"
            )
        evaluations[stage].append(evaluation)

    for stage, stage_evaluations in evaluations.items():
        ordinals = [evaluation["ordinal"] for evaluation in stage_evaluations]
        expected_ordinals = list(range(1, len(PROVIDERS) + 1))
        if ordinals != expected_ordinals:
            raise ResearchRecordError(
                f"provider evaluations for stage {stage!r} must have contiguous "
                f"ordinals {expected_ordinals}"
            )
        providers = [evaluation["provider"] for evaluation in stage_evaluations]
        if len(providers) != len(set(providers)) or set(providers) != set(PROVIDERS):
            raise ResearchRecordError(
                f"provider evaluations for stage {stage!r} must contain the complete catalogue"
            )

    assignments: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    stage_order: list[str] = []
    for index, assignment in enumerate(plan["stage_assignments"]):
        where = f"plan.stage_assignments[{index}]"
        stage = _nonblank(assignment["stage"], f"{where}.stage")
        _integer(assignment["ordinal"], f"{where}.ordinal", minimum=1)
        provider_name = assignment["provider"]
        _validate_catalogue_facts(assignment, where)
        expected_gate = assignment["usage_authorization_required"]
        if plan["no_paid"] and expected_gate:
            raise ResearchRecordError(f"{where} violates plan.no_paid")
        if (
            allowlist
            and provider_name not in allowlist
            and assignment["assignment_kind"] != "OVERRIDE"
        ):
            raise ResearchRecordError(
                f"{where}.provider is outside the recorded allowlist without OVERRIDE"
            )
        if assignment["provider_status"] != "available":
            raise ResearchRecordError(
                f"{where} cannot assign a provider that was not available"
            )
        if assignment["assignment_kind"] == "OVERRIDE":
            _nonblank(assignment.get("override_reason"), f"{where}.override_reason")
        elif "override_reason" in assignment:
            raise ResearchRecordError(
                f"{where}.override_reason is only valid for an OVERRIDE assignment"
            )
        _nonblank(assignment["objective"], f"{where}.objective")
        _nonblank(
            assignment["provider_status_reason"],
            f"{where}.provider_status_reason",
        )
        if stage not in assignments:
            stage_order.append(stage)
        elif stage_order[-1] != stage:
            raise ResearchRecordError(
                f"{where}.stage must be grouped with the other {stage!r} assignments"
            )
        assignments[stage].append(assignment)

    for stage, stage_assignments in assignments.items():
        ordinals = [assignment["ordinal"] for assignment in stage_assignments]
        expected = list(range(1, len(stage_assignments) + 1))
        if ordinals != expected:
            raise ResearchRecordError(
                f"assignments for stage {stage!r} must have contiguous ordinals {expected}"
            )
        providers = [assignment["provider"] for assignment in stage_assignments]
        if len(providers) != len(set(providers)):
            raise ResearchRecordError(
                f"assignments for stage {stage!r} contain a duplicate provider"
            )
        primary_kind = stage_assignments[0]["assignment_kind"]
        if primary_kind not in {"RECOMMENDED", "OVERRIDE"}:
            raise ResearchRecordError(
                f"stage {stage!r} ordinal 1 must be RECOMMENDED or OVERRIDE"
            )
        if any(
            assignment["assignment_kind"] != "FALLBACK"
            for assignment in stage_assignments[1:]
        ):
            raise ResearchRecordError(
                f"stage {stage!r} assignments after ordinal 1 must be FALLBACK"
            )

        if stage not in evaluations:
            raise ResearchRecordError(f"stage {stage!r} has no provider evaluations")
        by_provider = {
            evaluation["provider"]: evaluation for evaluation in evaluations[stage]
        }
        copied_fields = (
            "provider_status",
            "provider_status_reason",
            "fit",
            "relative_cost",
            "billing",
            "usage_authorization_required",
        )
        for index, assignment in enumerate(stage_assignments):
            evaluation = by_provider[assignment["provider"]]
            if any(assignment[field] != evaluation[field] for field in copied_fields):
                raise ResearchRecordError(
                    f"stage {stage!r} assignment {index + 1} contradicts its provider evaluation"
                )

        eligible = [
            evaluation["provider"]
            for evaluation in evaluations[stage]
            if evaluation["provider_status"] == "available"
            and evaluation["provider"] != "mock"
            and (not allowlist or evaluation["provider"] in allowlist)
            and (not plan["no_paid"] or evaluation["billing"] == "free")
        ]
        if primary_kind == "OVERRIDE":
            override = stage_assignments[0]["provider"]
            if eligible and override == eligible[0]:
                raise ResearchRecordError(
                    f"stage {stage!r} cannot label the ordinary recommendation as OVERRIDE"
                )
            expected_providers = [override, *(item for item in eligible if item != override)]
        else:
            expected_providers = eligible
        if providers != expected_providers:
            raise ResearchRecordError(
                f"stage {stage!r} assignments do not match the complete policy-eligible "
                "provider evaluation snapshot"
            )

    if list(assignments) != evaluation_stage_order:
        raise ResearchRecordError(
            "stage assignments and provider evaluations must cover the same ordered stages"
        )
    return dict(assignments)


def _validate_runs(
    record: Mapping[str, Any],
    assignments: Mapping[str, Sequence[Mapping[str, Any]]],
) -> dict[str, Mapping[str, Any]]:
    plan = record["plan"]
    generated_at = _timestamp(record["generated_at"], "generated_at")
    plan_created_at = _timestamp(plan["created_at"], "plan.created_at")
    if plan_created_at > generated_at:
        raise ResearchRecordError("plan.created_at must not be after generated_at")

    runs: dict[str, Mapping[str, Any]] = {}
    attempts: dict[str, list[int]] = defaultdict(list)
    for index, run in enumerate(record.get("runs", [])):
        where = f"runs[{index}]"
        run_id = run["run_id"]
        runs[run_id] = run
        if run["plan_id"] != plan["plan_id"]:
            raise ResearchRecordError(f"{where}.plan_id does not reference plan.plan_id")
        stage = run["stage"]
        if stage not in assignments:
            raise ResearchRecordError(f"{where}.stage does not exist in the plan")
        attempt = _integer(run["attempt"], f"{where}.attempt", minimum=1)
        attempts[stage].append(attempt)

        requested = run["requested_provider"]
        _canonical_provider_name(requested, f"{where}.requested_provider")
        stage_assignments = assignments[stage]
        assignment = next(
            (item for item in stage_assignments if item["provider"] == requested),
            None,
        )
        if assignment is None:
            raise ResearchRecordError(
                f"{where}.requested_provider does not match a stage assignment"
            )

        actual_name = run.get("provider")
        effective_assignment = assignment
        if actual_name is not None:
            _canonical_provider_name(actual_name, f"{where}.provider")
        substitution = run.get("provider_substitution_reason")
        if actual_name is not None and actual_name != requested:
            _nonblank(substitution, f"{where}.provider_substitution_reason")
            actual_assignment = next(
                (item for item in stage_assignments if item["provider"] == actual_name),
                None,
            )
            if actual_assignment is None:
                raise ResearchRecordError(
                    f"{where}.provider substitution is not a recorded stage fallback"
                )
            if (
                actual_assignment["assignment_kind"] != "FALLBACK"
                or actual_assignment["ordinal"] <= assignment["ordinal"]
            ):
                raise ResearchRecordError(
                    f"{where}.provider substitution must move to a lower-ranked fallback"
                )
            effective_assignment = actual_assignment
        elif substitution is not None:
            raise ResearchRecordError(
                f"{where}.provider_substitution_reason requires a different actual provider"
            )

        if (
            run["relative_cost"] != effective_assignment["relative_cost"]
            or run["billing"] != effective_assignment["billing"]
        ):
            raise ResearchRecordError(
                f"{where} cost/billing facts contradict its effective stage assignment"
            )
        expected_gate = run["billing"] != "free"
        if run["usage_authorization_required"] is not expected_gate:
            raise ResearchRecordError(
                f"{where}.usage_authorization_required contradicts billing class"
            )
        if plan["no_paid"] and expected_gate:
            raise ResearchRecordError(f"{where} violates plan.no_paid")
        _nonblank(run["provider_status_reason"], f"{where}.provider_status_reason")
        if (
            run["provider_status"] != effective_assignment["provider_status"]
            or run["provider_status_reason"]
            != effective_assignment["provider_status_reason"]
        ):
            raise ResearchRecordError(
                f"{where} provider status must match its effective stage assignment snapshot"
            )
        reasons = run["authorization_reasons"]
        if not reasons or any(not isinstance(reason, str) or not reason.strip() for reason in reasons):
            raise ResearchRecordError(
                f"{where}.authorization_reasons must contain non-empty strings"
            )

        query = _nonblank(run["rendered_query"], f"{where}.rendered_query")
        if run["query_sha256"] != sha256_text(query):
            raise ResearchRecordError(f"{where}.query_sha256 does not match rendered_query")
        created = _timestamp(run["created_at"], f"{where}.created_at")
        evaluated = _timestamp(run["policy_evaluated_at"], f"{where}.policy_evaluated_at")
        if not plan_created_at <= created <= evaluated <= generated_at:
            raise ResearchRecordError(
                f"{where} timestamps must satisfy plan.created_at <= created_at <= "
                "policy_evaluated_at <= generated_at"
            )
        started = (
            _timestamp(run["started_at"], f"{where}.started_at")
            if "started_at" in run
            else None
        )
        completed = (
            _timestamp(run["completed_at"], f"{where}.completed_at")
            if "completed_at" in run
            else None
        )
        if started is not None and (started < evaluated or started > generated_at):
            raise ResearchRecordError(f"{where}.started_at is outside the run timeline")
        if completed is not None and (
            completed > generated_at or (started is not None and completed < started)
        ):
            raise ResearchRecordError(f"{where}.completed_at is outside the run timeline")

        if run["mode"] == "DRY_RUN":
            forbidden = {
                "provider",
                "provider_task_id",
                "requested_model",
                "actual_model",
                "reported_cost",
                "cost_currency",
                "started_at",
                "completed_at",
                "error",
            }
            present = sorted(forbidden.intersection(run))
            if (
                run["status"] != "DRY_RUN"
                or run["provider_called"] is not False
                or run["live_authorized"] is not False
                or run["usage_authorized"] is not False
                or run["usage_authorization_method"] != "NOT_REQUESTED"
                or present
            ):
                detail = f"; forbidden fields: {present}" if present else ""
                raise ResearchRecordError(f"{where} is not a valid dry run{detail}")
        else:
            if run["status"] not in TERMINAL_LIVE_STATUSES:
                raise ResearchRecordError(f"{where}.status is invalid for LIVE mode")
            if (
                actual_name is None
                or run["provider_called"] is not True
                or run["live_authorized"] is not True
                or run["provider_status"] != "available"
                or started is None
                or completed is None
            ):
                raise ResearchRecordError(
                    f"{where} live terminal runs require an actual available provider, "
                    "provider_called/live_authorized, and start/completion times"
                )
            method = run["usage_authorization_method"]
            if expected_gate:
                if run["usage_authorized"] is not True or method not in {
                    "EXPLICIT_ACKNOWLEDGEMENT",
                    "COST_CEILING",
                }:
                    raise ResearchRecordError(
                        f"{where} non-free live use lacks usage authorization"
                    )
            elif run["usage_authorized"] is not False or method != "NOT_REQUIRED":
                raise ResearchRecordError(
                    f"{where} free live use must use NOT_REQUIRED without an acknowledgement"
                )
            if method == "COST_CEILING":
                ceiling = run.get("max_cost")
                if ceiling not in COST_VALUE or COST_VALUE[run["relative_cost"]] > COST_VALUE[ceiling]:
                    raise ResearchRecordError(f"{where}.max_cost does not admit provider cost")
            elif "max_cost" in run:
                raise ResearchRecordError(
                    f"{where}.max_cost is only valid with COST_CEILING authorization"
                )
            if run["status"] in {"FAILED", "UNUSABLE"}:
                _nonblank(run.get("error"), f"{where}.error")
            elif "error" in run:
                raise ResearchRecordError(f"{where}.error contradicts COMPLETED status")

        if "reported_cost" in run:
            _number(run["reported_cost"], f"{where}.reported_cost")
            _nonblank(run.get("cost_currency"), f"{where}.cost_currency")
        elif "cost_currency" in run:
            raise ResearchRecordError(f"{where}.cost_currency requires reported_cost")

    for stage, values in attempts.items():
        expected = list(range(1, len(values) + 1))
        if sorted(values) != expected or values != sorted(values):
            raise ResearchRecordError(
                f"runs for stage {stage!r} must have ordered contiguous attempts {expected}"
            )
        stage_runs = sorted(
            (run for run in runs.values() if run["stage"] == stage),
            key=lambda run: run["attempt"],
        )
        for previous, current in zip(stage_runs, stage_runs[1:]):
            previous_completed = previous.get("completed_at")
            if previous_completed is not None and _timestamp(
                current["created_at"],
                f"run {current['run_id']!r}.created_at",
            ) < _timestamp(
                previous_completed,
                f"run {previous['run_id']!r}.completed_at",
            ):
                raise ResearchRecordError(
                    f"run {current['run_id']!r} was created before the preceding "
                    f"attempt {previous['run_id']!r} completed"
                )
        completed_attempts = [
            run["attempt"] for run in stage_runs if run["status"] == "COMPLETED"
        ]
        if completed_attempts and (
            len(completed_attempts) != 1
            or completed_attempts[0] != stage_runs[-1]["attempt"]
        ):
            raise ResearchRecordError(
                f"stage {stage!r} has an attempt after its terminal COMPLETED run"
            )
        stage_assignments = assignments[stage]
        for run in stage_runs:
            effective_provider = run.get("provider") or run["requested_provider"]
            effective_assignment = next(
                item
                for item in stage_assignments
                if item["provider"] == effective_provider
            )
            preceding = [
                item
                for item in stage_assignments
                if item["ordinal"] < effective_assignment["ordinal"]
            ]
            for candidate in preceding:
                if not any(
                    prior["attempt"] < run["attempt"]
                    and prior.get("provider") == candidate["provider"]
                    and prior["status"] in {"FAILED", "UNUSABLE"}
                    for prior in stage_runs
                ):
                    raise ResearchRecordError(
                        f"run {run['run_id']!r} uses fallback "
                        f"{effective_provider!r} before higher-ranked provider "
                        f"{candidate['provider']!r} failed or was unusable"
                    )
    for run in runs.values():
        actual = run.get("provider")
        requested = run["requested_provider"]
        if actual is None or actual == requested:
            continue
        if not any(
            prior["stage"] == run["stage"]
            and prior["attempt"] < run["attempt"]
            and prior["requested_provider"] == requested
            and prior.get("provider") == requested
            and prior["status"] in {"FAILED", "UNUSABLE"}
            for prior in runs.values()
        ):
            raise ResearchRecordError(
                f"run {run['run_id']!r} provider substitution requires a prior "
                "failed/unusable attempt for the requested provider"
            )
    return runs


def _validate_evidence(
    record: Mapping[str, Any],
    runs: Mapping[str, Mapping[str, Any]],
    *,
    repository_root: Path | None,
    verify_artifacts: bool,
) -> tuple[
    dict[str, Mapping[str, Any]],
    dict[str, bytes],
    dict[str, Mapping[str, Any]],
    dict[str, Mapping[str, Any]],
]:
    artifacts: dict[str, Mapping[str, Any]] = {}
    artifact_contents: dict[str, bytes] = {}
    paths: set[str] = set()
    for index, artifact in enumerate(record.get("artifacts", [])):
        where = f"artifacts[{index}]"
        artifact_id = artifact["artifact_id"]
        artifacts[artifact_id] = artifact
        if "run_id" in artifact and artifact["run_id"] not in runs:
            raise ResearchRecordError(f"{where}.run_id does not resolve")
        path = artifact.get("path")
        embedded = artifact.get("content_base64")
        if (path is None) == (embedded is None):
            raise ResearchRecordError(
                f"{where} must contain exactly one of path or content_base64"
            )
        if path is not None:
            _relative_path(path, f"{where}.path")
            if path in paths:
                raise ResearchRecordError(f"{where}.path duplicates artifact path {path!r}")
            paths.add(path)
        elif artifact["role"] not in {"PROFILE", "TARGET_SNAPSHOT"} or "run_id" in artifact:
            raise ResearchRecordError(
                f"{where}.content_base64 is allowed only for bundle-level input snapshots"
            )
        _nonblank(artifact.get("media_type"), f"{where}.media_type")
        if artifact["role"] == "SOURCE_SNAPSHOT":
            external_id = _nonblank(artifact.get("external_id"), f"{where}.external_id")
            if STABLE_REFERENCE_PATTERN.fullmatch(external_id) is None:
                raise ResearchRecordError(
                    f"{where}.external_id must identify the independent source"
                )
        digest = _sha256(artifact["sha256"], f"{where}.sha256")
        size = _integer(artifact["size_bytes"], f"{where}.size_bytes")
        if artifact["role"] == "SOURCE_SNAPSHOT" and size == 0:
            raise ResearchRecordError(f"{where} SOURCE_SNAPSHOT must not be empty")
        if embedded is not None:
            try:
                content = base64.b64decode(
                    _nonblank(embedded, f"{where}.content_base64"), validate=True
                )
            except (ValueError, binascii.Error) as exc:
                raise ResearchRecordError(
                    f"{where}.content_base64 must be canonical base64"
                ) from exc
            if base64.b64encode(content).decode("ascii") != embedded:
                raise ResearchRecordError(
                    f"{where}.content_base64 must use canonical padded base64"
                )
            if sha256_bytes(content) != digest or len(content) != size:
                raise ResearchRecordError(
                    f"{where} embedded bytes do not match sha256 and size_bytes"
                )
            artifact_contents[artifact_id] = content
        elif verify_artifacts:
            if repository_root is None:
                raise ResearchRecordError("repository_root is required to verify artifacts")
            artifact_contents[artifact_id] = _check_file(
                repository_root,
                path,
                digest,
                where,
                expected_size=size,
            )

    citations: dict[str, Mapping[str, Any]] = {}
    generated_at = _timestamp(record["generated_at"], "generated_at")
    for index, citation in enumerate(record.get("citations", [])):
        where = f"citations[{index}]"
        citations[citation["citation_id"]] = citation
        if citation["run_id"] not in runs:
            raise ResearchRecordError(f"{where}.run_id does not resolve")
        _nonblank(citation["raw_reference"], f"{where}.raw_reference")
        normalized = citation.get("normalized_reference")
        if normalized is not None:
            normalized = _nonblank(normalized, f"{where}.normalized_reference")
            if STABLE_REFERENCE_PATTERN.fullmatch(normalized) is None:
                raise ResearchRecordError(
                    f"{where}.normalized_reference must be an HTTPS URL or normalized CURIE"
                )
        status = citation.get("validation_status")
        validation_fields = {
            "validation_artifact_id",
            "validated_by",
            "validated_at",
        }
        resolved_fields = {"normalized_reference", "title", "url", "retrieved_at"}
        if status is None:
            if (validation_fields | resolved_fields).intersection(citation):
                raise ResearchRecordError(
                    f"{where} resolved/validation fields require validation_status"
                )
        else:
            validation_id = citation.get("validation_artifact_id")
            if (
                validation_id not in artifacts
                or artifacts[validation_id]["role"] != "REFERENCE_VALIDATION"
            ):
                raise ResearchRecordError(
                    f"{where}.validation_artifact_id must resolve to a "
                    "REFERENCE_VALIDATION artifact"
                )
            if artifacts[validation_id].get("run_id") != citation["run_id"]:
                raise ResearchRecordError(
                    f"{where}.validation_artifact_id must belong to the same run"
                )
            if artifacts[validation_id]["size_bytes"] == 0:
                raise ResearchRecordError(
                    f"{where}.validation_artifact_id must preserve non-empty resolver output"
                )
            _nonblank(citation.get("validated_by"), f"{where}.validated_by")
            validated_at = _timestamp(citation.get("validated_at"), f"{where}.validated_at")
            if validated_at > generated_at:
                raise ResearchRecordError(f"{where}.validated_at is after generated_at")
            run_completed_at = _timestamp(
                runs[citation["run_id"]].get("completed_at"),
                f"runs[{citation['run_id']!r}].completed_at",
            )
            if validated_at < run_completed_at:
                raise ResearchRecordError(
                    f"{where}.validated_at is before its provider run completed"
                )
            if status == "VERIFIED" and normalized is None:
                raise ResearchRecordError(
                    f"{where}.normalized_reference is required for VERIFIED"
                )
            if status != "VERIFIED" and resolved_fields.intersection(citation):
                raise ResearchRecordError(
                    f"{where} resolved bibliographic metadata is permitted only for VERIFIED"
                )
        if "retrieved_at" in citation:
            retrieved = _timestamp(citation["retrieved_at"], f"{where}.retrieved_at")
            if retrieved > generated_at:
                raise ResearchRecordError(f"{where}.retrieved_at is after generated_at")
        if "title" in citation:
            _nonblank(citation["title"], f"{where}.title")
        if "url" in citation:
            _nonblank(citation["url"], f"{where}.url")

    evidence: dict[str, Mapping[str, Any]] = {}
    for index, assertion in enumerate(record.get("evidence", [])):
        where = f"evidence[{index}]"
        evidence_id = assertion["evidence_id"]
        evidence[evidence_id] = assertion
        run_id = assertion["run_id"]
        if run_id not in runs or runs[run_id]["status"] != "COMPLETED":
            raise ResearchRecordError(f"{where}.run_id must resolve to a COMPLETED run")
        source_id = assertion["source_artifact_id"]
        if source_id not in artifacts or artifacts[source_id]["role"] != "SOURCE_SNAPSHOT":
            raise ResearchRecordError(
                f"{where}.source_artifact_id must resolve to a SOURCE_SNAPSHOT artifact"
            )
        if artifacts[source_id].get("run_id") != run_id:
            raise ResearchRecordError(
                f"{where}.source_artifact_id must belong to the same run"
            )
        citation_id = assertion.get("citation_id")
        if citation_id is not None:
            if citation_id not in citations or citations[citation_id]["run_id"] != run_id:
                raise ResearchRecordError(
                    f"{where}.citation_id must resolve to a citation from the same run"
                )
            citation = citations[citation_id]
            if (
                citation.get("validation_status") != "VERIFIED"
                or citation.get("normalized_reference") is None
            ):
                raise ResearchRecordError(
                    f"{where}.citation_id must be independently VERIFIED"
                )
            if citation["normalized_reference"] != artifacts[source_id].get("external_id"):
                raise ResearchRecordError(
                    f"{where} citation and source snapshot identify different sources"
                )
        if assertion["relevance"] == "NOT_ASSESSED":
            raise ResearchRecordError(f"{where}.relevance contradicts an evidence assessment")
        if (
            assertion["support_level"] in EVIDENCE_BEARING_SUPPORT | {"NO_EVIDENCE"}
            and assertion["relevance"] != "ON_TOPIC"
        ):
            raise ResearchRecordError(
                f"{where} evidence-bearing support requires ON_TOPIC relevance"
            )
        _nonblank(assertion["rationale"], f"{where}.rationale")
        _nonblank(assertion["assessed_by"], f"{where}.assessed_by")
        assessed_at = _timestamp(assertion["assessed_at"], f"{where}.assessed_at")
        completed_at = _timestamp(runs[run_id]["completed_at"], f"run {run_id!r}.completed_at")
        if not completed_at <= assessed_at <= generated_at:
            raise ResearchRecordError(
                f"{where}.assessed_at must be between run completion and generated_at"
            )

        method = assertion["verification_method"]
        assessment_id = assertion.get("assessment_artifact_id")
        if assessment_id is not None:
            if (
                assessment_id not in artifacts
                or artifacts[assessment_id]["role"] != "EVIDENCE_ASSESSMENT"
            ):
                raise ResearchRecordError(
                    f"{where}.assessment_artifact_id must resolve to an "
                    "EVIDENCE_ASSESSMENT artifact"
                )
            if artifacts[assessment_id].get("run_id") != run_id:
                raise ResearchRecordError(
                    f"{where}.assessment_artifact_id must belong to the same run"
                )
            if artifacts[assessment_id]["size_bytes"] == 0:
                raise ResearchRecordError(
                    f"{where}.assessment_artifact_id must preserve non-empty assessment output"
                )
        if method == "EXACT_TEXT_MATCH":
            snippet = _nonblank(assertion.get("snippet"), f"{where}.snippet")
            if verify_artifacts:
                try:
                    source_text = artifact_contents[source_id].decode("utf-8")
                except UnicodeDecodeError as exc:
                    raise ResearchRecordError(
                        f"{where}.source_artifact_id is not a UTF-8 text artifact"
                    ) from exc
                if " ".join(snippet.split()) not in " ".join(source_text.split()):
                    raise ResearchRecordError(
                        f"{where}.snippet was not found in source_artifact_id {source_id!r}"
                    )
        else:
            if "snippet" in assertion:
                raise ResearchRecordError(
                    f"{where}.snippet is permitted only for EXACT_TEXT_MATCH"
                )
            _nonblank(assertion.get("locator"), f"{where}.locator")
            if assessment_id is None:
                raise ResearchRecordError(
                    f"{where}.assessment_artifact_id must resolve to a "
                    "EVIDENCE_ASSESSMENT artifact"
                )

    findings: dict[str, Mapping[str, Any]] = {}
    for index, finding in enumerate(record.get("findings", [])):
        where = f"findings[{index}]"
        findings[finding["finding_id"]] = finding
        _nonblank(finding["statement"], f"{where}.statement")
        _nonblank(finding["rationale"], f"{where}.rationale")
        evidence_ids = finding["evidence_ids"]
        if len(evidence_ids) != len(set(evidence_ids)):
            raise ResearchRecordError(f"{where}.evidence_ids contains duplicates")
        if any(item not in evidence for item in evidence_ids):
            raise ResearchRecordError(f"{where}.evidence_ids contains a dangling reference")
        if any(evidence[item]["finding_id"] != finding["finding_id"] for item in evidence_ids):
            raise ResearchRecordError(f"{where}.evidence_ids contains an assertion for another finding")
        polarities = {evidence[item]["support_level"] for item in evidence_ids}
        disposition = finding["disposition"]
        if polarities == {"SUPPORT"}:
            expected_disposition = "SUPPORT"
        elif polarities == {"REFUTE"}:
            expected_disposition = "REFUTE"
        elif polarities == {"WRONG_STATEMENT"}:
            expected_disposition = "WRONG_STATEMENT"
        elif polarities == {"NO_EVIDENCE"}:
            expected_disposition = "NO_EVIDENCE"
        else:
            expected_disposition = "PARTIAL"
        if disposition != expected_disposition:
            raise ResearchRecordError(f"{where}.disposition contradicts linked evidence")
    referenced = {
        evidence_id
        for finding in findings.values()
        for evidence_id in finding["evidence_ids"]
    }
    if referenced != set(evidence):
        raise ResearchRecordError("every ResearchEvidence assertion must belong to exactly one finding")
    return artifacts, artifact_contents, evidence, findings


def _validate_changes(
    record: Mapping[str, Any],
    artifacts: Mapping[str, Mapping[str, Any]],
    evidence: Mapping[str, Mapping[str, Any]],
    findings: Mapping[str, Mapping[str, Any]],
) -> None:
    for index, change in enumerate(record.get("proposed_changes", [])):
        where = f"proposed_changes[{index}]"
        _nonblank(change["summary"], f"{where}.summary")
        _nonblank(change["rationale"], f"{where}.rationale")
        if "field_path" in change:
            _nonblank(change["field_path"], f"{where}.field_path")
        _relative_path(change["target_path"], f"{where}.target_path")
        _relative_path(change["domain_schema_path"], f"{where}.domain_schema_path")
        schema_id = change["domain_schema_artifact_id"]
        if schema_id not in artifacts or artifacts[schema_id]["role"] != "DOMAIN_SCHEMA":
            raise ResearchRecordError(
                f"{where}.domain_schema_artifact_id must resolve to a DOMAIN_SCHEMA artifact"
            )
        if artifacts[schema_id]["size_bytes"] == 0:
            raise ResearchRecordError(
                f"{where}.domain_schema_artifact_id must preserve a non-empty schema"
            )
        if artifacts[schema_id]["path"] == change["domain_schema_path"]:
            raise ResearchRecordError(
                f"{where}.domain_schema_path must be distinct from its retained artifact"
            )
        pre_change_id = change.get("pre_change_artifact_id")
        if change["operation"] == "CREATE":
            if pre_change_id is not None:
                raise ResearchRecordError(
                    f"{where}.pre_change_artifact_id is forbidden for CREATE"
                )
        elif (
            pre_change_id not in artifacts
            or artifacts[pre_change_id]["role"] != "TARGET_SNAPSHOT"
        ):
            raise ResearchRecordError(
                f"{where}.pre_change_artifact_id must resolve to a TARGET_SNAPSHOT artifact"
            )
        elif artifacts[pre_change_id].get("path") == change["target_path"]:
            raise ResearchRecordError(
                f"{where}.target_path must be distinct from its retained snapshot artifact"
            )
        finding_ids = change["finding_ids"]
        if len(finding_ids) != len(set(finding_ids)):
            raise ResearchRecordError(f"{where}.finding_ids contains duplicates")
        if any(finding_id not in findings for finding_id in finding_ids):
            raise ResearchRecordError(f"{where}.finding_ids contains a dangling reference")
        patch_id = change["patch_artifact_id"]
        if patch_id not in artifacts or artifacts[patch_id]["role"] != "PATCH":
            raise ResearchRecordError(
                f"{where}.patch_artifact_id must resolve to a PATCH artifact"
            )
        if artifacts[patch_id]["size_bytes"] == 0:
            raise ResearchRecordError(
                f"{where}.patch_artifact_id must preserve a non-empty patch"
            )
        status = change["domain_validation_status"]
        validation_id = change.get("validation_artifact_id")
        if status == "NOT_RUN":
            forbidden = {"validation_artifact_id", "validation_command", "validated_at"}
            if forbidden.intersection(change):
                raise ResearchRecordError(
                    f"{where} validator details contradict NOT_RUN"
                )
            _nonblank(change.get("validation_message"), f"{where}.validation_message")
        else:
            if validation_id not in artifacts or artifacts[validation_id]["role"] != "DOMAIN_VALIDATION":
                raise ResearchRecordError(
                    f"{where}.validation_artifact_id must resolve to a "
                    "DOMAIN_VALIDATION artifact"
                )
            if artifacts[validation_id]["size_bytes"] == 0:
                raise ResearchRecordError(
                    f"{where}.validation_artifact_id must preserve non-empty validator output"
                )
            _nonblank(change.get("validation_message"), f"{where}.validation_message")
            _nonblank(change.get("validation_command"), f"{where}.validation_command")
            validated_at = _timestamp(change.get("validated_at"), f"{where}.validated_at")
            if validated_at > _timestamp(record["generated_at"], "generated_at"):
                raise ResearchRecordError(f"{where}.validated_at is after generated_at")
            assessed_at = max(
                _timestamp(evidence[evidence_id]["assessed_at"], "evidence.assessed_at")
                for finding_id in finding_ids
                for evidence_id in findings[finding_id]["evidence_ids"]
            )
            if validated_at < assessed_at:
                raise ResearchRecordError(
                    f"{where}.validated_at is before its supporting evidence assessment"
                )
        if all(findings[finding_id]["disposition"] == "NO_EVIDENCE" for finding_id in finding_ids):
            raise ResearchRecordError(
                f"{where} cannot be justified only by NO_EVIDENCE findings"
            )


def _validate_input_artifacts(
    record: Mapping[str, Any],
    artifacts: Mapping[str, Mapping[str, Any]],
    artifact_contents: Mapping[str, bytes],
) -> bytes:
    """Bind the plan's exact input bytes to typed, checksum-addressed artifacts."""

    plan = record["plan"]
    target = plan["question"]["target"]
    bindings = (
        (
            "plan.profile_artifact_id",
            plan["profile_artifact_id"],
            "PROFILE",
            plan["profile_sha256"],
        ),
        (
            "plan.question.target.target_artifact_id",
            target["target_artifact_id"],
            "TARGET_SNAPSHOT",
            target["target_sha256"],
        ),
    )
    if bindings[0][1] == bindings[1][1]:
        raise ResearchRecordError("profile and target input artifacts must be distinct")
    for where, artifact_id, role, digest in bindings:
        artifact = artifacts.get(artifact_id)
        if (
            artifact is None
            or artifact["role"] != role
            or "path" in artifact
            or "content_base64" not in artifact
            or artifact["sha256"] != digest
            or "run_id" in artifact
        ):
            raise ResearchRecordError(
                f"{where} must resolve to an embedded bundle-level {role} snapshot "
                "bound to the recorded input digest"
            )
        if artifact_id not in artifact_contents:
            raise ResearchRecordError(f"{where} embedded bytes were not decoded")
    return artifact_contents[plan["profile_artifact_id"]]


def _validate_lifecycle(
    record: Mapping[str, Any],
    runs: Mapping[str, Mapping[str, Any]],
    artifacts: Mapping[str, Mapping[str, Any]],
    evidence: Mapping[str, Mapping[str, Any]],
    findings: Mapping[str, Mapping[str, Any]],
) -> None:
    if not runs:
        raise ResearchRecordError("a research result must contain at least one run")
    status = record["status"]
    run_statuses = [run["status"] for run in runs.values()]
    planned_stages = {
        assignment["stage"] for assignment in record["plan"]["stage_assignments"]
    }
    stage_statuses: dict[str, set[str]] = defaultdict(set)
    stage_final_statuses: dict[str, str] = {}
    for run in runs.values():
        stage_statuses[run["stage"]].add(run["status"])
        stage_final_statuses[run["stage"]] = run["status"]
    run_ids_with_reports = {
        artifact.get("run_id")
        for artifact in artifacts.values()
        if artifact["role"] == "REPORT" and artifact["size_bytes"] > 0
    }
    for run_id, run in runs.items():
        if run["status"] == "COMPLETED" and run_id not in run_ids_with_reports:
            raise ResearchRecordError(f"completed run {run_id!r} has no REPORT artifact")
        if run["status"] == "UNUSABLE" and not any(
            artifact.get("run_id") == run_id
            and artifact["role"] in {"PROVIDER_RESPONSE", "REPORT"}
            for artifact in artifacts.values()
        ):
            raise ResearchRecordError(
                f"unusable run {run_id!r} must preserve its provider output"
            )

    assessment_status = record["assessment_status"]
    assessment_scope = record.get("assessment_scope")
    assessment_limitations = record.get("assessment_limitations", [])
    assessment_fields_present = bool(evidence or findings or record.get("proposed_changes"))
    if assessment_status == "NOT_ASSESSED":
        if assessment_fields_present:
            raise ResearchRecordError(
                "NOT_ASSESSED result must not claim evidence, findings, or proposed changes"
            )
        forbidden_artifacts = sorted(
            {
                artifact["role"]
                for artifact in artifacts.values()
                if artifact["role"] in RAW_FORBIDDEN_ARTIFACT_ROLES
            }
        )
        if forbidden_artifacts:
            raise ResearchRecordError(
                "NOT_ASSESSED result must not contain assessment-only artifacts: "
                + ", ".join(forbidden_artifacts)
            )
        if "assessment_scope" in record or "assessment_limitations" in record:
            raise ResearchRecordError(
                "NOT_ASSESSED result must not claim assessment scope or limitations"
            )
    else:
        _nonblank(assessment_scope, "assessment_scope")
        if not evidence or not findings:
            raise ResearchRecordError(
                "an assessed result must contain both evidence assertions and findings"
            )
        for index, limitation in enumerate(assessment_limitations):
            _nonblank(limitation, f"assessment_limitations[{index}]")
        if len(assessment_limitations) != len(set(assessment_limitations)):
            raise ResearchRecordError("assessment_limitations contains duplicates")
        if assessment_status == "PARTIALLY_ASSESSED" and not assessment_limitations:
            raise ResearchRecordError(
                "PARTIALLY_ASSESSED result must record at least one assessment limitation"
            )
        if assessment_status == "ASSESSED" and "assessment_limitations" in record:
            raise ResearchRecordError(
                "ASSESSED result must not record assessment limitations"
            )
    assessment_of = record.get("assessment_of_result_id")
    supersedes = record.get("supersedes_result_id")
    for prefix, value in (
        ("assessment_of", assessment_of),
        ("supersedes", supersedes),
    ):
        companion_fields = {f"{prefix}_path", f"{prefix}_sha256"}
        if value is not None:
            _nonblank(value, f"{prefix}_result_id")
            if RESULT_ID_PATTERN.fullmatch(value) is None:
                raise ResearchRecordError(
                    f"{prefix}_result_id must be a normalized result identifier"
                )
            if value == record["result_id"]:
                raise ResearchRecordError(
                    f"{prefix}_result_id must not reference this result itself"
                )
            if not companion_fields.issubset(record):
                raise ResearchRecordError(
                    f"{prefix}_result_id requires {prefix}_path and {prefix}_sha256"
                )
            _relative_path(record[f"{prefix}_path"], f"{prefix}_path")
            _sha256(record[f"{prefix}_sha256"], f"{prefix}_sha256")
        elif companion_fields.intersection(record):
            raise ResearchRecordError(
                f"{prefix}_path and {prefix}_sha256 require {prefix}_result_id"
            )
    if assessment_of is not None and assessment_status == "NOT_ASSESSED":
        raise ResearchRecordError("assessment_of_result_id requires an assessed result")
    if assessment_of is not None and assessment_of == supersedes:
        raise ResearchRecordError(
            "assessment_of_result_id and supersedes_result_id describe different relationships"
        )

    if status == "DRY_RUN":
        if any(run_status != "DRY_RUN" for run_status in run_statuses):
            raise ResearchRecordError("DRY_RUN result may contain only DRY_RUN runs")
        if set(stage_statuses) != planned_stages:
            raise ResearchRecordError("DRY_RUN result must cover every planned stage")
        if any(
            record.get(name)
            for name in ("citations", "evidence", "findings", "proposed_changes")
        ):
            raise ResearchRecordError("DRY_RUN result must not claim outputs or evidence")
        expected_inputs = {
            record["plan"]["profile_artifact_id"],
            record["plan"]["question"]["target"]["target_artifact_id"],
        }
        if set(artifacts) != expected_inputs:
            raise ResearchRecordError(
                "DRY_RUN result may retain only its PROFILE and TARGET_SNAPSHOT inputs"
            )
        if assessment_status != "NOT_ASSESSED":
            raise ResearchRecordError("DRY_RUN result must be NOT_ASSESSED")
    elif status == "COMPLETED":
        if any(run_status == "DRY_RUN" for run_status in run_statuses):
            raise ResearchRecordError("COMPLETED result may contain only live attempts")
        if set(stage_final_statuses) != planned_stages or any(
            stage_final_statuses[stage] != "COMPLETED" for stage in planned_stages
        ):
            raise ResearchRecordError(
                "COMPLETED result needs a final completed run for every stage"
            )
    elif status == "PARTIAL":
        if "DRY_RUN" in run_statuses:
            raise ResearchRecordError("PARTIAL result may contain only live attempts")
        final_statuses = set(stage_final_statuses.values())
        if "COMPLETED" not in final_statuses or not final_statuses.intersection(
            {"FAILED", "UNUSABLE"}
        ):
            raise ResearchRecordError(
                "PARTIAL result needs both a final completed and final failed/unusable stage"
            )
        if set(stage_final_statuses) != planned_stages:
            raise ResearchRecordError("PARTIAL result needs a live terminal outcome for every stage")
    elif status == "FAILED":
        if any(run_status not in {"FAILED", "DRY_RUN"} for run_status in run_statuses):
            raise ResearchRecordError("FAILED result has a contradictory run status")
        if "FAILED" not in run_statuses:
            raise ResearchRecordError("FAILED result needs an actual failed provider attempt")
        if assessment_status != "NOT_ASSESSED":
            raise ResearchRecordError("FAILED result must be NOT_ASSESSED")
    elif status == "UNUSABLE":
        if "UNUSABLE" not in set(stage_final_statuses.values()):
            raise ResearchRecordError("UNUSABLE result needs a final UNUSABLE stage")
        if "DRY_RUN" in run_statuses:
            raise ResearchRecordError("UNUSABLE result may contain only live attempts")
        if assessment_status != "NOT_ASSESSED":
            raise ResearchRecordError("UNUSABLE result must be NOT_ASSESSED")


def _validate_profile_binding(
    record: Mapping[str, Any],
    profile_bytes: bytes,
    *,
    profile_path: Path,
) -> None:
    """Bind every copied plan fact and dry-run query to exact profile bytes."""

    try:
        profile = load_profile_bytes(profile_bytes, path=profile_path)
        plan = record["plan"]
        focus = profile.focus(plan["focus"])
    except ProfileError as exc:
        raise ResearchRecordError(f"plan profile snapshot is invalid: {exc}") from exc

    expected = {
        "mech": profile.mech,
        "focus_label": focus.label,
        "evidence_policy": profile.evidence_policy,
        "source_priorities": list(focus.source_priorities),
    }
    for field, value in expected.items():
        if plan.get(field) != value:
            raise ResearchRecordError(
                f"plan.{field} does not match the checksum-bound research profile"
            )

    assignments: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for assignment in plan["stage_assignments"]:
        assignments[assignment["stage"]].append(assignment)
    evaluations: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for evaluation in plan["provider_evaluations"]:
        evaluations[evaluation["stage"]].append(evaluation)
    if list(assignments) != list(focus.stages):
        raise ResearchRecordError(
            "plan stages do not match the ordered stages in the checksum-bound profile"
        )
    for stage_name, stage in focus.stages.items():
        stage_assignments = assignments[stage_name]
        if any(item["objective"] != stage.objective for item in stage_assignments):
            raise ResearchRecordError(
                f"plan stage {stage_name!r} objective does not match the profile"
            )
        ranked = rank_stage(focus, stage_name, environ={})
        expected_order = [row.provider for row in ranked]
        actual_order = [item["provider"] for item in evaluations[stage_name]]
        if actual_order != expected_order:
            raise ResearchRecordError(
                f"plan stage {stage_name!r} provider evaluation order contradicts "
                "the triage contract"
            )
        expected_fit = {row.provider: row.fit for row in ranked}
        if any(
            item["fit"] != expected_fit[item["provider"]]
            for item in evaluations[stage_name]
        ):
            raise ResearchRecordError(
                f"plan stage {stage_name!r} provider evaluation fit contradicts "
                "the triage contract"
            )

    question = plan["question"]
    target = question["target"]
    for run in record.get("runs", []):
        expected_query = render_stage_query(
            profile,
            focus_name=focus.name,
            stage_name=run["stage"],
            question=question["text"],
            target_id=target["target_id"],
            target_label=target["target_label"],
            target_type=target["target_type"],
        )
        if run["rendered_query"] != expected_query:
            raise ResearchRecordError(
                f"rendered query for stage {run['stage']!r} does not match the profile"
            )


def _validate_lineage(record: Mapping[str, Any], repository_root: Path) -> None:
    """Resolve checksum-bound prior records without treating IDs as assertions."""

    generated_at = _timestamp(record["generated_at"], "generated_at")
    for prefix in ("assessment_of", "supersedes"):
        result_id = record.get(f"{prefix}_result_id")
        if result_id is None:
            continue
        content = _check_file(
            repository_root,
            record[f"{prefix}_path"],
            record[f"{prefix}_sha256"],
            prefix,
        )
        try:
            prior = yaml.load(content, Loader=_StrictResultLoader)
        except yaml.YAMLError as exc:
            raise ResearchRecordError(f"{prefix} record is not strict YAML: {exc}") from exc
        if not isinstance(prior, dict):
            raise ResearchRecordError(f"{prefix} record must be a YAML mapping")
        validate_result(prior)
        if prior["result_id"] != result_id:
            raise ResearchRecordError(
                f"{prefix}_result_id does not match the checksum-bound prior record"
            )
        if _timestamp(prior["generated_at"], f"{prefix}.generated_at") >= generated_at:
            raise ResearchRecordError(f"{prefix} record must predate this result")
        if record["result_id"] in {
            prior.get("assessment_of_result_id"),
            prior.get("supersedes_result_id"),
        }:
            raise ResearchRecordError(f"{prefix} record creates a direct lineage cycle")
        if prefix == "assessment_of" and (
            prior["assessment_status"] != "NOT_ASSESSED"
            or prior["status"] not in {"COMPLETED", "PARTIAL"}
        ):
            raise ResearchRecordError(
                "assessment_of must resolve to a raw terminal result with captured output"
            )
        if prefix == "assessment_of":
            if record["status"] != prior["status"] or record["plan"] != prior["plan"]:
                raise ResearchRecordError(
                    "assessment_of result must preserve the raw lifecycle status and plan"
                )
            if record.get("runs", []) != prior.get("runs", []):
                raise ResearchRecordError(
                    "assessment_of result must preserve every raw provider run"
                )
            current_citations = {
                citation["citation_id"]: citation
                for citation in record.get("citations", [])
            }
            prior_citations = {
                citation["citation_id"]: citation
                for citation in prior.get("citations", [])
            }
            if set(current_citations) != set(prior_citations):
                raise ResearchRecordError(
                    "assessment_of result must not add or remove provider citations"
                )
            for prior_citation in prior_citations.values():
                current_citation = current_citations.get(prior_citation["citation_id"])
                if current_citation is None or any(
                    current_citation.get(field) != value
                    for field, value in prior_citation.items()
                ):
                    raise ResearchRecordError(
                        "assessment_of result must preserve every raw citation field"
                    )
            current_artifacts = {
                artifact["artifact_id"]: artifact
                for artifact in record.get("artifacts", [])
            }
            prior_artifacts = {
                artifact["artifact_id"]: artifact
                for artifact in prior.get("artifacts", [])
            }
            for prior_artifact in prior_artifacts.values():
                if current_artifacts.get(prior_artifact["artifact_id"]) != prior_artifact:
                    raise ResearchRecordError(
                        "assessment_of result must preserve every raw artifact exactly"
                    )
            for artifact_id, artifact in current_artifacts.items():
                if (
                    artifact_id not in prior_artifacts
                    and artifact["role"] not in ASSESSMENT_ADDITION_ARTIFACT_ROLES
                ):
                    raise ResearchRecordError(
                        "assessment_of result may add only assessment or "
                        "proposed-change artifacts; "
                        f"artifact {artifact_id!r} has role {artifact['role']!r}"
                    )


def validate_result(
    record: Mapping[str, Any],
    *,
    repository_root: Path | None = None,
    verify_artifacts: bool = False,
    verify_snapshots: bool = False,
) -> None:
    """Validate one research result without provider or network access.

    External artifact checks are opt-in for in-memory callers and enabled by
    the CLI. Embedded profile/target integrity and profile/query replay are
    unconditional. ``verify_snapshots`` separately compares mutable current
    source files with the historical input and proposed-change snapshots.
    """

    if not isinstance(record, Mapping):
        raise ResearchRecordError("research result must be a mapping")
    try:
        with _pure_linkml_loader():
            report = _linkml_validator().validate(
                dict(record), target_class="ResearchResult"
            )
    except Exception as exc:
        raise ResearchRecordError(f"LinkML validation could not run: {exc}") from exc
    if report.results:
        messages = "; ".join(result.message for result in report.results[:8])
        suffix = f"; plus {len(report.results) - 8} more" if len(report.results) > 8 else ""
        raise ResearchRecordError(f"LinkML validation failed: {messages}{suffix}")

    if record["research_version"] != RESEARCH_VERSION:
        raise ResearchRecordError(
            f"unsupported research_version {record['research_version']!r}; "
            f"expected {RESEARCH_VERSION}"
        )
    if record["status"] not in SUPPORTED_RESULT_STATUSES:
        raise ResearchRecordError(f"unsupported result status {record['status']!r}")
    _unique_ids(record)
    assignments = _validate_plan(record)
    runs = _validate_runs(record, assignments)
    artifacts, artifact_contents, evidence, findings = _validate_evidence(
        record,
        runs,
        repository_root=repository_root,
        verify_artifacts=verify_artifacts,
    )
    _validate_changes(record, artifacts, evidence, findings)
    profile_bytes = _validate_input_artifacts(record, artifacts, artifact_contents)
    _validate_profile_binding(
        record,
        profile_bytes,
        profile_path=Path(record["plan"]["profile_path"]),
    )
    _validate_lifecycle(record, runs, artifacts, evidence, findings)

    if (verify_artifacts or verify_snapshots) and any(
        record.get(field) is not None
        for field in ("assessment_of_result_id", "supersedes_result_id")
    ):
        if repository_root is None:
            raise ResearchRecordError("repository_root is required to verify result lineage")
        _validate_lineage(record, repository_root)

    if verify_snapshots:
        if repository_root is None:
            raise ResearchRecordError("repository_root is required to verify snapshots")
        plan = record["plan"]
        _check_file(
            repository_root,
            plan["profile_path"],
            plan["profile_sha256"],
            "plan.profile",
        )
        target = plan["question"]["target"]
        _check_file(
            repository_root,
            target["target_path"],
            target["target_sha256"],
            "plan.question.target",
        )
        for index, change in enumerate(record.get("proposed_changes", [])):
            where = f"proposed_changes[{index}]"
            schema_artifact = artifacts[change["domain_schema_artifact_id"]]
            _check_file(
                repository_root,
                change["domain_schema_path"],
                schema_artifact["sha256"],
                f"{where}.domain_schema_snapshot",
                expected_size=schema_artifact["size_bytes"],
            )
            if change["operation"] == "CREATE":
                if _repository_path_exists(
                    repository_root,
                    change["target_path"],
                    f"{where}.target_path",
                ):
                    raise ResearchRecordError(
                        f"{where}.target_path already exists but operation is CREATE"
                    )
            else:
                target_artifact = artifacts[change["pre_change_artifact_id"]]
                _check_file(
                    repository_root,
                    change["target_path"],
                    target_artifact["sha256"],
                    f"{where}.pre_change_snapshot",
                    expected_size=target_artifact["size_bytes"],
                )


def load_result(
    path: Path,
    *,
    repository_root: Path | None = None,
    verify_artifacts: bool = False,
    verify_snapshots: bool = False,
) -> dict[str, Any]:
    """Load strict YAML and validate one research result."""

    result_path = Path(path)
    try:
        text = result_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ResearchRecordError(f"cannot read research result {result_path}: {exc}") from exc
    try:
        data = yaml.load(text, Loader=_StrictResultLoader)
    except yaml.YAMLError as exc:
        raise ResearchRecordError(
            f"research result {result_path} is not strict YAML: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise ResearchRecordError("research result must be a YAML mapping")
    validate_result(
        data,
        repository_root=repository_root,
        verify_artifacts=verify_artifacts,
        verify_snapshots=verify_snapshots,
    )
    return data


def _utc_text(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ResearchRecordError("record timestamp must include a timezone")
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _path_within(repository_root: Path, source: Path, where: str) -> tuple[str, bytes]:
    root = _root_directory(repository_root)
    candidate = Path(source)
    try:
        if candidate.is_absolute():
            try:
                relative = candidate.relative_to(root)
            except ValueError:
                # macOS exposes /var as a symlink to /private/var. Normalize an
                # absolute spelling before the containment decision, then read
                # the canonical repository-relative path without following any
                # repository-internal symlink.
                relative = candidate.resolve(strict=False).relative_to(root)
        else:
            relative = candidate
    except (OSError, RuntimeError, ValueError) as exc:
        raise ResearchRecordError(f"{where} must be a file inside repository root {root}") from exc
    path = _relative_path(relative.as_posix(), where).as_posix()
    return path, _read_repository_file(root, path, where)


def render_stage_query(
    profile: ResearchProfile,
    *,
    focus_name: str,
    stage_name: str,
    question: str,
    target_id: str,
    target_label: str,
    target_type: str,
) -> str:
    """Render the provider-neutral portion of a Mech-focused stage query."""

    focus = profile.focus(focus_name)
    stage = focus.stages[stage_name]
    priorities = "\n".join(f"- {item}" for item in focus.source_priorities)
    return (
        f"Research question: {question.strip()}\n\n"
        f"Mech: {profile.mech}\n"
        f"Target: {target_label.strip()} ({target_id.strip()})\n"
        f"Target type: {target_type.strip()}\n"
        f"Focus: {focus.label} [{focus.name}]\n"
        f"Focus objective: {focus.objective}\n"
        f"Stage: {stage.name}\n"
        f"Stage objective: {stage.objective}\n\n"
        f"Evidence policy: {profile.evidence_policy}\n\n"
        "Preferred source classes:\n"
        f"{priorities or '- No additional source priority declared.'}\n\n"
        "Return source-grounded leads. Preserve exact identifiers, conditions, "
        "and uncertainty. Every proposed finding must cite an independently "
        "resolvable source and either an exact snippet or a precise non-text "
        "locator; do not apply repository changes."
    )


def build_dry_run_result(
    *,
    repository_root: Path,
    profile_path: Path,
    target_path: Path,
    target_id: str,
    target_label: str,
    target_type: str,
    question: str,
    focus_name: str | None = None,
    question_id: str | None = None,
    allow: Sequence[str] | None = None,
    no_paid: bool = False,
    availability: AvailabilityEvidence | None = None,
    environ: Mapping[str, str] | None = None,
    probe: LocalProbe | None = None,
    now: datetime | None = None,
    short_id: str | None = None,
) -> dict[str, Any]:
    """Build a complete dry-run plan/result skeleton for one Mech target.

    A provider must be supported by current injected/cached functional evidence
    before it is recorded as RECOMMENDED.  ``authorize(..., apply=False)`` is
    still evaluated for every stage; it cannot call a provider and cannot be
    used later as execution authority.
    """

    root = _root_directory(repository_root)
    profile_relative, profile_bytes = _path_within(root, profile_path, "profile_path")
    target_relative, target_bytes = _path_within(root, target_path, "target_path")
    profile = load_profile_bytes(profile_bytes, path=root / profile_relative)
    if profile.source_sha256 != sha256_bytes(profile_bytes):
        raise ResearchRecordError("profile changed while the dry-run plan was being built")
    focus = profile.focus(focus_name)

    instant = now or datetime.now(timezone.utc)
    timestamp = _utc_text(instant)
    file_timestamp = instant.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    token = short_id or secrets.token_hex(6)
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", token):
        raise ResearchRecordError("short_id must contain only letters, digits, dot, dash, underscore")
    result_id = f"research-{file_timestamp}-{token}"
    plan_id = f"plan-{file_timestamp}-{token}"
    resolved_question_id = question_id or f"question-{file_timestamp}-{token}"

    evaluations: list[dict[str, Any]] = []
    assignments: list[dict[str, Any]] = []
    runs: list[dict[str, Any]] = []
    for stage_index, stage_name in enumerate(focus.stages, start=1):
        plan = plan_stage(
            profile,
            stage_name,
            focus=focus.name,
            allow=allow,
            no_paid=no_paid,
            environ=environ,
            probe=probe,
            availability=availability,
        )
        selected = plan.recommended
        if selected is None:
            raise ResearchRecordError(
                f"no provider is available for {profile.mech} "
                f"{focus.name}/{stage_name}; dry-run scaffolding made no provider call"
            )
        decision = authorize(plan, apply=False)
        for ordinal, candidate in enumerate(plan.ranking, start=1):
            evaluations.append(
                {
                    "stage": stage_name,
                    "ordinal": ordinal,
                    "provider": candidate.provider,
                    "provider_status": candidate.status,
                    "provider_status_reason": candidate.status_reason,
                    "fit": candidate.fit,
                    "relative_cost": candidate.cost,
                    "billing": candidate.billing,
                    "usage_authorization_required": candidate.usage_authorization_required,
                }
            )
        for ordinal, candidate in enumerate(plan.allowed, start=1):
            assignments.append(
                {
                    "stage": stage_name,
                    "ordinal": ordinal,
                    "objective": focus.stages[stage_name].objective,
                    "provider": candidate.provider,
                    "provider_status": candidate.status,
                    "provider_status_reason": candidate.status_reason,
                    "fit": candidate.fit,
                    "relative_cost": candidate.cost,
                    "billing": candidate.billing,
                    "usage_authorization_required": candidate.usage_authorization_required,
                    "assignment_kind": "RECOMMENDED" if ordinal == 1 else "FALLBACK",
                }
            )
        query = render_stage_query(
            profile,
            focus_name=focus.name,
            stage_name=stage_name,
            question=question,
            target_id=target_id,
            target_label=target_label,
            target_type=target_type,
        )
        runs.append(
            {
                "run_id": f"run-{stage_index}-{file_timestamp}-{token}",
                "plan_id": plan_id,
                "stage": stage_name,
                "attempt": 1,
                "requested_provider": decision.provider,
                "provider_status": selected.status,
                "provider_status_reason": selected.status_reason,
                "mode": "DRY_RUN",
                "status": "DRY_RUN",
                "provider_called": False,
                "live_authorized": False,
                "relative_cost": decision.cost,
                "billing": decision.billing,
                "usage_authorization_required": decision.usage_authorization_required,
                "usage_authorized": False,
                "usage_authorization_method": "NOT_REQUESTED",
                "rendered_query": query,
                "query_sha256": sha256_text(query),
                "created_at": timestamp,
                "policy_evaluated_at": timestamp,
                "authorization_reasons": list(decision.reasons),
            }
        )

    result: dict[str, Any] = {
        "research_version": RESEARCH_VERSION,
        "result_id": result_id,
        "generated_at": timestamp,
        "status": "DRY_RUN",
        "assessment_status": "NOT_ASSESSED",
        "plan": {
            "plan_id": plan_id,
            "created_at": timestamp,
            "authority": "audit_only",
            "mech": profile.mech,
            "focus": focus.name,
            "focus_label": focus.label,
            "evidence_policy": profile.evidence_policy,
            "source_priorities": list(focus.source_priorities),
            "profile_path": profile_relative,
            "profile_sha256": profile.source_sha256,
            "profile_artifact_id": f"profile-{token}",
            "provider_catalogue_version": PROVIDER_CATALOGUE_VERSION,
            "provider_catalogue_sha256": PROVIDER_CATALOGUE_SHA256,
            "triage_contract_version": TRIAGE_CONTRACT_VERSION,
            "triage_contract_sha256": TRIAGE_CONTRACT_SHA256,
            "no_paid": no_paid,
            "question": {
                "question_id": resolved_question_id,
                "text": _nonblank(question, "question"),
                "target": {
                    "target_id": _nonblank(target_id, "target_id"),
                    "target_label": _nonblank(target_label, "target_label"),
                    "target_type": _nonblank(target_type, "target_type"),
                    "target_path": target_relative,
                    "target_sha256": sha256_bytes(target_bytes),
                    "target_artifact_id": f"target-{token}",
                },
            },
            "provider_evaluations": evaluations,
            "stage_assignments": assignments,
        },
        "runs": runs,
        "artifacts": [
            {
                "artifact_id": f"profile-{token}",
                "role": "PROFILE",
                "content_base64": base64.b64encode(profile_bytes).decode("ascii"),
                "media_type": "application/yaml",
                "sha256": profile.source_sha256,
                "size_bytes": len(profile_bytes),
            },
            {
                "artifact_id": f"target-{token}",
                "role": "TARGET_SNAPSHOT",
                "content_base64": base64.b64encode(target_bytes).decode("ascii"),
                "media_type": (
                    "application/yaml"
                    if PurePosixPath(target_relative).suffix.casefold() in {".yaml", ".yml"}
                    else "application/octet-stream"
                ),
                "sha256": sha256_bytes(target_bytes),
                "size_bytes": len(target_bytes),
            },
        ],
    }
    if allow is not None:
        result["plan"]["provider_allowlist"] = sorted(
            {canonical_provider(provider) for provider in allow}
        )
    validate_result(
        result,
        repository_root=root,
        verify_snapshots=True,
    )
    return result


class _ReadableDumper(yaml.SafeDumper):
    """YAML dumper that preserves multiline questions and rendered queries."""

    def ignore_aliases(self, data: Any) -> bool:
        return True


def _represent_string(dumper: yaml.SafeDumper, value: str) -> yaml.ScalarNode:
    style = "|" if "\n" in value else None
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style=style)


_ReadableDumper.add_representer(str, _represent_string)


def result_yaml(record: Mapping[str, Any]) -> str:
    """Serialize a validated-compatible record deterministically."""

    return yaml.dump(
        dict(record),
        Dumper=_ReadableDumper,
        allow_unicode=True,
        sort_keys=False,
        width=100,
    )


def _destination_relative(repository_root: Path, path: Path) -> PurePosixPath:
    root = _root_directory(repository_root)
    destination = Path(path)
    if destination.is_absolute():
        try:
            try:
                relative = destination.relative_to(root)
            except ValueError:
                relative = destination.resolve(strict=False).relative_to(root)
        except (OSError, RuntimeError, ValueError) as exc:
            raise ResearchRecordError(
                f"research result path must stay inside repository root {root}"
            ) from exc
    else:
        relative = destination
    return _relative_path(relative.as_posix(), "research result path")


def _open_repository_parent(
    repository_root: Path,
    parts: Sequence[str],
) -> tuple[int, list[int]]:
    """Open/create a destination parent through descriptor-relative operations."""

    nofollow = getattr(os, "O_NOFOLLOW", 0)
    directory = getattr(os, "O_DIRECTORY", 0)
    cloexec = getattr(os, "O_CLOEXEC", 0)
    required = {os.open, os.mkdir, os.link, os.unlink}
    if not nofollow or not required.issubset(getattr(os, "supports_dir_fd", set())):
        raise ResearchRecordError(
            "append-only result publication requires POSIX dir_fd and O_NOFOLLOW support"
        )
    opened: list[int] = []
    try:
        current = _open_root_descriptor(
            repository_root, os.O_RDONLY | directory | cloexec
        )
        opened.append(current)
        for part in parts:
            try:
                child = os.open(
                    part,
                    os.O_RDONLY | directory | nofollow | cloexec,
                    dir_fd=current,
                )
            except FileNotFoundError:
                try:
                    os.mkdir(part, 0o755, dir_fd=current)
                except FileExistsError:
                    pass
                child = os.open(
                    part,
                    os.O_RDONLY | directory | nofollow | cloexec,
                    dir_fd=current,
                )
            opened.append(child)
            current = child
        return current, opened
    except Exception:
        for descriptor in reversed(opened):
            os.close(descriptor)
        raise


def _publish_new_bytes(
    repository_root: Path,
    relative: PurePosixPath,
    content: bytes,
    *,
    kind: str,
) -> Path:
    """Publish bytes once with descriptor-relative, no-follow operations."""

    destination = repository_root.joinpath(*relative.parts)
    parent_descriptor: int | None = None
    opened: list[int] = []
    temporary = f".{relative.name}.tmp-{secrets.token_hex(6)}"
    temporary_created = False
    try:
        parent_descriptor, opened = _open_repository_parent(
            repository_root, relative.parts[:-1]
        )
        descriptor = os.open(
            temporary,
            os.O_CREAT
            | os.O_EXCL
            | os.O_WRONLY
            | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
            0o644,
            dir_fd=parent_descriptor,
        )
        temporary_created = True
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(
                temporary,
                relative.name,
                src_dir_fd=parent_descriptor,
                dst_dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except FileExistsError:
            raise FileExistsError(
                f"{destination} already exists; {kind} are append-only"
            ) from None
        os.fsync(parent_descriptor)
    except (FileExistsError, ResearchRecordError):
        raise
    except OSError as exc:
        raise ResearchRecordError(f"cannot publish {kind} {destination}: {exc}") from exc
    finally:
        if parent_descriptor is not None and temporary_created:
            try:
                os.unlink(temporary, dir_fd=parent_descriptor)
            except FileNotFoundError:
                pass
        for descriptor in reversed(opened):
            os.close(descriptor)
    return destination


def write_result(
    path: Path,
    record: Mapping[str, Any],
    *,
    repository_root: Path,
    verify_artifacts: bool = True,
    verify_snapshots: bool = True,
) -> Path:
    """Validate one serialized snapshot and publish it once without following symlinks."""

    content = result_yaml(record).encode("utf-8")
    try:
        snapshot = yaml.load(content, Loader=_StrictResultLoader)
    except yaml.YAMLError as exc:  # pragma: no cover - our own dumper should be strict
        raise ResearchRecordError(f"serialized research result is not strict YAML: {exc}") from exc
    if not isinstance(snapshot, dict):
        raise ResearchRecordError("serialized research result must be a mapping")
    validate_result(
        snapshot,
        repository_root=repository_root,
        verify_artifacts=verify_artifacts,
        verify_snapshots=verify_snapshots,
    )
    root = _root_directory(repository_root)
    relative = _destination_relative(root, path)
    return _publish_new_bytes(root, relative, content, kind="research results")


def new_result_path(
    repository_root: Path,
    *,
    target_id: str,
    result_id: str,
) -> Path:
    """Choose a collision-resistant, append-only path beneath ``research/runs``."""

    target_token = re.sub(r"[^A-Za-z0-9._-]+", "-", target_id.strip()).strip("-.")
    if not target_token:
        target_token = "target"
    if not isinstance(result_id, str) or RESULT_ID_PATTERN.fullmatch(result_id) is None:
        raise ResearchRecordError(
            "result_id must contain only letters, digits, dot, dash, and underscore"
        )
    relative = PurePosixPath("research", "runs", target_token, f"{result_id}.yaml")
    _relative_path(relative.as_posix(), "new result path")
    return _root_directory(repository_root).joinpath(*relative.parts)
