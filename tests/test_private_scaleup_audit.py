"""Offline private boundary, bounded receipt and independent provenance controls."""
from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from test_governance_cycle_release_audit import commit, git, init, put

from kg_microbe_governance import private_scaleup_audit as audit

NOW = datetime(2026, 11, 9, 4, 0, tzinfo=timezone.utc)
SUBJECT = "a" * 40
PRODUCER = "c" * 40
APP_ID = 901
CONTEXT = {"sha": PRODUCER, "run_id": 101, "run_attempt": 2, "workflow": audit.WORKFLOW,
           "app_id": APP_ID, "subject_head": SUBJECT}
SECRET = "SYNTHETIC_PRIVATE_RECORD_CONTENT_MUST_NOT_APPEAR"


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()


@pytest.fixture
def source():
    policy = copy.deepcopy(audit.load_policy())
    payloads = {}
    for row in policy["artifacts"]:
        content = ("public expected payload " + row["id"] + "\n").encode()
        row["sha256"] = audit.digest(content)
        payloads[row["source"]] = content
    manifest = {"version": 1, "canonical_repository": audit.CONTROL,
                "pin_path": policy["pin_path"], "consumers": {
                    "scaleupmech": {"github": audit.PRIVATE, "package_path": "src/scaleupmech"}},
                "artifacts": [{**row, "consumers": "all"} for row in policy["artifacts"]]}
    raw = json.dumps(manifest).encode()
    policy["source_manifest_sha256"] = audit.digest(raw)
    payloads[audit.CANONICAL_MANIFEST_PATH] = raw
    return policy, payloads


class PrivateAPI:
    def __init__(self, policy, payloads, *, installed=True, empty=False, pin=None):
        self.policy = policy
        self.head = policy["bootstrap_main_ref"] if empty else "b" * 40
        self.next_head = self.head
        self.ref_reads = 0
        self.calls = []
        self.scope = {"total_count": 1, "repositories": [{"id": audit.PRIVATE_ID}]}
        self.repo = {"id": audit.PRIVATE_ID, "full_name": audit.PRIVATE, "private": True, "default_branch": "main"}
        self.entries = {}
        self.blobs = {}
        if installed:
            for row in policy["artifacts"]:
                self.add(row["target"], payloads[row["source"]], "10" + row["mode"])
            self.add(policy["pin_path"], (policy["source_ref"] + "\n").encode() if pin is None else pin)
        if not empty:
            self.add("data/private-record.yaml", SECRET.encode())
        self.rebuild()

    def add(self, path, content, mode="100644"):
        self.entries[path] = (content, mode)

    def rebuild(self):
        directories = {"": {}}
        for path, (content, mode) in self.entries.items():
            parts = path.split("/")
            for count in range(len(parts)):
                directories.setdefault("/".join(parts[:count]), {})
            sha = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
            self.blobs[sha] = {"sha": sha, "size": len(content), "encoding": "base64",
                               "content": base64.b64encode(content).decode()}
            directories["/".join(parts[:-1])][parts[-1]] = {
                "path": parts[-1], "sha": sha, "size": len(content), "type": "blob", "mode": mode}
        ids = {path: hashlib.sha1(("tree:" + path).encode()).hexdigest() for path in directories}
        for path in directories:
            if path:
                parent, _, name = path.rpartition("/")
                directories[parent][name] = {"path": name, "sha": ids[path], "type": "tree", "mode": "040000"}
        self.trees = {ids[path]: {"sha": ids[path], "truncated": False, "tree": list(rows.values())}
                      for path, rows in directories.items()}
        self.trees[self.head] = self.trees[ids[""]]
        self.secret_tree = ids.get("data")

    def get(self, path):
        self.calls.append(path)
        if path == "/installation/repositories?per_page=100":
            return copy.deepcopy(self.scope)
        if path == f"/repos/{audit.PRIVATE}":
            return copy.deepcopy(self.repo)
        if path.endswith("/git/ref/heads/main"):
            self.ref_reads += 1
            return {"ref": "refs/heads/main", "object": {
                "type": "commit", "sha": self.head if self.ref_reads == 1 else self.next_head}}
        if "/git/trees/" in path:
            return copy.deepcopy(self.trees[path.rsplit("/", 1)[-1]])
        if "/git/blobs/" in path:
            return copy.deepcopy(self.blobs[path.rsplit("/", 1)[-1]])
        raise AssertionError("Unexpected fixed API request")


