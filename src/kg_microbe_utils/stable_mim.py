"""Consume captured native MIM identities; never allocate IDs or approve mappings."""

from __future__ import annotations

import csv
import hashlib
import importlib
import io
import json
import re
import subprocess
import sys
import threading
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType


def load_owner_record(content):
    """Parse captured stable-owner bytes without hiding duplicate keys.

    This matches the native MIM stable-ID validator's unique-key policy at
    every mapping depth. Legacy parsing is explicitly separate.
    """
    import yaml

    class UniqueKeyLoader(yaml.SafeLoader):
        pass

    def mapping(loader, node, deep=False):
        result = {}
        for key_node, value_node in node.value:
            key = loader.construct_object(key_node, deep=deep)
            if key in result:
                raise ValueError(f"Duplicate YAML key: {key}")
            result[key] = loader.construct_object(value_node, deep=deep)
        return result

    UniqueKeyLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)
    return yaml.load(content, Loader=UniqueKeyLoader)


def identity_snapshot(root, records, mint, lifecycle, source, source_path, source_sha256):
    """Validate the complete captured corpus with the explicitly pinned native contract.

    The caller captures/rechecks all bytes and path memberships, including this
    producer. Native source is executable trusted-caller input, not a signature.
    No import of an ambient installed MIM package or cached bytecode is used.
    """
    if (not isinstance(source_sha256, str)
            or not re.fullmatch(r"[a-f0-9]{64}", source_sha256)
            or hashlib.sha256(source).hexdigest() != source_sha256):
        raise ValueError("Native MIM stable-ID contract digest differs")
    name = f"_captured_mim_ids_{source_sha256}"
    module = ModuleType(name)
    module.__file__ = str(source_path)
    # Dataclasses consult their declaring module while the captured code runs.
    previous = sys.modules.get(name)
    sys.modules[name] = module
    try:
        exec(compile(source, str(source_path), "exec", dont_inherit=True), module.__dict__)
        registry = module.parse_registry(mint, lifecycle)
        relative = {str(path.relative_to(root)): value for path, value in records.items()}
        module.validate_records(registry, relative)
        index = module.build_record_index(relative)
        subjects = {path: module.validate_id(value["mim_id"]) for path, value in records.items()}
        return subjects, index, module.MIM_PREFIX
    finally:
        if previous is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = previous


