"""Dormant, Scaleup-only private governance inspection and public receipt protocol.

This does not replace a fleet gate, activate an admission, or execute downstream
code. Production transport has fixed GitHub endpoints; private response bytes
stay in memory. Errors are closed codes, never server bodies or private values.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta, timezone
from importlib.resources import files
from pathlib import Path
from typing import Any

from .artifacts.scripts.check_vendored_sync import (
    CANONICAL_MANIFEST_PATH,
    Consumer,
    _run_git,
    parse_manifest,
)

CONTROL = "CultureBotAI/culturebotai-claw"
PRIVATE = "CultureBotAI/ScaleupMech"
CONTROL_ID = 1193181994
PRIVATE_ID = 1450887724
WORKFLOW = ".github/workflows/private-scaleup-audit.yaml"
ENVIRONMENT = "scaleup-private-audit"
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
MAX_RECEIPT = 32_768
MAX_RESPONSE = 8_388_608
MAX_BLOB = 4_194_304
CODES = frozenset({
    "configuration_missing", "invalid_arguments", "invalid_json", "invalid_policy",
    "transport_refused", "source_unverified", "private_identity_mismatch",
    "app_scope_unverified", "private_snapshot_invalid", "private_main_changed",
    "environment_unprotected", "producer_untrusted", "invalid_receipt",
    "receipt_expired", "artifact_unverified", "inspection_invalid", "unexpected_failure",
})


class AuditError(ValueError):
    def __init__(self, code: str):
        self.code = code if code in CODES else "unexpected_failure"
        super().__init__(self.code)


def require(condition: bool, code: str) -> None:
    if not condition:
        raise AuditError(code)


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def is_sha(value: Any, size: int = 40) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{" + str(size) + r"}", value) is not None


def positive(value: Any) -> bool:
    return type(value) is int and value > 0


def parse_json(raw: bytes) -> Any:
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "invalid_json")
            result[key] = value
        return result
    try:
        require(len(raw) <= MAX_RESPONSE, "invalid_json")
        return json.loads(raw, object_pairs_hook=pairs)
    except (ValueError, UnicodeError, TypeError):
        raise AuditError("invalid_json") from None


def utc(value: Any) -> datetime:
    try:
        require(isinstance(value, str), "invalid_receipt")
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        require(parsed.tzinfo is not None and parsed.utcoffset() == timedelta(0), "invalid_receipt")
        return parsed
    except (ValueError, TypeError, AttributeError):
        raise AuditError("invalid_receipt") from None


def load_policy() -> dict:
    policy = parse_json(files("kg_microbe_governance").joinpath("private_audit/scaleup-v1.json").read_bytes())
    fields = {"version", "scope", "repository", "repository_id", "control_repository",
              "control_repository_id", "source_ref", "source_manifest_sha256", "bootstrap_main_ref",
              "pin_path", "producer_workflow", "environment", "max_age_seconds", "artifacts"}
    require(isinstance(policy, dict) and set(policy) == fields, "invalid_policy")
    require(type(policy["version"]) is int and policy["version"] == 1 and policy["scope"] == "scaleup_governance_only"
            and policy["repository"] == PRIVATE and policy["repository_id"] == PRIVATE_ID
            and policy["control_repository"] == CONTROL and policy["control_repository_id"] == CONTROL_ID
            and policy["producer_workflow"] == WORKFLOW and policy["environment"] == ENVIRONMENT
            and policy["pin_path"] == "scripts/.vendored_canon_ref"
            and type(policy["max_age_seconds"]) is int and 0 < policy["max_age_seconds"] <= 900,
            "invalid_policy")
    require(is_sha(policy["source_ref"]) and is_sha(policy["bootstrap_main_ref"])
            and is_sha(policy["source_manifest_sha256"], 64), "invalid_policy")
    artifacts = policy["artifacts"]
    require(isinstance(artifacts, list) and len(artifacts) == 22, "invalid_policy")
    require(all(isinstance(row, dict) and set(row) == {"id", "source", "target", "sha256", "mode"}
                and all(isinstance(value, str) for value in row.values()) for row in artifacts), "invalid_policy")
    require([row["id"] for row in artifacts] == sorted({row["id"] for row in artifacts}), "invalid_policy")
    for row in artifacts:
        require(is_sha(row["sha256"], 64) and row["mode"] in {"0644", "0755"}
                and row["source"].startswith("src/kg_microbe_governance/artifacts/")
                and all(not path.startswith("/") and all(part not in {"", ".", ".."} for part in path.split("/"))
                        for path in (row["source"], row["target"])), "invalid_policy")
    return policy


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


class GitHubRead:
    """GET-only bounded transport; authorization never crosses a redirect."""
    def __init__(self, token: str):
        require(isinstance(token, str) and bool(token.strip()), "configuration_missing")
        self._token = token
        self._opener = urllib.request.build_opener(NoRedirect())

    def request(self, path: str, *, archive: bool = False) -> bytes:
        require((path in {f"/repos/{CONTROL}", f"/repos/{PRIVATE}"} or path.startswith((f"/repos/{CONTROL}/", f"/repos/{PRIVATE}/", "/installation/repositories")))
                and not any(char in path for char in "\r\n#") and not path.startswith("//"), "transport_refused")
        request = urllib.request.Request("https://api.github.com" + path, headers={
            "Authorization": "Bearer " + self._token, "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "claw-scaleup-governance-audit",
        })
        try:
            try:
                response = self._opener.open(request, timeout=30)
            except urllib.error.HTTPError as exc:
                if not archive or exc.code != 302:
                    raise AuditError("transport_refused") from None
                target = urllib.parse.urlsplit(exc.headers.get("Location", ""))
                require(target.scheme == "https" and target.hostname is not None
                        and target.hostname.endswith((".githubusercontent.com", ".blob.core.windows.net",
                                                       ".actions.githubusercontent.com"))
                        and not target.username and not target.password and not target.fragment,
                        "transport_refused")
                # No Authorization header is sent to the artifact-storage host.
                response = self._opener.open(target.geturl(), timeout=30)
            with response:
                raw = response.read(MAX_RESPONSE + 1)
            require(len(raw) <= MAX_RESPONSE, "transport_refused")
            return raw
        except (OSError, ValueError, urllib.error.URLError):
            raise AuditError("transport_refused") from None

    def get(self, path: str) -> Any:
        return parse_json(self.request(path))


def public_source(path: str, ref: str) -> bytes:
    require(is_sha(ref) and (path == CANONICAL_MANIFEST_PATH or path.startswith(
        "src/kg_microbe_governance/artifacts/")) and ".." not in path.split("/"), "source_unverified")
    try:
        url = f"https://raw.githubusercontent.com/{CONTROL}/{ref}/{path}"
        with urllib.request.build_opener(NoRedirect()).open(url, timeout=30) as response:
            raw = response.read(MAX_BLOB + 1)
        require(len(raw) <= MAX_BLOB, "source_unverified")
        return raw
    except (OSError, ValueError, urllib.error.URLError):
        raise AuditError("source_unverified") from None


def authenticate_source(policy: dict, fetch: Callable[[str, str], bytes]) -> dict[str, bytes]:
    raw = fetch(CANONICAL_MANIFEST_PATH, policy["source_ref"])
    require(digest(raw) == policy["source_manifest_sha256"], "source_unverified")
    try:
        manifest = parse_manifest(raw)
        consumer = manifest.consumer_for("scaleupmech")
        actual = sorted(({
            "id": a.artifact_id, "source": a.source,
            "target": a.target.replace("{package_path}", consumer.package_path),
            "sha256": a.sha256, "mode": f"{a.mode:04o}",
        } for a in manifest.artifacts_for(consumer)), key=lambda row: row["id"])
        require(consumer.github == PRIVATE and consumer.package_path == "src/scaleupmech"
                and manifest.canonical_repository == CONTROL and manifest.pin_path == policy["pin_path"]
                and actual == policy["artifacts"], "source_unverified")
        payloads = {}
        for artifact in manifest.artifacts:
            content = fetch(artifact.source, policy["source_ref"])
            require(len(content) <= MAX_BLOB and digest(content) == artifact.sha256, "source_unverified")
            payloads[artifact.source] = content
        return payloads
    except (KeyError, TypeError, ValueError):
        raise AuditError("source_unverified") from None


def environment_is_protected(public: GitHubRead) -> None:
    environment = public.get(f"/repos/{CONTROL}/environments/{ENVIRONMENT}")
    branches = public.get(f"/repos/{CONTROL}/environments/{ENVIRONMENT}/deployment-branch-policies?per_page=100")
    require(environment.get("deployment_branch_policy") == {
        "protected_branches": False, "custom_branch_policies": True,
    } and branches.get("total_count") == 1 and isinstance(branches.get("branch_policies"), list)
        and len(branches["branch_policies"]) == 1
        and branches["branch_policies"][0].get("name") == "main"
        and branches["branch_policies"][0].get("type") == "branch", "environment_unprotected")


def producer_context(public: GitHubRead, environ: Mapping[str, str], subject_head: str) -> dict:
    require(environ.get("GITHUB_REPOSITORY") == CONTROL and environ.get("GITHUB_REF") == "refs/heads/main"
            and environ.get("GITHUB_EVENT_NAME") == "workflow_dispatch"
            and environ.get("GITHUB_WORKFLOW_REF") == f"{CONTROL}/{WORKFLOW}@refs/heads/main"
            and is_sha(environ.get("GITHUB_SHA")) and is_sha(subject_head), "producer_untrusted")
    try:
        run_id = int(environ.get("GITHUB_RUN_ID", ""))
        attempt = int(environ.get("GITHUB_RUN_ATTEMPT", ""))
        app_id = int(environ.get("SCALEUP_AUDIT_APP_ID", ""))
    except ValueError:
        raise AuditError("configuration_missing") from None
    require(all(positive(value) for value in (run_id, attempt, app_id)), "configuration_missing")
    environment_is_protected(public)
    run = public.get(f"/repos/{CONTROL}/actions/runs/{run_id}/attempts/{attempt}")
    require(run.get("id") == run_id and run.get("run_attempt") == attempt
            and run.get("event") == "workflow_dispatch" and run.get("head_branch") == "main"
            and run.get("head_sha") == environ["GITHUB_SHA"] and run.get("path") == WORKFLOW
            and run.get("repository", {}).get("id") == CONTROL_ID, "producer_untrusted")
    commit = public.get(f"/repos/{CONTROL}/commits/{subject_head}")
    require(commit.get("sha") == subject_head, "producer_untrusted")
    return {"sha": environ["GITHUB_SHA"], "run_id": run_id, "run_attempt": attempt,
            "workflow": WORKFLOW, "app_id": app_id, "subject_head": subject_head}


class PrivateSnapshot:
    def __init__(self, private: GitHubRead, bootstrap_main_ref: str):
        self.api = private
        scope = private.get("/installation/repositories?per_page=100")
        require(scope.get("total_count") == 1 and isinstance(scope.get("repositories"), list)
                and len(scope["repositories"]) == 1
                and scope["repositories"][0].get("id") == PRIVATE_ID, "app_scope_unverified")
        repo = private.get(f"/repos/{PRIVATE}")
        require(repo.get("id") == PRIVATE_ID and repo.get("full_name") == PRIVATE
                and repo.get("private") is True and repo.get("default_branch") == "main",
                "private_identity_mismatch")
        self.head = self.main()
        commit = private.get(f"/repos/{PRIVATE}/git/commits/{self.head}")
        require(commit.get("sha") == self.head and isinstance(commit.get("tree"), dict)
                and is_sha(commit["tree"].get("sha")), "private_snapshot_invalid")
        self.root_tree = commit["tree"]["sha"]
        self.trees: dict[str, dict] = {}
        if self.head == bootstrap_main_ref:
            # GitHub returns 404 for the canonical empty Git tree. Authenticate
            # the exact bootstrap commit's tree instead; never reinterpret a
            # failed tree request or an unknown object as an empty installation.
            require(self.root_tree == EMPTY_TREE, "private_snapshot_invalid")
            self.trees[self.root_tree] = {}

    def main(self) -> str:
        ref = self.api.get(f"/repos/{PRIVATE}/git/ref/heads/main")
        require(ref.get("ref") == "refs/heads/main" and ref.get("object", {}).get("type") == "commit"
                and is_sha(ref.get("object", {}).get("sha")), "private_snapshot_invalid")
        return ref["object"]["sha"]

    def tree(self, ref: str) -> dict:
        if ref not in self.trees:
            tree = self.api.get(f"/repos/{PRIVATE}/git/trees/{ref}")
            require(tree.get("truncated") is False and tree.get("sha") == ref
                    and isinstance(tree.get("tree"), list), "private_snapshot_invalid")
            entries = tree["tree"]
            require(all(isinstance(row, dict) and isinstance(row.get("path"), str)
                        and is_sha(row.get("sha")) for row in entries), "private_snapshot_invalid")
            require(len({row["path"] for row in entries}) == len(entries), "private_snapshot_invalid")
            self.trees[ref] = {row["path"]: row for row in entries}
        return self.trees[ref]

    def read(self, path: str) -> tuple[str, bytes] | None:
        parts = path.split("/")
        tree_ref = self.root_tree
        for part in parts[:-1]:
            row = self.tree(tree_ref).get(part)
            if row is None:
                return None
            require(row.get("type") == "tree" and row.get("mode") == "040000", "private_snapshot_invalid")
            tree_ref = row["sha"]
        row = self.tree(tree_ref).get(parts[-1])
        if row is None:
            return None
        require(row.get("type") == "blob" and row.get("mode") in {"100644", "100755"}
                and type(row.get("size")) is int and 0 <= row["size"] <= MAX_BLOB, "private_snapshot_invalid")
        blob = self.api.get(f"/repos/{PRIVATE}/git/blobs/{row['sha']}")
        require(blob.get("encoding") == "base64" and blob.get("sha") == row["sha"]
                and blob.get("size") == row["size"] and isinstance(blob.get("content"), str), "private_snapshot_invalid")
        try:
            content = base64.b64decode("".join(blob["content"].split()), validate=True)
        except ValueError:
            raise AuditError("private_snapshot_invalid") from None
        expected_sha = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
        require(len(content) == row["size"] and expected_sha == row["sha"], "private_snapshot_invalid")
        return row["mode"], content


def inspect(policy: dict, private: GitHubRead, payloads: Mapping[str, bytes], producer: dict,
            now: datetime) -> dict:
    require(now.tzinfo is not None and now.utcoffset() == timedelta(0), "invalid_arguments")
    snapshot = PrivateSnapshot(private, policy["bootstrap_main_ref"])
    rows = []
    for artifact in policy["artifacts"]:
        actual = snapshot.read(artifact["target"])
        rows.append({"id": artifact["id"], "expected_sha256": artifact["sha256"],
                     "present": actual is not None,
                     "content_matches": actual is not None and actual[1] == payloads[artifact["source"]],
                     "mode_matches": actual is not None and actual[0] == "10" + artifact["mode"]})
    pin = snapshot.read(policy["pin_path"])
    pin_valid = pin is not None and re.fullmatch(rb"[0-9a-f]{40}\n?", pin[1]) is not None
    pin_matches = pin_valid and pin is not None and pin[0] == "100644" and pin[1].decode().strip() == policy["source_ref"]
    pending = (snapshot.head == policy["bootstrap_main_ref"] and pin is None
               and not any(row["present"] for row in rows))
    installed = pin_matches and all(row["content_matches"] and row["mode_matches"] for row in rows)
    require(snapshot.main() == snapshot.head, "private_main_changed")
    return {"version": 1, "scope": "scaleup_governance_only", "repository": PRIVATE,
            "repository_id": PRIVATE_ID, "private_main_sha": snapshot.head,
            "source_ref": policy["source_ref"], "source_manifest_sha256": policy["source_manifest_sha256"],
            "producer": producer, "created_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=policy["max_age_seconds"])).isoformat(),
            "state": "pending_bootstrap" if pending else "installed" if installed else "invalid",
            "pin": {"present": pin is not None, "valid": bool(pin_valid), "matches": bool(pin_matches)},
            "artifacts": rows}


def validate_receipt(raw: bytes, policy: dict, *, subject_head: str, app_id: int,
                     now: datetime) -> dict:
    require(len(raw) <= MAX_RECEIPT, "invalid_receipt")
    receipt = parse_json(raw)
    fields = {"version", "scope", "repository", "repository_id", "private_main_sha", "source_ref",
              "source_manifest_sha256", "producer", "created_at", "expires_at", "state", "pin", "artifacts"}
    require(isinstance(receipt, dict) and set(receipt) == fields and type(receipt["version"]) is int
            and receipt["version"] == 1 and receipt["scope"] == "scaleup_governance_only"
            and receipt["repository"] == PRIVATE and receipt["repository_id"] == PRIVATE_ID
            and is_sha(receipt["private_main_sha"]) and receipt["source_ref"] == policy["source_ref"]
            and receipt["source_manifest_sha256"] == policy["source_manifest_sha256"]
            and receipt["state"] in {"pending_bootstrap", "installed", "invalid"}, "invalid_receipt")
    producer = receipt["producer"]
    require(isinstance(producer, dict) and set(producer) == {
        "sha", "run_id", "run_attempt", "workflow", "app_id", "subject_head",
    } and is_sha(producer["sha"]) and producer["subject_head"] == subject_head
        and is_sha(subject_head) and producer["workflow"] == WORKFLOW
        and positive(app_id) and positive(producer["app_id"]) and producer["app_id"] == app_id
        and positive(producer["run_id"]) and positive(producer["run_attempt"]), "invalid_receipt")
    created, expires = utc(receipt["created_at"]), utc(receipt["expires_at"])
    require(created <= now < expires and timedelta(0) < expires - created
            <= timedelta(seconds=policy["max_age_seconds"]), "receipt_expired")
    pin = receipt["pin"]
    require(isinstance(pin, dict) and set(pin) == {"present", "valid", "matches"}
            and all(type(value) is bool for value in pin.values()), "invalid_receipt")
    rows = receipt["artifacts"]
    require(isinstance(rows, list) and len(rows) == len(policy["artifacts"]), "invalid_receipt")
    for actual, expected in zip(rows, policy["artifacts"], strict=True):
        require(isinstance(actual, dict) and set(actual) == {
            "id", "expected_sha256", "present", "content_matches", "mode_matches",
        } and actual["id"] == expected["id"] and actual["expected_sha256"] == expected["sha256"]
            and all(type(actual[field]) is bool for field in ("present", "content_matches", "mode_matches"))
            and (actual["present"] or not (actual["content_matches"] or actual["mode_matches"])), "invalid_receipt")
    pending = (receipt["private_main_sha"] == policy["bootstrap_main_ref"]
               and pin == {"present": False, "valid": False, "matches": False}
               and not any(row["present"] for row in rows))
    installed = all(pin.values()) and all(all(row[field] for field in (
        "present", "content_matches", "mode_matches")) for row in rows)
    expected_state = "pending_bootstrap" if pending else "installed" if installed else "invalid"
    require(receipt["state"] == expected_state, "invalid_receipt")
    return receipt


def trusted_producer_shas(root: Path, public: GitHubRead) -> set[str]:
    """Trust only today's exact authoritative main, never selected historical files.

    The caller must execute this verifier from a trusted protected checkout.
    Checking an arbitrary candidate checkout cannot make its Python trustworthy.
    """
    from . import _require_clean_worktree, _validate_target_repository

    try:
        root = _validate_target_repository(root, Consumer("claw", CONTROL, "src/kg_microbe_governance"))
        _require_clean_worktree(root)
        head = _run_git(root, ("rev-parse", "HEAD")).strip()
        local_main = _run_git(root, ("rev-parse", "refs/remotes/origin/main")).strip()
        remote = public.get(f"/repos/{CONTROL}/git/ref/heads/main")
        require(remote.get("ref") == "refs/heads/main"
                and remote.get("object", {}).get("type") == "commit"
                and is_sha(remote["object"].get("sha"))
                and head == local_main == remote["object"]["sha"], "producer_untrusted")
        # Main advancing invalidates earlier receipts even when governed bytes
        # did not change: all executable startup/build/import context is bound.
        return {head}
    except (OSError, ValueError):
        raise AuditError("producer_untrusted") from None


def verified_receipt(public: GitHubRead, policy: dict, *, run_id: int, attempt: int,
                     subject_head: str, app_id: int, protected_shas: set[str], now: datetime) -> dict:
    require(positive(run_id) and positive(attempt), "producer_untrusted")
    run = public.get(f"/repos/{CONTROL}/actions/runs/{run_id}/attempts/{attempt}")
    require(run.get("id") == run_id and run.get("run_attempt") == attempt
            and run.get("repository", {}).get("id") == CONTROL_ID
            and run.get("event") == "workflow_dispatch" and run.get("path") == WORKFLOW
            and run.get("head_branch") == "main" and run.get("head_sha") in protected_shas
            and run.get("status") == "completed" and run.get("conclusion") == "success", "producer_untrusted")
    listing = public.get(f"/repos/{CONTROL}/actions/runs/{run_id}/artifacts?per_page=100")
    require(type(listing.get("total_count")) is int and 0 <= listing["total_count"] <= 100
            and isinstance(listing.get("artifacts"), list)
            and len(listing["artifacts"]) == listing["total_count"], "artifact_unverified")
    name = f"scaleup-governance-receipt-{run_id}-{attempt}"
    matching = [item for item in listing["artifacts"] if item.get("name") == name]
    require(len(matching) == 1, "artifact_unverified")
    artifact = matching[0]
    require(positive(artifact.get("id")) and artifact.get("expired") is False
            and isinstance(artifact.get("digest"), str)
            and re.fullmatch(r"sha256:[0-9a-f]{64}", artifact["digest"]) is not None
            and utc(run["run_started_at"]) <= utc(artifact["created_at"]) <= utc(run["updated_at"]), "artifact_unverified")
    archive = public.request(f"/repos/{CONTROL}/actions/artifacts/{artifact['id']}/zip", archive=True)
    require(digest(archive) == artifact["digest"][7:], "artifact_unverified")
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            entries = bundle.infolist()
            require(len(entries) == 1 and entries[0].filename == "receipt.json"
                    and not entries[0].is_dir() and 0 < entries[0].file_size <= MAX_RECEIPT
                    and not entries[0].flag_bits & 1, "artifact_unverified")
            with bundle.open(entries[0]) as stream:
                raw = stream.read(MAX_RECEIPT + 1)
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError):
        raise AuditError("artifact_unverified") from None
    receipt = validate_receipt(raw, policy, subject_head=subject_head, app_id=app_id, now=now)
    require(receipt["producer"]["run_id"] == run_id and receipt["producer"]["run_attempt"] == attempt
            and receipt["producer"]["sha"] == run["head_sha"]
            and utc(run["run_started_at"]) <= utc(receipt["created_at"]) <= utc(run["updated_at"]), "producer_untrusted")
    require(receipt["state"] != "invalid", "inspection_invalid")
    return receipt


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise AuditError("invalid_arguments")


def main(argv=None) -> int:
    try:
        parser = Parser(description=__doc__)
        parser.add_argument("command", choices=("preflight", "produce", "verify"))
        parser.add_argument("--subject-head", required=True)
        parser.add_argument("--output", type=Path)
        parser.add_argument("--trusted-root", type=Path)
        parser.add_argument("--run-id", type=int)
        parser.add_argument("--attempt", type=int)
        args = parser.parse_args(argv)
        policy = load_policy()
        public = GitHubRead(os.environ.get("GH_PUBLIC_READ_TOKEN", ""))
        now = datetime.now(timezone.utc)
        if args.command in {"preflight", "produce"}:
            context = producer_context(public, os.environ, args.subject_head)
            if args.command == "preflight":
                print("scaleup_private_audit_preflight_passed")
                return 0
            require(args.output is not None and not args.output.exists(), "invalid_arguments")
            payloads = authenticate_source(policy, public_source)
            private = GitHubRead(os.environ.get("SCALEUP_PRIVATE_READ_TOKEN", ""))
            receipt = inspect(policy, private, payloads, context, now)
            raw = (json.dumps(receipt, sort_keys=True, separators=(",", ":")) + "\n").encode()
            validate_receipt(raw, policy, subject_head=args.subject_head, app_id=context["app_id"], now=now)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("xb") as stream:
                stream.write(raw)
            print("scaleup_governance_receipt_" + receipt["state"])
            return 0 if receipt["state"] != "invalid" else 1
        require(args.trusted_root is not None, "producer_untrusted")
        app_id = int(os.environ.get("SCALEUP_AUDIT_APP_ID", ""))
        receipt = verified_receipt(public, policy, run_id=args.run_id, attempt=args.attempt,
            subject_head=args.subject_head, app_id=app_id,
            protected_shas=trusted_producer_shas(args.trusted_root, public), now=now)
        print("verified_scaleup_governance_receipt_" + receipt["state"])
        return 0
    except AuditError as exc:
        print(exc.code, file=sys.stderr)
        return 2
    except Exception:
        print("unexpected_failure", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