def receipt(source, **kwargs):
    policy, payloads = source
    private = PrivateAPI(policy, payloads, **kwargs)
    value = audit.inspect(policy, private, payloads, dict(CONTEXT), NOW)
    return value, private


def test_real_scope_is_one_private_repository_and_twenty_two_public_obligations():
    policy = audit.load_policy()
    assert policy["repository"] == audit.PRIVATE
    assert policy["source_ref"] == "88e719d5480d0008d6ce082510dcd066775f232b"
    assert policy["bootstrap_main_ref"] == "38f8157fc960299f2458f4916dd581ce1b5d0262"
    assert len(policy["artifacts"]) == 22
    assert {"curation_timestamp_contract", "record_review_contract", "skill_frontmatter_contract"} <= {
        row["id"] for row in policy["artifacts"]}


def test_authenticates_source_before_private_inspection(source):
    policy, payloads = source
    fetched = []
    def fetch(path, ref):
        assert ref == policy["source_ref"]
        fetched.append(path)
        return payloads[path]
    result = audit.authenticate_source(policy, fetch)
    assert set(result) == {row["source"] for row in policy["artifacts"]}
    assert fetched[0] == audit.CANONICAL_MANIFEST_PATH


@pytest.mark.parametrize("change", ["manifest", "payload", "target", "mode"])
def test_source_changes_cannot_redirect_private_reads(source, change):
    policy, payloads = source
    if change == "manifest":
        payloads[audit.CANONICAL_MANIFEST_PATH] += b" "
    elif change == "payload":
        payloads[policy["artifacts"][0]["source"]] += b" "
    else:
        policy["artifacts"][0][change] = "data/private-record.yaml" if change == "target" else "0755"
    with pytest.raises(audit.AuditError, match="source_unverified"):
        audit.authenticate_source(policy, lambda path, ref: payloads[path])


def test_installed_private_audit_reads_no_records_and_serializes_only_closed_status(source):
    value, private = receipt(source)
    assert value["state"] == "installed"
    assert len(value["artifacts"]) == 22
    assert private.ref_reads == 2
    assert not any(private.secret_tree in path for path in private.calls)
    raw = encoded(value)
    assert SECRET.encode() not in raw and b"data/" not in raw and b"target" not in raw
    assert audit.validate_receipt(raw, source[0], subject_head=SUBJECT, app_id=APP_ID, now=NOW) == value


def test_exact_empty_tip_is_pending_bootstrap_not_installed(source):
    value, _ = receipt(source, installed=False, empty=True)
    assert value["state"] == "pending_bootstrap"
    assert not any(row["present"] for row in value["artifacts"])
    assert not any(value["pin"].values())
    audit.validate_receipt(encoded(value), source[0], subject_head=SUBJECT, app_id=APP_ID, now=NOW)


def test_changed_empty_tip_does_not_inherit_bootstrap(source):
    value, _ = receipt(source, installed=False)
    assert value["private_main_sha"] != source[0]["bootstrap_main_ref"]
    assert value["state"] == "invalid"


@pytest.mark.parametrize("change", ["missing", "drift", "mode", "partial", "unknown_pin", "invalid_pin"])
def test_private_changes_never_become_success_or_leak_content(source, change):
    policy, payloads = source
    private = PrivateAPI(policy, payloads)
    path = policy["artifacts"][0]["target"]
    if change == "missing":
        del private.entries[path]
    elif change == "drift":
        private.add(path, SECRET.encode())
    elif change == "mode":
        content, mode = private.entries[path]
        private.add(path, content, "100755" if mode == "100644" else "100644")
    elif change == "partial":
        private.head = policy["bootstrap_main_ref"]
        private.next_head = private.head
        private.entries = {path: private.entries[path]}
    else:
        private.add(policy["pin_path"], b"d" * 40 if change == "unknown_pin" else SECRET.encode())
    private.rebuild()
    value = audit.inspect(policy, private, payloads, dict(CONTEXT), NOW)
    assert value["state"] == "invalid"
    assert SECRET.encode() not in encoded(value)


@pytest.mark.parametrize("change", ["wrong_identity", "public", "broad_token", "race", "symlink", "truncated"])
def test_private_preflight_fails_closed(source, change):
    policy, payloads = source
    private = PrivateAPI(policy, payloads)
    if change == "wrong_identity":
        private.repo["id"] += 1
    elif change == "public":
        private.repo["private"] = False
    elif change == "broad_token":
        private.scope["total_count"] = 2
    elif change == "race":
        private.next_head = "e" * 40
    elif change == "symlink":
        path = policy["artifacts"][0]["target"]
        private.add(path, b"data/private-record.yaml", "120000")
        private.rebuild()
    else:
        private.trees[private.head]["truncated"] = True
    with pytest.raises(audit.AuditError):
        audit.inspect(policy, private, payloads, dict(CONTEXT), NOW)


