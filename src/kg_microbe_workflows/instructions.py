"""Append-only, bounded references for supervisor instructions.

This module writes only an instruction artifact. It never sends session input.
A received reference is not evidence that an agent read or executed its body.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
from pathlib import Path
from typing import Any

MAX_WIRE_BYTES = 512  # Defensive envelope budget, not a measured Terminal limit.
MAX_INSTRUCTION_BYTES = 65536
FORMAT = "immutable_instruction_v1"
ACTION_ID = re.compile(r"[a-zA-Z0-9_-]{1,64}\Z")


class InstructionError(ValueError):
    """A definite pre-input refusal; never authority to clear or retry a draft."""


def _text(value: Any, name: str) -> str:
    if (not isinstance(value, str) or not value
            or any(ord(char) < 32 or 127 <= ord(char) < 160 for char in value)):
        raise InstructionError(f"{name} must be nonempty and contain no control characters")
    return value


def _directory(path: Path, *, create_leaf: bool = False) -> int:
    """Walk using directory descriptors; no symlink component is followed."""
    if not path.is_absolute() or path.resolve() != path:
        raise InstructionError("instruction directory must be absolute and contain no symlink/escape")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    fd = os.open(path.anchor, flags)
    try:
        for index, component in enumerate(path.parts[1:]):
            if create_leaf and index == len(path.parts) - 2:
                try:
                    os.mkdir(component, mode=0o700, dir_fd=fd)
                    os.fsync(fd)
                except FileExistsError:
                    pass
            child = os.open(component, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _read(fd: int, name: str) -> bytes:
    handle = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
    with os.fdopen(handle, "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_INSTRUCTION_BYTES:
            raise InstructionError("instruction artifact must be a bounded regular file")
        return stream.read(MAX_INSTRUCTION_BYTES + 1)


def _publish(directory: Path, name: str, raw: bytes) -> None:
    # The session directory may be new; its existing parent is never created.
    session_fd = _directory(directory.parent, create_leaf=True)
    os.close(session_fd)
    fd = _directory(directory, create_leaf=True)
    temporary = "." + name + "." + secrets.token_hex(16) + ".tmp"
    try:
        try:
            existing = _read(fd, name)
        except FileNotFoundError:
            pass
        else:
            if existing != raw:
                raise InstructionError("immutable instruction artifact already has different bytes")
            return
        handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                         mode=0o600, dir_fd=fd)
        try:
            with os.fdopen(handle, "wb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            # Hard-link publication is atomic and cannot overwrite an existing name.
            try:
                os.link(temporary, name, src_dir_fd=fd, dst_dir_fd=fd, follow_symlinks=False)
            except FileExistsError:
                if _read(fd, name) != raw:
                    raise InstructionError("instruction artifact appeared with different bytes") from None
            os.fsync(fd)
        finally:
            os.unlink(temporary, dir_fd=fd)
            os.fsync(fd)
        if _read(fd, name) != raw:
            raise InstructionError("instruction artifact changed during publication")
    finally:
        os.close(fd)


def prepare_instruction(session: Path, context: dict, instruction: str) -> dict:
    """Publish the full task, returning only the bounded actual wire message.

    The artifact binds the workflow/objective to the reserved action. Its path
    and digest are part of native exact-input acceptance; receiving this short
    reference alone never proves file consumption or task completion.
    """
    identifier = _text(context.get("action_id"), "action ID")
    if not ACTION_ID.fullmatch(identifier):
        raise InstructionError("unsafe instruction action ID")
    _text(str(session), "instruction directory")
    if (not isinstance(instruction, str) or not instruction
            or any((ord(char) < 32 and char not in "\n\t") or 127 <= ord(char) < 160
                   for char in instruction)):
        raise InstructionError("instruction must be nonempty text without unsafe control characters")
    kind = context.get("kind")
    if kind not in {"start_goal", "finalize", "repair_closure", "assess_and_finalize", "policy_update"}:
        raise InstructionError("unsupported instruction kind")
    if not session.is_absolute() or session.resolve() != session:
        raise InstructionError("instruction directory must be absolute and contain no symlink/escape")
    path = session / "instructions" / (identifier + ".json")
    payload = {**context, "schema_version": "1.0.0", "delivery_format": FORMAT,
               "instruction": instruction,
               "execution_note": ("The native /goal was already established by this reference. "
                                  "Carry out the full objective below; do not replay its /goal prefix."
                                  if kind == "start_goal" else
                                  "Continue only the existing adopted goal; do not start or replay a goal.")}
    raw = (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n").encode()
    if len(raw) > MAX_INSTRUCTION_BYTES:
        raise InstructionError("instruction artifact exceeds its byte budget")
    checksum = hashlib.sha256(raw).hexdigest()
    prefix = "/goal " if kind == "start_goal" else ""
    wire = (f'{prefix}[MECH-WORKFLOW-{identifier}] Read {json.dumps(str(path), ensure_ascii=True)}. '
            f'Verify SHA-256 {checksum}, then follow its instruction. Stop if missing or mismatched.')
    _text(wire, "wire message")
    if len(wire.encode("utf-8")) > MAX_WIRE_BYTES:
        raise InstructionError("instruction reference exceeds its wire byte budget")
    _publish(path.parent, path.name, raw)
    artifact = {"path": str(path), "sha256": checksum, "bytes": len(raw)}
    verify_instruction(session, artifact)
    return {"delivery_format": FORMAT, "instruction_artifact": artifact,
            "message": wire, "message_sha256": hashlib.sha256(wire.encode()).hexdigest()}


def verify_instruction(session: Path, artifact: dict) -> None:
    """Recheck the referenced bytes before transport, without changing them."""
    path = Path(_text(artifact.get("path"), "instruction path"))
    if (path.parent != session / "instructions" or not path.name.endswith(".json")
            or not ACTION_ID.fullmatch(path.stem)):
        raise InstructionError("instruction reference escapes its session")
    fd = _directory(path.parent)
    try:
        raw = _read(fd, path.name)
    finally:
        os.close(fd)
    if len(raw) != artifact.get("bytes") or hashlib.sha256(raw).hexdigest() != artifact.get("sha256"):
        raise InstructionError("instruction artifact is missing or changed")
