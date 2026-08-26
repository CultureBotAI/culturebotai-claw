"""Structural contract for the bounded Phase 1 compatibility mirror."""

import os
import subprocess
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


def test_fleet_audit_derives_repositories_and_hub_from_manifest_cli() -> None:
    audit = (ROOT / "scripts" / "audit_idlabel_fleet.sh").read_text(encoding="utf-8")

    assert "python -m kg_microbe_fleet" in audit
    assert "--capability id_label_validation" in audit
    assert "scope --capability id_label_validation --require-vendored-hub" in audit
    assert "show --field vendored_hub" not in audit
    assert "REPOS=(CultureMech" not in audit
    assert 'ORG="${ORG:-' not in audit
    assert 'cd "$ORCHESTRATION_ROOT"' in audit


def test_fleet_audit_uses_manifest_github_identities_without_network(
    tmp_path: Path,
) -> None:
    mirror = tmp_path / "mirror"
    spoke = tmp_path / "spoke"
    mirror.mkdir()
    spoke.mkdir()
    (mirror / "MANIFEST").write_text("rules.yaml\n", encoding="utf-8")
    (mirror / "rules.yaml").write_text("same bytes\n", encoding="utf-8")
    (spoke / "MANIFEST").write_text("governance.txt\n", encoding="utf-8")
    (spoke / "governance.txt").write_text("same bytes\n", encoding="utf-8")
    history = tmp_path / "history.yaml"
    history.write_text("same bytes\n", encoding="utf-8")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$*\" >> \"$UV_CALL_LOG\"\n"
        "case \" $* \" in\n"
        "  *\" scope \"*)\n"
        "    printf 'hub\\tCanonical Mech\\tExampleOrg/CanonicalMech\\tHUB_ROOT\\tsrc/canonical\\thub\\n'\n"
        "    printf 'spoke\\tSpoke Mech\\tDifferentOrg/SpokeMech\\tSPOKE_ROOT\\tsrc/spoke\\tspoke\\n'\n"
        "    ;;\n"
        "  *) exit 2 ;;\n"
        "esac\n",
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)
    fake_curl = fake_bin / "curl"
    fake_curl.write_text(
        "#!/bin/sh\n"
        "out=''\n"
        "for argument in \"$@\"; do\n"
        "  case \"$argument\" in\n"
        "    https://*) printf '%s\\n' \"$argument\" >> \"$AUDIT_URL_LOG\" ;;\n"
        "  esac\n"
        "done\n"
        "while [ \"$#\" -gt 0 ]; do\n"
        "  if [ \"$1\" = '-o' ]; then shift; out=\"$1\"; break; fi\n"
        "  shift\n"
        "done\n"
        "[ -n \"$out\" ] || exit 2\n"
        "printf 'same bytes\\n' > \"$out\"\n",
        encoding="utf-8",
    )
    fake_curl.chmod(0o755)
    url_log = tmp_path / "urls.log"
    uv_call_log = tmp_path / "uv-calls.log"
    environment = os.environ.copy()
    environment.update(
        {
            "PATH": f"{fake_bin}{os.pathsep}{environment['PATH']}",
            "AUDIT_URL_LOG": str(url_log),
            "UV_CALL_LOG": str(uv_call_log),
            "MIRROR_ROOT": str(mirror),
            "MANIFEST": str(mirror / "MANIFEST"),
            "SPOKE_ROOT": str(spoke),
            "SPOKE_MANIFEST": str(spoke / "MANIFEST"),
            "CLAW_HISTORY": str(history),
            "REF": "main",
        }
    )

    result = subprocess.run(
        ["bash", str(ROOT / "scripts" / "audit_idlabel_fleet.sh")],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    urls = url_log.read_text(encoding="utf-8")
    assert "ExampleOrg/CanonicalMech/main/rules.yaml" in urls
    assert "DifferentOrg/SpokeMech/main/rules.yaml" in urls
    uv_calls = uv_call_log.read_text(encoding="utf-8").splitlines()
    assert len(uv_calls) == 1
    assert " scope " in f" {uv_calls[0]} "
    assert "--require-vendored-hub" in uv_calls[0]