@pytest.mark.parametrize("change", ["extra", "missing_row", "duplicate_row", "private_sha", "expired",
                                    "future", "long_ttl", "subject", "app", "boolean_app", "false_installed"])
def test_receipt_schema_is_closed_complete_bound_and_fresh(source, change):
    value, _ = receipt(source)
    if change == "extra":
        value["private_record"] = SECRET
    elif change == "missing_row":
        value["artifacts"].pop()
    elif change == "duplicate_row":
        value["artifacts"][1] = value["artifacts"][0]
    elif change == "private_sha":
        value["private_main_sha"] = SECRET
    elif change == "expired":
        value["created_at"] = (NOW - timedelta(seconds=10)).isoformat()
        value["expires_at"] = NOW.isoformat()
    elif change == "future":
        value["created_at"] = (NOW + timedelta(seconds=1)).isoformat()
    elif change == "long_ttl":
        value["expires_at"] = (NOW + timedelta(hours=24)).isoformat()
    elif change == "subject":
        value["producer"]["subject_head"] = "e" * 40
    elif change == "app":
        value["producer"]["app_id"] += 1
    elif change == "boolean_app":
        value["producer"]["app_id"] = True
    else:
        value["artifacts"][0]["content_matches"] = False
    with pytest.raises(audit.AuditError):
        audit.validate_receipt(encoded(value), source[0], subject_head=SUBJECT,
                               app_id=1 if change == "boolean_app" else APP_ID, now=NOW)


class PublicAPI:
    def __init__(self, value):
        self.calls = []
        self.run = {"id": 101, "run_attempt": 2, "event": "workflow_dispatch", "head_branch": "main",
                    "head_sha": PRODUCER, "path": audit.WORKFLOW, "repository": {"id": audit.CONTROL_ID},
                    "status": "completed", "conclusion": "success", "run_started_at": NOW.isoformat(),
                    "updated_at": (NOW + timedelta(seconds=30)).isoformat()}
        self.environment = {"deployment_branch_policy": {"protected_branches": False, "custom_branch_policies": True}}
        self.branches = {"total_count": 1, "branch_policies": [{"name": "main", "type": "branch"}]}
        self.package(value)

    def package(self, value, extra=False):
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as archive:
            archive.writestr("receipt.json", encoded(value))
            if extra:
                archive.writestr("private-record.yaml", SECRET)
        self.archive = out.getvalue()
        self.artifact = {"id": 51, "name": "scaleup-governance-receipt-101-2", "expired": False,
                         "digest": "sha256:" + audit.digest(self.archive), "created_at": NOW.isoformat()}
        self.listing = {"total_count": 1, "artifacts": [self.artifact]}

    def get(self, path):
        self.calls.append(path)
        if path.endswith("/attempts/2"):
            return copy.deepcopy(self.run)
        if path.endswith("/artifacts?per_page=100"):
            return copy.deepcopy(self.listing)
        if path.endswith(f"/environments/{audit.ENVIRONMENT}"):
            return copy.deepcopy(self.environment)
        if "deployment-branch-policies" in path:
            return copy.deepcopy(self.branches)
        if path.endswith("/commits/" + SUBJECT):
            return {"sha": SUBJECT}
        raise AssertionError("Unexpected public provenance request")

    def request(self, path, *, archive=False):
        self.calls.append(path)
        assert path == f"/repos/{audit.CONTROL}/actions/artifacts/51/zip" and archive
        return self.archive


def verify(public, source, **kwargs):
    return audit.verified_receipt(public, source[0], run_id=101, attempt=2, subject_head=SUBJECT,
                                  app_id=APP_ID, protected_shas=kwargs.get("protected_shas", {PRODUCER}), now=NOW)


def test_verifier_fetches_actual_trusted_artifact_not_caller_supplied_json(source):
    value, _ = receipt(source)
    public = PublicAPI(value)
    assert verify(public, source) == value
    assert any("/artifacts/51/zip" in path for path in public.calls)
    assert all(audit.PRIVATE not in path for path in public.calls)


@pytest.mark.parametrize("change", ["workflow", "event", "branch", "head", "repository", "attempt", "failure",
                                    "digest", "old_artifact", "duplicate", "extra_zip", "subject", "producer_sha"])
