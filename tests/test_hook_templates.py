"""Portability tests for installed coordination hook templates."""

import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from git import Repo

from kg_microbe_fleet import load_fleet_manifest


def _fake_fleet_cli(directory: Path, targets: list[Path]) -> Path:
    directory.mkdir(exist_ok=True)
    fake_uv = directory / "uv"
    fake_claude = directory / "claude"
    manifest = load_fleet_manifest()
    rows = []
    for key, target in zip(
        manifest.with_capability("coordination_hooks"), targets, strict=False
    ):
        mech = manifest.get(key)
        rows.append(
            "\t".join(
                (
                    key,
                    mech.display_name,
                    mech.github,
                    mech.environment_variable,
                    str(target),
                )
            )
        )
    fake_uv.write_text(
        "#!/bin/sh\n"
        "[ -z \"${FLEET_ARGS_LOG:-}\" ] || printf '%s\\n' \"$*\" > \"$FLEET_ARGS_LOG\"\n"
        "if [ -n \"${FLEET_REJECT_DOTENV:-}\" ]; then\n"
        "    case \" $* \" in *\" --dotenv \"*) exit 19 ;; esac\n"
        "fi\n"
        "printf '%b\\n' "
        + " ".join(repr(row) for row in rows)
        + "\n",
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)
    fake_claude.write_text(
        "#!/bin/sh\n"
        "[ \"${1:-}\" = doctor ] || exit 64\n"
        "[ -z \"${CLAUDE_PROJECT_DIR:-}\" ] || exit 65\n"
        "case \"${CLAUDE_DOCTOR_MODE:-valid}\" in\n"
        "  invalid) printf '%s\\n' 'Claude Code doctor' 'Running: test' "
        "'Invalid settings' '- prospective settings were rejected' ;;\n"
        "  failure) exit 23 ;;\n"
        "  unrecognized) echo 'unexpected output' ;;\n"
        "  *) printf '%s\\n' 'Claude Code doctor' 'Running: test' 'No problems found' ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    fake_claude.chmod(0o755)
    return directory


def _install_hooks(
    repository_root: Path,
    targets: list[Path],
    *,
    path_prefix: Path | None = None,
    workspace_root: Path | None = None,
    force: bool = False,
) -> subprocess.CompletedProcess[str]:
    manifest = load_fleet_manifest()
    environment = os.environ.copy()
    for mech in manifest.mechs.values():
        environment.pop(mech.environment_variable, None)
    for key, target in zip(
        manifest.with_capability("coordination_hooks"), targets, strict=False
    ):
        environment[manifest.get(key).environment_variable] = str(target)
    environment["OPENCLAW_WORKSPACE"] = str(
        workspace_root or targets[0].parent / ".coordination-workspace"
    )
    cli_bin = path_prefix or _fake_fleet_cli(
        targets[0].parent / ".fleet-cli-bin", targets
    )
    environment["PATH"] = f"{cli_bin}{os.pathsep}{environment['PATH']}"
    command = ["bash", str(repository_root / "scripts" / "install_hooks.sh")]
    if force:
        command.append("--force")
    return subprocess.run(
        command,
        cwd=repository_root,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )


def _hook_input(
    event: str, tool: str, command: str | None = None, *, cwd: Path
) -> str:
    if command is not None:
        tool_input = {"command": command}
    elif tool == "NotebookEdit":
        tool_input = {"notebook_path": "x.ipynb"}
    else:
        tool_input = {"file_path": "x.txt"}
    return json.dumps(
        {
            "hook_event_name": event,
            "tool_name": tool,
            "tool_input": tool_input,
            "cwd": str(cwd),
        }
    )


def _registered_command(
    settings: dict, event: str, matcher: str, hook_name: str
) -> str:
    matches = [
        handler["command"]
        for entry in settings["hooks"][event]
        if entry.get("matcher") == matcher
        for handler in entry.get("hooks", [])
        if handler.get("type") == "command"
        and f"/hooks/kg-microbe/{hook_name}" in handler.get("command", "")
    ]
    assert len(matches) == 1
    return matches[0]


def _installed_hook(target: Path, name: str) -> Path:
    return target / ".claude" / "hooks" / "kg-microbe" / name


def _run_hook_command(
    command: str,
    target: Path,
    hook_input: str,
    environment: dict[str, str],
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["/bin/sh", "-c", command],
        cwd=target,
        env=environment,
        input=hook_input,
        capture_output=True,
        text=True,
        check=False,
    )


def test_hook_installer_replaces_paths_and_uses_workspace_status(tmp_path):
    repository_root = Path(__file__).parents[1]
    targets = [
        tmp_path / key
        for key in load_fleet_manifest().with_capability("coordination_hooks")
    ]
    for target in targets:
        target.mkdir()
    workspace = tmp_path / "status-workspace"
    result = _install_hooks(repository_root, targets, workspace_root=workspace)

    assert result.returncode == 0, result.stderr
    post_edit = _installed_hook(targets[0], "post-edit").read_text()
    assert "{{ORCHESTRATION_ROOT}}" not in post_edit
    assert "{{WORKSPACE_ROOT}}" not in post_edit
    assert 'STATUS_DIR="$WORKSPACE/status"' in post_edit
    assert 'mkdir -p "$STATUS_DIR"' in post_edit
    assert all(_installed_hook(target, "pre-edit").is_file() for target in targets)


def test_hook_registration_preserves_settings_and_user_hooks_idempotently(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).parents[1]
    target = tmp_path / "configured"
    claude_dir = target / ".claude"
    claude_dir.mkdir(parents=True)
    initial = {
        "permissions": {"allow": ["Read"]},
        "theme": "dark",
        "includeCoAuthoredBy": False,
        "statusLine": {"type": "command", "command": "status-command"},
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": "Bash",
                    "futureGroupOption": {"enabled": True},
                    "hooks": [
                        {
                            "type": "command",
                            "command": "/opt/user-hooks/pre-bash",
                            "timeout": 7,
                            "futureHandlerOption": {"value": 1},
                        }
                    ],
                }
            ],
            "Notification": [
                {
                    "matcher": "",
                    "hooks": [{"type": "command", "command": "notify-user"}],
                }
            ],
        },
    }
    settings_file = claude_dir / "settings.json"
    settings_file.write_text(json.dumps(initial, indent=4) + "\n", encoding="utf-8")

    first = _install_hooks(repository_root, [target])
    assert first.returncode == 0, first.stderr
    first_bytes = settings_file.read_bytes()
    settings = json.loads(first_bytes)

    assert settings["permissions"] == initial["permissions"]
    assert settings["theme"] == "dark"
    assert settings["includeCoAuthoredBy"] is False
    assert settings["statusLine"] == initial["statusLine"]
    assert settings["hooks"]["Notification"] == initial["hooks"]["Notification"]
    assert settings["hooks"]["PreToolUse"][0] == initial["hooks"]["PreToolUse"][0]
    expected = (
        ("PreToolUse", "Edit|Write|NotebookEdit", "pre-edit"),
        ("PostToolUse", "Edit|Write|NotebookEdit", "post-edit"),
        ("PreToolUse", "Bash", "pre-bash"),
        ("PreToolUse", "Bash", "pre-commit"),
        ("PostToolUse", "Bash", "post-commit"),
    )
    for event, matcher, hook_name in expected:
        command = _registered_command(settings, event, matcher, hook_name)
        assert f"/hooks/kg-microbe/{hook_name}" in command
        assert str(target) not in command
        assert '"$CLAUDE_PROJECT_DIR"' in command
    assert "then exit 2" in _registered_command(
        settings, "PreToolUse", "Bash", "pre-commit"
    )

    second = _install_hooks(repository_root, [target])
    assert second.returncode == 0, second.stderr
    assert settings_file.read_bytes() == first_bytes
    assert not list(claude_dir.glob(".settings.json.*"))


