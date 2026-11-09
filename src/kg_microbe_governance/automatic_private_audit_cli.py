"""Workflow entry points for protected automatic private receipts.

This module never executes candidate code. Errors use the closed manual audit
codes. The producer token and public verifier token have separate environments.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path

from . import automatic_private_audit as auto
from . import private_scaleup_audit as manual


def timestamp():
    return datetime.now(timezone.utc)


def integer(name: str) -> int:
    try:
        value = int(os.environ.get(name, ""))
    except ValueError:
        raise manual.AuditError("configuration_missing") from None
    auto.check(manual.positive(value), "configuration_missing")
    return value


def event_parent() -> tuple[int, int]:
    auto.check(os.environ.get("GITHUB_EVENT_NAME") == "workflow_run")
    event = manual.parse_json(Path(os.environ["GITHUB_EVENT_PATH"]).read_bytes())
    auto.check(isinstance(event, dict) and event.get("action") == "in_progress")
    run = event.get("workflow_run", {})
    auto.check(
        run.get("repository", {}).get("id") == manual.CONTROL_ID
        and manual.positive(run.get("id"))
        and manual.positive(run.get("run_attempt"))
    )
    return run["id"], run["run_attempt"]


def emit_output(name: str, value: str) -> None:
    auto.check(
        name in {"required_private", "parent_binding_sha256", "artifact_name"}
        and isinstance(value, str)
        and bool(value)
        and not any(c in value for c in "\r\n")
    )
    output = os.environ.get("GITHUB_OUTPUT")
    auto.check(bool(output), "configuration_missing")
    with Path(str(output)).open("a", encoding="utf-8") as stream:
        stream.write(name + "=" + value + "\n")


def append_receipt(path: Path, value: dict) -> None:
    auto.check(not path.exists(), "invalid_arguments")
    raw = auto.canonical(value) + b"\n"
    auto.check(len(raw) <= 2 * manual.MAX_RECEIPT, "invalid_receipt")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(raw)


def protected_runtime(public, root: Path) -> str:
    permitted = manual.trusted_producer_shas(root, public)
    auto.check(len(permitted) == 1)
    return next(iter(permitted))


def own_producer_run(public, main: str) -> None:
    auto.check(
        os.environ.get("GITHUB_REPOSITORY") == manual.CONTROL
        and os.environ.get("GITHUB_REF") == "refs/heads/main"
        and os.environ.get("GITHUB_EVENT_NAME") == "workflow_run"
        and os.environ.get("GITHUB_WORKFLOW_REF")
        == f"{manual.CONTROL}/{auto.PRODUCER_WORKFLOW}@refs/heads/main"
        and os.environ.get("GITHUB_SHA") == main
    )
    run_id, attempt = integer("GITHUB_RUN_ID"), integer("GITHUB_RUN_ATTEMPT")
    run = public.get(
        f"/repos/{manual.CONTROL}/actions/runs/{run_id}/attempts/{attempt}"
    )
    auto.check(
        run.get("id") == run_id
        and run.get("run_attempt") == attempt
        and run.get("repository", {}).get("id") == manual.CONTROL_ID
        and run.get("event") == "workflow_run"
        and run.get("head_branch") == "main"
        and run.get("path") == auto.PRODUCER_WORKFLOW
        and run.get("head_sha") == main
    )


def discover_receipt(
    public,
    binding: dict,
    policy: dict,
    app_id: int,
    *,
    timeout: int = auto.MAX_WAIT_SECONDS,
    clock=timestamp,
    sleep=time.sleep,
    monotonic=time.monotonic,
):
    auto.check(type(timeout) is int and 0 < timeout <= auto.MAX_WAIT_SECONDS)
    deadline = monotonic() + timeout
    title = f"Scaleup parent {binding['run_id']} attempt {binding['run_attempt']}"
    while True:
        auto.check(
            auto.parent_binding(
                public,
                binding["run_id"],
                binding["run_attempt"],
                checkout_sha=binding["checkout_sha"],
            )
            == binding
        )
        page = public.get(
            f"/repos/{manual.CONTROL}/actions/workflows/private-scaleup-automatic.yaml/"
            f"runs?event=workflow_run&branch=main&per_page={auto.MAX_RUNS}"
        )
        auto.check(
            isinstance(page.get("workflow_runs"), list)
            and len(page["workflow_runs"]) <= auto.MAX_RUNS
        )
        matches = [
            row
            for row in page["workflow_runs"]
            if row.get("display_title") == title
            and row.get("head_sha") == binding["protected_main_sha"]
        ]
        # Only the newest matching run can supply authority. A failed newest
        # attempt never falls back to an earlier successful receipt.
        if matches:
            auto.check(
                all(
                    manual.positive(row.get("id"))
                    and manual.positive(row.get("run_attempt"))
                    for row in matches
                )
            )
            latest = max(matches, key=lambda row: row["id"])
            if latest.get("status") == "completed":
                auto.check(latest.get("conclusion") == "success")
                return auto.verify_producer(
                    public,
                    policy,
                    binding,
                    run_id=latest["id"],
                    attempt=latest["run_attempt"],
                    app_id=app_id,
                    now=clock(),
                    clock=clock,
                )
        auto.check(monotonic() < deadline)
        sleep(10)


def main(argv=None) -> int:
    try:
        parser = manual.Parser(description=__doc__)
        parser.add_argument(
            "command", choices=("producer-preflight", "produce", "verify")
        )
        parser.add_argument("--trusted-root", type=Path, required=True)
        parser.add_argument("--output", type=Path)
        parser.add_argument("--expected-binding-sha256")
        parser.add_argument("--checkout-sha")
        parser.add_argument("--require-protected-environment", action="store_true")
        args = parser.parse_args(argv)
        public = manual.GitHubRead(os.environ.get("GH_PUBLIC_READ_TOKEN", ""))
        main_sha = protected_runtime(public, args.trusted_root)
        policy = manual.load_policy()
        if args.command in {"producer-preflight", "produce"}:
            own_producer_run(public, main_sha)
            parent, attempt = event_parent()
            binding = auto.parent_binding(public, parent, attempt)
            auto.check(binding["protected_main_sha"] == main_sha)
            obligation = auto.private_obligation(public, binding, policy)
            binding_sha = manual.digest(auto.canonical(binding))
            if args.command == "producer-preflight":
                if obligation["required"]:
                    auto.wait_components(public, binding)
                if args.require_protected_environment:
                    auto.check(
                        obligation["required"]
                        and manual.is_sha(args.expected_binding_sha256, 64)
                        and args.expected_binding_sha256 == binding_sha
                    )
                    auto.producer_context(public, dict(os.environ), binding)
                emit_output(
                    "required_private", "true" if obligation["required"] else "false"
                )
                emit_output("parent_binding_sha256", binding_sha)
                print("automatic_private_preflight_complete")
                return 0
            auto.check(
                manual.is_sha(args.expected_binding_sha256, 64)
                and args.expected_binding_sha256 == binding_sha
                and obligation["required"]
            )
            auto.check(auto.component_state(public, binding))
            context = auto.producer_context(public, dict(os.environ), binding)
            payloads = manual.authenticate_source(policy, manual.public_source)
            private = manual.GitHubRead(
                os.environ.get("SCALEUP_PRIVATE_READ_TOKEN", "")
            )
            value = auto.produce(
                public, private, policy, payloads, binding, context, timestamp()
            )
            auto.validate_envelope(
                auto.canonical(value),
                policy,
                binding,
                obligation,
                app_id=context["app_id"],
                producer_run_id=context["run_id"],
                producer_attempt=context["run_attempt"],
                now=timestamp(),
            )
            auto.check(args.output is not None, "invalid_arguments")
            append_receipt(args.output, value)
            emit_output(
                "artifact_name",
                f'scaleup-automatic-{parent}-{attempt}-{context["run_id"]}-{context["run_attempt"]}',
            )
            print("automatic_private_receipt_created")
            return 0
        parent, attempt = integer("GITHUB_RUN_ID"), integer("GITHUB_RUN_ATTEMPT")
        auto.check(manual.is_sha(args.checkout_sha))
        binding = auto.parent_binding(
            public, parent, attempt, checkout_sha=args.checkout_sha
        )
        auto.check(binding["protected_main_sha"] == main_sha)
        obligation = auto.private_obligation(public, binding, policy)
        auto.check(auto.component_state(public, binding))
        from .automatic_fleet_component import authenticate_report, finalize

        report = authenticate_report(public, args.trusted_root, binding)
        if obligation["required"]:
            evidence = discover_receipt(
                public, binding, policy, integer("SCALEUP_AUDIT_EXPECTED_APP_ID")
            )
            # The full-fleet adapter consumes this typed object in-process.
            finalize(public, args.trusted_root, binding, evidence, report=report)
            auto.check(
                auto.parent_binding(
                    public, parent, attempt, checkout_sha=args.checkout_sha
                )
                == binding
            )
            evidence.fresh(timestamp())
        else:
            finalize(public, args.trusted_root, binding, None, report=report)
            auto.check(
                auto.parent_binding(
                    public, parent, attempt, checkout_sha=args.checkout_sha
                )
                == binding
            )
        print("automatic_full_fleet_audit_passed")
        return 0
    except manual.AuditError as exc:
        print(exc.code, file=__import__("sys").stderr)
        return 2
    except Exception:
        print("unexpected_failure", file=__import__("sys").stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
