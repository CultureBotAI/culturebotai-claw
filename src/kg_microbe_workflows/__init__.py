"""Pinned, LinkML-validated Mech cycles and immutable goal evidence.

This package validates records and artifact bytes. It never executes goals, Git,
GitHub calls or embedded commands; remote closure remains the supervisor's gate.
"""
from __future__ import annotations

import copy
import hashlib
import importlib
import json
import os
import re
import stat
import tempfile
import threading
from contextlib import contextmanager
from datetime import datetime
from functools import lru_cache
from pathlib import Path, PurePosixPath
from typing import Any

import yaml
from jsonschema.validators import validator_for
from linkml.generators.jsonschemagen import JsonSchemaGenerator
from linkml_runtime.linkml_model.meta import SchemaDefinition

SCHEMA_PATH = Path(__file__).parent / "schema/workflow.yaml"
PARENT_PATH = Path(__file__).parent / "templates/mech-cycle.yaml"
VERSION = "1.0.0"
STAGE_KEYS = (
    "add_records", "causal_graphs", "protein_examples", "record_review",
    "resolve_review_findings", "infrastructure",
)
CLOSURE_STEPS = (
    "commit_and_push_pr", "independent_adversarial_review", "make_issues", "address_issues",
    "independent_rereview", "verify_checks", "merge", "delete_branch",
)
REQUIRED_OUTPUTS = {4: {"review_report", "review_findings"}, 5: {"issue_map", "validation"},
                    6: {"infra_snapshot", "implementation_plan", "validation"}}
OPEN = {"open", "deferred"}


class WorkflowError(ValueError):
    """The workflow or its claimed evidence does not meet the shared contract."""


class _LinkMLLoader(yaml.SafeLoader):
    """Isolate LinkML from process-global YAML path resolver contamination."""

    yaml_path_resolvers: dict[Any, Any] = {}

    def construct_mapping(self, node, deep=False):
        self.flatten_mapping(node)
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if key in result:
                raise WorkflowError(f"duplicate LinkML YAML key: {key!r}")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


_linkml_yaml_loader = importlib.import_module("linkml_runtime.loaders.yaml_loader")
# Share the lock with independently loaded review/research payloads when present.
_LINKML_LOADER_LOCK = vars(_linkml_yaml_loader).setdefault(
    "_claw_linkml_loader_lock", threading.RLock()
)


@contextmanager
def _pure_linkml_loader():
    with _LINKML_LOADER_LOCK:
        original = getattr(_linkml_yaml_loader, "DupCheckYamlLoader")
        setattr(_linkml_yaml_loader, "DupCheckYamlLoader", _LinkMLLoader)
        try:
            yield
        finally:
            setattr(_linkml_yaml_loader, "DupCheckYamlLoader", original)