def test_registrar_canonicalizes_all_managed_pre_handlers(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).parents[1]
    target = tmp_path / "configured"
    target.mkdir()
    first = _install_hooks(repository_root, [target])
    assert first.returncode == 0, first.stderr

    settings_file = target / ".claude" / "settings.json"
    settings = json.loads(settings_file.read_text(encoding="utf-8"))
    managed_pre = (
        ("Edit|Write|NotebookEdit", "pre-edit"),
        ("Bash", "pre-bash"),
        ("Bash", "pre-commit"),
    )
    commands: dict[str, str] = {}
    for matcher, hook_name in managed_pre:
        command = _registered_command(
            settings, "PreToolUse", matcher, hook_name
        )
        commands[hook_name] = command
        group = next(
            entry
            for entry in settings["hooks"]["PreToolUse"]
            if entry.get("matcher") == matcher
            and any(
                handler.get("command") == command
                for handler in entry.get("hooks", [])
            )
        )
        handler = next(
            handler
            for handler in group["hooks"]
            if handler.get("command") == command
        )
        handler.update(
            {
                "async": True,
                "asyncRewake": True,
                "timeout": 0.001,
                "args": ["--replace-command-form"],
                "shell": "powershell",
                "if": "false",
            }
        )
        # Mix malformed/asynchronous and already-canonical duplicates. The
        # registrar owns an exact managed command and must leave exactly one
        # synchronous two-field handler, regardless of ordering.
        group["hooks"].append(
            {
                "type": "command",
                "command": command,
                "async": "not-a-boolean",
            }
        )
        group["hooks"].append({"type": "command", "command": command})

    user_handler = {
        "type": "command",
        "command": "/opt/user-hooks/pre-bash",
        "async": True,
        "timeout": 0.001,
    }
    settings["hooks"]["PreToolUse"][0]["hooks"].append(user_handler)

    post_command = _registered_command(
        settings, "PostToolUse", "Bash", "post-commit"
    )
    post_group = next(
        entry
        for entry in settings["hooks"]["PostToolUse"]
        if entry.get("matcher") == "Bash"
    )
    post_handler = next(
        handler
        for handler in post_group["hooks"]
        if handler.get("command") == post_command
    )
    post_handler.update({"async": True, "asyncRewake": True, "timeout": 0.001})
    settings_file.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")

    registrar = repository_root / "scripts" / "register_claude_hooks.py"
    registrar_environment = os.environ.copy()
    registrar_environment["PATH"] = (
        f"{target.parent / '.fleet-cli-bin'}{os.pathsep}"
        f"{registrar_environment['PATH']}"
    )
    repaired = subprocess.run(
        [sys.executable, str(registrar), str(settings_file)],
        env=registrar_environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert repaired.returncode == 0, repaired.stderr
    assert repaired.stdout.strip() == "updated"
    repaired_settings = json.loads(settings_file.read_text(encoding="utf-8"))

    for matcher, hook_name in managed_pre:
        command = commands[hook_name]
        matches = [
            handler
            for entry in repaired_settings["hooks"]["PreToolUse"]
            if entry.get("matcher") == matcher
            for handler in entry.get("hooks", [])
            if handler.get("type") == "command"
            and handler.get("command") == command
        ]
        assert matches == [{"type": "command", "command": command}]

    assert user_handler in repaired_settings["hooks"]["PreToolUse"][0]["hooks"]
    repaired_post = [
        handler
        for entry in repaired_settings["hooks"]["PostToolUse"]
        if entry.get("matcher") == "Bash"
        for handler in entry.get("hooks", [])
        if handler.get("command") == post_command
    ]
    assert repaired_post == [{"type": "command", "command": post_command}]

    repaired_bytes = settings_file.read_bytes()
    unchanged = subprocess.run(
        [sys.executable, str(registrar), str(settings_file)],
        env=registrar_environment,
        capture_output=True,
        text=True,
        check=False,
    )
    assert unchanged.returncode == 0, unchanged.stderr
    assert unchanged.stdout.strip() == "unchanged"
    assert settings_file.read_bytes() == repaired_bytes


def test_installer_never_overwrites_or_registers_ambiguous_generic_hooks(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).parents[1]
    target = tmp_path / "configured"
    generic_hooks = target / ".claude" / "hooks"
    generic_hooks.mkdir(parents=True)
    old_or_custom = "#!/bin/sh\n# pre-namespace installer or user hook\nexit 0\n"
    for name in ("pre-edit", "post-edit", "pre-commit", "post-commit"):
        (generic_hooks / name).write_text(old_or_custom, encoding="utf-8")

    result = _install_hooks(repository_root, [target])
    assert result.returncode == 0, result.stderr
    settings = json.loads((target / ".claude" / "settings.json").read_text())

    for name in ("pre-edit", "post-edit", "pre-commit", "post-commit"):
        assert (generic_hooks / name).read_text(encoding="utf-8") == old_or_custom
        assert _installed_hook(target, name).is_file()
    registered = json.dumps(settings["hooks"])
    assert "/hooks/kg-microbe/" in registered
    assert '"/.claude/hooks/pre-edit' not in registered


def test_installer_refuses_different_namespaced_hook_without_force(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).parents[1]
    target = tmp_path / "configured"
    managed_hooks = target / ".claude" / "hooks" / "kg-microbe"
    managed_hooks.mkdir(parents=True)
    collision = managed_hooks / "pre-edit"
    collision.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")

    refused = _install_hooks(repository_root, [target])

    assert refused.returncode == 1
    assert "contains unowned content" in refused.stderr
    assert collision.read_text(encoding="utf-8") == "#!/bin/sh\nexit 0\n"
    assert not (target / ".claude" / "settings.json").exists()

    replaced = _install_hooks(repository_root, [target], force=True)
    assert replaced.returncode == 0, replaced.stderr
    assert collision.read_text(encoding="utf-8") != "#!/bin/sh\nexit 0\n"
    assert (target / ".claude" / "settings.json").is_file()


def test_installer_upgrades_marker_owned_namespaced_hook_without_force(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).parents[1]
    target = tmp_path / "configured"
    managed_hooks = target / ".claude" / "hooks" / "kg-microbe"
    managed_hooks.mkdir(parents=True)
    stale = managed_hooks / "pre-edit"
    stale.write_text(
        "#!/bin/sh\n"
        "# Managed by kg-microbe coordination hook installer.\n"
        "exit 0\n",
        encoding="utf-8",
    )

    result = _install_hooks(repository_root, [target])

    assert result.returncode == 0, result.stderr
    assert "Upgrading managed pre-edit" in result.stdout
    assert "hook-input.py" in stale.read_text(encoding="utf-8")
    assert (target / ".claude" / "settings.json").is_file()


@pytest.mark.parametrize(
    "raw_settings",
    [
        '{"permissions": ',
        '{"value": NaN}',
        '{"hooks": {}, "hooks": {}}',
        '["not", "an", "object"]',
        '{"hooks": []}',
        '{"hooks": null}',
        '{"hooks": {"PreToolUse": {}}}',
        '{"hooks": {"PreToolUse": null}}',
        '{"hooks": {"PreToolUse": ["not-a-group"]}}',
        '{"hooks": {"PostToolUse": [{"matcher": "Bash", "hooks": {}}]}}',
        '{"hooks":{"Notification":[{"matcher":"","hooks":[{}]}]}}',
        '{"hooks":{"PreToolUse":[{"matcher":"Bash","hooks":'
        '[{"type":"command"}]}]}}',
        '{"hooks":{"PreToolUse":[{"matcher":"Bash","hooks":'
        '[{"type":"command","command":7}]}]}}',
        '{"hooks":{"PreToolUse":[{"matcher":"Bash","hooks":'
        '[{"type":"command","command":"check","async":"yes"}]}]}}',
        '{"hooks":{"PreToolUse":[{"matcher":"Bash","hooks":'
        '[{"type":"command","command":"check","args":[1]}]}]}}',
        '{"hooks":{"PreToolUse":[{"matcher":"Bash","hooks":'
        '[{"type":"prompt","prompt":[]}]}]}}',
        '{"hooks":{"PreToolUse":[{"matcher":"Bash","hooks":'
        '[{"type":"mystery","command":"check"}]}]}}',
        '{"hooks":{"PreToolUse":[{"matcher":"Bash","hooks":'
        '[{"type":"mcp_tool","server":"server"}]}]}}',
        '{"hooks":{"PreToolUse":[{"matcher":"Bash","hooks":'
        '[{"type":"mcp_tool","server":"server","tool":"check",'
        '"input":[]}]}]}}',
        '{"hooks":{"PreToolUse":[{"matcher":"Bash","hooks":'
        '[{"type":"http","url":"not a URL"}]}]}}',
        '{"hooks":{"PreToolUse":[{"matcher":"Bash","hooks":'
        '[{"type":"command","command":"check","timeout":1e999}]}]}}',
        '{"hooks":{"PreToolUse":[{"matcher":"Bash","hooks":'
        '[{"type":"command","command":"check","rewakeMessage":""}]}]}}',
        '{"permissions":"bad"}',
        '{"permissions":{"allow":[7]}}',
        '{"enabledPlugins":{"example@marketplace":"yes"}}',
        '{"disableAllHooks": true}',
        '{"disableAllHooks": "true"}',
        '{"allowManagedHooksOnly": true}',
        '{"allowManagedHooksOnly": 1}',
    ],
    ids=(
        "malformed-json",
        "non-standard-number",
        "duplicate-key",
        "non-object-document",
        "non-object-hooks",
        "null-hooks",
        "non-array-event",
        "null-event",
        "non-object-group",
        "non-array-handlers",
        "missing-handler-type",
        "missing-command",
        "non-string-command",
        "non-boolean-async",
        "non-string-args",
        "non-string-prompt",
        "unknown-handler-type",
        "incomplete-mcp-handler",
        "non-object-mcp-input",
        "invalid-http-url",
        "non-finite-timeout",
        "empty-rewake-message",
        "non-object-permissions",
        "non-string-permission-rule",
        "non-boolean-plugin-toggle",
        "hooks-disabled",
        "hooks-disabled-non-boolean",
        "managed-hooks-only",
        "managed-hooks-only-non-boolean",
    ),
)
def test_hook_registration_fails_closed_without_rewriting_bad_settings(
    tmp_path: Path, raw_settings: str
) -> None:
    repository_root = Path(__file__).parents[1]
    target = tmp_path / "configured"
    claude_dir = target / ".claude"
    claude_dir.mkdir(parents=True)
    settings_file = claude_dir / "settings.json"
    settings_file.write_text(raw_settings, encoding="utf-8")

    result = _install_hooks(repository_root, [target])

    assert result.returncode == 1
    assert "Cannot register Claude Code hooks" in result.stderr
    assert settings_file.read_text(encoding="utf-8") == raw_settings
    assert not list(claude_dir.glob(".settings.json.*"))


def test_hook_registration_preserves_valid_local_settings(tmp_path: Path) -> None:
    repository_root = Path(__file__).parents[1]
    target = tmp_path / "configured"
    claude_dir = target / ".claude"
    claude_dir.mkdir(parents=True)
    local_settings = claude_dir / "settings.local.json"
    local_bytes = (
        b'{"permissions":{"allow":["Read"]},"hooks":{"Notification":'
        b'[{"matcher":"","hooks":[{"type":"command","command":"notify"}]}]}}\n'
    )
    local_settings.write_bytes(local_bytes)

    result = _install_hooks(repository_root, [target])

    assert result.returncode == 0, result.stderr
    assert local_settings.read_bytes() == local_bytes
    assert (claude_dir / "settings.json").is_file()


@pytest.mark.parametrize(
    "raw_local_settings",
    [
        '{"permissions":',
        '{"value": Infinity}',
        '{"hooks": {}, "hooks": {}}',
        '[]',
        '{"hooks": []}',
        '{"permissions":"bad"}',
        '{"disableAllHooks": true}',
        '{"disableAllHooks": "yes"}',
        '{"allowManagedHooksOnly": true}',
        '{"allowManagedHooksOnly": null}',
    ],
    ids=(
        "malformed-json",
        "non-standard-number",
        "duplicate-key",
        "non-object-document",
        "invalid-hooks-shape",
        "invalid-permissions-shape",
        "hooks-disabled",
        "hooks-disabled-non-boolean",
        "managed-hooks-only",
        "managed-hooks-only-non-boolean",
    ),
)
def test_installer_fails_before_hook_install_for_unsafe_local_settings(
    tmp_path: Path, raw_local_settings: str
) -> None:
    repository_root = Path(__file__).parents[1]
    target = tmp_path / "configured"
    claude_dir = target / ".claude"
    claude_dir.mkdir(parents=True)
    project_settings = claude_dir / "settings.json"
    project_bytes = b'{"permissions":{"allow":["Read"]}}\n'
    project_settings.write_bytes(project_bytes)
    local_settings = claude_dir / "settings.local.json"
    local_settings.write_text(raw_local_settings, encoding="utf-8")

    result = _install_hooks(repository_root, [target])

    assert result.returncode == 1
    assert "Cannot safely activate hooks" in result.stderr
    assert local_settings.read_text(encoding="utf-8") == raw_local_settings
    assert project_settings.read_bytes() == project_bytes
    assert not _installed_hook(target, "pre-edit").exists()


@pytest.mark.parametrize("local_kind", ["symlink", "directory"])
def test_installer_rejects_unsafe_local_settings_target(
    tmp_path: Path, local_kind: str
) -> None:
    repository_root = Path(__file__).parents[1]
    target = tmp_path / "configured"
    claude_dir = target / ".claude"
    claude_dir.mkdir(parents=True)
    local_settings = claude_dir / "settings.local.json"
    outside = tmp_path / "outside-local-settings.json"
    outside.write_text('{"leave":"unchanged"}\n', encoding="utf-8")
    if local_kind == "symlink":
        local_settings.symlink_to(outside)
    else:
        local_settings.mkdir()

    result = _install_hooks(repository_root, [target])

    assert result.returncode == 1
    assert "Cannot safely activate hooks" in result.stderr
    assert outside.read_text(encoding="utf-8") == '{"leave":"unchanged"}\n'
    assert not _installed_hook(target, "pre-edit").exists()


@pytest.mark.parametrize(
    "doctor_mode, expected_error",
    [
        ("invalid", "rejected the prospective settings"),
        ("failure", "exited with status 23"),
        ("unrecognized", "returned unrecognized output"),
    ],
)
def test_installer_fails_before_hook_install_when_claude_doctor_cannot_validate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    doctor_mode: str,
    expected_error: str,
) -> None:
    repository_root = Path(__file__).parents[1]
    target = tmp_path / "configured"
    target.mkdir()
    monkeypatch.setenv("CLAUDE_DOCTOR_MODE", doctor_mode)
    monkeypatch.setenv("CLAUDE_PROJECT_DIR", str(tmp_path / "hostile-project"))

    result = _install_hooks(repository_root, [target])

    assert result.returncode == 1
    assert expected_error in result.stderr
    assert "Cannot safely activate hooks" in result.stderr
    assert not _installed_hook(target, "pre-edit").exists()