def test_public_provenance_rejects_forged_or_replayed_receipts(source, change):
    value, _ = receipt(source)
    public = PublicAPI(value)
    if change == "workflow":
        public.run["path"] = ".github/workflows/attacker.yaml"
    elif change == "event":
        public.run["event"] = "pull_request"
    elif change == "branch":
        public.run["head_branch"] = "feature"
    elif change == "head":
        public.run["head_sha"] = "d" * 40
    elif change == "repository":
        public.run["repository"]["id"] += 1
    elif change == "attempt":
        public.run["run_attempt"] = 1
    elif change == "failure":
        public.run["conclusion"] = "failure"
    elif change == "digest":
        public.artifact["digest"] = "sha256:" + "0" * 64
    elif change == "old_artifact":
        public.artifact["created_at"] = (NOW - timedelta(seconds=1)).isoformat()
    elif change == "duplicate":
        public.listing["artifacts"].append(copy.deepcopy(public.artifact))
        public.listing["total_count"] = 2
    elif change == "extra_zip":
        public.package(value, extra=True)
    elif change == "subject":
        value["producer"]["subject_head"] = "d" * 40
        public.package(value)
    else:
        value["producer"]["sha"] = "e" * 40
        public.package(value)
    with pytest.raises(audit.AuditError):
        verify(public, source)


def context_environment():
    return {"GITHUB_REPOSITORY": audit.CONTROL, "GITHUB_REF": "refs/heads/main",
            "GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_SHA": PRODUCER,
            "GITHUB_WORKFLOW_REF": f"{audit.CONTROL}/{audit.WORKFLOW}@refs/heads/main",
            "GITHUB_RUN_ID": "101", "GITHUB_RUN_ATTEMPT": "2", "SCALEUP_AUDIT_APP_ID": str(APP_ID)}


def test_producer_preflight_requires_real_main_environment_and_exact_subject(source):
    value, _ = receipt(source)
    public = PublicAPI(value)
    assert audit.producer_context(public, context_environment(), SUBJECT) == CONTEXT


@pytest.mark.parametrize("change", ["missing_app", "wrong_ref", "candidate_workflow", "event", "wildcard", "tag", "unprotected"])
def test_no_secret_environment_or_producer_authority_can_be_selected_by_candidate(source, change):
    value, _ = receipt(source)
    public = PublicAPI(value)
    env = context_environment()
    if change == "missing_app":
        env.pop("SCALEUP_AUDIT_APP_ID")
    elif change == "wrong_ref":
        env["GITHUB_REF"] = "refs/heads/feature"
    elif change == "candidate_workflow":
        env["GITHUB_WORKFLOW_REF"] = f"{audit.CONTROL}/{audit.WORKFLOW}@refs/heads/feature"
    elif change == "event":
        env["GITHUB_EVENT_NAME"] = "pull_request"
    elif change == "wildcard":
        public.branches["branch_policies"][0]["name"] = "*"
    elif change == "tag":
        public.branches["branch_policies"][0]["type"] = "tag"
    else:
        public.environment["deployment_branch_policy"] = None
    with pytest.raises(audit.AuditError):
        audit.producer_context(public, env, SUBJECT)


def test_producer_version_requires_exact_authoritative_main_including_other_executable_files(tmp_path):
    root = tmp_path / "trusted"
    init(root, audit.CONTROL)
    put(root, audit.WORKFLOW, "protected workflow\n")
    old = commit(root)
    # An omitted startup hook changes the whole executable context, even if
    # every originally allowlisted producer file remains identical.
    put(root, "sitecustomize.py", "new protected startup context\n")
    current = commit(root)
    class MainAPI:
        head = current
        def get(self, path):
            assert path == f"/repos/{audit.CONTROL}/git/ref/heads/main"
            return {"ref": "refs/heads/main", "object": {"type": "commit", "sha": self.head}}
    public = MainAPI()
    assert audit.trusted_producer_shas(root, public) == {current}
    assert old not in audit.trusted_producer_shas(root, public)
    # A stale or forged local origin/main is not authority.
    public.head = old
    with pytest.raises(audit.AuditError, match="producer_untrusted"):
        audit.trusted_producer_shas(root, public)
    public.head = current
    git(root, "update-ref", "refs/remotes/origin/main", old)
    with pytest.raises(audit.AuditError, match="producer_untrusted"):
        audit.trusted_producer_shas(root, public)
    git(root, "update-ref", "refs/remotes/origin/main", current)
    put(root, "sitecustomize.py", "dirty startup context\n")
    with pytest.raises(audit.AuditError, match="producer_untrusted"):
        audit.trusted_producer_shas(root, public)


