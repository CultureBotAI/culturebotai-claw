"""Bounded offline regression for #913: require --body-file for PR and issue bodies."""

from __future__ import annotations

import json
import os
import stat
import subprocess
from pathlib import Path

from kg_microbe_skills.catalogue import canonical_text

ROOT = Path(__file__).resolve().parents[1]


def test_canonical_and_adapter_guidance_require_body_file_and_operator_owned_tasks() -> None:
    """Canonical publication guidance and claw's adapters must require --body-file,
    retain the body artifact, verify published text, and keep background tasks
    operator-owned (#913)."""
    for name in ("triage-and-resolve-issues", "evolve-mech-workflow"):
        text = " ".join(canonical_text(name).split())
        assert "--body-file" in text, f"{name} canonical template must require --body-file"
        assert "Retain the body" in text
        assert "--json body" in text
        assert "operator-owned" in text and "never kills them" in text

    for rel in (
        ".claude/skills/triage-and-resolve-issues/SKILL.md",
        ".claude/skills/evolve-mech-workflow/SKILL.md",
        ".claude/skills/fleet-pr-review/SKILL.md",
        "docs/guides/MECH_PORT_PRESSURE.md",
    ):
        body = " ".join((ROOT / rel).read_text(encoding="utf-8").split())
        assert "--body-file" in body, f"{rel} must require --body-file"
        assert "--json body" in body or "verifying the published text" in body


def test_body_file_publication_preserves_backticks_command_substitution_quotes_and_newlines(
    tmp_path: Path,
) -> None:
    """Passing Markdown with backticks (`PR`), $(...), quotes, and newlines via
    --body-file delivers literal bytes without invoking /usr/bin/pr or shell
    substitution, retains the body file, and verifies the published text (#913)."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    store_path = tmp_path / "published_store.json"
    canary_marker = tmp_path / "substituted_pr_invoked"

    # A fake `pr` binary in PATH: if a shell ever evaluated `PR` via command
    # substitution on a case-insensitive or PATH-resolved lookup, this marker
    # would be created.
    for cmd_name in ("pr", "PR"):
        shim = bin_dir / cmd_name
        shim.write_text(
            f"#!/bin/sh\necho invoked > {canary_marker}\nexit 99\n",
            encoding="utf-8",
        )
        shim.chmod(shim.stat().st_mode | stat.S_IXUSR)

    gh_shim = bin_dir / "gh"
    gh_shim.write_text(
        "#!/usr/bin/env python3\n"
        "import json, pathlib, sys\n"
        f"store = pathlib.Path({str(store_path)!r})\n"
        "data = json.loads(store.read_text(encoding='utf-8')) if store.exists() else {}\n"
        "args = sys.argv[1:]\n"
        "if len(args) >= 2 and args[1] in ('create', 'edit', 'comment'):\n"
        "    if '--body' in args:\n"
        "        sys.stderr.write('inline --body is forbidden by #913\\n')\n"
        "        sys.exit(2)\n"
        "    idx = args.index('--body-file')\n"
        "    body_path = pathlib.Path(args[idx + 1])\n"
        "    data[args[0]] = {\n"
        "        'body': body_path.read_text(encoding='utf-8'),\n"
        "        'body_file': str(body_path),\n"
        "    }\n"
        "    store.write_text(json.dumps(data), encoding='utf-8')\n"
        "    print('https://github.com/CultureBotAI/example/' + args[0] + '/1')\n"
        "    sys.exit(0)\n"
        "if len(args) >= 2 and args[1] == 'view' and '--json' in args:\n"
        "    entry = data[args[0]]\n"
        "    print(json.dumps({'body': entry['body']}))\n"
        "    sys.exit(0)\n"
        "sys.exit(1)\n",
        encoding="utf-8",
    )
    gh_shim.chmod(gh_shim.stat().st_mode | stat.S_IXUSR)

    markdown_body = (
        "## Summary\n\n"
        "- Follow up on `PR` #802 and `gh pr create --body-file`.\n"
        "- Literal shell tokens: `$(pr)` `${USER}` $HOME \"double\" 'single'.\n"
        "- Multi-line block:\n"
        "  ```bash\n"
        "  echo $(uname -s) `PR`\n"
        "  ```\n"
    )
    artifact_dir = tmp_path / ".temp" / "gh-bodies"
    artifact_dir.mkdir(parents=True)
    pr_body_file = artifact_dir / "pr-body.md"
    issue_body_file = artifact_dir / "issue-body.md"
    pr_body_file.write_text(markdown_body, encoding="utf-8")
    issue_body_file.write_text(markdown_body, encoding="utf-8")

    env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ.get('PATH', '')}",
    }

    subprocess.run(
        [
            str(gh_shim),
            "pr",
            "create",
            "--title",
            "Test PR",
            "--body-file",
            str(pr_body_file),
        ],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        [
            str(gh_shim),
            "issue",
            "create",
            "--title",
            "Test issue",
            "--body-file",
            str(issue_body_file),
        ],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )

    assert not canary_marker.exists(), "command substitution must never execute"
    assert pr_body_file.is_file() and pr_body_file.read_text(encoding="utf-8") == markdown_body
    assert issue_body_file.is_file() and issue_body_file.read_text(encoding="utf-8") == markdown_body

    pr_view = subprocess.run(
        [str(gh_shim), "pr", "view", "1", "--json", "body"],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    issue_view = subprocess.run(
        [str(gh_shim), "issue", "view", "1", "--json", "body"],
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    assert json.loads(pr_view.stdout)["body"] == markdown_body
    assert json.loads(issue_view.stdout)["body"] == markdown_body
