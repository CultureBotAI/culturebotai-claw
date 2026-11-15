"""Protected automatic Scaleup receipts, bound to an actual parent run and attempt.

No candidate code or artifact is consumed by the credentialed producer. GitHub
metadata and public JSON are data. All private reads use the fixed v1 policy.
"""

from __future__ import annotations

import base64
import io
import json
import re
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from . import private_scaleup_audit as manual

PARENT_WORKFLOW = ".github/workflows/governance-fleet-audit.yaml"
PRODUCER_WORKFLOW = ".github/workflows/private-scaleup-automatic.yaml"
COMPONENT_JOBS = ("candidate-contracts", "public-fleet")
MAX_FINAL_AGE = 120
MAX_WAIT_SECONDS = 600
MAX_RUNS = 30
MANIFEST_PATH = "src/kg_microbe_governance/vendored_artifacts.json"


def check(condition: bool, code: str = "producer_untrusted") -> None:
    manual.require(condition, code)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def current_main(public) -> str:
    value = public.get(f"/repos/{manual.CONTROL}/git/ref/heads/main")
    check(
        value.get("ref") == "refs/heads/main"
        and value.get("object", {}).get("type") == "commit"
        and manual.is_sha(value["object"].get("sha"))
    )
    return value["object"]["sha"]


def public_blob(public, path: str, ref: str) -> bytes:
    check(
        manual.is_sha(ref)
        and path in {MANIFEST_PATH, "src/kg_microbe_fleet/fleet.yaml"}
    )
    value = public.get(f"/repos/{manual.CONTROL}/contents/{path}?ref={ref}")
    check(
        value.get("type") == "file"
        and value.get("encoding") == "base64"
        and type(value.get("size")) is int
        and 0 <= value["size"] <= manual.MAX_BLOB
        and isinstance(value.get("content"), str),
        "source_unverified",
    )
    try:
        raw = base64.b64decode("".join(value["content"].split()), validate=True)
    except ValueError:
        raise manual.AuditError("source_unverified") from None
    check(len(raw) == value["size"], "source_unverified")
    return raw


def _pull_request(public, run: dict) -> dict:
    """Use authenticated commit associations when fork run.pull_requests is empty."""
    source_repository_id = run.get("head_repository", {}).get("id")
    check(manual.positive(source_repository_id))
    rows = run.get("pull_requests")
    check(isinstance(rows, list) and len(rows) <= 100)
    recorded_associations = bool(rows)
    if not rows:
        rows = public.get(
            f"/repos/{manual.CONTROL}/commits/{run['head_sha']}/pulls?per_page=100"
        )
        # A full page cannot establish uniqueness/completeness; never guess.
        check(isinstance(rows, list) and len(rows) < 100)
    numbers = {row.get("number") for row in rows if isinstance(row, dict)}
    check(
        len(numbers) == len(rows) and all(manual.positive(number) for number in numbers)
    )
    candidates = []
    for number in sorted(numbers, key=str):
        pr = public.get(f"/repos/{manual.CONTROL}/pulls/{number}")
        if recorded_associations:
            recorded = next(row for row in rows if row["number"] == number)
            for side in ("head", "base"):
                observed = recorded.get(side, {})
                actual = pr.get(side, {})
                check(
                    observed.get("sha") == actual.get("sha")
                    and observed.get("ref") == actual.get("ref")
                    and manual.is_sha(observed.get("sha"))
                    and manual.positive(observed.get("repo", {}).get("id"))
                    and observed["repo"]["id"] == actual.get("repo", {}).get("id")
                )
        if (
            pr.get("state") == "open"
            and pr.get("head", {}).get("sha") == run["head_sha"]
            and pr.get("head", {}).get("ref") == run["head_branch"]
            and pr.get("head", {}).get("repo", {}).get("id") == source_repository_id
            and pr.get("base", {}).get("repo", {}).get("id") == manual.CONTROL_ID
            and pr.get("base", {}).get("ref") == "main"
        ):
            candidates.append(pr)
    check(len(candidates) == 1)
    return candidates[0]