def test_cli_masks_unexpected_private_errors_and_refuses_missing_configuration(monkeypatch, capsys, tmp_path):
    monkeypatch.delenv("GH_PUBLIC_READ_TOKEN", raising=False)
    assert audit.main(["produce", "--subject-head", SUBJECT, "--output", str(tmp_path / "out.json")]) == 2
    assert capsys.readouterr().err.strip() == "configuration_missing"
    monkeypatch.setenv("GH_PUBLIC_READ_TOKEN", "synthetic-public-token")
    def sensitive_error(*args, **kwargs):
        raise RuntimeError(SECRET)
    monkeypatch.setattr(audit, "producer_context", sensitive_error)
    assert audit.main(["produce", "--subject-head", SUBJECT, "--output", str(tmp_path / "out.json")]) == 2
    captured = capsys.readouterr()
    assert captured.err.strip() == "unexpected_failure" and SECRET not in captured.out + captured.err
    assert not (tmp_path / "out.json").exists()
    assert audit.main([SECRET]) == 2
    assert SECRET not in capsys.readouterr().err


def test_transport_follows_only_bounded_artifact_redirect_without_authorization():
    import urllib.error
    from email.message import Message

    class Reply(io.BytesIO):
        pass

    class Opener:
        calls = []
        target = "https://fixture.blob.core.windows.net/bounded-artifact?signature=synthetic"
        def open(self, request, timeout):
            self.calls.append(request)
            if len(self.calls) == 1:
                headers = Message()
                headers["Location"] = self.target
                raise urllib.error.HTTPError(request.full_url, 302, SECRET, headers, None)
            assert isinstance(request, str), "artifact redirect must not inherit a credential-bearing Request"
            return Reply(b"bounded artifact")

    client = audit.GitHubRead("synthetic-sensitive-token")
    opener = Opener()
    client._opener = opener
    assert client.request(f"/repos/{audit.CONTROL}/actions/artifacts/123/zip", archive=True) == b"bounded artifact"
    assert opener.calls[0].get_header("Authorization") == "Bearer synthetic-sensitive-token"
    assert "synthetic-sensitive-token" not in opener.calls[1]
    for target in ("https://attacker.invalid/file", "http://fixture.blob.core.windows.net/file",
                   "https://user:password@fixture.blob.core.windows.net/file"):
        opener.calls = []
        opener.target = target
        with pytest.raises(audit.AuditError, match="transport_refused"):
            client.request(f"/repos/{audit.CONTROL}/actions/artifacts/123/zip", archive=True)
        assert len(opener.calls) == 1
    opener.calls = []
    opener.target = "https://fixture.blob.core.windows.net/file"
    with pytest.raises(audit.AuditError, match="transport_refused"):
        client.request(f"/repos/{audit.PRIVATE}/git/trees/" + "a" * 40)
    assert len(opener.calls) == 1


def test_transport_denies_other_repositories_and_bounds_response():
    client = audit.GitHubRead("synthetic-token")
    with pytest.raises(audit.AuditError, match="transport_refused"):
        client.request("/repos/CultureBotAI/OtherPrivateMech/git/ref/heads/main")
    class Opener:
        def open(self, request, timeout):
            assert request.get_method() == "GET"
            return io.BytesIO(b"x" * (audit.MAX_RESPONSE + 1))
    client._opener = Opener()
    with pytest.raises(audit.AuditError, match="transport_refused"):
        client.request(f"/repos/{audit.PRIVATE}")