def test_retired_coordination_proposal_cannot_compete_with_supported_guide() -> None:
    root = Path(__file__).parents[1]
    index = (root / "docs" / "guides" / "README.md").read_text(encoding="utf-8")
    retired = (
        root / "docs" / "guides" / "MULTI_CLAUDE_ARCHITECTURE.md"
    ).read_text(encoding="utf-8")
    autonomous = (root / "docs" / "AUTONOMOUS_LOOPS.md").read_text(
        encoding="utf-8"
    )
    autonomous_words = " ".join(autonomous.split())

    assert "a retired proposal" in index
    assert retired.startswith("# Retired multi-Claude architecture proposal")
    assert "MULTI_CLAUDE_COORDINATION.md" in retired
    assert "must not be used" in retired
    assert "release it before a hook-bearing worker edits or commits" in retired
    assert "workspace/tasks/curation_batch" not in retired
    assert "same-machine, bounded coordination" in autonomous_words
    assert "use GitHub objects as the authority" in autonomous_words
    assert "system that does not run" not in autonomous_words
    assert "retire the file-based protocol" not in autonomous_words


@pytest.mark.parametrize("target_kind", ["symlink", "directory"])
def test_hook_registration_rejects_unsafe_settings_target(
    tmp_path: Path, target_kind: str
) -> None:
    repository_root = Path(__file__).parents[1]
    target = tmp_path / "configured"
    claude_dir = target / ".claude"
    claude_dir.mkdir(parents=True)
    settings_file = claude_dir / "settings.json"
    outside = tmp_path / "outside-settings.json"
    outside.write_text('{"leave": "unchanged"}\n', encoding="utf-8")
    if target_kind == "symlink":
        settings_file.symlink_to(outside)
    else:
        settings_file.mkdir()

    result = _install_hooks(repository_root, [target])

    assert result.returncode == 1
    assert "settings target must" in result.stderr
    assert outside.read_text(encoding="utf-8") == '{"leave": "unchanged"}\n'