class _Loader(yaml.SafeLoader):
    yaml_implicit_resolvers = {
        key: [item for item in values if item[0] != "tag:yaml.org,2002:timestamp"]
        for key, values in yaml.SafeLoader.yaml_implicit_resolvers.items()
    }
    yaml_path_resolvers: dict[Any, Any] = {}

    def compose_node(self, parent, index):
        event = self.peek_event()
        if (self.check_event(yaml.AliasEvent) or getattr(event, "anchor", None)
                or getattr(event, "tag", None)):
            raise WorkflowError("YAML aliases, anchors, and explicit tags are forbidden")
        return super().compose_node(parent, index)

    def construct_mapping(self, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            key = self.construct_object(key_node, deep=deep)
            if not isinstance(key, str) or key in result:
                raise WorkflowError(f"duplicate or non-string YAML key: {key!r}")
            result[key] = self.construct_object(value_node, deep=deep)
        return result


def load_document(raw: str | bytes) -> dict:
    try:
        data = yaml.load(raw, Loader=_Loader)
        if not isinstance(data, dict):
            raise WorkflowError("document must be a mapping")
        json.dumps(data, allow_nan=False)
        return data
    except (yaml.YAMLError, UnicodeError, TypeError, ValueError, RecursionError) as exc:
        raise WorkflowError(f"invalid workflow YAML: {exc}") from exc


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def relative_path(value: str) -> PurePosixPath:
    if (not isinstance(value, str) or not value or value.startswith("/")
            or "\\" in value or any(ord(c) < 32 for c in value)
            or any(c in value for c in ":?#%")
            or any(part in {"", ".", ".."} for part in value.split("/"))):
        raise WorkflowError(f"unsafe repository-relative path: {value!r}")
    return PurePosixPath(value)


def _read_regular(path: Path, boundary: Path | None = None) -> bytes:
    path = Path(path)
    if boundary is not None and not path.resolve().is_relative_to(boundary.resolve()):
        raise WorkflowError(f"artifact escapes repository: {path}")
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(fd, "rb") as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise WorkflowError(f"not a regular artifact: {path}")
            return stream.read()
    except OSError as exc:
        raise WorkflowError(f"cannot read artifact {path}: {exc}") from exc


@lru_cache(maxsize=24)
def _validator(schema_text: str, class_name: str):
    schema = load_document(schema_text)
    if schema.get("imports"):
        raise WorkflowError("workflow schemas must be self-contained; imports are forbidden")
    if class_name not in schema.get("classes", {}):
        raise WorkflowError(f"schema has no class {class_name}")
    try:
        with _pure_linkml_loader():
            generated = json.loads(JsonSchemaGenerator(
                SchemaDefinition(**schema), topClass=class_name, not_closed=False,
                include_null=False,
            ).serialize())
        cls = validator_for(generated)
        cls.check_schema(generated)
        return cls(generated)
    except Exception as exc:
        raise WorkflowError(f"invalid LinkML schema: {exc}") from exc


def _shape(data: dict, class_name: str, schema_path: Path = SCHEMA_PATH) -> None:
    # Always validate the canonical shape even if a caller supplies a pinned copy.
    texts = {_read_regular(SCHEMA_PATH).decode(), _read_regular(schema_path).decode()}
    for text in texts:
        errors = sorted(_validator(text, class_name).iter_errors(data), key=lambda e: str(e.path))
        if errors:
            error = errors[0]
            raise WorkflowError(f"{class_name} {list(error.path)}: {error.message}")
    if data.get("schema_version") != VERSION:
        raise WorkflowError(f"unsupported schema_version; expected {VERSION}")


def _ordered_stages(stages: list[dict]) -> None:
    if [(s["stage"], s["key"]) for s in stages] != list(enumerate(STAGE_KEYS, 1)):
        raise WorkflowError("exactly six canonical stages in order are required")


def validate_parent(parent: dict, schema_path: Path = SCHEMA_PATH) -> None:
    _shape(parent, "WorkflowTemplate", schema_path)
    _ordered_stages(parent["stages"])
    if parent["id"] != "mech-goal-cycle":
        raise WorkflowError("unrecognized parent identity")
    if parent["closure_policy"]["steps"] != list(CLOSURE_STEPS):
        raise WorkflowError("parent must retain the ordered full closure sequence")
    for name in ("closure_policy", "review_policy", "infrastructure_policy", "cycle_policy"):
        for key, value in parent[name].items():
            if isinstance(value, bool) and not value:
                raise WorkflowError(f"parent invariant cannot be weakened: {name}.{key}")
    review = parent["review_policy"]
    if (review["artifact_root"] != "reviews/workflow"
            or review["latest_index_path"] != "reviews/workflow/latest.yaml"
            or review["carry_forward_statuses"] != ["open", "deferred"]):
        raise WorkflowError("parent review paths and carry-forward policy are fixed")
    if parent["infrastructure_policy"]["notebook_path"] != "INFRA_TASKS.md":
        raise WorkflowError("infrastructure notebook must be INFRA_TASKS.md")
    if parent["cycle_policy"]["restart_stage"] != 1:
        raise WorkflowError("the next cycle must restart at stage 1")
    allowed_outputs = {"review_report", "review_findings", "issue_map", "infra_snapshot",
                       "implementation_plan", "validation", "supporting"}
    for stage in parent["stages"]:
        outputs = stage["required_outputs"]
        if len(outputs) != len(set(outputs)) or not set(outputs) <= allowed_outputs:
            raise WorkflowError("parent outputs must name unique supported artifact kinds")
        if not REQUIRED_OUTPUTS.get(stage["stage"], set()) <= set(stage["required_outputs"]):
            raise WorkflowError("parent cannot remove required review/infrastructure outputs")


def load_effective_workflow(
    parent_path: Path | str, profile_path: Path | str, repository_key: str | None = None,
    *, schema_path: Path = SCHEMA_PATH,
) -> dict:
    """Resolve a byte-pinned profile; a local extension can only add separate data."""
    parent_raw, profile_raw = _read_regular(Path(parent_path)), _read_regular(Path(profile_path))
    parent, profile = load_document(parent_raw), load_document(profile_raw)
    validate_parent(parent, schema_path)
    _shape(profile, "WorkflowProfile", schema_path)
    _ordered_stages(profile["stages"])
    pin = profile["parent"]
    if (pin["id"] != parent["id"] or pin["version"] != parent["version"]
            or pin["sha256"] != sha256(parent_raw)
            or pin["schema_sha256"] != sha256(_read_regular(schema_path))):
        raise WorkflowError("parent identity, version, content, or schema pin mismatch")
    if pin["repository"] != "CultureBotAI/culturebotai-claw":
        raise WorkflowError("parent repository must be the canonical CLAW repository")
    if repository_key is not None and profile["repository_key"] != repository_key:
        raise WorkflowError("profile repository identity does not match its configured target")
    relative_path(profile["adaptation_skill"])
    for stage in profile["stages"]:
        if not stage["skill_paths"]:
            raise WorkflowError(f"stage {stage['stage']} must name its local skills")
        for path in stage["skill_paths"]:
            relative_path(path)
        if stage["applicability"] != "enabled" and not stage.get("applicability_reason"):
            raise WorkflowError("non-enabled stages need an explicit applicability reason")
        if stage["stage"] >= 4 and stage["applicability"] != "enabled":
            raise WorkflowError("review, issue resolution, and infrastructure stages are mandatory")
    result = {
        "parent_id": parent["id"], "parent_version": parent["version"],
        "parent_sha256": sha256(parent_raw), "profile_sha256": sha256(profile_raw),
        "schema_sha256": sha256(_read_regular(schema_path)),
        "parent_repository": pin["repository"], "parent_revision": pin["revision"],
        "profile_id": profile["profile_id"], "profile_version": profile["profile_version"],
        "repository_key": profile["repository_key"], "github_repository": profile["github_repository"],
        "adaptation_skill": profile["adaptation_skill"], "stages": copy.deepcopy(profile["stages"]),
        "sources": [{"path": str(Path(path).resolve()), "sha256": sha256(raw), "kind": kind}
                    for path, raw, kind in [(parent_path, parent_raw, "parent"),
                                             (profile_path, profile_raw, "profile"),
                                             (schema_path, _read_regular(schema_path), "schema")]],
    }
    for name in ("closure_policy", "review_policy", "infrastructure_policy", "cycle_policy"):
        result[name] = copy.deepcopy(parent[name])
    for stage in result["stages"]:
        stage["required_outputs"] = parent["stages"][stage["stage"] - 1]["required_outputs"]
    if "extension" in profile:
        extension = profile["extension"]
        directory = Path(profile_path).resolve().parent
        schema = directory / relative_path(extension["schema_path"])
        data = directory / relative_path(extension["data_path"])
        schema_raw, data_raw = _read_regular(schema, directory), _read_regular(data, directory)
        if (sha256(schema_raw) != extension["schema_sha256"]
                or sha256(data_raw) != extension["data_sha256"]):
            raise WorkflowError("local extension content pin mismatch")
        adaptation = load_document(data_raw)
        errors = list(_validator(schema_raw.decode(), extension["class_name"]).iter_errors(adaptation))
        if errors:
            raise WorkflowError(f"local extension validation failed: {errors[0].message}")
        result["adaptation"] = adaptation  # Deliberately not merged into execution policy.
        result["extension"] = copy.deepcopy(extension)
        result["sources"].extend([
            {"path": str(schema.resolve()), "sha256": sha256(schema_raw), "kind": "extension"},
            {"path": str(data.resolve()), "sha256": sha256(data_raw), "kind": "extension"},
        ])
    return result


def load_workflow(profile_path, *, parent_path=PARENT_PATH, schema_path=SCHEMA_PATH) -> dict:
    return load_effective_workflow(parent_path, profile_path, schema_path=schema_path)


def evidence_directory(run_id: str, cycle: int, stage: int, revision: int) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,159}", run_id):
        raise WorkflowError("invalid run_id")
    if (type(cycle) is not int or cycle < 1 or type(revision) is not int or revision < 1
            or type(stage) is not int or stage not in range(1, 7)):
        raise WorkflowError("invalid evidence cycle, stage, or revision")
    return (f"reviews/workflow/{run_id}/cycle-{cycle:06d}/stage-{stage:02d}"
            f"/revision-{revision:04d}")


