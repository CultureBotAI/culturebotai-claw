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


def compatibility_registry_objects(records, subjects, index, canonical):
    """Retain literal existing local objects, never derive one from a numeric ID.

    Current curated local primaries and the captured canonical registry rows are
    the authority for object spellings. Historical MIM aliases must identify one
    actual owner. Shared external aliases never choose an owner. This preserves
    candidate mapping content, not prior scientific stamps or release approval.
    """
    prefixes = ("kgmicrobe.compound:", "kgmicrobe.ingredient:")
    result = {subject: set() for subject in subjects.values()}
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
    for row in rows:
        if None in row or None in row.values():
            raise ValueError("Malformed canonical compatibility row")
        old, obj = row["subject_id"], row["object_id"]
        if row["predicate_id"] != "skos:exactMatch" or not obj.startswith(prefixes):
            continue
        if old in result:
            subject = old
        elif old.startswith("MIM:") and old in index.aliases:
            owner = index.lookup(old)  # Ambiguous historical MIM aliases fail.
            subject = {path: key for key, path in index.stable_ids.items()}[owner]
        elif old.startswith("MIM:"):
            raise ValueError(f"Canonical registry alias has no current stable owner: {old}")
        else:
            continue
        result[subject].add(obj)
    for subject, objects in result.items():
        if len({obj.split(":", 1)[0] for obj in objects}) > 1:
            raise ValueError(f"Competing registry namespaces for {subject}")
        if any(obj.split(":", 1)[1] == subject.split(":", 1)[1] for obj in objects):
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