@pytest.mark.parametrize("workspace_kind", ["traversal", "symlink", "file"])
def test_installer_rejects_unsafe_coordination_workspace(
    tmp_path: Path, workspace_kind: str
) -> None:
    repository_root = Path(__file__).parents[1]
    target = tmp_path / "configured"
    target.mkdir()
    if workspace_kind == "traversal":
        workspace = Path("../outside-orchestration")
    elif workspace_kind == "symlink":
        real_workspace = tmp_path / "real-workspace"
        real_workspace.mkdir()
        workspace = tmp_path / "workspace-link"
        workspace.symlink_to(real_workspace, target_is_directory=True)
    else:
        workspace = tmp_path / "workspace-file"
        workspace.write_text("not a directory", encoding="utf-8")

    result = _install_hooks(repository_root, [target], workspace_root=workspace)

    assert result.returncode == 1
    assert "coordination workspace" in result.stderr
    assert not (target / ".claude").exists()


def test_registered_commands_execute_with_claude_exit_and_status_semantics(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).parents[1]
    target = tmp_path / "configured"
    target.mkdir()
    workspace = tmp_path / "trusted-workspace"
    result = _install_hooks(repository_root, [target], workspace_root=workspace)
    assert result.returncode == 0, result.stderr
    settings = json.loads((target / ".claude" / "settings.json").read_text())

    repo = Repo.init(target)
    (target / "record.txt").write_text("content\n", encoding="utf-8")
    repo.index.add(["record.txt"])
    repo.index.commit("registered hook test")

    fake_bin = tmp_path / "runtime-bin"
    fake_bin.mkdir()
    hook_log = tmp_path / "lock-checks.log"
    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        "#!/bin/sh\n"
        'printf \'%s\\n\' "$*" >> "$HOOK_LOG"\n'
        'exit "${HOOK_UV_EXIT:-0}"\n',
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)
    hostile_workspace = tmp_path / "runtime-workspace-override"
    environment = os.environ.copy()
    environment["CLAUDE_PROJECT_DIR"] = str(target)
    environment["OPENCLAW_WORKSPACE"] = str(hostile_workspace)
    environment["HOOK_LOG"] = str(hook_log)
    environment["PATH"] = f"{fake_bin}{os.pathsep}{environment['PATH']}"
    for name in ("GIT_COMMON_DIR", "GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE"):
        environment.pop(name, None)

    pre_edit = _registered_command(
        settings, "PreToolUse", "Edit|Write|NotebookEdit", "pre-edit"
    )
    post_edit = _registered_command(
        settings, "PostToolUse", "Edit|Write|NotebookEdit", "post-edit"
    )
    pre_bash = _registered_command(settings, "PreToolUse", "Bash", "pre-bash")
    pre_commit = _registered_command(
        settings, "PreToolUse", "Bash", "pre-commit"
    )
    post_commit = _registered_command(
        settings, "PostToolUse", "Bash", "post-commit"
    )

    for tool in ("Edit", "Write", "NotebookEdit"):
        execution = _run_hook_command(
            pre_edit,
            target,
            _hook_input("PreToolUse", tool, cwd=target),
            environment,
        )
        assert execution.returncode == 0, execution.stderr

    edit_status = _run_hook_command(
        post_edit,
        target,
        _hook_input("PostToolUse", "NotebookEdit", cwd=target),
        environment,
    )
    assert edit_status.returncode == 0, edit_status.stderr
    status_file = workspace / "status" / f"{load_fleet_manifest().keys[0]}_claude_status.yaml"
    status = yaml.safe_load(status_file.read_text(encoding="utf-8"))
    assert status["status"] == "idle"
    assert status["last_completed_operation"]["type"] == "edit"
    assert not hostile_workspace.exists()

    ordinary_input = _hook_input(
        "PreToolUse", "Bash", "printf '%s' 'git commit'", cwd=target
    )
    ordinary_guard = _run_hook_command(pre_bash, target, ordinary_input, environment)
    assert ordinary_guard.returncode == 0, ordinary_guard.stderr
    checks_after_guard = hook_log.read_text(encoding="utf-8").splitlines()
    ordinary_commit_filter = _run_hook_command(
        pre_commit, target, ordinary_input, environment
    )
    assert ordinary_commit_filter.returncode == 0, ordinary_commit_filter.stderr
    assert hook_log.read_text(encoding="utf-8").splitlines() == checks_after_guard

    status_before_noncommit = status_file.read_bytes()
    noncommit_post = _run_hook_command(
        post_commit,
        target,
        _hook_input("PostToolUse", "Bash", "git status", cwd=target),
        environment,
    )
    assert noncommit_post.returncode == 0, noncommit_post.stderr
    assert status_file.read_bytes() == status_before_noncommit

    commit_pre = _run_hook_command(
        pre_commit,
        target,
        _hook_input(
            "PreToolUse", "Bash", "git >/dev/null commit --dry-run", cwd=target
        ),
        environment,
    )
    assert commit_pre.returncode == 0, commit_pre.stderr
    assert len(hook_log.read_text(encoding="utf-8").splitlines()) == len(
        checks_after_guard
    ) + 1

    commit_post = _run_hook_command(
        post_commit,
        target,
        _hook_input("PostToolUse", "Bash", "git commit -m test", cwd=target),
        environment,
    )
    assert commit_post.returncode == 0, commit_post.stderr
    status = yaml.safe_load(status_file.read_text(encoding="utf-8"))
    assert status["last_completed_operation"]["type"] == "commit"

    blocked_environment = environment | {"HOOK_UV_EXIT": "1"}
    blocked = _run_hook_command(pre_bash, target, ordinary_input, blocked_environment)
    assert blocked.returncode == 2
    assert "blocked" in blocked.stderr.lower()

    missing_project = tmp_path / "missing-hook-project"
    missing_project.mkdir()
    missing_environment = environment | {"CLAUDE_PROJECT_DIR": str(missing_project)}
    missing = _run_hook_command(
        pre_bash, target, ordinary_input, missing_environment
    )
    assert missing.returncode == 2