def _unique(items: list[dict], key: str) -> dict:
    result = {item[key]: item for item in items}
    if len(result) != len(items):
        raise WorkflowError(f"duplicate {key}")
    return result


def _issue(url: str, repository: str) -> None:
    if not url.startswith(f"https://github.com/{repository}/issues/"):
        raise WorkflowError("issue belongs to a different repository")


def _resolved(item: dict, paths: set[str]) -> None:
    if item["status"] == "open":
        raise WorkflowError("resolution-stage scope must be resolved or explicitly deferred")
    refs = item.get("resolution_evidence", [])
    if item["status"] == "resolved" and (not refs or not set(refs) <= paths):
        raise WorkflowError("resolved item needs artifact-backed resolution evidence")
    if item["status"] == "deferred" and not item.get("disposition"):
        raise WorkflowError("deferred item needs an explicit disposition")


def _validate_evidence_record(
    data: dict, *, repository_root: Path | None = None, previous: dict | None = None,
    expected: dict | None = None, schema_path: Path = SCHEMA_PATH,
    supersedes: dict | None = None, required_outputs: list[str] | None = None,
) -> None:
    """Validate immutable evidence, references and (when rooted) exact artifact bytes.

    This validates recorded claims, not remote issue closure or Git tracking.
    The caller must verify those claims against the reviewed final commit.
    """
    top = {4: "ReviewReport", 5: "FindingGroupResolution", 6: "InfrastructurePlan"}.get(
        data.get("stage", 0), "GoalEvidence")
    _shape(data, top, schema_path)
    for key, value in (expected or {}).items():
        if data.get(key) != value:
            raise WorkflowError(f"evidence scope mismatch: {key}")
    directory = evidence_directory(data["run_id"], data["cycle"], data["stage"], data["revision"])
    artifacts = _unique(data["artifacts"], "path")
    for path, artifact in artifacts.items():
        relative_path(path)
        if not path.startswith(directory + "/"):
            raise WorkflowError("artifacts must live in the immutable run/cycle/stage/revision directory")
        if repository_root is not None:
            raw = _read_regular(Path(repository_root) / path, Path(repository_root))
            if sha256(raw) != artifact["sha256"]:
                raise WorkflowError(f"artifact checksum mismatch: {path}")
    kinds = {item["kind"] for item in artifacts.values()}
    required = REQUIRED_OUTPUTS.get(data["stage"], set()) | set(required_outputs or [])
    if not required <= kinds:
        raise WorkflowError("required goal output artifacts are missing")
    findings, groups = _unique(data["findings"], "finding_id"), _unique(data["groups"], "group_id")
    tasks = _unique(data["infra_tasks"], "task_id")
    open_ids = {key for key, item in findings.items() if item["status"] in OPEN}
    if (len(set(data["carry_forward_ids"])) != len(data["carry_forward_ids"])
            or set(data["carry_forward_ids"]) != open_ids):
        raise WorkflowError("carry_forward_ids must exactly retain open and deferred finding IDs")
    if data["outcome"] == "no_findings" and (findings or groups or tasks):
        raise WorkflowError("no_findings cannot hide findings, issue groups, or infrastructure tasks")
    if data["stage"] >= 4 and data["outcome"] == "not_applicable":
        raise WorkflowError("the review and backlog stages cannot be skipped as not applicable")
    for item in findings.values():
        if "issue_url" in item:
            _issue(item["issue_url"], data["github_repository"])
        if item["status"] == "deferred" and not item.get("disposition"):
            raise WorkflowError("deferred findings need an explicit disposition")
    if "previous_evidence" in data:
        reference = data["previous_evidence"]
        relative_path(reference["path"])
        if repository_root is not None:
            raw = _read_regular(Path(repository_root) / reference["path"], Path(repository_root))
            if sha256(raw) != reference["sha256"]:
                raise WorkflowError("previous evidence checksum mismatch")
            if previous is not None and load_document(raw) != previous:
                raise WorkflowError("supplied previous evidence differs from the pinned bytes")
    if previous is not None:
        _shape(previous, {4: "ReviewReport", 5: "FindingGroupResolution"}.get(
            previous.get("stage", 0), "GoalEvidence"), schema_path)
        if "previous_evidence" not in data:
            raise WorkflowError("previous evidence must be pinned by path and SHA256")
        if previous["repository_key"] != data["repository_key"]:
            raise WorkflowError("previous evidence repository mismatch")
        prior_findings = _unique(previous["findings"], "finding_id")
        pending = {key for key, value in prior_findings.items() if value["status"] in OPEN}
        if not pending <= findings.keys():
            raise WorkflowError("unresolved prior findings disappeared")
        for key in pending:
            if findings[key].get("carried_from") != key:
                raise WorkflowError("carried findings must preserve their stable identity")
        if data["stage"] == 4:
            next_cycle = (previous["stage"] in {4, 5}
                          and previous["cycle"] == data["cycle"] - 1)
            if previous["run_id"] != data["run_id"] or not next_cycle:
                raise WorkflowError("review lineage must reference the prior cycle")
    elif data["stage"] == 5:
        raise WorkflowError("review resolution requires the pinned stage-4 review evidence")
    elif data["stage"] == 4 and data["cycle"] > 1:
        raise WorkflowError("later-cycle review requires prior-cycle evidence")
    if data["revision"] > 1:
        if supersedes is None or "supersedes_evidence" not in data:
            raise WorkflowError("later revisions require the immediate previous immutable revision")
        if (any(supersedes[key] != data[key] for key in
                ("repository_key", "github_repository", "run_id", "cycle", "stage"))
                or supersedes["revision"] != data["revision"] - 1):
            raise WorkflowError("supersedes must identify the immediate previous revision")
        predecessor_path = evidence_directory(data["run_id"], data["cycle"], data["stage"],
                                               data["revision"] - 1) + "/evidence.yaml"
        if data["supersedes_evidence"]["path"] != predecessor_path:
            raise WorkflowError("supersedes path must identify the immediate previous revision")
        if supersedes.get("previous_evidence") != data.get("previous_evidence"):
            raise WorkflowError("a revised report cannot replace its frozen source evidence")
        for finding in supersedes["findings"]:
            if finding["status"] in OPEN:
                current = findings.get(finding["finding_id"], {})
                if current.get("carried_from") != finding["finding_id"]:
                    raise WorkflowError("unresolved finding disappeared from the preceding revision")
        if data["stage"] == 6:
            old_snapshot = [a["sha256"] for a in supersedes["artifacts"]
                            if a["kind"] == "infra_snapshot"]
            new_snapshot = [a["sha256"] for a in data["artifacts"] if a["kind"] == "infra_snapshot"]
            if old_snapshot != new_snapshot or supersedes.get("scope_frozen_at") != data.get("scope_frozen_at"):
                raise WorkflowError("infrastructure revisions must preserve their frozen input scope")
    elif supersedes is not None or "supersedes_evidence" in data:
        raise WorkflowError("revision 1 cannot supersede another revision")
    if data["stage"] in {5, 6}:
        frozen = data.get("scope_frozen_at", "")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z", frozen):
            raise WorkflowError("resolution scope requires a frozen UTC timestamp")
        try:
            datetime.fromisoformat(frozen.replace("Z", "+00:00"))
        except ValueError as exc:
            raise WorkflowError("invalid scope freeze timestamp") from exc
    if data["stage"] == 5:
        assert previous is not None  # Required and checked before this stage-specific branch.
        if (previous["stage"] != 4 or previous["run_id"] != data["run_id"]
                or previous["cycle"] != data["cycle"]):
            raise WorkflowError("resolution must reference stage 4 of the same run and cycle")
        if findings.keys() != prior_findings.keys():
            raise WorkflowError("resolution scope must exactly match the frozen review findings")
        covered = []
        for group in groups.values():
            _issue(group["issue_url"], data["github_repository"])
            _resolved(group, set(artifacts))
            if not group["finding_ids"]:
                raise WorkflowError("empty finding group")
            covered.extend(group["finding_ids"])
            for key in group["finding_ids"]:
                item = findings.get(key)
                if (item is None or item.get("group_id") != group["group_id"]
                        or item.get("issue_url") != group["issue_url"]
                        or item["status"] != group["status"]):
                    raise WorkflowError("finding/group/issue/status references disagree")
        if len(covered) != len(set(covered)) or set(covered) != set(findings):
            raise WorkflowError("groups must cover every review finding exactly once")
    elif groups:
        raise WorkflowError("issue groups belong to the review-resolution stage")
    if data["stage"] == 6:
        snapshots = [a for a in artifacts.values() if a["kind"] == "infra_snapshot"]
        if len(snapshots) != 1:
            raise WorkflowError("exactly one frozen infrastructure notebook snapshot is required")
        if repository_root is not None:
            raw = _read_regular(Path(repository_root) / snapshots[0]["path"], Path(repository_root))
            notebook = validate_infra_notebook(raw, data["github_repository"])
            pending_tasks = {item["task_id"]: item for item in notebook["tasks"]
                             if item["status"] != "resolved"}
            if tasks.keys() != pending_tasks.keys():
                raise WorkflowError("infrastructure plan must cover the entire frozen notebook scope")
            for key, note in pending_tasks.items():
                if note.get("issue_url") and note["issue_url"] != tasks[key]["issue_url"]:
                    raise WorkflowError("infrastructure plan changed a frozen task issue URL")
        for task in tasks.values():
            _issue(task["issue_url"], data["github_repository"])
            _resolved(task, set(artifacts))
    elif tasks:
        raise WorkflowError("infrastructure tasks belong to stage 6")