def registry_retirement_inputs(root, path, raw, expected_sha256):
    """Bind an authored diagnostic proposal and all evidence, never approve removal.

    #1189: an obsolete canonical compatibility row may prevent generating the
    candidate that the separate whole-table publication review needs. This input
    proposes only an exact exclusion from that diagnostic compatibility view.
    """
    def keys(value, expected):
        if not isinstance(value, dict) or set(value) != set(expected):
            raise ValueError("Malformed registry retirement proposal")

    def pin(value):
        if not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value):
            raise ValueError("Invalid registry retirement input digest")

    def relative(value):
        if (not isinstance(value, str) or not value or Path(value).is_absolute()
                or ".." in Path(value).parts or Path(value).as_posix() != value):
            raise ValueError("Invalid registry retirement input path")
        return root / value

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate registry retirement proposal key")
            result[key] = value
        return result

    pin(expected_sha256)
    if not isinstance(raw, bytes) or hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("Registry retirement proposal digest differs")
    path.relative_to(root)
    proposal = json.loads(raw, object_pairs_hook=unique)
    keys(proposal, {"schema_version", "capability", "scope", "author", "canonical",
                    "evidence_inputs", "entries", "scientific_approval"})
    if (type(proposal["schema_version"]) is not int or proposal["schema_version"] != 1
            or proposal["capability"] != "stable-registry-retirement-proposal-v1"
            or proposal["scope"] != "diagnostic_candidate_only"
            or proposal["scientific_approval"] is not False
            or not isinstance(proposal["author"], str) or not proposal["author"].strip()):
        raise ValueError("Registry retirement is an authored diagnostic proposal only")
    keys(proposal["canonical"], {"path", "sha256"})
    if proposal["canonical"]["path"] != "mappings/ingredient_mappings.sssom.tsv":
        raise ValueError("Registry retirement requires the original canonical table")
    pin(proposal["canonical"]["sha256"])
    paths = {path, relative(proposal["canonical"]["path"])}
    evidence = proposal["evidence_inputs"]
    if not isinstance(evidence, dict) or not evidence:
        raise ValueError("Registry retirement requires exact evidence inputs")
    for name, digest in evidence.items():
        paths.add(relative(name))
        pin(digest)
    if not isinstance(proposal["entries"], list) or not proposal["entries"]:
        raise ValueError("Registry retirement requires explicit row proposals")
    positions = set()
    for entry in proposal["entries"]:
        keys(entry, {"row_position", "row", "owner", "reason", "evidence"})
        position = entry["row_position"]
        if type(position) is not int or position < 1 or position in positions:
            raise ValueError("Registry retirement row position is invalid or duplicated")
        positions.add(position)
        if (not isinstance(entry["row"], dict) or not entry["row"]
                or not all(isinstance(k, str) and isinstance(v, str)
                           for k, v in entry["row"].items())
                or not isinstance(entry["reason"], str) or not entry["reason"].strip()
                or not isinstance(entry["evidence"], list) or not entry["evidence"]
                or not all(isinstance(name, str) and name in evidence
                           for name in entry["evidence"])
                or len(set(entry["evidence"])) != len(entry["evidence"])):
            raise ValueError("Registry retirement requires full row, reason and pinned evidence")
        keys(entry["owner"], {"path", "sha256", "mim_id"})
        paths.add(relative(entry["owner"]["path"]))
        pin(entry["owner"]["sha256"])
        if not isinstance(entry["owner"]["mim_id"], str):
            raise ValueError("Registry retirement owner ID is invalid")
    return paths, proposal


def registry_retirement_evidence(root, path, raw, expected_sha256, snapshot):
    """Verify the complete captured proposal closure and retain its exact content."""
    paths, proposal = registry_retirement_inputs(root, path, raw, expected_sha256)
    required = dict(proposal["evidence_inputs"])
    canonical_name, canonical_digest = proposal["canonical"]["path"], proposal["canonical"]["sha256"]
    if canonical_name in required and required[canonical_name] != canonical_digest:
        raise ValueError("Registry retirement input pins conflict")
    required[canonical_name] = canonical_digest
    for entry in proposal["entries"]:
        name, digest = entry["owner"]["path"], entry["owner"]["sha256"]
        if name in required and required[name] != digest:
            raise ValueError("Registry retirement input pins conflict")
        required[name] = digest
    for name, digest in required.items():
        content = snapshot.get(root / name)
        if content is None or hashlib.sha256(content).hexdigest() != digest:
            raise ValueError("Registry retirement evidence changed: " + name)
    if snapshot.get(path) != raw or not paths <= set(snapshot):
        raise ValueError("Registry retirement capture is incomplete")
    return {"path": str(path), "sha256": expected_sha256, "content": proposal,
            "scientific_approval_added": False}


def _retained_cas_identity(record, obj, subject):
    """Check one existing exact CAS assertion against its current owner (#1192).

    This retains candidate content only. Supplied-form procurement metadata,
    synonyms and cross-references cannot create or justify an identity row.
    """
    rn = obj.removeprefix("cas:")
    if not re.fullmatch(r"[1-9][0-9]{1,6}-[0-9]{2}-[0-9]", rn):
        raise ValueError(f"Malformed canonical CAS identity for {subject}: {obj}")
    digits = rn.replace("-", "")
    checksum = sum(i * int(digit) for i, digit in enumerate(reversed(digits[:-1]), 1)) % 10
    if checksum != int(digits[-1]):
        raise ValueError(f"Invalid canonical CAS check digit for {subject}: {obj}")
    primary = record.get("identifier")
    chemistry = record.get("chemical_properties") or {}
    current = chemistry.get("cas_rn") if isinstance(chemistry, dict) else None
    if (not isinstance(primary, str)
            or (primary.startswith("cas:") and primary != obj)
            or (current is not None and current != rn)
            or not (primary == obj or current == rn)):
        raise ValueError(f"Canonical CAS identity lacks matching current owner evidence: {subject} {obj}")
    if record.get("mapping_status") != "MAPPED":
        raise ValueError(f"Canonical CAS identity owner requires mapping review: {subject} {obj}")