def test_pre_hooks_block_malformed_and_out_of_project_targets(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).parents[1]
    target = tmp_path / "configured"
    sibling = tmp_path / "sibling"
    target.mkdir()
    sibling.mkdir()
    nested = target / "nested-repo"
    Repo.init(nested)
    result = _install_hooks(repository_root, [target])
    assert result.returncode == 0, result.stderr
    settings = json.loads((target / ".claude" / "settings.json").read_text())
    pre_edit = _registered_command(
        settings, "PreToolUse", "Edit|Write|NotebookEdit", "pre-edit"
    )
    pre_commit = _registered_command(
        settings, "PreToolUse", "Bash", "pre-commit"
    )
    pre_bash = _registered_command(settings, "PreToolUse", "Bash", "pre-bash")

    fake_bin = tmp_path / "target-check-bin"
    fake_bin.mkdir()
    hook_log = tmp_path / "unexpected-lock-check.log"
    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        "#!/bin/sh\n"
        'printf called >> "$HOOK_LOG"\n'
        "exit 0\n",
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)
    environment = os.environ.copy()
    environment["CLAUDE_PROJECT_DIR"] = str(target)
    environment["HOOK_LOG"] = str(hook_log)
    environment["PATH"] = f"{fake_bin}{os.pathsep}{environment['PATH']}"
    for name in ("GIT_COMMON_DIR", "GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE"):
        environment.pop(name, None)

    outside_edit = json.loads(_hook_input("PreToolUse", "Edit", cwd=target))
    outside_edit["tool_input"]["file_path"] = str(sibling / "guarded.yaml")
    edit_result = _run_hook_command(
        pre_edit, target, json.dumps(outside_edit), environment
    )
    assert edit_result.returncode == 2
    outside_bash = _run_hook_command(
        pre_bash,
        target,
        _hook_input("PreToolUse", "Bash", "printf changed", cwd=sibling),
        environment,
    )
    assert outside_bash.returncode == 2

    unsafe_commands = (
        f"git -C {shlex.quote(str(sibling))} commit -m test",
        f"cd {shlex.quote(str(sibling))} && git commit -m test",
        f"GIT_DIR={shlex.quote(str(sibling / '.git'))} git commit -m test",
        f"env -C {shlex.quote(str(sibling))} git commit -m test",
        "git -C \"$OUTSIDE\" commit -m test",
        "git -C ~ commit -m test",
        "pushd ../sibling && git commit -m test",
        "builtin cd ../sibling; git commit -m test",
        "export GIT_DIR=../sibling/.git; git commit -m test",
        "GIT_DIR=../sibling/.git; git commit -m test",
        "GIT_DIR=../sibling/.git sh -c 'git commit -m test'",
        "export GIT_DIR=../sibling/.git; bash -lc 'git commit -m test'",
        "git -C nested-repo commit -m test",
    )
    for command in unsafe_commands:
        execution = _run_hook_command(
            pre_commit,
            target,
            _hook_input("PreToolUse", "Bash", command, cwd=target),
            environment | {"OUTSIDE": str(sibling)},
        )
        assert execution.returncode == 2, command

    malformed_inputs = (
        "{not json",
        '{"hook_event_name":"PreToolUse","tool_name":"Bash",'
        '"tool_input":{"command":"git commit","command":"git status"},'
        f'"cwd":{json.dumps(str(target))}}}',
        _hook_input("PreToolUse", "Bash", "git commit 'unterminated", cwd=target),
        '{"hook_event_name":"PreToolUse","tool_name":"Bash",'
        '"tool_input":{"command":"git commit"},"cwd":'
        f'{json.dumps(str(target))},"extra":NaN}}',
    )
    for malformed in malformed_inputs:
        execution = _run_hook_command(pre_commit, target, malformed, environment)
        assert execution.returncode == 2

    inherited = _run_hook_command(
        pre_commit,
        target,
        _hook_input("PreToolUse", "Bash", "git commit -m test", cwd=target),
        environment | {"GIT_DIR": str(sibling / ".git")},
    )
    assert inherited.returncode == 2
    assert not hook_log.exists()


@pytest.mark.parametrize(
    "command",
    (
        ">/dev/null git commit -m test",
        "time -p git commit -m test",
        "command -p git commit -m test",
        "exec -c git commit -m test",
        "bash -lc 'git commit -m test'",
        "nice git commit -m test",
        "nohup git commit -m test",
        "timeout 5 git commit -m test",
        'message="$(git commit -m test)" echo done',
    ),
)
def test_pre_commit_filter_recognizes_supported_commit_shell_forms(
    tmp_path: Path, command: str
) -> None:
    repository_root = Path(__file__).parents[1]
    target = tmp_path / "configured"
    target.mkdir()
    result = _install_hooks(repository_root, [target])
    assert result.returncode == 0, result.stderr
    settings = json.loads((target / ".claude" / "settings.json").read_text())
    pre_commit = _registered_command(
        settings, "PreToolUse", "Bash", "pre-commit"
    )
    fake_bin = tmp_path / "supported-shell-bin"
    fake_bin.mkdir()
    fake_uv = fake_bin / "uv"
    fake_uv.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    fake_uv.chmod(0o755)
    environment = os.environ.copy()
    environment["CLAUDE_PROJECT_DIR"] = str(target)
    environment["PATH"] = f"{fake_bin}{os.pathsep}{environment['PATH']}"
    for name in ("GIT_COMMON_DIR", "GIT_DIR", "GIT_INDEX_FILE", "GIT_WORK_TREE"):
        environment.pop(name, None)

    execution = _run_hook_command(
        pre_commit,
        target,
        _hook_input("PreToolUse", "Bash", command, cwd=target),
        environment,
    )

    assert execution.returncode == 2
    assert "Commit blocked" in execution.stderr