def _evidence_graph(data: dict, repository_root: Path) -> tuple[dict, dict]:
    """Read a bounded, hash-pinned ancestry DAG without recursively trusting claims."""
    def identity(document):
        _shape(document, {4: "ReviewReport", 5: "FindingGroupResolution", 6: "InfrastructurePlan"}.get(
            document.get("stage", 0), "GoalEvidence"))
        return evidence_directory(document["run_id"], document["cycle"], document["stage"],
                                  document["revision"]) + "/evidence.yaml"

    first = identity(data)
    documents: dict[str, dict] = {first: data}
    references: dict[str, dict] = {}
    pending = [first]
    while pending:
        path = pending.pop()
        current = documents[path]
        for field in ("previous_evidence", "supersedes_evidence"):
            reference = current.get(field)
            if reference is None:
                continue
            ancestor = str(relative_path(reference["path"]))
            if ancestor == first:
                raise WorkflowError("evidence lineage contains a cycle")
            if ancestor in references and references[ancestor] != reference:
                raise WorkflowError("conflicting immutable ancestor checksums")
            references[ancestor] = reference
            if ancestor in documents:
                continue
            raw = _read_regular(Path(repository_root) / ancestor, Path(repository_root))
            if sha256(raw) != reference["sha256"]:
                raise WorkflowError("ancestor evidence checksum mismatch")
            document = load_document(raw)
            if identity(document) != ancestor:
                raise WorkflowError("ancestor manifest path does not match its immutable identity")
            documents[ancestor] = document
            if len(documents) > 10000:
                raise WorkflowError("evidence lineage exceeds the validation bound")
            pending.append(ancestor)
    # A graph may point backwards without involving the current root. Check all nodes.
    remaining = {path: {doc[field]["path"] for field in ("previous_evidence", "supersedes_evidence")
                        if field in doc} for path, doc in documents.items()}
    while remaining:
        leaves = {path for path, dependencies in remaining.items() if not dependencies}
        if not leaves:
            raise WorkflowError("evidence lineage contains a cycle")
        remaining = {path: dependencies - leaves for path, dependencies in remaining.items()
                     if path not in leaves}
    return documents, references


