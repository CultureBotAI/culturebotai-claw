"""`kg-microbe-governance pin-coupling` finds what a re-pin will leave stale (#526).

Every case is a throwaway git repository, so nothing reads a Mech checkout.
The two positive cases are the two files that broke CI in the re-pin to
cb83def3: a workflow that checks claw out at a hard-coded ref, and a committed
snapshot of claw's manifest.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from kg_microbe_governance import GovernanceError
from kg_microbe_governance.__main__ import main
from kg_microbe_governance.pin_coupling import find_pin_couplings

OLD = "44db08d59226073425b206a36a257b2b6a8900df"
PIN = "scripts/.vendored_canon_ref"


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def _repo(tmp_path: Path, files: dict[str, str], *, uncommitted: dict[str, str] | None = None) -> Path:
    root = tmp_path / "mech"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    for path, text in {PIN: OLD + "\n", **files}.items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "fixture")
    _git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    for path, text in (uncommitted or {}).items():
        (root / path).parent.mkdir(parents=True, exist_ok=True)
        (root / path).write_text(text, encoding="utf-8")
    return root


def _found(root: Path) -> list[tuple[str, str]]:
    return [(c.path, c.kind) for c in find_pin_couplings(root, OLD, pin_path=PIN)]


def test_the_pin_file_alone_is_not_a_coupling(tmp_path: Path) -> None:
    assert _found(_repo(tmp_path, {"README.md": "nothing here\n"})) == []


def test_a_workflow_checking_claw_out_at_the_old_pin_is_found(tmp_path: Path) -> None:
    """MediaIngredientMech's qc-evidence.yaml, the first CI failure of #526."""
    root = _repo(tmp_path, {".github/workflows/qc-evidence.yaml": f"          ref: {OLD}\n"})
    assert _found(root) == [(".github/workflows/qc-evidence.yaml", "pin-reference")]


@pytest.mark.parametrize("length", [7, 8, 12, 40])
def test_an_abbreviated_pin_is_found(tmp_path: Path, length: int) -> None:
    root = _repo(tmp_path, {"docs/pin.md": f"pinned at `{OLD[:length]}`\n"})
    assert _found(root) == [("docs/pin.md", "pin-reference")]


def test_an_uppercase_pin_is_found(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"docs/pin.md": f"ref: {OLD.upper()}\n"})
    assert _found(root) == [("docs/pin.md", "pin-reference")]


def test_another_commit_sharing_the_first_eight_characters_is_not_the_pin(tmp_path: Path) -> None:
    other = OLD[:8] + "f" * 32
    assert other != OLD
    assert _found(_repo(tmp_path, {"docs/other.md": f"see {other}\n"})) == []


def test_a_committed_manifest_snapshot_is_found_by_name(tmp_path: Path) -> None:
    """NaturalProductMech's snapshot quotes no SHA, the second failure of #526."""
    root = _repo(tmp_path, {"scripts/.vendored_manifest.json": '{"consumers": {}}\n'})
    assert _found(root) == [("scripts/.vendored_manifest.json", "manifest-snapshot")]


def test_dated_reports_are_records_not_couplings(tmp_path: Path) -> None:
    root = _repo(tmp_path, {"reports/2026-09-21/run.json": f'{{"claw": "{OLD}"}}\n'})
    assert _found(root) == []


def test_only_the_committed_tree_is_read(tmp_path: Path) -> None:
    """A worktree edit is not on main, so it is not what the re-pin PR starts from."""
    root = _repo(tmp_path, {}, uncommitted={"scratch.yaml": f"ref: {OLD}\n"})
    assert _found(root) == []


def test_a_checkout_without_the_tree_is_an_error_not_a_clean_result(tmp_path: Path) -> None:
    root = _repo(tmp_path, {})
    with pytest.raises(GovernanceError, match="no origin/nope"):
        find_pin_couplings(root, OLD, pin_path=PIN, treeish="origin/nope")


def test_the_command_exits_one_on_a_coupling_and_zero_without(tmp_path: Path, capsys) -> None:
    coupled = _repo(tmp_path, {".github/workflows/qc.yaml": f"ref: {OLD}\n"})
    clean = tmp_path / "clean"
    clean.mkdir()
    _git(clean, "clone", "-q", str(coupled), str(clean / "r"))
    _git(clean / "r", "config", "user.email", "t@example.invalid")
    _git(clean / "r", "config", "user.name", "t")
    _git(clean / "r", "rm", "-q", ".github/workflows/qc.yaml")
    _git(clean / "r", "commit", "-q", "-m", "drop")
    _git(clean / "r", "update-ref", "refs/remotes/origin/main", "HEAD")

    assert main(["pin-coupling", "--old-ref", OLD, "--json",
                 "--target-root", f"culturemech={coupled}"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["culturemech"]["couplings"][0]["path"] == ".github/workflows/qc.yaml"
    assert report["culturemech"]["pins_outgoing"] is True
    assert main(["pin-coupling", "--old-ref", OLD,
                 "--target-root", f"culturemech={clean / 'r'}"]) == 0


def test_an_unknown_mech_key_is_refused(tmp_path: Path) -> None:
    root = _repo(tmp_path, {})
    assert main(["pin-coupling", "--old-ref", OLD, "--target-root", f"notamech={root}"]) == 2


def test_a_consumer_not_pinning_the_outgoing_commit_is_not_ok(tmp_path: Path, capsys) -> None:
    """A mistyped --old-ref, or a Mech already re-pinned, read as OK (#536)."""
    root = _repo(tmp_path, {})
    other = "cb83def3a6b5af2aff24a0e50cc411f26c820f7c"
    assert main(["pin-coupling", "--old-ref", other,
                 "--target-root", f"culturemech={root}"]) == 1
    out = capsys.readouterr().out
    assert f"is {OLD}, not the outgoing pin" in out
    assert main(["pin-coupling", "--old-ref", OLD,
                 "--target-root", f"culturemech={root}"]) == 0
    assert "not the outgoing pin" not in capsys.readouterr().out