@pytest.mark.parametrize("hook_name", ["pre-edit", "pre-commit"])
def test_installed_pre_hooks_fail_closed_when_checker_errors(
    tmp_path: Path, hook_name: str
) -> None:
    repository_root = Path(__file__).parents[1]
    targets = [
        tmp_path / key
        for key in load_fleet_manifest().with_capability("coordination_hooks")
    ]
    for target in targets:
        target.mkdir()
    workspace = tmp_path / "status-workspace"
    result = _install_hooks(repository_root, targets, workspace_root=workspace)
    assert result.returncode == 0, result.stderr

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_uv = fake_bin / "uv"
    fake_uv.write_text("#!/bin/sh\nexit 2\n", encoding="utf-8")
    fake_uv.chmod(0o755)
    environment = os.environ.copy()
    environment["CLAUDE_PROJECT_DIR"] = str(targets[0])
    environment["PATH"] = f"{fake_bin}{os.pathsep}{environment['PATH']}"

    hook = _installed_hook(targets[0], hook_name)
    hook_result = subprocess.run(
        [str(hook)],
        cwd=targets[0],
        env=environment,
        input=(
            _hook_input("PreToolUse", "Bash", "git commit -m test", cwd=targets[0])
            if hook_name == "pre-commit"
            else _hook_input("PreToolUse", "Edit", cwd=targets[0])
        ),
        capture_output=True,
        text=True,
        check=False,
    )

    assert hook_result.returncode == 2
    assert "Lock check failed" in hook_result.stdout


def test_hook_installer_shell_escapes_special_orchestration_path(tmp_path: Path) -> None:
    source_root = Path(__file__).parents[1]
    special_root = tmp_path / 'orchestration "quoted" \\ path'
    (special_root / "scripts").mkdir(parents=True)
    shutil.copy2(source_root / "scripts" / "install_hooks.sh", special_root / "scripts")
    shutil.copy2(
        source_root / "scripts" / "register_claude_hooks.py",
        special_root / "scripts",
    )
    shutil.copytree(source_root / "hook_templates", special_root / "hook_templates")
    targets = [
        tmp_path / key
        for key in load_fleet_manifest().with_capability("coordination_hooks")
    ]
    for target in targets:
        target.mkdir()

    fleet_bin = _fake_fleet_cli(tmp_path / "fleet-bin", targets)
    result = _install_hooks(special_root, targets, path_prefix=fleet_bin)
    assert result.returncode == 0, result.stderr

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        "#!/bin/sh\n"
        "while [ \"$#\" -gt 0 ]; do\n"
        '    if [ "$1" = "--project" ]; then\n'
        '        shift\n'
        '        [ "$1" = "$EXPECTED_ROOT" ] || exit 9\n'
        '        exit 0\n'
        "    fi\n"
        "    shift\n"
        "done\n"
        "exit 9\n",
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)
    environment = os.environ.copy()
    environment["CLAUDE_PROJECT_DIR"] = str(targets[0])
    environment["EXPECTED_ROOT"] = str(special_root)
    environment["PATH"] = f"{fake_bin}{os.pathsep}{environment['PATH']}"
    hook = _installed_hook(targets[0], "pre-edit")

    syntax = subprocess.run(
        ["bash", "-n", str(hook)], capture_output=True, text=True, check=False
    )
    hook_result = subprocess.run(
        [str(hook)],
        cwd=targets[0],
        env=environment,
        input=_hook_input("PreToolUse", "Edit", cwd=targets[0]),
        capture_output=True,
        text=True,
        check=False,
    )

    assert syntax.returncode == 0, syntax.stderr
    assert hook_result.returncode == 0, hook_result.stdout + hook_result.stderr


@pytest.mark.parametrize("hook_name", ["pre-edit", "pre-commit"])
def test_installed_pre_hooks_pin_the_trusted_root_for_relative_workspaces(
    tmp_path: Path, hook_name: str
) -> None:
    source_root = Path(__file__).parents[1]
    orchestration_root = tmp_path / "trusted orchestration"
    (orchestration_root / "scripts").mkdir(parents=True)
    shutil.copy2(
        source_root / "scripts" / "install_hooks.sh",
        orchestration_root / "scripts",
    )
    shutil.copy2(
        source_root / "scripts" / "register_claude_hooks.py",
        orchestration_root / "scripts",
    )
    shutil.copytree(source_root / "hook_templates", orchestration_root / "hook_templates")
    target = tmp_path / "configured"
    target.mkdir()
    fleet_bin = _fake_fleet_cli(tmp_path / "fleet-bin", [target])
    expected_workspace = orchestration_root / "runtime"
    result = _install_hooks(
        orchestration_root,
        [target],
        path_prefix=fleet_bin,
        workspace_root=expected_workspace,
    )
    assert result.returncode == 0, result.stderr

    resolution_log = tmp_path / "pre-hook-workspace"
    fake_uv = fleet_bin / "uv"
    fake_uv.write_text(
        "#!/bin/sh\n"
        '[ "$OPENCLAW_ORCHESTRATION_ROOT" = "$EXPECTED_ROOT" ] || exit 9\n'
        'case "$OPENCLAW_WORKSPACE" in\n'
        '    /*) resolved="$OPENCLAW_WORKSPACE" ;;\n'
        '    *) resolved="$OPENCLAW_ORCHESTRATION_ROOT/$OPENCLAW_WORKSPACE" ;;\n'
        "esac\n"
        'printf \'%s\\n\' "$resolved" > "$RESOLUTION_LOG"\n',
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)
    hostile_root = tmp_path / "stale-or-hostile-root"
    environment = os.environ.copy()
    environment["CLAUDE_PROJECT_DIR"] = str(target)
    environment["EXPECTED_ROOT"] = str(orchestration_root)
    environment["OPENCLAW_ORCHESTRATION_ROOT"] = str(hostile_root)
    environment["OPENCLAW_WORKSPACE"] = "runtime"
    environment["PATH"] = f"{fleet_bin}{os.pathsep}{environment['PATH']}"
    environment["RESOLUTION_LOG"] = str(resolution_log)

    pre_result = subprocess.run(
        [str(_installed_hook(target, hook_name))],
        cwd=target,
        env=environment,
        input=(
            _hook_input("PreToolUse", "Bash", "git commit -m test", cwd=target)
            if hook_name == "pre-commit"
            else _hook_input("PreToolUse", "Edit", cwd=target)
        ),
        capture_output=True,
        text=True,
        check=False,
    )
    post_result = subprocess.run(
        [str(_installed_hook(target, "post-edit"))],
        cwd=target,
        env=environment,
        input=_hook_input("PostToolUse", "Edit", cwd=target),
        capture_output=True,
        text=True,
        check=False,
    )

    assert pre_result.returncode == 0, pre_result.stdout + pre_result.stderr
    assert post_result.returncode == 0, post_result.stderr
    assert resolution_log.read_text(encoding="utf-8").strip() == str(
        expected_workspace
    )
    status_file = (
        expected_workspace
        / "status"
        / f"{load_fleet_manifest().keys[0]}_claude_status.yaml"
    )
    assert status_file.is_file()
    assert not (hostile_root / "runtime").exists()