def parent_binding(
    public, run_id: int, attempt: int, *, checkout_sha: str | None = None
) -> dict:
    check(manual.positive(run_id) and manual.positive(attempt))
    run = public.get(
        f"/repos/{manual.CONTROL}/actions/runs/{run_id}/attempts/{attempt}"
    )
    workflow = public.get(
        f"/repos/{manual.CONTROL}/actions/workflows/{PARENT_WORKFLOW.rsplit('/', 1)[-1]}"
    )
    check(
        run.get("id") == run_id
        and run.get("run_attempt") == attempt
        and run.get("repository", {}).get("id") == manual.CONTROL_ID
        and run.get("path") == PARENT_WORKFLOW
        and workflow.get("path") == PARENT_WORKFLOW
        and manual.positive(workflow.get("id"))
        and run.get("workflow_id") == workflow["id"]
        and manual.is_sha(run.get("head_sha"))
        and isinstance(run.get("head_branch"), str)
        and run.get("status") in {"queued", "in_progress", "completed"}
        and run.get("conclusion") in {None, "success"}
    )
    main = current_main(public)
    source = run["head_sha"]
    event = run.get("event")
    pr_number = None
    base = main
    head_repository_id = manual.CONTROL_ID
    if event == "pull_request":
        pr = _pull_request(public, run)
        pr_number = pr["number"]
        base = pr["base"]["sha"]
        head_repository_id = pr["head"].get("repo", {}).get("id")
        check(
            manual.positive(head_repository_id)
            and base == main
            and pr["head"]["sha"] == source
            and manual.is_sha(pr.get("merge_commit_sha"))
        )
        # GitHub's run.head_sha is the PR source head, not the tested merge tree.
        tested = pr["merge_commit_sha"]
        commit = public.get(f"/repos/{manual.CONTROL}/git/commits/{tested}")
        parents = commit.get("parents")
        check(
            commit.get("sha") == tested
            and isinstance(parents, list)
            and len(parents) == 2
            and [row.get("sha") for row in parents] == [base, source]
        )
    elif event == "merge_group":
        check(run["head_branch"].startswith("gh-readonly-queue/main/"))
        ref = public.get(f"/repos/{manual.CONTROL}/git/ref/heads/{run['head_branch']}")
        check(
            ref.get("ref") == "refs/heads/" + run["head_branch"]
            and ref.get("object", {}).get("type") == "commit"
            and ref["object"].get("sha") == source
        )
        comparison = public.get(f"/repos/{manual.CONTROL}/compare/{main}...{source}")
        check(
            comparison.get("merge_base_commit", {}).get("sha") == main
            and comparison.get("status") in {"ahead", "identical"}
        )
        tested = source
    elif event in {"push", "schedule", "workflow_dispatch"}:
        check(run["head_branch"] == "main" and source == main)
        tested = source
    else:
        raise manual.AuditError("producer_untrusted")
    if checkout_sha is not None:
        check(manual.is_sha(checkout_sha) and checkout_sha == tested)
    return {
        "repository_id": manual.CONTROL_ID,
        "workflow_id": workflow["id"],
        "workflow": PARENT_WORKFLOW,
        "run_id": run_id,
        "run_attempt": attempt,
        "event": event,
        "source_head": source,
        "checkout_sha": tested,
        "base_sha": base,
        "protected_main_sha": main,
        "head_branch": run["head_branch"],
        "head_repository_id": head_repository_id,
        "pull_request": pr_number,
    }


def component_state(public, binding: dict) -> bool:
    listing = public.get(
        f"/repos/{manual.CONTROL}/actions/runs/{binding['run_id']}/attempts/"
        f"{binding['run_attempt']}/jobs?per_page=100"
    )
    check(
        type(listing.get("total_count")) is int
        and 0 <= listing["total_count"] < 100
        and isinstance(listing.get("jobs"), list)
        and len(listing["jobs"]) == listing["total_count"]
    )
    waiting = False
    for name in COMPONENT_JOBS:
        rows = [row for row in listing["jobs"] if row.get("name") == name]
        check(len(rows) <= 1)
        if not rows or rows[0].get("status") != "completed":
            waiting = True
        else:
            check(rows[0].get("conclusion") == "success")
    return not waiting


def wait_components(
    public,
    binding: dict,
    *,
    timeout: int = MAX_WAIT_SECONDS,
    sleep=time.sleep,
    monotonic=time.monotonic,
) -> None:
    check(type(timeout) is int and 0 < timeout <= MAX_WAIT_SECONDS)
    deadline = monotonic() + timeout
    while True:
        check(
            parent_binding(
                public,
                binding["run_id"],
                binding["run_attempt"],
                checkout_sha=binding["checkout_sha"],
            )
            == binding
        )
        if component_state(public, binding):
            return
        check(monotonic() < deadline)
        sleep(10)


