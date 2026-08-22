"""Structural contract for claw's passive fleet-governance mirror."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MIRROR = ROOT / "shared" / "spoke"


def _manifest_entries() -> list[str]:
    return [
        line.strip()
        for line in (MIRROR / "MANIFEST").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_manifest_is_complete_and_has_no_duplicate_entries() -> None:
    entries = _manifest_entries()
    assert len(entries) == len(set(entries))

    tracked_payload = {
        path.relative_to(MIRROR).as_posix()
        for path in MIRROR.rglob("*")
        if path.is_file() and path.name not in {"MANIFEST", "README.md"}
    }
    assert set(entries) == tracked_payload


def test_claw_operational_governance_files_match_mirror() -> None:
    for relative in (
        "tests/test_skill_frontmatter.py",
        "prompts/backlog-loop-goal.md",
    ):
        assert (ROOT / relative).read_bytes() == (MIRROR / relative).read_bytes()


def test_fleet_audit_covers_claws_packaged_history_schema() -> None:
    audit = (ROOT / "scripts" / "audit_idlabel_fleet.sh").read_text(encoding="utf-8")
    assert 'MAPPED=(' in audit and "schema/history.yaml" in audit
    assert "shared/history/history.yaml" in audit
    assert 'if [ "$suf" = "schema/history.yaml" ]' in audit