def validate_goal_evidence(
    data: dict, *, repository_root: Path | None = None, previous: dict | None = None,
    expected: dict | None = None, schema_path: Path = SCHEMA_PATH,
    required_outputs: list[str] | None = None,
) -> None:
    """Validate the goal and every pinned historical manifest and artifact payload."""
    if repository_root is None:
        _validate_evidence_record(data, previous=previous, expected=expected,
                                  schema_path=schema_path, required_outputs=required_outputs)
        return
    documents, _ = _evidence_graph(data, Path(repository_root))
    first = evidence_directory(data["run_id"], data["cycle"], data["stage"], data["revision"]) + "/evidence.yaml"
    if previous is not None:
        reference = data.get("previous_evidence", {})
        if not reference or documents.get(reference.get("path")) != previous:
            raise WorkflowError("supplied previous evidence differs from the pinned bytes")
    for path, document in documents.items():
        prior = documents.get(document.get("previous_evidence", {}).get("path"))
        supersedes = documents.get(document.get("supersedes_evidence", {}).get("path"))
        _validate_evidence_record(document, repository_root=repository_root, previous=prior,
                                  supersedes=supersedes, schema_path=schema_path,
                                  expected=expected if path == first else None,
                                  required_outputs=required_outputs if path == first else None)


def evidence_artifacts(
    data: dict, *, repository_root: Path, previous: dict | None = None,
    schema_path: Path = SCHEMA_PATH,
) -> list[dict]:
    """Return checked current/historical payloads and ancestor manifest descriptors.

    The caller must additionally prove these exact files remain committed at its
    reviewed final Git head. The current manifest is supplied by its receipt.
    """
    validate_goal_evidence(data, repository_root=repository_root, previous=previous,
                           schema_path=schema_path)
    documents, references = _evidence_graph(data, repository_root)
    descriptors = {path: dict(reference) for path, reference in references.items()}
    for document in documents.values():
        for artifact in document["artifacts"]:
            existing = descriptors.get(artifact["path"])
            if existing and existing["sha256"] != artifact["sha256"]:
                raise WorkflowError("conflicting immutable artifact checksums")
            descriptors[artifact["path"]] = dict(artifact)
    return list(descriptors.values())