def test_hook_installer_passes_its_project_dotenv_without_exposing_secrets(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source_root = Path(__file__).parents[1]
    orchestration_root = tmp_path / "orchestration"
    (orchestration_root / "scripts").mkdir(parents=True)
    shutil.copy2(
        source_root / "scripts" / "install_hooks.sh",
        orchestration_root / "scripts",
    )
    shutil.copy2(
        source_root / "scripts" / "register_claude_hooks.py",
        orchestration_root / "scripts",
    )
    shutil.copytree(source_root / "hook_templates", orchestration_root / "hook_templates")
    secret = "must-never-appear-in-installer-output"
    (orchestration_root / ".env").write_text(
        f"UNRELATED_SECRET={secret}\n", encoding="utf-8"
    )
    targets = [
        tmp_path / key
        for key in load_fleet_manifest().with_capability("coordination_hooks")
    ]
    for target in targets:
        target.mkdir()
    fleet_bin = _fake_fleet_cli(tmp_path / "fleet-bin", targets)
    arguments_log = tmp_path / "fleet-arguments.log"
    monkeypatch.setenv("FLEET_ARGS_LOG", str(arguments_log))
    result = _install_hooks(orchestration_root, targets, path_prefix=fleet_bin)

    assert result.returncode == 0, result.stderr
    arguments = arguments_log.read_text(encoding="utf-8")
    assert f"--dotenv {orchestration_root / '.env'}" in arguments
    assert secret not in result.stdout + result.stderr + arguments


@pytest.mark.parametrize("dotenv_kind", ["directory", "broken-symlink"])
def test_hook_installer_passes_unsafe_dotenv_to_strict_fleet_loader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    dotenv_kind: str,
) -> None:
    source_root = Path(__file__).parents[1]
    orchestration_root = tmp_path / "orchestration"
    (orchestration_root / "scripts").mkdir(parents=True)
    shutil.copy2(
        source_root / "scripts" / "install_hooks.sh",
        orchestration_root / "scripts",
    )
    shutil.copy2(
        source_root / "scripts" / "register_claude_hooks.py",
        orchestration_root / "scripts",
    )
    shutil.copytree(source_root / "hook_templates", orchestration_root / "hook_templates")
    dotenv = orchestration_root / ".env"
    if dotenv_kind == "directory":
        dotenv.mkdir()
    else:
        dotenv.symlink_to(orchestration_root / "missing.env")
    target = tmp_path / "configured"
    target.mkdir()
    fleet_bin = _fake_fleet_cli(tmp_path / "fleet-bin", [target])
    monkeypatch.setenv("FLEET_REJECT_DOTENV", "1")

    result = _install_hooks(orchestration_root, [target], path_prefix=fleet_bin)

    assert result.returncode == 2
    assert "Unable to load coordination targets" in result.stderr
    assert not (target / ".claude").exists()


def test_hook_installer_fails_for_a_configured_missing_checkout(tmp_path: Path) -> None:
    repository_root = Path(__file__).parents[1]
    missing = tmp_path / "configured-but-missing"

    result = _install_hooks(repository_root, [missing])

    assert result.returncode == 1
    assert "Repository not found" in result.stdout
    assert "configured target" in result.stdout


def test_hook_installer_fails_closed_when_hook_directory_cannot_be_created(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).parents[1]
    target = tmp_path / "configured"
    target.mkdir()
    (target / ".claude").write_text("not a directory", encoding="utf-8")

    result = _install_hooks(repository_root, [target])

    assert result.returncode == 1
    assert "Cannot create hooks directory" in result.stderr


def test_hook_installer_rejects_a_symlinked_hook_directory(tmp_path: Path) -> None:
    repository_root = Path(__file__).parents[1]
    target = tmp_path / "configured"
    outside = tmp_path / "outside"
    target.mkdir()
    outside.mkdir()
    (target / ".claude").symlink_to(outside, target_is_directory=True)

    result = _install_hooks(repository_root, [target])

    assert result.returncode == 1
    assert "must not be a symlink" in result.stderr
    assert not (outside / "hooks").exists()


def test_hook_installer_rejects_an_existing_symlink_hook_without_force(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).parents[1]
    target = tmp_path / "configured"
    hooks_dir = target / ".claude" / "hooks" / "kg-microbe"
    hooks_dir.mkdir(parents=True)
    outside_hook = tmp_path / "outside-pre-edit"
    outside_hook.write_text("leave me alone\n", encoding="utf-8")
    installed_hook = hooks_dir / "pre-edit"
    installed_hook.symlink_to(outside_hook)

    result = _install_hooks(repository_root, [target])

    assert result.returncode == 1
    assert "Existing hook target must not be a symlink" in result.stderr
    assert installed_hook.is_symlink()
    assert outside_hook.read_text(encoding="utf-8") == "leave me alone\n"


@pytest.mark.parametrize("target_kind", ["directory", "fifo"])
def test_hook_installer_rejects_an_existing_non_regular_hook_without_force(
    tmp_path: Path, target_kind: str
) -> None:
    repository_root = Path(__file__).parents[1]
    target = tmp_path / "configured"
    hooks_dir = target / ".claude" / "hooks" / "kg-microbe"
    hooks_dir.mkdir(parents=True)
    installed_hook = hooks_dir / "pre-edit"
    if target_kind == "directory":
        installed_hook.mkdir()
    else:
        os.mkfifo(installed_hook)

    result = _install_hooks(repository_root, [target])

    assert result.returncode == 1
    assert "Existing hook target must be a regular file" in result.stderr


def test_hook_installer_rechecks_for_a_directory_immediately_before_move(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository_root = Path(__file__).parents[1]
    target = tmp_path / "configured"
    target.mkdir()
    hooks_dir = target / ".claude" / "hooks" / "kg-microbe"
    race_target = hooks_dir / "pre-edit"
    fleet_bin = _fake_fleet_cli(tmp_path / "fleet-bin", [target])
    real_chmod = shutil.which("chmod")
    assert real_chmod is not None
    fake_chmod = fleet_bin / "chmod"
    fake_chmod.write_text(
        "#!/bin/sh\n"
        'mkdir -p "$RACE_TARGET"\n'
        f'exec "{real_chmod}" "$@"\n',
        encoding="utf-8",
    )
    fake_chmod.chmod(0o755)
    monkeypatch.setenv("RACE_TARGET", str(race_target))

    result = _install_hooks(repository_root, [target], path_prefix=fleet_bin)

    assert result.returncode == 1
    assert "Hook destination must not be a directory" in result.stderr
    assert race_target.is_dir()
    assert not list(race_target.iterdir())


def test_hook_installer_queries_manifest_instead_of_declaring_repositories() -> None:
    repository_root = Path(__file__).parents[1]
    installer = (repository_root / "scripts" / "install_hooks.sh").read_text()

    assert "python -m kg_microbe_fleet" in installer
    assert "targets --capability coordination_hooks" in installer
    for mech in load_fleet_manifest().mechs.values():
        assert f'{mech.environment_variable}="' not in installer


def test_post_commit_hook_writes_schema_parseable_yaml_for_punctuation(
    tmp_path: Path,
) -> None:
    repository_root = Path(__file__).parents[1]
    targets = [
        tmp_path / key
        for key in load_fleet_manifest().with_capability("coordination_hooks")
    ]
    for target in targets:
        target.mkdir()
    workspace = tmp_path / "status-workspace"
    result = _install_hooks(repository_root, targets, workspace_root=workspace)
    assert result.returncode == 0, result.stderr

    repo = Repo.init(targets[0])
    (targets[0] / "record.txt").write_text("content\n", encoding="utf-8")
    repo.index.add(["record.txt"])
    subject = "can't break: YAML # still text\rstatus: injected"
    repo.index.commit(subject)
    fake_bin = tmp_path / "post-commit-bin"
    fake_bin.mkdir()
    uv_called = tmp_path / "unexpected-uv-call"
    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        '#!/bin/sh\nprintf called > "$UV_CALLED"\nexit 88\n', encoding="utf-8"
    )
    fake_uv.chmod(0o755)
    environment = os.environ.copy()
    environment["CLAUDE_PROJECT_DIR"] = str(targets[0])
    environment["OPENCLAW_WORKSPACE"] = str(workspace)
    environment["UV_CALLED"] = str(uv_called)
    environment["PATH"] = f"{fake_bin}{os.pathsep}{environment['PATH']}"

    hook_result = subprocess.run(
        [str(_installed_hook(targets[0], "post-commit"))],
        cwd=targets[0],
        env=environment,
        input=_hook_input(
            "PostToolUse", "Bash", "git commit -m test", cwd=targets[0]
        ),
        capture_output=True,
        text=True,
        check=False,
    )

    assert hook_result.returncode == 0, hook_result.stderr
    assert not uv_called.exists()
    status_file = workspace / "status" / f"{load_fleet_manifest().keys[0]}_claude_status.yaml"
    status = yaml.safe_load(status_file.read_text(encoding="utf-8"))
    assert status["status"] == "idle"
    assert status["last_completed_operation"]["details"]["commit_message"] == subject