def compatibility_registry_objects(records, subjects, index, canonical, *, retirement=None, root=None):
    """Retain literal local objects and corroborated existing exact CAS objects.

    Current curated local primaries and the captured canonical registry rows are
    the authority for object spellings. Historical MIM aliases must identify one
    actual owner. Shared external aliases never choose an owner. This preserves
    candidate mapping content, not prior scientific stamps or release approval.
    Canonical CAS rows must agree with current identity-bearing chemistry; never
    add a CAS row merely because a number occurs in the owner's metadata (#1192).
    """
    prefixes = ("kgmicrobe.compound:", "kgmicrobe.ingredient:")
    result = {subject: set() for subject in subjects.values()}
    owner_by_subject = {subject: records[path] for path, subject in subjects.items()}
    for path, record in records.items():
        primary = record.get("identifier", "")
        if isinstance(primary, str) and primary.startswith(prefixes):
            result[subjects[path]].add(primary)
    rows = csv.DictReader(io.StringIO("".join(
        line for line in canonical.decode("utf-8").splitlines(keepends=True)
        if not line.startswith("#")
    )), delimiter="\t")
    if not rows.fieldnames or not {"subject_id", "predicate_id", "object_id"} <= set(rows.fieldnames):
        raise ValueError("Stable mode requires a complete canonical compatibility table")
    if len(rows.fieldnames) != len(set(rows.fieldnames)):
        raise ValueError("Duplicate canonical compatibility column name")
    entries = {} if retirement is None else {
        entry["row_position"]: entry for entry in retirement["content"]["entries"]}
    if retirement is not None and hashlib.sha256(canonical).hexdigest() != retirement["content"]["canonical"]["sha256"]:
        raise ValueError("Registry retirement canonical bytes differ")
    visited = set()
    for position, row in enumerate(rows, 1):
        if None in row or None in row.values():
            raise ValueError("Malformed canonical compatibility row")
        old, obj = row["subject_id"], row["object_id"]
        selected = entries.get(position)
        if selected is not None and selected["row"] != row:
            raise ValueError("Registry retirement full canonical row differs")
        is_cas = obj.startswith("cas:")
        if row["predicate_id"] != "skos:exactMatch" or not (obj.startswith(prefixes) or is_cas):
            if selected is not None:
                raise ValueError("Only exact registry compatibility rows can be proposed")
            continue
        if old in result:
            subject = old
        elif old.startswith("MIM:") and old in index.aliases:
            owner = index.lookup(old)  # Ambiguous historical MIM aliases fail.
            subject = {path: key for key, path in index.stable_ids.items()}[owner]
        elif old.startswith("MIM:"):
            raise ValueError(f"Canonical registry alias has no current stable owner: {old}")
        else:
            if selected is not None or is_cas:
                raise ValueError("Registry retirement row has no stable MIM owner")
            continue
        if selected is not None:
            if is_cas:
                raise ValueError("CAS retention is not a local registry retirement proposal")
            owner = selected["owner"]
            path = root / owner["path"]
            if path not in records or subjects[path] != subject or owner["mim_id"] != subject:
                raise ValueError("Registry retirement owner differs")
            primary = records[path].get("identifier", "")
            if (not isinstance(primary, str) or not primary.startswith(prefixes)
                    or obj.split(":", 1)[0] == primary.split(":", 1)[0]):
                raise ValueError("Registry retirement requires a competing curated primary")
            if obj.split(":", 1)[1] == subject.split(":", 1)[1]:
                raise ValueError(f"Numeric MIM suffix is not a registry identity: {subject}")
            visited.add(position)
            continue
        if is_cas:
            _retained_cas_identity(owner_by_subject[subject], obj, subject)
        result[subject].add(obj)
    if visited != set(entries):
        raise ValueError("Registry retirement row position is absent")
    for subject, objects in result.items():
        local_objects = {obj for obj in objects if obj.startswith(prefixes)}
        if len({obj.split(":", 1)[0] for obj in local_objects}) > 1:
            raise ValueError(f"Competing registry namespaces for {subject}")
        if any(obj.split(":", 1)[1] == subject.split(":", 1)[1] for obj in local_objects):
            raise ValueError(f"Numeric MIM suffix is not a registry identity: {subject}")
    return {subject: tuple(sorted(objects)) for subject, objects in result.items()}


