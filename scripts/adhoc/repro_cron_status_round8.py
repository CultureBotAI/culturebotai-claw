#!/usr/bin/env python3
"""Reproduce the eighth review's findings against scripts/cron_status.py.

Purpose: Codex's eighth adversarial review of PR #820 reported that undecodable
scheduler output aborts the report, that a workflow file which is not a mapping
is silently dropped from a complete report, and that Unicode line separators
(U+0085, U+2028) split one crontab line, or one gh JSON line, in two. Each case
runs through main(), with fake `crontab` and `launchctl` executables first on
PATH and an injected gh, so no real scheduler or GitHub is read. It prints one
line per case and exits 1 if any case reproduces.
Inputs: none; run from the claw checkout root.
Outputs: stdout only.
Serves: PR #820 and the round-8 review issue. Written 2026-11-05.
"""
from __future__ import annotations

import base64
import contextlib
import io
import json
import os
import plistlib
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, "scripts")
import cron_status as cs  # noqa: E402


def fake_bin(directory: Path, name: str, payload: bytes) -> None:
    script = directory / name
    script.write_text(f"#!{sys.executable}\nimport sys\nsys.stdout.buffer.write({payload!r})\n")
    script.chmod(0o755)


def run_main(argv: list[str], gh, crontab: bytes, launchctl: bytes = b"{};\n") -> tuple[str, dict | None]:
    with tempfile.TemporaryDirectory() as tmp:
        bin_dir, agents = Path(tmp) / "bin", Path(tmp) / "agents"
        bin_dir.mkdir()
        agents.mkdir()
        fake_bin(bin_dir, "crontab", crontab)
        fake_bin(bin_dir, "launchctl", launchctl)
        (agents / "job.plist").write_bytes(plistlib.dumps({"Label": "me.job", "StartInterval": 60}))
        saved = os.environ["PATH"]
        os.environ["PATH"] = f"{bin_dir}{os.pathsep}{saved}"
        out = io.StringIO()
        try:
            with contextlib.redirect_stdout(out):
                code = cs.main([*argv, "--json", "--launch-agents-dir", str(agents)], gh=gh)
        except BaseException as exc:  # the defect being reproduced is an escape
            return f"raised {type(exc).__name__}: {str(exc)[:80]}", None
        finally:
            os.environ["PATH"] = saved
        report = json.loads(out.getvalue())
        return f"exit {code}", report


def no_repositories(args: list[str]) -> str:
    return ""


def one_workflow(content: str, name: str = "w") -> callable:
    def gh(args: list[str]) -> str:
        endpoint = args[-1] if args[1] != "--paginate" else args[2]
        if endpoint.endswith("/actions/workflows"):
            line = json.dumps({"id": 1, "name": name, "path": ".github/workflows/w.yaml", "state": "active"},
                              ensure_ascii=False)
            return line + "\n"
        if "/contents/" in endpoint:
            return json.dumps({"content": base64.b64encode(content.encode()).decode()})
        return "0" if ".total_count" in args else ""
    return gh


def main() -> int:
    ok = True

    outcome, report = run_main([], no_repositories, crontab=b"0 0 * * * echo \xff\n")
    good = report is not None and [job["job"] for job in report["local"] if job["source"] == "crontab"] == [
        "echo \\xff"]
    print(f"{'ok  ' if good else 'BAD '} non-UTF-8 crontab output: {outcome}")
    ok &= good

    outcome, report = run_main([], no_repositories, crontab=b"", launchctl=b'"LastExitStatus" = \xff;\n')
    good = report is not None
    print(f"{'ok  ' if good else 'BAD '} non-UTF-8 launchctl output: {outcome}")
    ok &= good

    outcome, report = run_main([], one_workflow("- not\n- a workflow\n"), crontab=b"")
    good = report is not None and report["complete"] is False and report["workflows"] and "mapping" in (
        report["workflows"][0]["error"] or "")
    print(f"{'ok  ' if good else 'BAD '} workflow file that is a list: {outcome}, "
          f"complete={report and report['complete']}, workflows={report and report['workflows']}")
    ok &= good

    outcome, report = run_main([], no_repositories, crontab="0 0 * * * echo a\u0085b\n".encode())
    jobs = report and [(job["schedule"], job["job"]) for job in report["local"] if job["source"] == "crontab"]
    good = jobs == [("0 0 * * *", "echo a\u0085b")]
    print(f"{'ok  ' if good else 'BAD '} U+0085 inside a crontab command: {outcome}, jobs={jobs!r}")
    ok &= good

    cell = cs._cell(cs.Code("echo a\u2028b"))
    good = "\u2028" in cell
    print(f"{'ok  ' if good else 'BAD '} U+2028 inside a rendered command: {cell!r}")
    ok &= good

    outcome, report = run_main([], one_workflow("on:\n  schedule:\n    - cron: '0 0 * * *'\n", name="a\u2028b"),
                               crontab=b"")
    good = report is not None and not report["failures"] and report["workflows"] and \
        report["workflows"][0]["name"] == "a\u2028b"
    print(f"{'ok  ' if good else 'BAD '} U+2028 inside a workflow name from gh: {outcome}, "
          f"failures={report and report['failures']}")
    ok &= good

    print("no case reproduces" if ok else "DEFECTS REPRODUCED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
