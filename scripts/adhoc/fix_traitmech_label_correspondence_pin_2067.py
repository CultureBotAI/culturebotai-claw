#!/usr/bin/env python3
"""Move TraitMech's label-correspondence claw ref to the governance pin, and enforce it (#2067).

Purpose: TraitMech's .github/workflows/label-correspondence.yaml says to keep its
claw ref at scripts/.vendored_canon_ref. It calls the reusable workflow at
c8b8f89e while the pin is 76c1ebee, and nothing enforces the rule. The reusable
workflow is byte-identical at both commits and checks out only the caller, so
moving the ref is behaviour-neutral. This moves it, points the comment at
the new test that enforces it, and adds that test. The test is run against
the old ref (it must fail) and the new ref (it must pass) before anything is
committed.
Inputs: Mech roots exported from claw's .env (set -a; . ./.env); --worktree PATH;
--apply to commit and push. Without --apply the worktree is prepared and tested
but nothing is committed or pushed.
Outputs: a worktree from TraitMech origin/main on branch
fix/2067-label-correspondence-pin, with the commit pushed when --apply is given.
Holds TraitMech's LockManager lease for every write; verifies origin against the
fleet manifest before the push. Never touches TraitMech's own checkout.
Serves: CultureBotAI/TraitMech#2067 (raised in the culturebotai-claw#729 re-pin
reviews). Written 2026-11-05.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from kg_microbe_fleet import load_fleet_manifest  # noqa: E402
from plugins.lock_manager import LockManager  # noqa: E402
from plugins.repository_settings import RepositorySettings, RepositoryTarget  # noqa: E402

KEY = "traitmech"
BRANCH = "fix/2067-label-correspondence-pin"
WORKFLOW = ".github/workflows/label-correspondence.yaml"
TEST = "tests/test_label_correspondence_pin.py"
OLD_REF = "c8b8f89ecf29574d7e24f6c65cfd925aefbdd007"
OLD_COMMENT = "    # Keep this at the same immutable CLAW revision as scripts/.vendored_canon_ref.\n"
NEW_COMMENT = (
    "    # Keep this at the same immutable CLAW revision as scripts/.vendored_canon_ref:\n"
    "    # tests/test_label_correspondence_pin.py fails when they differ, and claw's\n"
    "    # `kg-microbe-governance pin-coupling` names this file on a re-pin (#2067).\n"
)
TEST_TEXT = '''"""label-correspondence.yaml calls claw at the governance pin (#2067).

The workflow says to keep its claw ref at scripts/.vendored_canon_ref, and the
ref drifted once with nothing to notice: the pin moved and this call did not.
A re-pin that leaves this ref behind now fails here. claw's
`kg-microbe-governance pin-coupling` also reports the outgoing pin in this
file, so the re-pin commit knows to change both.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CALL = re.compile(
    r"^\\s*uses:\\s*CultureBotAI/culturebotai-claw/\\.github/workflows/"
    r"label-correspondence-reusable\\.yaml@(\\S+)\\s*$",
    re.MULTILINE,
)


def test_the_reusable_workflow_is_called_at_the_governance_pin() -> None:
    workflow = (ROOT / ".github/workflows/label-correspondence.yaml").read_text(encoding="utf-8")
    pin = (ROOT / "scripts/.vendored_canon_ref").read_text(encoding="utf-8").strip()
    refs = CALL.findall(workflow)
    assert len(refs) == 1, f"expected one call to the reusable workflow, found {refs}"
    assert re.fullmatch(r"[0-9a-f]{40}", pin), pin
    assert refs[0] == pin, f"label-correspondence calls claw at {refs[0]}, but the pin is {pin}"
'''


def run(*args: str, cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    completed = subprocess.run(list(args), cwd=cwd, text=True, capture_output=True, check=False)
    if check and completed.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} failed: {completed.stderr.strip() or completed.stdout.strip()}")
    return completed


def pytest_passes(worktree: Path) -> bool:
    completed = run("uv", "run", "--quiet", "python", "-m", "pytest", "-q", "-p", "no:cacheprovider", TEST,
                    cwd=worktree, check=False)
    print(completed.stdout.strip().splitlines()[-1] if completed.stdout.strip() else completed.stderr.strip())
    return completed.returncode == 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worktree", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    root = RepositorySettings.from_environment().paths[KEY]
    slug = load_fleet_manifest().mechs[KEY].github
    RepositoryTarget(name=KEY, path=root, expected_repository=slug).open()
    run("git", "-C", str(root), "fetch", "-q", "origin")
    worktree = args.worktree
    with LockManager().lock(KEY, "label-correspondence-pin-2067"):
        run("git", "-C", str(root), "worktree", "add", "-q", "-b", BRANCH, str(worktree), "origin/main")
        pin = (worktree / "scripts/.vendored_canon_ref").read_text(encoding="utf-8").strip()
        path = worktree / WORKFLOW
        text = path.read_text(encoding="utf-8")
        for needle in (OLD_REF, OLD_COMMENT):
            if text.count(needle) != 1:
                raise RuntimeError(f"{needle!r} occurs {text.count(needle)} times in {WORKFLOW}")
        (worktree / TEST).write_text(TEST_TEXT, encoding="utf-8")
        print("old ref (must fail):")
        if pytest_passes(worktree):
            raise RuntimeError("the new test passes against the old ref, so it cannot detect drift")
        path.write_text(text.replace(OLD_REF, pin).replace(OLD_COMMENT, NEW_COMMENT), encoding="utf-8")
        print("pin ref (must pass):")
        if not pytest_passes(worktree):
            raise RuntimeError("the new test fails against the pin ref")
        status = run("git", "-C", str(worktree), "status", "--porcelain").stdout.split("\n")
        if sorted(line for line in status if line) != sorted([f" M {WORKFLOW}", f"?? {TEST}"]):
            raise RuntimeError(f"unexpected worktree state: {status}")
        if not args.apply:
            print(f"prepared {worktree}; rerun with --apply on a fresh worktree to commit and push")
            return 0
        run("git", "-C", str(worktree), "add", WORKFLOW, TEST)
        message = (
            "Call label-correspondence at the governance pin, and test that it stays there\n\n"
            "The workflow says to keep its claw ref at scripts/.vendored_canon_ref,\n"
            f"but it called the reusable workflow at {OLD_REF[:10]} while the pin is\n"
            f"{pin[:10]} (#2067). Nothing enforced the rule, and it had already drifted\n"
            "once. The reusable workflow is byte-identical at both commits and checks\n"
            "out only this repository, so the move changes no behaviour.\n\n"
            "tests/test_label_correspondence_pin.py now fails when the ref and the pin\n"
            "differ. It fails on the previous ref and passes on the pin. claw's\n"
            "pin-coupling already reports this file on a re-pin, so the re-pin commit\n"
            "changes both.\n\n"
            "Fixes #2067.\n\n"
            "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
        )
        run("git", "-C", str(worktree), "commit", "-q", "-m", message)
        RepositoryTarget(name=KEY, path=worktree.resolve(), expected_repository=slug).open()
        run("git", "-C", str(worktree), "push", "-q", "-u", "origin", BRANCH)
    print(f"pushed {BRANCH} {run('git', '-C', str(worktree), 'rev-parse', 'HEAD').stdout.strip()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