def test_post_commit_hook_surfaces_python_serialization_failure(tmp_path: Path) -> None:
    repository_root = Path(__file__).parents[1]
    targets = [tmp_path / load_fleet_manifest().keys[0]]
    targets[0].mkdir()
    workspace = tmp_path / "status-workspace"
    result = _install_hooks(repository_root, targets, workspace_root=workspace)
    assert result.returncode == 0, result.stderr

    fake_bin = tmp_path / "failing-python-bin"
    fake_bin.mkdir()
    fake_python = fake_bin / "python3"
    real_python = shutil.which("python3")
    assert real_python is not None
    fake_python.write_text(
        "#!/bin/sh\n"
        'case "$1" in\n'
        f'    */hook-input.py) exec "{real_python}" "$@" ;;\n'
        "    *) exit 17 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    fake_python.chmod(0o755)
    environment = os.environ.copy()
    environment["CLAUDE_PROJECT_DIR"] = str(targets[0])
    environment["OPENCLAW_WORKSPACE"] = str(workspace)
    environment["PATH"] = f"{fake_bin}{os.pathsep}{environment['PATH']}"

    hook_result = subprocess.run(
        [str(_installed_hook(targets[0], "post-commit"))],
        cwd=targets[0],
        env=environment,
        input=_hook_input(
            "PostToolUse", "Bash", "git commit -m test", cwd=targets[0]
        ),
        capture_output=True,
        text=True,
        check=False,
    )

    assert hook_result.returncode != 0
    assert "Cannot serialize commit message with python3" in hook_result.stderr
    assert not list((workspace / "status").glob("*_status.yaml"))


@pytest.mark.parametrize("hook_name", ["post-edit", "post-commit"])
def test_post_hooks_surface_status_write_failures(
    tmp_path: Path, hook_name: str
) -> None:
    repository_root = Path(__file__).parents[1]
    targets = [
        tmp_path / key
        for key in load_fleet_manifest().with_capability("coordination_hooks")
    ]
    for target in targets:
        target.mkdir()
    blocked_workspace = tmp_path / "workspace-is-a-file"
    result = _install_hooks(
        repository_root, targets, workspace_root=blocked_workspace
    )
    assert result.returncode == 0, result.stderr
    blocked_workspace.write_text("not a directory", encoding="utf-8")

    environment = os.environ.copy()
    environment["CLAUDE_PROJECT_DIR"] = str(targets[0])
    environment["OPENCLAW_WORKSPACE"] = str(blocked_workspace)
    hook_result = subprocess.run(
        [str(_installed_hook(targets[0], hook_name))],
        cwd=targets[0],
        env=environment,
        input=(
            _hook_input(
                "PostToolUse", "Bash", "git commit -m test", cwd=targets[0]
            )
            if hook_name == "post-commit"
            else _hook_input("PostToolUse", "Edit", cwd=targets[0])
        ),
        capture_output=True,
        text=True,
        check=False,
    )

    assert hook_result.returncode != 0


@pytest.mark.parametrize("hook_name", ["post-edit", "post-commit"])
def test_post_hooks_reject_a_symlinked_status_directory(
    tmp_path: Path, hook_name: str
) -> None:
    repository_root = Path(__file__).parents[1]
    targets = [
        tmp_path / key
        for key in load_fleet_manifest().with_capability("coordination_hooks")
    ]
    for target in targets:
        target.mkdir()
    workspace = tmp_path / "workspace"
    outside = tmp_path / "outside-status"
    workspace.mkdir()
    outside.mkdir()
    (workspace / "status").symlink_to(outside, target_is_directory=True)
    result = _install_hooks(repository_root, targets, workspace_root=workspace)
    assert result.returncode == 0, result.stderr

    environment = os.environ.copy()
    environment["CLAUDE_PROJECT_DIR"] = str(targets[0])
    environment["OPENCLAW_WORKSPACE"] = str(workspace)
    hook_result = subprocess.run(
        [str(_installed_hook(targets[0], hook_name))],
        cwd=targets[0],
        env=environment,
        input=(
            _hook_input(
                "PostToolUse", "Bash", "git commit -m test", cwd=targets[0]
            )
            if hook_name == "post-commit"
            else _hook_input("PostToolUse", "Edit", cwd=targets[0])
        ),
        capture_output=True,
        text=True,
        check=False,
    )

    assert hook_result.returncode != 0
    assert "must not be symlinks" in hook_result.stderr
    assert not list(outside.iterdir())


@pytest.mark.parametrize("hook_name", ["post-edit", "post-commit"])
def test_post_hooks_recheck_for_a_directory_immediately_before_move(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    hook_name: str,
) -> None:
    repository_root = Path(__file__).parents[1]
    targets = [tmp_path / load_fleet_manifest().keys[0]]
    targets[0].mkdir()
    workspace = tmp_path / "workspace"
    result = _install_hooks(repository_root, targets, workspace_root=workspace)
    assert result.returncode == 0, result.stderr

    status_file = (
        workspace
        / "status"
        / f"{load_fleet_manifest().keys[0]}_claude_status.yaml"
    )
    fake_bin = tmp_path / "racing-status-bin"
    fake_bin.mkdir()
    real_cat = shutil.which("cat")
    assert real_cat is not None
    fake_cat = fake_bin / "cat"
    fake_cat.write_text(
        "#!/bin/sh\n"
        'mkdir -p "$RACE_TARGET"\n'
        f'exec "{real_cat}" "$@"\n',
        encoding="utf-8",
    )
    fake_cat.chmod(0o755)
    monkeypatch.setenv("RACE_TARGET", str(status_file))
    environment = os.environ.copy()
    environment["CLAUDE_PROJECT_DIR"] = str(targets[0])
    environment["OPENCLAW_WORKSPACE"] = str(workspace)
    environment["PATH"] = f"{fake_bin}{os.pathsep}{environment['PATH']}"
    hook_result = subprocess.run(
        [str(_installed_hook(targets[0], hook_name))],
        cwd=targets[0],
        env=environment,
        input=(
            _hook_input(
                "PostToolUse", "Bash", "git commit -m test", cwd=targets[0]
            )
            if hook_name == "post-commit"
            else _hook_input("PostToolUse", "Edit", cwd=targets[0])
        ),
        capture_output=True,
        text=True,
        check=False,
    )

    assert hook_result.returncode != 0
    assert "Status file destination must not be a directory" in hook_result.stderr
    assert status_file.is_dir()
    assert not list(status_file.iterdir())
