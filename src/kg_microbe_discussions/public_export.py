"""Version 1 public projection of native discussions, with no acquisition or writes.

Scientific source records remain authoritative. Callers own public membership,
source-byte hashes, licensing decisions, complete extraction and publication.
"""
from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path, PurePosixPath
from urllib.parse import quote, urlsplit

from jsonschema import Draft202012Validator, FormatChecker

SCHEMA_VERSION = 1
SCHEMA_PATH = Path(__file__).with_name("public_export.schema.json")
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
_VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())
_REVIEW = re.compile(r"\bcurator\s+review\s+required\b", re.I)
_SCAN_PROVENANCE = re.compile(r"^\s*Scan provenance\b", re.I)
_SCAN_ATTRIBUTION = re.compile(r"\bkg-microbe-kgscan\s+pass\s+raised\s+this\s+discussion\b", re.I)
_EMAIL = re.compile(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_EXPERIMENT_FIELDS = frozenset(SCHEMA["$defs"]["experiment"]["properties"])


class PublicExportError(ValueError):
    """A source or public projection cannot satisfy the public contract."""


def _text(value, field, *, required=False):
    if not isinstance(value, str):
        raise PublicExportError(f"{field} must be a string")
    if required and not value.strip():
        raise PublicExportError(f"{field} must not be blank")
    return value


def _list(value, field):
    if not isinstance(value, list):
        raise PublicExportError(f"{field} must be a list")
    return value


def _strings(value, field):
    return [_text(v, field, required=True) for v in _list(value, field)]


def _date(value, field):
    if isinstance(value, datetime):
        raise PublicExportError(f"{field} must be a calendar date, not a timestamp")
    if isinstance(value, date):
        value = value.isoformat()
    _text(value, field)
    if value:
        try:
            parsed = date.fromisoformat(value)
        except ValueError as error:
            raise PublicExportError(f"{field} must be an ISO calendar date") from error
        if parsed.isoformat() != value:
            raise PublicExportError(f"{field} must use YYYY-MM-DD")
    return value


def _https(value, field, *, optional=False):
    _text(value, field)
    if optional and value == "":
        return
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme == "https" and bool(parsed.hostname)
                 and not parsed.username and not parsed.password
                 and not re.search(r"[\s\\\x00-\x1f\x7f]", value))
        parsed.port  # Refuse malformed numeric ports as well.
    except ValueError as error:
        raise PublicExportError(f"{field} must be a safe HTTPS URL") from error
    if not valid:
        raise PublicExportError(f"{field} must be a safe HTTPS URL")


def _source_url(source):
    path = source["path"]
    if (path.startswith("/") or "\\" in path or
            any(part in {"", ".", ".."} for part in path.split("/")) or
            str(PurePosixPath(path)) != path or
            re.search(r"[\x00-\x1f\x7f]", path)):
        raise PublicExportError("source.path must be a normalized relative Git path")
    return (f"https://github.com/{source['repository']}/blob/"
            f"{source['revision']}/{quote(path, safe='/')}")


def stable_id(repository, path, record_id, discussion_id):
    """Delimiter-safe identity, independent of prose, source pin or row order."""
    identity = json.dumps([repository.lower(), path, record_id, discussion_id],
                          ensure_ascii=False, separators=(",", ":"))
    return "gap-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _public_text(value):
    if isinstance(value, str):
        if _EMAIL.search(value):
            raise PublicExportError("Public projection contains an email address")
        if any(ord(char) < 32 and char not in "\n\t\r" for char in value):
            raise PublicExportError("Public projection contains control characters")
    elif isinstance(value, dict):
        for child in value.values():
            _public_text(child)
    elif isinstance(value, list):
        for child in value:
            _public_text(child)


def _classification_reason(required, current_attribution, origin_basis):
    if required:
        return "explicit_review_requirement"
    if current_attribution == "scanner":
        return "current_scanner_attribution"
    if current_attribution == "other":
        return "current_other_attribution"
    if origin_basis == "documented_scan_provenance":
        return "documented_scanner_history_without_current_attribution"
    return "no_review_or_origin_assertion"


def validate_item(item):
    """Fail closed on shape, identity, source links and classification consistency."""
    errors = sorted(_VALIDATOR.iter_errors(item), key=lambda error: str(error.path))
    if errors:
        error = errors[0]
        raise PublicExportError(f"Invalid public item at {list(error.path)}: {error.message}")
    source = item["source"]
    if source["url"] != _source_url(source):
        raise PublicExportError("source.url must name the exact pinned source file")
    _https(source["url"], "source.url")
    _https(source["record_url"], "source.record_url", optional=True)
    if item["id"] != stable_id(source["repository"], source["path"],
                               item["record_id"], item["discussion_id"]):
        raise PublicExportError("id disagrees with the source record identity")
    if item["evidence_refs"] != list(dict.fromkeys(e["reference"] for e in item["evidence"])):
        raise PublicExportError("evidence_refs must equal the distinct evidence references")
    for reference in item["evidence_refs"]:
        if "://" in reference:
            _https(reference, "evidence.reference")
        elif re.match(r"(?i)^(?:javascript|data|file|vbscript|mailto):", reference):
            raise PublicExportError("Unsafe evidence reference")
    required = bool(_REVIEW.search(item["rationale"]))
    expected_review = "required" if required else "unspecified"
    current = item["current_attribution"]
    basis = item["origin_basis"]
    if basis == "current_attribution":
        valid_origin = current != "unspecified" and item["origin"] == current
    elif basis == "documented_scan_provenance":
        valid_origin = item["origin"] == "scanner" and current != "scanner"
    else:
        valid_origin = item["origin"] == current == "unspecified"
    if not valid_origin:
        raise PublicExportError("Origin, basis and current attribution disagree")
    candidate = required or current == "scanner"
    expected_reason = _classification_reason(required, current, basis)
    if (item["review_state"] != expected_review or
            item["lane"] != ("candidate" if candidate else "recorded") or
            item["classification_reason"] != expected_reason):
        raise PublicExportError("Classification disagrees with current provenance and rationale")
    _public_text(item)