def wait_verifier_ready(
    public,
    binding: dict,
    *,
    timeout: int = MAX_WAIT_SECONDS,
    sleep=time.sleep,
    monotonic=time.monotonic,
) -> None:
    """Do not age a private observation while the public verifier installs dependencies."""
    check(type(timeout) is int and 0 < timeout <= MAX_WAIT_SECONDS)
    deadline = monotonic() + timeout
    while True:
        check(
            parent_binding(
                public,
                binding["run_id"],
                binding["run_attempt"],
                checkout_sha=binding["checkout_sha"],
            )
            == binding
        )
        page = public.get(
            f'/repos/{manual.CONTROL}/actions/runs/{binding["run_id"]}/attempts/'
            f'{binding["run_attempt"]}/jobs?per_page=100'
        )
        check(
            type(page.get("total_count")) is int
            and 0 <= page["total_count"] < 100
            and isinstance(page.get("jobs"), list)
            and len(page["jobs"]) == page["total_count"]
        )
        jobs = [job for job in page["jobs"] if job.get("name") == "fleet-audit"]
        check(len(jobs) <= 1)
        if jobs:
            job = jobs[0]
            check(job.get("status") != "completed")
            steps = job.get("steps", [])
            check(isinstance(steps, list))
            ready = [
                step
                for step in steps
                if step.get("name")
                == "Verify exact full coverage or public-only bootstrap"
            ]
            check(len(ready) <= 1)
            if ready and ready[0].get("status") == "in_progress":
                return
        check(monotonic() < deadline)
        sleep(10)


def private_obligation(public, binding: dict, policy: dict) -> dict:
    """Bind candidate and protected authority bytes; only exact Scaleup is delegated."""
    manifests = {}
    required = False
    for label, ref in (
        ("candidate", binding["checkout_sha"]),
        ("protected", binding["protected_main_sha"]),
    ):
        raw = public_blob(public, MANIFEST_PATH, ref)
        manifest = manual.parse_manifest(raw)
        manifests[label] = manual.digest(raw)
        consumer = manifest.consumers.get("scaleupmech")
        if consumer is None:
            continue
        required = True
        check(
            consumer.github == manual.PRIVATE
            and consumer.package_path == "src/scaleupmech",
            "source_unverified",
        )
        rows = sorted(
            (
                {
                    "id": a.artifact_id,
                    "source": a.source,
                    "target": a.target.replace("{package_path}", consumer.package_path),
                    "sha256": a.sha256,
                    "mode": f"{a.mode:04o}",
                }
                for a in manifest.artifacts_for(consumer)
            ),
            key=lambda row: row["id"],
        )
        check(
            manifest.pin_path == policy["pin_path"] and rows == policy["artifacts"],
            "source_unverified",
        )
    return {
        "required": required,
        "manifest_sha256": manifests,
        "consumer": "scaleupmech" if required else None,
        "source_ref": policy["source_ref"] if required else None,
    }


def producer_context(public, environ: dict, binding: dict) -> dict:
    check(
        environ.get("GITHUB_REPOSITORY") == manual.CONTROL
        and environ.get("GITHUB_REF") == "refs/heads/main"
        and environ.get("GITHUB_EVENT_NAME") == "workflow_run"
        and environ.get("GITHUB_WORKFLOW_REF")
        == f"{manual.CONTROL}/{PRODUCER_WORKFLOW}@refs/heads/main"
        and environ.get("GITHUB_SHA")
        == current_main(public)
        == binding["protected_main_sha"]
    )
    try:
        run_id, attempt, app_id = (
            int(environ.get(name, ""))
            for name in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "SCALEUP_AUDIT_APP_ID")
        )
    except ValueError:
        raise manual.AuditError("configuration_missing") from None
    check(
        all(manual.positive(v) for v in (run_id, attempt, app_id)),
        "configuration_missing",
    )
    manual.environment_is_protected(public)
    run = public.get(
        f"/repos/{manual.CONTROL}/actions/runs/{run_id}/attempts/{attempt}"
    )
    check(
        run.get("id") == run_id
        and run.get("run_attempt") == attempt
        and run.get("event") == "workflow_run"
        and run.get("head_branch") == "main"
        and run.get("path") == PRODUCER_WORKFLOW
        and run.get("head_sha") == binding["protected_main_sha"]
        and run.get("repository", {}).get("id") == manual.CONTROL_ID
    )
    return {
        "sha": binding["protected_main_sha"],
        "run_id": run_id,
        "run_attempt": attempt,
        "workflow": PRODUCER_WORKFLOW,
        "app_id": app_id,
        "subject_head": binding["checkout_sha"],
    }