def source_binding_inputs(root, bundle, review, manifest_bytes, manifest_sha256):
    """Enumerate the distinct native product and its declared closure; no admission."""
    if hashlib.sha256(manifest_bytes).hexdigest() != manifest_sha256:
        raise ValueError("Source-binding manifest digest differs")
    manifest = json.loads(manifest_bytes)
    if (manifest.get("required_capabilities") != ["reviewed-source-bindings-v1"]
            or manifest.get("semantic_status") != "REVIEWED_CANDIDATE_ONLY"
            or manifest.get("production_authorized") is not False):
        raise ValueError("Unsupported source-binding candidate capability/status")
    paths = {bundle / "manifest.json", review}
    for key, base in (("inputs", root), ("files", bundle)):
        if not isinstance(manifest.get(key), dict) or not manifest[key]:
            raise ValueError("Source-binding candidate lacks its complete input/product map")
        for name, digest in manifest[key].items():
            if (not isinstance(name, str) or not name or Path(name).is_absolute()
                    or ".." in Path(name).parts or not isinstance(digest, str)
                    or not re.fullmatch(r"[a-f0-9]{64}", digest)):
                raise ValueError("Invalid source-binding input/product pin")
            paths.add(base / name)
    return paths, manifest


def native_source_paths(root):
    """Bind the actual MIM package/resources used by its native readonly replay."""
    return tuple(sorted({
        root / "scripts/record_review.py", root / "schema/record_review.yaml",
        *(path for path in (root / "src/mediaingredientmech").rglob("*")
          if path.suffix in {".py", ".yaml", ".json"}),
    }))


@contextmanager
def _pure_linkml_loader():
    """Scope native schema loading away from PyYAML C import-state damage.

    Use the existing shared LinkML loader lock convention. Do not replace
    PyYAML globally or suppress any native parser/schema validation failure.
    """
    import yaml

    class PureLinkMLLoader(yaml.SafeLoader):
        yaml_path_resolvers = {}

        def construct_mapping(self, node, deep=False):
            self.flatten_mapping(node)
            result = {}
            for key_node, value_node in node.value:
                key = self.construct_object(key_node, deep=deep)
                try:
                    duplicate = key in result
                except TypeError as exc:
                    raise yaml.constructor.ConstructorError(
                        "while constructing a mapping", node.start_mark,
                        "found an unhashable key", key_node.start_mark) from exc
                if duplicate:
                    raise yaml.constructor.ConstructorError(
                        "while constructing a mapping", node.start_mark,
                        f"found duplicate key {key!r}", key_node.start_mark)
                result[key] = self.construct_object(value_node, deep=deep)
            return result

    loader_module = importlib.import_module("linkml_runtime.loaders.yaml_loader")
    lock = vars(loader_module).setdefault("_claw_linkml_loader_lock", threading.RLock())
    with lock:
        original = loader_module.DupCheckYamlLoader
        loader_module.DupCheckYamlLoader = PureLinkMLLoader
        try:
            yield
        finally:
            loader_module.DupCheckYamlLoader = original