def validate_items(items):
    """Validate a complete item list and reject duplicate public identities."""
    _list(items, "items")
    seen = set()
    for item in items:
        validate_item(item)
        if item["id"] in seen:
            raise PublicExportError("Duplicate public discussion identity")
        seen.add(item["id"])


def normalize_record(doc, *, mech, repository, revision, path, source_sha256,
                     root_config, license, record_url=""):
    """Project native discussions without modifying source or inventing review.

    Empty/absent discussions yield no items. Malformed populated discussions
    raise; callers must retain that failure in their extraction coverage.
    """
    if not isinstance(doc, dict) or not isinstance(root_config, dict):
        raise PublicExportError("record and root_config must be mappings")
    discussions = _list(doc.get("discussions", []), "discussions")
    if not discussions:
        return []
    id_fields = ([root_config["id_field"]] if "id_field" in root_config else ["id", "identifier"])
    id_fields = _strings(id_fields, "root_config.id_field")
    record_id = next((doc[field] for field in id_fields if field in doc), "")
    _text(record_id, "record_id", required=True)
    name_fields = _strings(root_config.get("name_fields", ["name", "label", "preferred_term"]),
                           "root_config.name_fields")
    record_label = next((doc[field] for field in name_fields if field in doc), record_id)
    _text(record_label, "record_label", required=True)
    aliases = []
    alias_value_fields = _strings(root_config.get("alias_value_fields", []),
                                   "root_config.alias_value_fields")
    for field in _strings(root_config.get("alias_fields", []), "root_config.alias_fields"):
        values = doc.get(field, [])
        if isinstance(values, str):
            values = [values]
        for alias in _list(values, field):
            if isinstance(alias, dict):
                alias = next((alias[key] for key in alias_value_fields
                              if key in alias), None)
            aliases.append(_text(alias, field, required=True))
    source = {"repository": repository, "revision": revision, "path": path,
              "sha256": source_sha256, "record_url": record_url, "license": license}
    for field, value in source.items():
        _text(value, f"source.{field}")
    source["url"] = _source_url(source)
    items = []
    for discussion in discussions:
        if not isinstance(discussion, dict):
            raise PublicExportError("discussion must be a mapping")
        discussion_id = _text(discussion.get("discussion_id", ""), "discussion_id", required=True)
        prompt = _text(discussion.get("prompt", ""), "prompt", required=True)
        rationale = _text(discussion.get("rationale", ""), "rationale")
        posed_by = _text(discussion.get("posed_by", ""), "posed_by").strip()
        current = "scanner" if posed_by.casefold() == "kg-microbe-kgscan" else "other" if posed_by else "unspecified"
        notes = discussion.get("notes", "")
        documented_scan = (isinstance(notes, str) and bool(_SCAN_PROVENANCE.search(notes))
                           and bool(_SCAN_ATTRIBUTION.search(notes)))
        if current == "scanner":
            origin, basis = "scanner", "current_attribution"
        elif documented_scan:
            origin, basis = "scanner", "documented_scan_provenance"
        else:
            origin, basis = current, "current_attribution" if current == "other" else "unspecified"
        required = bool(_REVIEW.search(rationale))
        evidence = []
        for entry in _list(discussion.get("evidence", []), "evidence"):
            if not isinstance(entry, dict):
                raise PublicExportError("evidence entry must be a mapping")
            evidence.append({"reference": _text(entry.get("reference", ""), "evidence.reference", required=True),
                             "supports": _text(entry.get("supports", "UNSPECIFIED"), "evidence.supports"),
                             "explanation": _text(entry.get("explanation", ""), "evidence.explanation")})
        experiments = []
        for experiment in _list(discussion.get("proposed_experiments", []), "proposed_experiments"):
            if not isinstance(experiment, dict):
                raise PublicExportError("experiment must be a mapping")
            experiments.append({field: deepcopy(value) for field, value in experiment.items()
                                if field in _EXPERIMENT_FIELDS})
        item = {
            "id": stable_id(repository, path, record_id, discussion_id), "mech": mech,
            "record_id": record_id, "record_label": record_label, "aliases": sorted(set(aliases)),
            "discussion_id": discussion_id, "prompt": prompt, "rationale": rationale,
            "kind": discussion.get("kind", "UNSPECIFIED"),
            "status": discussion.get("status", "UNSPECIFIED"),
            "storage_mode": "native_record", "origin": origin,
            "current_attribution": current, "origin_basis": basis,
            "review_state": "required" if required else "unspecified",
            "lane": "candidate" if required or current == "scanner" else "recorded",
            "evidence_refs": list(dict.fromkeys(e["reference"] for e in evidence)),
            "attaches_to": deepcopy(discussion.get("attaches_to", [])), "evidence": evidence,
            "proposed_experiments": experiments,
            "posed_date": _date(discussion.get("posed_date", ""), "posed_date"),
            "resolved_date": _date(discussion.get("resolved_date", ""), "resolved_date"),
            "resolution_note": discussion.get("resolution_note", ""),
            "source": {**deepcopy(source), "locator": "discussions#" + discussion_id},
            "classification_reason": _classification_reason(required, current, basis),
        }
        validate_item(item)
        items.append(item)
    validate_items(items)
    return items
