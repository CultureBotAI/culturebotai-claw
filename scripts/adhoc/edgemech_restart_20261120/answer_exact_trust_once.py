"""One explicitly authorized checkout-trust input; no general prompt answering.

Purpose/date/issue: parameterized successor to the private 2026-11-20 restart
helper, CultureBotAI/EdgeMech#228. Inputs: private authorization and exact binding
JSON, explicit tmux binary/socket, and fresh private receipt path. Outputs: an
exclusive consumed receipt before input and a separate actual command/readback
result. No retries, client creation, launch, goal operation, or continuation claim.
Historical source and receipts remain private; see README.md and PROVENANCE.json.
"""
from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def document(raw: bytes) -> dict:
    def unique(items):
        result = {}
        for key, value in items:
            require(key not in result, "Duplicate JSON key")
            result[key] = value
        return result
    value = json.loads(raw, object_pairs_hook=unique)
    require(isinstance(value, dict), "Expected a JSON object")
    return value


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def validate_authorization(authorization: dict, binding: dict) -> None:
    require(authorization.get("source") == "explicit_user_response", "Explicit user authorization required")
    require(authorization.get("action") == "Trust and continue", "Wrong authorized action")
    require(re.fullmatch(r"%[0-9]+", binding.get("pane", "")) is not None, "Invalid exact pane")
    for key in ("pane", "checkout"):
        require(authorization.get(key) == binding.get(key), "Authorization binding mismatch: " + key)
    require(Path(binding["checkout"]).is_absolute(), "Absolute checkout required")
    require(all(isinstance(binding.get(key), str) and binding[key] and "|" not in binding[key]
                and "\n" not in binding[key]
                for key in ("session_name", "pane_pid", "pane_tty", "checkout")),
            "Incomplete exact pane binding")
    require(binding["pane_pid"].isdigit(), "Invalid pane PID")
    if binding.get("control_client") is not None:
        require(isinstance(binding["control_client"], str) and bool(binding["control_client"]),
                "Invalid control client")
        require(authorization.get("control_client") == binding["control_client"],
                "Explicit control-client selection required")


def validate_screen(screen: str, binding: dict) -> None:
    # The whole visible panel must match. Historical trust text before another
    # current prompt is not authority, even when all familiar choices are present.
    expected = (
        "Folder access " + binding["checkout"] + " "
        "Trust this folder? Codex can read, edit, and run files here, subject to your "
        "permission settings. Folder settings can run code automatically, even "
        "without a model request. Continue only if you trust these files. Your trust "
        "decision will be saved. 1. Trust and continue 2. Back to Agent Command Center "
        "enter continue · esc back"
    )
    normalized = " ".join(screen.split()).replace("› 1. Trust and continue", "1. Trust and continue")
    require(normalized == expected, "Expected exact visible checkout trust panel")


def validate_live_binding(actual: str, binding: dict) -> None:
    expected = "|".join(binding[key] for key in ("session_name", "pane_pid", "pane_tty", "checkout"))
    require(actual.strip() == expected, "Live session/PID/TTY/checkout mismatch")


def answer(*, authorization_file: Path, binding_file: Path, receipt: Path,
           tmux_binary: Path, tmux_socket: Path, apply: bool = False) -> dict:
    require(apply, "Explicit --apply required; this helper never infers permission")
    require(tmux_binary.is_absolute() and tmux_socket.is_absolute(), "Absolute tmux paths required")
    require(receipt.is_absolute(), "Absolute private receipt path required")
    result_path = receipt.with_name(receipt.stem + ".result.json")
    require(not os.path.lexists(receipt) and not os.path.lexists(result_path), "Consumed or existing receipt; no retry")
    authorization_raw, binding_raw = authorization_file.read_bytes(), binding_file.read_bytes()
    authorization, binding = document(authorization_raw), document(binding_raw)
    require(authorization.get("binding_sha256") == digest(binding_raw), "Authorization binding digest mismatch")
    require(binding.get("tmux_socket") == str(tmux_socket)
            and binding.get("tmux_binary") == str(tmux_binary), "Authorized tmux transport mismatch")
    validate_authorization(authorization, binding)
    require(authorization.get("receipt") == str(receipt), "Authorization receipt binding mismatch")
    base = [str(tmux_binary), "-N", "-S", str(tmux_socket)]
    pane = binding["pane"]

    def capture() -> str:
        return subprocess.check_output(base + ["capture-pane", "-p", "-t", pane], text=True)

    screen = capture()
    validate_screen(screen, binding)
    actual = subprocess.check_output(
        base + ["display-message", "-p", "-t", pane,
                "#{session_name}|#{pane_pid}|#{pane_tty}|#{pane_current_path}"], text=True)
    validate_live_binding(actual, binding)
    require(authorization_file.read_bytes() == authorization_raw
            and binding_file.read_bytes() == binding_raw, "Authorization or binding changed")
    record = {
        "at": datetime.now(timezone.utc).isoformat(),
        "state": "ONE_SHOT_CONSUMED_BEFORE_INPUT",
        "helper_sha256": digest(Path(__file__).read_bytes()),
        "authorization_sha256": digest(authorization_raw),
        "binding_sha256": digest(binding_raw),
        "screen_sha256": digest(screen.encode()),
        "continuation_verified": False,
    }
    # Exclusive consumption precedes input. Failure or lost output never restores permission.
    with receipt.open("x") as stream:
        json.dump(record, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    directory = os.open(receipt.parent, os.O_RDONLY)
    try:
        try:
            os.fsync(directory)
        except OSError as error:
            if error.errno not in (errno.EINVAL, errno.ENOTSUP):
                raise
    finally:
        os.close(directory)
    command = base + ["send-keys"]
    if binding.get("control_client") is not None:
        command += ["-c", binding["control_client"]]
    command += ["-t", pane, "1", "Enter"]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    outcome = {
        "at": datetime.now(timezone.utc).isoformat(),
        "state": "INPUT_COMMAND_SUCCEEDED_CONTINUATION_UNPROVEN" if result.returncode == 0
                 else "INPUT_COMMAND_FAILED_NO_RETRY",
        "returncode": result.returncode,
        "stdout_sha256": digest(result.stdout.encode()),
        "stderr_sha256": digest(result.stderr.encode()),
        "consumed_receipt_sha256": digest(receipt.read_bytes()),
        "continuation_verified": False,
    }
    if result.returncode == 0:
        try:
            outcome["screen_after_sha256"] = digest(capture().encode())
        except subprocess.CalledProcessError as error:
            outcome["readback_error"] = type(error).__name__
    with result_path.open("x") as stream:
        json.dump(outcome, stream, indent=2)
        stream.write("\n")
    require(result.returncode == 0, "Input command failed after consumption; do not retry")
    return outcome


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("authorization-file", "binding-file", "receipt", "tmux-binary", "tmux-socket"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(answer(**vars(args)), indent=2))


if __name__ == "__main__":
    main()
