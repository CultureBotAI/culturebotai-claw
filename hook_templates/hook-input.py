#!/usr/bin/env python3
# Managed by kg-microbe coordination hook installer.
"""Validate edit targets and classify Bash input for coordination hooks.

Exit codes are intentionally tri-state:

* 0: the event is relevant and targets this Claude project;
* 1: valid Bash input that does not invoke ``git commit``;
* 2: malformed, ambiguous, or out-of-project input.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
from pathlib import Path
from typing import Any

_ASSIGNMENT = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=(.*)", re.DOTALL)
_BOUNDARY_CHARS = frozenset(";&|(){}`\n")
_REDIRECTIONS = frozenset(
    {"<", ">", "<<", ">>", "<<<", "<>", ">|", "<&", ">&", "&>", "&>>"}
)
_RETARGETING_ENVIRONMENT = frozenset(
    {"GIT_COMMON_DIR", "GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE"}
)
_SHELLS = frozenset({"bash", "dash", "ksh", "sh", "zsh"})


class InputError(ValueError):
    """Raised when hook input cannot be classified safely."""


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InputError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> Any:
    raise InputError(f"non-standard JSON constant: {value}")


def _project_root() -> Path:
    value = os.environ.get("CLAUDE_PROJECT_DIR")
    if not value:
        raise InputError("CLAUDE_PROJECT_DIR is missing")
    return Path(value).resolve(strict=False)


def _event_cwd(payload: dict[str, Any]) -> Path:
    value = payload.get("cwd")
    if not isinstance(value, str) or not value:
        raise InputError("hook cwd is missing")
    return Path(value).resolve(strict=False)


def _is_within(path: Path, root: Path) -> bool:
    try:
        return os.path.commonpath((path, root)) == str(root)
    except ValueError:
        return False


def _validate_envelope(payload: Any, expected_event: str, tool: str) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise InputError("hook input must be a JSON object")
    if payload.get("hook_event_name") != expected_event:
        raise InputError("unexpected hook event")
    if payload.get("tool_name") != tool:
        raise InputError("unexpected hook tool")
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        raise InputError("tool_input must be a JSON object")
    return tool_input


def validate_edit(payload: Any, expected_event: str) -> int:
    if not isinstance(payload, dict):
        raise InputError("hook input must be a JSON object")
    tool = payload.get("tool_name")
    if tool not in {"Edit", "NotebookEdit", "Write"}:
        raise InputError("unexpected edit tool")
    tool_input = _validate_envelope(payload, expected_event, tool)
    path_key = "notebook_path" if tool == "NotebookEdit" else "file_path"
    value = tool_input.get(path_key)
    if not isinstance(value, str) or not value:
        raise InputError(f"{path_key} must be a non-empty string")

    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = _event_cwd(payload) / candidate
    resolved = candidate.resolve(strict=False)
    if not _is_within(resolved, _project_root()):
        raise InputError("edit target is outside CLAUDE_PROJECT_DIR")
    return 0


def _tokenize(command: str) -> list[list[str]]:
    lexer = shlex.shlex(
        command,
        posix=True,
        punctuation_chars=";&|(){}`<>\n",
    )
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    segments: list[list[str]] = []
    current: list[str] = []
    try:
        for token in lexer:
            if token and set(token) <= _BOUNDARY_CHARS:
                if current:
                    segments.append(current)
                    current = []
            else:
                current.append(token)
    except ValueError as error:
        raise InputError(f"cannot parse Bash command: {error}") from error
    if current:
        segments.append(current)
    return segments


def _assignment_name(token: str) -> str | None:
    match = _ASSIGNMENT.fullmatch(token)
    return match.group(1) if match else None


def _skip_env(tokens: list[str], index: int) -> tuple[int, bool]:
    index += 1
    retargeted = False
    while index < len(tokens):
        token = tokens[index]
        assignment = _assignment_name(token)
        if assignment is not None:
            retargeted |= assignment in _RETARGETING_ENVIRONMENT
            index += 1
        elif token in {"-i", "--ignore-environment"}:
            index += 1
        elif token in {"-u", "--unset", "-C", "--chdir"}:
            if index + 1 >= len(tokens):
                raise InputError("env option is missing its value")
            retargeted |= token in {"-C", "--chdir"}
            index += 2
        elif token.startswith("--unset="):
            index += 1
        elif token.startswith("--chdir="):
            retargeted = True
            index += 1
        elif token == "--":
            return index + 1, retargeted
        elif token.startswith("-"):
            raise InputError("unsupported env option before possible commit")
        else:
            return index, retargeted
    raise InputError("env command is missing its utility")


def _command_index(tokens: list[str]) -> tuple[int | None, bool]:
    index = 0
    retargeted = False
    while index < len(tokens):
        redirected = _consume_redirection(tokens, index)
        if redirected is not None:
            index = redirected
            continue
        assignment = _assignment_name(tokens[index])
        if assignment is None:
            break
        retargeted |= assignment in _RETARGETING_ENVIRONMENT
        index += 1

    while index < len(tokens) and tokens[index] in {
        "!",
        "do",
        "elif",
        "else",
        "if",
        "then",
        "until",
        "while",
    }:
        index += 1
    if index >= len(tokens):
        return None, retargeted

    if tokens[index] == "time":
        index += 1
        while index < len(tokens) and tokens[index] in {"-p", "--"}:
            index += 1
        if index >= len(tokens):
            return None, retargeted

    if tokens[index] == "command":
        index += 1
        while index < len(tokens) and tokens[index] == "-p":
            index += 1
        if index < len(tokens) and tokens[index] in {"-V", "-v"}:
            return None, retargeted
        if index < len(tokens) and tokens[index] == "--":
            index += 1
        elif index < len(tokens) and tokens[index].startswith("-"):
            raise InputError("unsupported command wrapper option")
    elif tokens[index] == "exec":
        index += 1
        while index < len(tokens) and tokens[index] == "-l":
            index += 1
        if index < len(tokens) and tokens[index] == "-c":
            index += 1
        elif index < len(tokens) and tokens[index] == "-a":
            if index + 1 >= len(tokens):
                raise InputError("exec option is missing its value")
            index += 2
        if index < len(tokens) and tokens[index] == "--":
            index += 1
        elif index < len(tokens) and tokens[index].startswith("-"):
            raise InputError("unsupported exec wrapper option")
    elif tokens[index] == "builtin":
        index += 1
    while index < len(tokens) and os.path.basename(tokens[index]) in {"nice", "nohup"}:
        wrapper = os.path.basename(tokens[index])
        index += 1
        if wrapper == "nice" and index < len(tokens) and tokens[index] == "-n":
            if index + 1 >= len(tokens):
                raise InputError("nice -n is missing its value")
            index += 2
        elif wrapper == "nice" and index < len(tokens) and tokens[index].startswith("-"):
            index += 1
        elif wrapper == "nohup" and index < len(tokens) and tokens[index] == "--":
            index += 1
    if index < len(tokens) and os.path.basename(tokens[index]) == "timeout":
        index += 1
        while index < len(tokens) and tokens[index].startswith("-"):
            option = tokens[index]
            index += 1
            if option in {"-k", "--kill-after", "-s", "--signal"}:
                if index >= len(tokens):
                    raise InputError("timeout option is missing its value")
                index += 1
        if index >= len(tokens):
            raise InputError("timeout is missing its duration")
        index += 1
    if index >= len(tokens):
        return None, retargeted
    if os.path.basename(tokens[index]) == "env":
        env_index, env_retargeted = _skip_env(tokens, index)
        return env_index, retargeted or env_retargeted
    return index, retargeted


def _consume_redirection(tokens: list[str], index: int) -> int | None:
    token = tokens[index]
    if token.isdigit() and index + 1 < len(tokens) and tokens[index + 1] in _REDIRECTIONS:
        index += 1
        token = tokens[index]
    if token not in _REDIRECTIONS:
        return None
    if index + 1 >= len(tokens):
        raise InputError("redirection is missing its target")
    return index + 2


def _resolve_cd(tokens: list[str], cwd: Path) -> Path | None:
    index, retargeted = _command_index(tokens)
    if index is not None and tokens[index] == "popd":
        raise InputError("cannot resolve popd before possible commit")
    if retargeted or index is None or tokens[index] not in {"cd", "pushd"}:
        return None
    arguments = tokens[index + 1 :]
    if (
        len(arguments) != 1
        or arguments[0] == "-"
        or any(character in arguments[0] for character in "$`~")
    ):
        raise InputError("cannot resolve shell directory change")
    target = Path(arguments[0])
    return (target if target.is_absolute() else cwd / target).resolve(strict=False)


def _shell_script(tokens: list[str], index: int) -> str | None:
    executable = os.path.basename(tokens[index])
    if executable in _SHELLS:
        arguments = tokens[index + 1 :]
        command_index = next(
            (
                option_index
                for option_index, option in enumerate(arguments)
                if option == "-c"
                or (option.startswith("-") and "c" in option[1:] and option != "--")
            ),
            None,
        )
        if command_index is None:
            return None
        if command_index + 1 >= len(arguments):
            raise InputError("shell -c is missing its command")
        return arguments[command_index + 1]
    if executable == "eval":
        return " ".join(tokens[index + 1 :])
    return None


def _git_commit_target(
    tokens: list[str], index: int, cwd: Path, retargeted: bool
) -> Path | None:
    if os.path.basename(tokens[index]) != "git":
        return None
    index += 1
    git_cwd = cwd
    while index < len(tokens):
        redirected = _consume_redirection(tokens, index)
        if redirected is not None:
            index = redirected
            continue
        token = tokens[index]
        if token == "--":
            index += 1
            break
        if token in {"--help", "--version", "-h", "-v"}:
            return None
        if token == "-C":
            if index + 1 >= len(tokens):
                raise InputError("git -C is missing its directory")
            target = Path(tokens[index + 1])
            if any(character in tokens[index + 1] for character in "$`~"):
                raise InputError("cannot resolve expanded git -C directory")
            git_cwd = (
                target if target.is_absolute() else git_cwd / target
            ).resolve(strict=False)
            index += 2
            continue
        if token.startswith("-C") and token != "-C":
            if any(character in token[2:] for character in "$`~"):
                raise InputError("cannot resolve expanded git -C directory")
            target = Path(token[2:])
            git_cwd = (
                target if target.is_absolute() else git_cwd / target
            ).resolve(strict=False)
            index += 1
            continue
        if token in {"-c", "--config-env", "--exec-path", "--namespace"}:
            if index + 1 >= len(tokens):
                raise InputError(f"{token} is missing its value")
            index += 2
            continue
        if token in {"--git-dir", "--work-tree"}:
            retargeted = True
            if index + 1 >= len(tokens):
                raise InputError(f"{token} is missing its value")
            index += 2
            continue
        if token.startswith(("--git-dir=", "--work-tree=")):
            retargeted = True
            index += 1
            continue
        if token.startswith(("-c", "--config-env=", "--exec-path=", "--namespace=")):
            index += 1
            continue
        if token.startswith("-"):
            index += 1
            continue
        break
    if index >= len(tokens) or tokens[index] != "commit":
        return None
    if retargeted:
        raise InputError("git environment/options can retarget commit outside the project")
    return git_cwd


def _persists_git_retargeting(tokens: list[str]) -> bool:
    """Detect shell state that can retarget a later git command."""
    assignments = [
        name
        for token in tokens
        if (name := _assignment_name(token)) is not None
    ]
    index, retargeted = _command_index(tokens)
    if retargeted and index is None:
        return True
    if index is None or index >= len(tokens):
        return False
    executable = tokens[index]
    if executable == "export":
        return any(name in _RETARGETING_ENVIRONMENT for name in assignments)
    if executable == "unset":
        return any(token in _RETARGETING_ENVIRONMENT for token in tokens[index + 1 :])
    return False


def _crosses_nested_git_boundary(path: Path, root: Path) -> bool:
    current = path
    while current != root:
        if os.path.lexists(current / ".git"):
            return True
        if current.parent == current:
            return True
        current = current.parent
    return False


def _classify_command(
    command: str,
    cwd: Path,
    root: Path,
    depth: int = 0,
    inherited_retargeting: bool = False,
) -> int:
    if depth > 4:
        raise InputError("nested shell command is too deep to classify")
    found_commit = False
    current_cwd = cwd
    persistent_retargeting = inherited_retargeting
    for tokens in _tokenize(command):
        persistent_retargeting |= _persists_git_retargeting(tokens)
        for token in tokens:
            marker = token.find("$(")
            if marker >= 0 and token.endswith(")"):
                nested_result = _classify_command(
                    token[marker + 2 : -1],
                    current_cwd,
                    root,
                    depth + 1,
                    persistent_retargeting,
                )
                if nested_result == 0:
                    found_commit = True
        changed_cwd = _resolve_cd(tokens, current_cwd)
        if changed_cwd is not None:
            current_cwd = changed_cwd
            continue

        index, retargeted = _command_index(tokens)
        if index is None or index >= len(tokens):
            continue
        nested = _shell_script(tokens, index)
        if nested is not None:
            nested_result = _classify_command(
                nested,
                current_cwd,
                root,
                depth + 1,
                retargeted or persistent_retargeting,
            )
            if nested_result == 0:
                found_commit = True
            continue

        commit_target = _git_commit_target(
            tokens, index, current_cwd, retargeted or persistent_retargeting
        )
        if commit_target is None:
            continue
        found_commit = True
        if not _is_within(commit_target.resolve(strict=False), root):
            raise InputError("git commit target is outside CLAUDE_PROJECT_DIR")
        if _crosses_nested_git_boundary(commit_target.resolve(strict=False), root):
            raise InputError("git commit target crosses a nested Git repository")
    return 0 if found_commit else 1


def classify_commit(payload: Any, expected_event: str) -> int:
    tool_input = _validate_envelope(payload, expected_event, "Bash")
    command = tool_input.get("command")
    if not isinstance(command, str):
        raise InputError("Bash command must be a string")
    root = _project_root()
    cwd = _event_cwd(payload)
    if any(name in os.environ for name in _RETARGETING_ENVIRONMENT):
        raise InputError("inherited Git environment can retarget commit")
    if not _is_within(cwd, root):
        raise InputError("Bash cwd is outside CLAUDE_PROJECT_DIR")
    return _classify_command(command, cwd, root)


def validate_bash(payload: Any, expected_event: str) -> int:
    tool_input = _validate_envelope(payload, expected_event, "Bash")
    if not isinstance(tool_input.get("command"), str):
        raise InputError("Bash command must be a string")
    if not _is_within(_event_cwd(payload), _project_root()):
        raise InputError("Bash cwd is outside CLAUDE_PROJECT_DIR")
    return 0


def main() -> int:
    if len(sys.argv) != 3:
        return 2
    operation, expected_event = sys.argv[1:]
    if operation not in {"bash", "commit", "edit"}:
        return 2
    try:
        payload = json.load(
            sys.stdin,
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_json_constant,
        )
        if operation == "edit":
            return validate_edit(payload, expected_event)
        if operation == "bash":
            return validate_bash(payload, expected_event)
        return classify_commit(payload, expected_event)
    except (InputError, json.JSONDecodeError, RecursionError, UnicodeDecodeError):
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
