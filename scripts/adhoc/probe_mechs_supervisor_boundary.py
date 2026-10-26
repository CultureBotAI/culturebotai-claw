#!/usr/bin/env python3
"""Read-only proof for XMechBay #7; 2026-10-25.

Input: local tmux server and claw checkout (--claw-root). Output: JSON on stdout
for a claw workspace/reports/ artifact. Run over ssh with this file on stdin;
never reads screens, conversation databases or credentials, and sends no input.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path


def output(*args: str) -> str:
    return subprocess.run(args, text=True, capture_output=True, check=True).stdout


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--claw-root", type=Path, required=True)
    args = parser.parse_args()
    root = args.claw_root.resolve()
    spec = importlib.util.spec_from_file_location(
        "terminal_boundary_probe", root / "scripts/mech_session_terminal.py"
    )
    terminal = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(terminal)
    panes = []
    for row in output("tmux", "list-panes", "-a", "-F",
                      "#{session_name}|#{window_name}|#{pane_tty}|#{pane_current_command}").splitlines():
        session, window, tty, current = row.split("|", 3)
        if session != "mechs":
            continue
        identities = output("/bin/ps", "-t", Path(tty).name, "-o", "pid=,tty=,lstart=,comm=")
        accepted = [record for line in identities.splitlines()
                    if (record := terminal.process_record(line)) is not None]
        panes.append({"session": session, "window": window, "tty": tty,
                      "current_command": current,
                      "process_identities": identities.splitlines(),
                      "accepted_agy_processes": accepted})
    if not panes:
        raise SystemExit("No mechs panes observed; no boundary claim is possible")
    result = {
        "observed_at": datetime.now(timezone.utc).isoformat(),
        "claw_root": str(root),
        "claw_head": output("git", "-C", str(root), "rev-parse", "HEAD").strip(),
        "panes": panes,
        "all_mechs_processes_rejected_as_agy": all(not p["accepted_agy_processes"] for p in panes),
        "input_sent": False,
    }
    print(json.dumps(result, indent=2))
    if not result["all_mechs_processes_rejected_as_agy"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
