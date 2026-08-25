#!/usr/bin/env python3
"""Safely add the coordination hooks to a Claude Code project settings file."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit


class SettingsError(ValueError):
    """Raised when an existing settings target cannot be updated safely."""


# Claude Code only treats exit status 2 as a blocking PreToolUse result. The
# wrapper also converts shell failures such as a missing/non-executable script
# (126/127) into that blocking status. Paths come from Claude's project-root
# environment variable and are quoted; no target path is interpolated here.
_PRE_EDIT_COMMAND = (
    'if ! "$CLAUDE_PROJECT_DIR"/.claude/hooks/kg-microbe/pre-edit 1>&2; '
    "then exit 2; fi"
)
_PRE_COMMIT_COMMAND = (
    'if ! "$CLAUDE_PROJECT_DIR"/.claude/hooks/kg-microbe/pre-commit 1>&2; '
    "then exit 2; fi"
)
_PRE_BASH_COMMAND = (
    'if ! "$CLAUDE_PROJECT_DIR"/.claude/hooks/kg-microbe/pre-bash 1>&2; '
    "then exit 2; fi"
)

REGISTRATIONS: tuple[tuple[str, str, str], ...] = (
    ("PreToolUse", "Edit|Write|NotebookEdit", _PRE_EDIT_COMMAND),
    (
        "PostToolUse",
        "Edit|Write|NotebookEdit",
        '"$CLAUDE_PROJECT_DIR"/.claude/hooks/kg-microbe/post-edit',
    ),
    ("PreToolUse", "Bash", _PRE_BASH_COMMAND),
    ("PreToolUse", "Bash", _PRE_COMMIT_COMMAND),
    (
        "PostToolUse",
        "Bash",
        '"$CLAUDE_PROJECT_DIR"/.claude/hooks/kg-microbe/post-commit',
    ),
)

_PERMISSION_MODES = {
    "acceptEdits",
    "auto",
    "bypassPermissions",
    "default",
    "dontAsk",
    "manual",
    "plan",
}


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise SettingsError(f"duplicate JSON key: {key!r}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> Any:
    raise SettingsError(f"non-standard JSON constant: {value}")


def _read_settings(path: Path) -> tuple[dict[str, Any], os.stat_result | None]:
    """Read settings without following a symlink and retain its identity."""
    try:
        path_stat = path.lstat()
    except FileNotFoundError:
        return {}, None

    if stat.S_ISLNK(path_stat.st_mode):
        raise SettingsError(f"settings target must not be a symlink: {path}")
    if not stat.S_ISREG(path_stat.st_mode):
        raise SettingsError(f"settings target must be a regular file: {path}")

    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError as error:
        raise SettingsError(f"cannot safely open settings file {path}: {error}") from error

    try:
        opened_stat = os.fstat(descriptor)
        if not stat.S_ISREG(opened_stat.st_mode):
            raise SettingsError(f"settings target must be a regular file: {path}")
        if (opened_stat.st_dev, opened_stat.st_ino) != (
            path_stat.st_dev,
            path_stat.st_ino,
        ):
            raise SettingsError(f"settings target changed while opening it: {path}")
        with os.fdopen(descriptor, encoding="utf-8") as stream:
            descriptor = -1
            try:
                settings = json.load(
                    stream,
                    object_pairs_hook=_reject_duplicate_keys,
                    parse_constant=_reject_json_constant,
                )
            except (json.JSONDecodeError, RecursionError, UnicodeDecodeError) as error:
                raise SettingsError(f"malformed JSON in {path}: {error}") from error
    finally:
        if descriptor >= 0:
            os.close(descriptor)

    if not isinstance(settings, dict):
        raise SettingsError(f"settings document must be a JSON object: {path}")
    return settings, opened_stat


def _canonicalize_managed_registration(
    entries: list[Any], matcher: str, command: str
) -> tuple[bool, bool]:
    """Make every exact managed handler deterministic and synchronous.

    Claude Code treats ``async`` and ``asyncRewake`` handlers as background
    work, and fields such as ``if``, ``timeout``, ``args``, or ``shell`` can
    skip, terminate, or change execution. The exact managed command identifies
    an entry we own, so replace its complete handler object with the canonical
    two-field form. Duplicate managed handlers are removed after the first;
    unrelated groups and handlers are left byte-for-byte equivalent after JSON
    serialization.
    """
    canonical = {"type": "command", "command": command}
    found = False
    changed = False
    for entry in entries:
        if not isinstance(entry, dict) or entry.get("matcher") != matcher:
            continue
        handlers = entry.get("hooks")
        if not isinstance(handlers, list):
            continue
        retained: list[Any] = []
        for handler in handlers:
            is_managed = (
                isinstance(handler, dict)
                and handler.get("type") == "command"
                and handler.get("command") == command
            )
            if not is_managed:
                retained.append(handler)
                continue
            if not found:
                retained.append(canonical)
                found = True
                changed |= handler != canonical
            else:
                changed = True
        if retained != handlers:
            entry["hooks"] = retained
    return found, changed


def _validate_activation_settings(settings: dict[str, Any], path: Path) -> None:
    for field, consequence in (
        ("disableAllHooks", "leave registrations inactive"),
        ("allowManagedHooksOnly", "ignore project registrations"),
    ):
        value = settings.get(field, False)
        if not isinstance(value, bool):
            raise SettingsError(f"settings {field!r} value must be a boolean: {path}")
        if value:
            raise SettingsError(f"settings {field}=true would {consequence}: {path}")


def _validate_string_array(value: Any, context: str) -> None:
    if not isinstance(value, list) or any(
        not isinstance(item, str) for item in value
    ):
        raise SettingsError(f"{context} must be an array of strings")


def _validate_permissions(value: Any, path: Path) -> None:
    context = f"settings 'permissions' in {path}"
    if not isinstance(value, dict):
        raise SettingsError(f"{context} must be an object")
    for field in ("additionalDirectories", "allow", "ask", "deny"):
        if field in value:
            _validate_string_array(value[field], f"{context}.{field}")
    if "defaultMode" in value and value["defaultMode"] not in _PERMISSION_MODES:
        raise SettingsError(f"{context}.defaultMode is not a supported mode")
    if (
        "disableBypassPermissionsMode" in value
        and value["disableBypassPermissionsMode"] != "disable"
    ):
        raise SettingsError(
            f"{context}.disableBypassPermissionsMode must be 'disable'"
        )


def _validate_known_top_level_fields(settings: dict[str, Any], path: Path) -> None:
    for field in ("$schema", "effortLevel", "language", "model", "outputStyle", "theme"):
        if field in settings and not isinstance(settings[field], str):
            raise SettingsError(f"settings {field!r} value must be a string: {path}")
    for field in ("alwaysThinkingEnabled", "enableAllProjectMcpServers"):
        if field in settings and not isinstance(settings[field], bool):
            raise SettingsError(f"settings {field!r} value must be a boolean: {path}")
    for field in ("disabledMcpjsonServers", "enabledMcpjsonServers"):
        if field in settings:
            _validate_string_array(settings[field], f"settings {field!r} in {path}")
    if "env" in settings and (
        not isinstance(settings["env"], dict)
        or any(not isinstance(value, str) for value in settings["env"].values())
    ):
        raise SettingsError(f"settings 'env' must map strings to strings: {path}")
    if "enabledPlugins" in settings and (
        not isinstance(settings["enabledPlugins"], dict)
        or any(
            not isinstance(value, bool)
            for value in settings["enabledPlugins"].values()
        )
    ):
        raise SettingsError(f"settings 'enabledPlugins' must map strings to booleans: {path}")
    if "cleanupPeriodDays" in settings and (
        isinstance(settings["cleanupPeriodDays"], bool)
        or not isinstance(settings["cleanupPeriodDays"], int)
        or settings["cleanupPeriodDays"] < 1
    ):
        raise SettingsError(
            f"settings 'cleanupPeriodDays' must be a positive integer: {path}"
        )
    if "defaultMode" in settings and settings["defaultMode"] not in _PERMISSION_MODES:
        raise SettingsError(f"settings 'defaultMode' is not a supported mode: {path}")
    if "permissions" in settings:
        _validate_permissions(settings["permissions"], path)


def _require_string(handler: dict[str, Any], field: str, context: str) -> None:
    if not isinstance(handler.get(field), str):
        raise SettingsError(f"{context} requires string field {field!r}")


def _validate_optional_handler_fields(
    handler: dict[str, Any], hook_type: str, context: str
) -> None:
    string_fields = {"if", "statusMessage"}
    boolean_fields = {"once"}
    if hook_type == "command":
        string_fields.update({"rewakeMessage", "rewakeSummary"})
        boolean_fields.update({"async", "asyncRewake"})
    elif hook_type in {"agent", "prompt"}:
        string_fields.add("model")
        if hook_type == "prompt":
            boolean_fields.add("continueOnBlock")

    for field in string_fields:
        if field in handler and not isinstance(handler[field], str):
            raise SettingsError(f"{context} field {field!r} must be a string")
    for field in {"rewakeMessage", "rewakeSummary"} & string_fields:
        if field in handler and not handler[field]:
            raise SettingsError(f"{context} field {field!r} must not be empty")
    for field in boolean_fields:
        if field in handler and not isinstance(handler[field], bool):
            raise SettingsError(f"{context} field {field!r} must be a boolean")
    if "timeout" in handler and (
        isinstance(handler["timeout"], bool)
        or not isinstance(handler["timeout"], (int, float))
        or not math.isfinite(handler["timeout"])
        or handler["timeout"] <= 0
    ):
        raise SettingsError(f"{context} field 'timeout' must be a positive number")


def _validate_hook_handler(
    handler: dict[str, Any],
    *,
    event: str,
    matcher: str | None,
    index: int,
    path: Path,
    repair_managed: bool,
) -> None:
    context = f"settings hooks.{event} handler {index} in {path}"
    hook_type = handler.get("type")
    if hook_type not in {"agent", "command", "http", "mcp_tool", "prompt"}:
        raise SettingsError(f"{context} has an unsupported or missing hook type")
    if repair_managed and any(
        registered_event == event
        and registered_matcher == matcher
        and hook_type == "command"
        and handler.get("command") == registered_command
        for registered_event, registered_matcher, registered_command in REGISTRATIONS
    ):
        # The registration pass owns and replaces this complete handler object,
        # so even malformed enforcement options can be repaired safely.
        return
    _validate_optional_handler_fields(handler, hook_type, context)

    if hook_type == "command":
        _require_string(handler, "command", context)
        if "args" in handler and (
            not isinstance(handler["args"], list)
            or any(not isinstance(value, str) for value in handler["args"])
        ):
            raise SettingsError(f"{context} field 'args' must be an array of strings")
        if "shell" in handler and handler["shell"] not in {"bash", "powershell"}:
            raise SettingsError(
                f"{context} field 'shell' must be 'bash' or 'powershell'"
            )
    elif hook_type in {"agent", "prompt"}:
        _require_string(handler, "prompt", context)
    elif hook_type == "http":
        _require_string(handler, "url", context)
        parsed_url = urlsplit(handler["url"])
        if (
            not re.fullmatch(r"[A-Za-z][A-Za-z0-9+.-]*", parsed_url.scheme)
            or not (parsed_url.netloc or parsed_url.path)
            or any(character.isspace() for character in handler["url"])
        ):
            raise SettingsError(f"{context} field 'url' must be an absolute URL")
        if "headers" in handler and (
            not isinstance(handler["headers"], dict)
            or any(
                not isinstance(key, str) or not isinstance(value, str)
                for key, value in handler["headers"].items()
            )
        ):
            raise SettingsError(
                f"{context} field 'headers' must map strings to strings"
            )
        if "allowedEnvVars" in handler and (
            not isinstance(handler["allowedEnvVars"], list)
            or any(
                not isinstance(value, str) for value in handler["allowedEnvVars"]
            )
        ):
            raise SettingsError(
                f"{context} field 'allowedEnvVars' must be an array of strings"
            )
    else:
        _require_string(handler, "server", context)
        _require_string(handler, "tool", context)
        if "input" in handler and not isinstance(handler["input"], dict):
            raise SettingsError(f"{context} field 'input' must be an object")


def _validate_hooks_shape(
    settings: dict[str, Any], path: Path, *, repair_managed: bool = False
) -> None:
    if "hooks" not in settings:
        return
    hooks = settings["hooks"]
    if not isinstance(hooks, dict):
        raise SettingsError(f"settings 'hooks' value must be a JSON object: {path}")
    for event, entries in hooks.items():
        if not isinstance(entries, list):
            raise SettingsError(
                f"settings hooks.{event} value must be a JSON array: {path}"
            )
        for entry in entries:
            if not isinstance(entry, dict):
                raise SettingsError(
                    f"settings hooks.{event} entries must be JSON objects: {path}"
                )
            if "matcher" in entry and not isinstance(entry["matcher"], str):
                raise SettingsError(
                    f"settings hooks.{event} matcher values must be strings: {path}"
                )
            handlers = entry.get("hooks")
            if not isinstance(handlers, list):
                raise SettingsError(
                    "settings hooks."
                    f"{event} hook groups must contain a hooks array of objects: {path}"
                )
            for index, handler in enumerate(handlers):
                if not isinstance(handler, dict):
                    raise SettingsError(
                        "settings hooks."
                        f"{event} hook groups must contain a hooks array of objects: {path}"
                    )
                _validate_hook_handler(
                    handler,
                    event=event,
                    matcher=entry.get("matcher"),
                    index=index,
                    path=path,
                    repair_managed=repair_managed,
                )


def _validate_settings(
    settings: dict[str, Any], path: Path, *, repair_managed: bool = False
) -> None:
    _validate_known_top_level_fields(settings, path)
    _validate_activation_settings(settings, path)
    _validate_hooks_shape(settings, path, repair_managed=repair_managed)


def _write_doctor_settings(path: Path, settings: dict[str, Any]) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(settings, stream, ensure_ascii=True, allow_nan=False)
        stream.write("\n")


def _validate_with_claude_doctor(
    project_settings: dict[str, Any],
    local_settings: dict[str, Any],
    *,
    local_exists: bool,
) -> None:
    """Ask the installed Claude Code build to parse the prospective settings."""
    executable = shutil.which("claude")
    if executable is None:
        raise SettingsError(
            "Claude Code executable is required to validate its settings schema"
        )

    environment = os.environ.copy()
    environment.pop("CLAUDE_PROJECT_DIR", None)
    environment.update(
        {
            "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
            "DISABLE_AUTOUPDATER": "1",
            "DISABLE_TELEMETRY": "1",
            "DO_NOT_TRACK": "1",
        }
    )
    try:
        with tempfile.TemporaryDirectory(prefix="kg-microbe-claude-settings-") as root:
            claude_directory = Path(root) / ".claude"
            claude_directory.mkdir(mode=0o700)
            _write_doctor_settings(
                claude_directory / "settings.json", project_settings
            )
            if local_exists:
                _write_doctor_settings(
                    claude_directory / "settings.local.json", local_settings
                )
            result = subprocess.run(
                [executable, "doctor"],
                cwd=root,
                env=environment | {"PWD": root},
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise SettingsError(f"Claude Code settings validation failed: {error}") from error

    output = "\n".join((result.stdout, result.stderr))
    if result.returncode != 0:
        raise SettingsError(
            f"Claude Code doctor exited with status {result.returncode}"
        )
    if "Claude Code doctor" not in output or "Running:" not in output:
        raise SettingsError("Claude Code doctor returned unrecognized output")
    if re.search(r"(?m)^Invalid settings\s*$", output):
        raise SettingsError("Claude Code rejected the prospective settings document")


def _add_registrations(settings: dict[str, Any]) -> bool:
    if "hooks" not in settings:
        hooks = {}
        settings["hooks"] = hooks
    else:
        hooks = settings["hooks"]

    changed = False
    for event, matcher, command in REGISTRATIONS:
        if event not in hooks:
            entries = []
            hooks[event] = entries
        else:
            entries = hooks[event]
        if not isinstance(entries, list):
            raise SettingsError(f"settings hooks.{event} value must be a JSON array")

        found, normalized = _canonicalize_managed_registration(
            entries, matcher, command
        )
        changed |= normalized
        if found:
            continue
        entries.append(
            {
                "matcher": matcher,
                "hooks": [{"type": "command", "command": command}],
            }
        )
        changed = True
    return changed


def _same_file_state(path: Path, original: os.stat_result | None) -> bool:
    """Return whether the destination still has the state that was read."""
    try:
        current = path.lstat()
    except FileNotFoundError:
        return original is None

    if original is None or not stat.S_ISREG(current.st_mode):
        return False
    return (
        current.st_dev,
        current.st_ino,
        current.st_size,
        current.st_mtime_ns,
    ) == (
        original.st_dev,
        original.st_ino,
        original.st_size,
        original.st_mtime_ns,
    )


def _atomic_write(
    path: Path, settings: dict[str, Any], original: os.stat_result | None
) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".settings.json.", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        mode = stat.S_IMODE(original.st_mode) if original is not None else 0o600
        os.fchmod(descriptor, mode)
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            descriptor = -1
            json.dump(settings, stream, indent=2, ensure_ascii=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())

        # Do not silently replace a file created or changed by another process,
        # nor a symlink/non-regular object swapped in after the initial read.
        if not _same_file_state(path, original):
            raise SettingsError(f"settings target changed while updating it: {path}")
        os.replace(temporary, path)

        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _validate_settings_directory(path: Path, *, allow_missing: bool = False) -> bool:
    try:
        parent_stat = path.parent.lstat()
    except FileNotFoundError:
        if allow_missing:
            return False
        raise SettingsError(f"settings directory does not exist: {path.parent}") from None
    if stat.S_ISLNK(parent_stat.st_mode) or not stat.S_ISDIR(parent_stat.st_mode):
        raise SettingsError(f"settings directory must be a real directory: {path.parent}")
    return True


def preflight_hooks(path: Path) -> None:
    """Validate project/local settings without creating or modifying either."""
    if not _validate_settings_directory(path, allow_missing=True):
        return
    local_path = path.with_name("settings.local.json")
    project_settings, _ = _read_settings(path)
    local_settings, local_original = _read_settings(local_path)
    _validate_settings(project_settings, path, repair_managed=True)
    _validate_settings(local_settings, local_path)
    _add_registrations(project_settings)
    _validate_settings(project_settings, path)
    _validate_with_claude_doctor(
        project_settings,
        local_settings,
        local_exists=local_original is not None,
    )


def register_hooks(path: Path) -> bool:
    _validate_settings_directory(path)

    local_path = path.with_name("settings.local.json")
    local_settings, local_original = _read_settings(local_path)
    _validate_settings(local_settings, local_path)
    settings, original = _read_settings(path)
    _validate_settings(settings, path, repair_managed=True)
    changed = _add_registrations(settings)
    _validate_settings(settings, path)
    _validate_with_claude_doctor(
        settings,
        local_settings,
        local_exists=local_original is not None,
    )
    if not _same_file_state(local_path, local_original):
        raise SettingsError(f"local settings changed while registering hooks: {local_path}")
    if not changed:
        return False
    _atomic_write(path, settings, original)
    if not _same_file_state(local_path, local_original):
        raise SettingsError(f"local settings changed while registering hooks: {local_path}")
    return True


def resolve_workspace(orchestration_root: Path, configured: str) -> Path:
    root_stat = orchestration_root.lstat()
    if stat.S_ISLNK(root_stat.st_mode) or not stat.S_ISDIR(root_stat.st_mode):
        raise SettingsError("orchestration root must be a real directory")
    root = orchestration_root.resolve()
    workspace = Path(configured).expanduser()
    candidate = workspace if workspace.is_absolute() else root / workspace
    if candidate.is_symlink():
        raise SettingsError("coordination workspace must not be a symlink")
    resolved = candidate.resolve(strict=False)
    if not workspace.is_absolute():
        try:
            resolved.relative_to(root)
        except ValueError as error:
            raise SettingsError(
                "relative coordination workspace must stay within orchestration root"
            ) from error
    if candidate.exists() and not candidate.is_dir():
        raise SettingsError("coordination workspace must be a directory")
    return resolved


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("settings", type=Path, nargs="?")
    parser.add_argument(
        "--preflight",
        action="store_true",
        help="validate project/local settings without modifying them",
    )
    parser.add_argument(
        "--resolve-workspace",
        nargs=2,
        metavar=("ORCHESTRATION_ROOT", "CONFIGURED_WORKSPACE"),
    )
    arguments = parser.parse_args(argv)
    try:
        if arguments.resolve_workspace is not None:
            if arguments.preflight:
                parser.error("--preflight cannot be combined with --resolve-workspace")
            root, configured = arguments.resolve_workspace
            print(resolve_workspace(Path(root), configured))
            return 0
        if arguments.settings is None:
            parser.error("settings is required unless --resolve-workspace is used")
        if arguments.preflight:
            preflight_hooks(arguments.settings)
            print("ok")
            return 0
        changed = register_hooks(arguments.settings)
    except (OSError, SettingsError) as error:
        print(f"Cannot register Claude Code hooks: {error}", file=sys.stderr)
        return 1
    print("updated" if changed else "unchanged")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