def produce(
    public,
    private,
    policy: dict,
    payloads: dict,
    binding: dict,
    context: dict,
    now: datetime,
    *,
    clock=lambda: datetime.now(timezone.utc),
) -> dict:
    check(component_state(public, binding))
    obligation = private_obligation(public, binding, policy)
    check(obligation["required"])
    value = manual.inspect(policy, private, payloads, context, now)
    manual.validate_receipt(
        canonical(value),
        policy,
        subject_head=binding["checkout_sha"],
        app_id=context["app_id"],
        now=now,
        expected_workflow=PRODUCER_WORKFLOW,
    )
    check(value["state"] != "invalid", "inspection_invalid")
    # A separate authenticated ref read follows all private object inspection.
    final_tip = private.get(f"/repos/{manual.PRIVATE}/git/ref/heads/main")
    checked_at = clock()
    check(
        final_tip.get("ref") == "refs/heads/main"
        and final_tip.get("object", {}).get("type") == "commit"
        and final_tip["object"].get("sha") == value["private_main_sha"],
        "private_main_changed",
    )
    check(
        parent_binding(
            public,
            binding["run_id"],
            binding["run_attempt"],
            checkout_sha=binding["checkout_sha"],
        )
        == binding
    )
    return {
        "version": 1,
        "scope": "automatic_scaleup_governance",
        "parent": binding,
        "obligation": obligation,
        "producer_workflow": PRODUCER_WORKFLOW,
        "private_receipt": value,
        "private_tip_recheck": {
            "sha": value["private_main_sha"],
            "checked_at": checked_at.isoformat(),
        },
    }


@dataclass(frozen=True)
class VerifiedPrivateEvidence:
    """Construct only after authenticating the completed protected workflow artifact."""

    receipt: dict
    parent: dict
    obligation: dict
    checked_at: datetime
    producer_run_id: int
    producer_attempt: int

    def fresh(self, now: datetime) -> None:
        check(
            timedelta(0) <= now - self.checked_at <= timedelta(seconds=MAX_FINAL_AGE),
            "receipt_expired",
        )


def validate_envelope(
    raw: bytes,
    policy: dict,
    binding: dict,
    obligation: dict,
    *,
    app_id: int,
    producer_run_id: int,
    producer_attempt: int,
    now: datetime,
) -> VerifiedPrivateEvidence:
    check(len(raw) <= 2 * manual.MAX_RECEIPT, "invalid_receipt")
    value = manual.parse_json(raw)
    check(
        isinstance(value, dict)
        and set(value)
        == {
            "version",
            "scope",
            "parent",
            "obligation",
            "producer_workflow",
            "private_receipt",
            "private_tip_recheck",
        }
        and type(value["version"]) is int
        and value["version"] == 1
        and value["scope"] == "automatic_scaleup_governance"
        and value["producer_workflow"] == PRODUCER_WORKFLOW
        and value["parent"] == binding
        and value["obligation"] == obligation,
        "invalid_receipt",
    )
    receipt = manual.validate_receipt(
        canonical(value["private_receipt"]),
        policy,
        subject_head=binding["checkout_sha"],
        app_id=app_id,
        now=now,
        expected_workflow=PRODUCER_WORKFLOW,
    )
    producer = receipt["producer"]
    check(
        producer["run_id"] == producer_run_id
        and producer["run_attempt"] == producer_attempt
        and producer["sha"] == binding["protected_main_sha"]
        and receipt["state"] != "invalid"
    )
    tip = value["private_tip_recheck"]
    check(
        isinstance(tip, dict)
        and set(tip) == {"sha", "checked_at"}
        and tip["sha"] == receipt["private_main_sha"],
        "invalid_receipt",
    )
    checked_at = manual.utc(tip["checked_at"])
    check(manual.utc(receipt["created_at"]) <= checked_at, "invalid_receipt")
    result = VerifiedPrivateEvidence(
        receipt, binding, obligation, checked_at, producer_run_id, producer_attempt
    )
    result.fresh(now)
    return result