def test_workflow_is_manual_protected_and_never_executes_candidate_or_private_checkout():
    import yaml
    root = Path(__file__).resolve().parents[1]
    workflow = yaml.load((root / audit.WORKFLOW).read_text(), Loader=yaml.BaseLoader)
    assert set(workflow["on"]) == {"workflow_dispatch"}
    assert workflow["permissions"] == {"contents": "read", "actions": "read"}
    assert set(workflow["jobs"]) == {"produce"}
    job = workflow["jobs"]["produce"]
    assert job["environment"] == audit.ENVIRONMENT
    assert job["env"]["SUBJECT_HEAD"] == "${{ inputs.subject_head }}"
    steps = job["steps"]
    checkout = [s for s in steps if s.get("uses", "").startswith("actions/checkout@")]
    assert len(checkout) == 1
    assert checkout[0]["with"] == {"ref": "${{ github.sha }}", "fetch-depth": "0", "persist-credentials": "false"}
    uv = next(s for s in steps if s.get("uses", "").startswith("astral-sh/setup-uv@"))
    assert uv["with"]["enable-cache"] == "false"
    preflight = next(i for i, s in enumerate(steps) if "preflight --subject-head" in s.get("run", ""))
    mint = next(i for i, s in enumerate(steps) if s.get("id") == "private-token")
    assert preflight < mint
    assert steps[mint]["with"] == {
        "app-id": "${{ vars.SCALEUP_AUDIT_APP_ID }}",
        "private-key": "${{ secrets.SCALEUP_AUDIT_APP_PRIVATE_KEY }}",
        "owner": "CultureBotAI", "repositories": "ScaleupMech", "permission-contents": "read",
    }
    for step in steps:
        if "uses" in step:
            assert audit.is_sha(step["uses"].split("@")[-1])
        if "run" in step:
            assert "${{" not in step["run"]
            assert "git clone" not in step["run"]
        if "--subject-head" in step.get("run", ""):
            assert '--subject-head "$SUBJECT_HEAD"' in step["run"]
    produce = next(s for s in steps if "produce --subject-head" in s.get("run", ""))
    assert produce["env"]["SCALEUP_PRIVATE_READ_TOKEN"] == "${{ steps.private-token.outputs.token }}"
    upload = next(s for s in steps if s.get("uses", "").startswith("actions/upload-artifact@"))
    assert upload["with"]["path"] == ".audit-public/receipt.json"
    assert upload["with"]["name"] == "scaleup-governance-receipt-${{ github.run_id }}-${{ github.run_attempt }}"
    assert upload["with"]["overwrite"] == "false"
    assert upload["with"]["if-no-files-found"] == "error"


def test_produce_cli_authenticates_public_bytes_before_constructing_private_client(source, monkeypatch, tmp_path, capsys):
    policy, payloads = source
    calls = []
    private = PrivateAPI(policy, payloads)
    def client(token):
        calls.append(token)
        if token == "public-token":
            return object()
        assert calls == ["public-token", "authenticated", "private-token"]
        return private
    def authenticate(actual_policy, fetch):
        assert actual_policy == policy
        calls.append("authenticated")
        return payloads
    monkeypatch.setattr(audit, "load_policy", lambda: policy)
    monkeypatch.setattr(audit, "producer_context", lambda *args: CONTEXT)
    monkeypatch.setattr(audit, "GitHubRead", client)
    monkeypatch.setattr(audit, "authenticate_source", authenticate)
    monkeypatch.setenv("GH_PUBLIC_READ_TOKEN", "public-token")
    monkeypatch.setenv("SCALEUP_PRIVATE_READ_TOKEN", "private-token")
    output = tmp_path / "receipt.json"
    assert audit.main(["produce", "--subject-head", SUBJECT, "--output", str(output)]) == 0
    value = json.loads(output.read_bytes())
    assert value["state"] == "installed" and SECRET not in output.read_text()
    assert capsys.readouterr().out.strip() == "scaleup_governance_receipt_installed"
    calls.clear()
    def fail_source(*args):
        raise audit.AuditError("source_unverified")
    monkeypatch.setattr(audit, "authenticate_source", fail_source)
    assert audit.main(["produce", "--subject-head", SUBJECT, "--output", str(tmp_path / "rejected.json")]) == 2
    assert calls == ["public-token"]
    assert capsys.readouterr().err.strip() == "source_unverified"
    assert not (tmp_path / "rejected.json").exists()


def test_producer_workflow_runtime_is_proven_by_dependency_guard():
    import yaml
    from test_workflow_dependency_provisioning import (
        declared_dependencies,
        unprovisioned_claw_invocations,
    )
    root = Path(__file__).resolve().parents[1]
    workflow = yaml.safe_load((root / audit.WORKFLOW).read_text())
    dependencies = declared_dependencies()
    assert not unprovisioned_claw_invocations(workflow, dependencies)
    broken = copy.deepcopy(workflow)
    for step in broken["jobs"]["produce"]["steps"]:
        if "run" in step:
            step["run"] = step["run"].replace("uv run --locked --no-dev", "uv run --no-sync")
    findings = unprovisioned_claw_invocations(broken, dependencies)
    assert len(findings) == 2
    assert all(row[0] == "produce" and "linkml" in row[2] for row in findings)