def validate_empty_candidate(path, columns, mim_prefix):
    """Validate a genuine zero-row table without accepting parser row loss.

    sssom-py can log a phantom missing-predicate warning for a header-only
    table. Require exactly one physical non-comment line, the complete header,
    explicit metadata and zero parsed mappings before the same three native
    validators used by the ordinary CLI. A blank/skeleton data row is refused.
    This path is only for stable mode with a validated separate source bundle.
    """
    import yaml
    from sssom.constants import SchemaValidationType
    from sssom.parsers import parse_sssom_table, to_mapping_set_document
    from sssom.validators import validate

    lines = path.read_text(encoding="utf-8").splitlines()
    data = [line for line in lines if not line.startswith("#")]
    if data != ["\t".join(columns)]:
        raise ValueError("Empty candidate must contain only its complete physical header")
    metadata = yaml.safe_load("\n".join(line[1:].removeprefix(" ")
                                      for line in lines if line.startswith("#")))
    if (not isinstance(metadata, dict)
            or not all(metadata.get(key) for key in ("mapping_set_id", "license", "mapping_set_version"))
            or not isinstance(metadata.get("curie_map"), dict)
            or metadata["curie_map"].get("MIM") != mim_prefix):
        raise ValueError("Empty candidate lacks explicit stable metadata")
    with _pure_linkml_loader():
        native = parse_sssom_table(path, strict=True)
        if len(native.df) or to_mapping_set_document(native).mapping_set.mappings:
            raise ValueError("Empty candidate parser produced a mapping")
        validate(native, [SchemaValidationType.JsonSchema,
                          SchemaValidationType.PrefixMapCompleteness,
                          SchemaValidationType.StrictCurieFormat], fail_on_error=True)


def validate_source_bindings(root, bundle, review, manifest, producer_sha256, snapshot, stage):
    """Delegate review semantics to native MIM; do not reinterpret source decisions.

    A fresh subprocess imports the selected root, with a fresh bytecode prefix,
    and invokes only validate_candidate. It never exports or modifies a source.
    The caller rechecks this complete snapshot before/after and at publication.
    """
    producer = root / "src/mediaingredientmech/export/source_bindings.py"
    content = snapshot.get(producer)
    if (not content or not isinstance(producer_sha256, str)
            or hashlib.sha256(content).hexdigest() != producer_sha256):
        raise ValueError("Native source-binding producer digest differs")
    for key, base in (("inputs", root), ("files", bundle)):
        for name, digest in manifest[key].items():
            content = snapshot.get(base / name)
            if content is None or hashlib.sha256(content).hexdigest() != digest:
                raise ValueError("Source-binding captured input/product differs: " + name)
    command = (
        "import json,sys; from pathlib import Path; "
        "sys.path.insert(0,str(Path(sys.argv[1])/'src')); "
        "from mediaingredientmech.export.source_bindings import validate_candidate; "
        "print(json.dumps(validate_candidate(Path(sys.argv[1]),Path(sys.argv[2]),"
        "Path(sys.argv[3])),sort_keys=True))"
    )
    process = subprocess.run(
        [sys.executable, "-I", "-B", "-X", f"pycache_prefix={stage / 'native-pycache'}",
         "-c", command, str(root), str(review), str(bundle)],
        capture_output=True, text=True, cwd=stage, timeout=300,
    )
    if process.returncode:
        raise ValueError("Native source-binding validation failed: " + process.stderr[-2000:])
    if json.loads(process.stdout) != manifest:
        raise ValueError("Native source-binding reconstruction differs from captured manifest")
    return {"manifest_sha256": hashlib.sha256(snapshot[bundle / "manifest.json"]).hexdigest(),
            "review": str(review), "bundle": str(bundle), "counts": manifest["counts"],
            "capability": "reviewed-source-bindings-v1", "production_authorized": False,
            "native_validation": "passed", "canonical_rows_modified_by_source_bindings": False}