def read_goal_evidence(
    path: Path | str, *, repository_root: Path | None = None, previous: dict | None = None,
    expected: dict | None = None, schema_path: Path = SCHEMA_PATH,
    required_outputs: list[str] | None = None,
) -> dict:
    raw = _read_regular(Path(path), repository_root)
    data = load_document(raw)
    validate_goal_evidence(data, repository_root=repository_root, previous=previous,
                           expected=expected, schema_path=schema_path,
                           required_outputs=required_outputs)
    if repository_root is not None:
        expected_path = (evidence_directory(data["run_id"], data["cycle"], data["stage"],
                                            data["revision"]) + "/evidence.yaml")
        if Path(path).resolve() != (Path(repository_root) / expected_path).resolve():
            raise WorkflowError("evidence manifest path does not match its immutable identity")
    return data


def validate_infra_notebook(raw: str | bytes, github_repository: str) -> dict:
    """Parse the bounded machine-readable task block in INFRA_TASKS.md."""
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeError as exc:
            raise WorkflowError("infrastructure notebook must be UTF-8") from exc
    start, end = "<!-- mech-infra-tasks:start -->", "<!-- mech-infra-tasks:end -->"
    if raw.count(start) != 1 or raw.count(end) != 1 or raw.index(start) > raw.index(end):
        raise WorkflowError("infrastructure notebook needs exactly one task block")
    body = raw.split(start, 1)[1].split(end, 1)[0].strip()
    if not body.startswith("```yaml\n") or not body.endswith("\n```"):
        raise WorkflowError("infrastructure task block must contain fenced YAML")
    data = load_document(body[len("```yaml\n"):-len("\n```")])
    _shape(data, "InfrastructureNotebook")
    _unique(data["tasks"], "task_id")
    for task in data["tasks"]:
        if task["status"] != "note" and not task.get("issue_url"):
            raise WorkflowError("actionable infrastructure tasks require a real issue URL")
        if task.get("issue_url"):
            _issue(task["issue_url"], github_repository)
        if task["status"] == "deferred" and not task.get("disposition"):
            raise WorkflowError("deferred infrastructure notes need a disposition")
    return data


def save_goal_evidence(
    repository_root: Path, data: dict, *, previous: dict | None = None,
    required_outputs: list[str] | None = None,
) -> Path:
    """Append a new immutable manifest; existing revisions can never be overwritten."""
    validate_goal_evidence(data, repository_root=repository_root, previous=previous,
                           required_outputs=required_outputs)
    directory = evidence_directory(data["run_id"], data["cycle"], data["stage"], data["revision"])
    path = Path(repository_root) / directory / "evidence.yaml"
    if not path.parent.resolve().is_relative_to(Path(repository_root).resolve()):
        raise WorkflowError("manifest parent escapes repository")
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = yaml.safe_dump(data, sort_keys=False, allow_unicode=True).encode()
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".evidence-", delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.link(temporary, path)  # Atomic create-if-absent, never replace an old revision.
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except FileExistsError as exc:
        raise WorkflowError("immutable evidence revision already exists; increment revision") from exc
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return path


def read_infra_notebook(
    path: Path | str, github_repository: str, repository_root: Path | None = None,
) -> dict:
    return validate_infra_notebook(_read_regular(Path(path), repository_root), github_repository)