def artifact_bytes(
    public, run_id: int, name: str, *, maximum: int = 2 * manual.MAX_RECEIPT
) -> tuple[bytes, dict]:
    listing = public.get(
        f"/repos/{manual.CONTROL}/actions/runs/{run_id}/artifacts?per_page=100"
    )
    check(
        type(listing.get("total_count")) is int
        and 0 <= listing["total_count"] < 100
        and isinstance(listing.get("artifacts"), list)
        and len(listing["artifacts"]) == listing["total_count"],
        "artifact_unverified",
    )
    matches = [row for row in listing["artifacts"] if row.get("name") == name]
    check(len(matches) == 1, "artifact_unverified")
    row = matches[0]
    check(
        manual.positive(row.get("id"))
        and row.get("expired") is False
        and isinstance(row.get("digest"), str)
        and re.fullmatch(r"sha256:[0-9a-f]{64}", row["digest"]) is not None,
        "artifact_unverified",
    )
    archive = public.request(
        f"/repos/{manual.CONTROL}/actions/artifacts/{row['id']}/zip", archive=True
    )
    check(manual.digest(archive) == row["digest"][7:], "artifact_unverified")
    try:
        with zipfile.ZipFile(io.BytesIO(archive)) as zipped:
            entries = zipped.infolist()
            check(
                len(entries) == 1
                and entries[0].filename == "receipt.json"
                and not entries[0].is_dir()
                and not entries[0].flag_bits & 1
                and 0 < entries[0].file_size <= maximum,
                "artifact_unverified",
            )
            with zipped.open(entries[0]) as stream:
                raw = stream.read(maximum + 1)
    except (OSError, ValueError, RuntimeError, zipfile.BadZipFile):
        raise manual.AuditError("artifact_unverified") from None
    check(len(raw) <= maximum, "artifact_unverified")
    return raw, row


def verify_producer(
    public,
    policy: dict,
    binding: dict,
    *,
    run_id: int,
    attempt: int,
    app_id: int,
    now: datetime,
    clock=lambda: datetime.now(timezone.utc),
) -> VerifiedPrivateEvidence:
    check(manual.positive(run_id) and manual.positive(attempt))
    check(
        parent_binding(
            public,
            binding["run_id"],
            binding["run_attempt"],
            checkout_sha=binding["checkout_sha"],
        )
        == binding
    )
    workflow = public.get(
        f"/repos/{manual.CONTROL}/actions/workflows/{PRODUCER_WORKFLOW.rsplit('/', 1)[-1]}"
    )
    run = public.get(
        f"/repos/{manual.CONTROL}/actions/runs/{run_id}/attempts/{attempt}"
    )
    check(
        workflow.get("path") == PRODUCER_WORKFLOW
        and manual.positive(workflow.get("id"))
        and run.get("workflow_id") == workflow["id"]
        and run.get("id") == run_id
        and run.get("run_attempt") == attempt
        and run.get("event") == "workflow_run"
        and run.get("path") == PRODUCER_WORKFLOW
        and run.get("head_branch") == "main"
        and run.get("head_sha") == current_main(public) == binding["protected_main_sha"]
        and run.get("repository", {}).get("id") == manual.CONTROL_ID
        and run.get("status") == "completed"
        and run.get("conclusion") == "success"
    )
    name = f"scaleup-automatic-{binding['run_id']}-{binding['run_attempt']}-{run_id}-{attempt}"
    raw, artifact = artifact_bytes(public, run_id, name)
    result = validate_envelope(
        raw,
        policy,
        binding,
        private_obligation(public, binding, policy),
        app_id=app_id,
        producer_run_id=run_id,
        producer_attempt=attempt,
        now=now,
    )
    start, end = manual.utc(run["run_started_at"]), manual.utc(run["updated_at"])
    check(
        start <= manual.utc(artifact["created_at"]) <= end
        and start <= result.checked_at <= end
    )
    check(
        parent_binding(
            public,
            binding["run_id"],
            binding["run_attempt"],
            checkout_sha=binding["checkout_sha"],
        )
        == binding
    )
    result.fresh(clock())
    return result
