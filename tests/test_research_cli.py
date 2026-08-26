"""CLI contracts for `kg-microbe-research`.

The exit codes matter as much as the output: a caller gates a real run on
`authorize`, so a refusal must be distinguishable from a permitted dry run.
"""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from kg_microbe_research.__main__ import main

PROFILE = textwrap.dedent(
    """\
    mech: TestMech
    target: things
    default_focus: primary
    focuses:
      primary:
        label: primary focus
        objective: find things
        source_priorities: []
        provider_adjustments: {asta: 5}
        stages:
          discovery:
            objective: find
            capabilities: {academic_search: 4, snippets: 2}
            speed_weight: 1
    """
)


@pytest.fixture
def profile_path(tmp_path: Path) -> Path:
    path = tmp_path / "deep_research_provider.yaml"
    path.write_text(PROFILE, encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _no_ambient_credentials(monkeypatch):
    """The CLI reads the real environment; pin it so results are deterministic."""
    for key in (
        "ASTA_API_KEY",
        "OPENAI_API_KEY",
        "CBORG_API_KEY",
        "EDISON_API_KEY",
        "EDISON_PLATFORM_API_KEY",
        "FUTUREHOUSE_API_KEY",
        "OPENSCIENTIST_API_KEY",
        "PERPLEXITY_API_KEY",
        "CONSENSUS_API_KEY",
        "ENABLE_MOCK_PROVIDER",
    ):
        monkeypatch.delenv(key, raising=False)


def test_providers_json_lists_the_whole_catalogue(capsys):
    assert main(["providers", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    from kg_microbe_research import PROVIDERS

    assert {row["provider"] for row in payload["providers"]} == set(PROVIDERS)


def test_providers_never_prints_a_credential_value(monkeypatch, capsys):
    monkeypatch.setenv("ASTA_API_KEY", "super-secret-token")
    assert main(["providers", "--json"]) == 0
    assert "super-secret-token" not in capsys.readouterr().out


def test_triage_reports_every_stage(profile_path, capsys):
    assert main(["triage", "--profile", str(profile_path), "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["mech"] == "TestMech"
    assert [stage["name"] for stage in report["stages"]] == ["discovery"]


def test_triage_of_an_invalid_profile_exits_nonzero(tmp_path, capsys):
    bad = tmp_path / "bad.yaml"
    bad.write_text("focuses: {}\n", encoding="utf-8")
    assert main(["triage", "--profile", str(bad)]) == 1
    assert "error:" in capsys.readouterr().err


def test_authorize_defaults_to_a_dry_run(monkeypatch, profile_path, capsys):
    monkeypatch.setenv("ASTA_API_KEY", "x")
    assert main(
        ["authorize", "--profile", str(profile_path), "--stage", "discovery", "--json"]
    ) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["permitted"] is True
    assert payload["mode"] == "dry-run"


def test_authorize_refuses_a_live_paid_call_with_exit_code_two(
    monkeypatch, profile_path, capsys
):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    exit_code = main(
        [
            "authorize",
            "--profile",
            str(profile_path),
            "--stage",
            "discovery",
            "--provider",
            "openai",
            "--apply",
            "--json",
        ]
    )
    assert exit_code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["permitted"] is False
    assert "paid authorization" in payload["error"]


def test_authorize_permits_the_same_call_once_the_charge_is_acknowledged(
    monkeypatch, profile_path, capsys
):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    exit_code = main(
        [
            "authorize",
            "--profile",
            str(profile_path),
            "--stage",
            "discovery",
            "--provider",
            "openai",
            "--apply",
            "--acknowledge-paid",
            "--json",
        ]
    )
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "live"
    assert payload["paid"] is True


def test_authorize_refuses_a_blocked_provider(monkeypatch, profile_path, capsys):
    monkeypatch.setenv("EDISON_API_KEY", "x")
    exit_code = main(
        [
            "authorize",
            "--profile",
            str(profile_path),
            "--stage",
            "discovery",
            "--provider",
            "falcon",
            "--apply",
            "--acknowledge-paid",
            "--json",
        ]
    )
    assert exit_code == 2
    assert "blocked" in json.loads(capsys.readouterr().out)["error"]


def test_an_unknown_max_cost_is_rejected_by_the_parser(profile_path):
    with pytest.raises(SystemExit):
        main(
            [
                "authorize",
                "--profile",
                str(profile_path),
                "--stage",
                "discovery",
                "--max-cost",
                "cheap",
            ]
        )


def test_a_missing_subcommand_exits_nonzero():
    with pytest.raises(SystemExit) as excinfo:
        main([])
    assert excinfo.value.code != 0


# --------------------------------------------------------------------------
# triage and authorize must not disagree (#136, #137, #138)
# --------------------------------------------------------------------------


def _triage_recommendation(profile_path: Path, capsys, *allow: str) -> str | None:
    args = ["triage", "--profile", str(profile_path), "--json"]
    for name in allow:
        args += ["--allow", name]
    assert main(args) == 0
    report = json.loads(capsys.readouterr().out)
    recommended = report["stages"][0]["recommended_available"]
    return None if recommended is None else recommended["provider"]


def _authorize_provider(profile_path: Path, capsys, *allow: str) -> str | None:
    args = ["authorize", "--profile", str(profile_path), "--stage", "discovery", "--json"]
    for name in allow:
        args += ["--allow", name]
    code = main(args)
    payload = json.loads(capsys.readouterr().out)
    return payload["provider"] if code == 0 else None


def test_triage_and_authorize_agree_on_an_aliased_allowlist(
    monkeypatch, profile_path, capsys
):
    """#136: triage said nothing fit while authorize routed to claude_code."""
    monkeypatch.setenv("ASTA_API_KEY", "x")
    monkeypatch.setattr(
        "kg_microbe_research.providers.SystemProbe.which",
        lambda self, executable: executable == "claude",
    )
    assert _triage_recommendation(profile_path, capsys, "claude-code") == "claude_code"
    assert _authorize_provider(profile_path, capsys, "claude-code") == "claude_code"


def test_triage_and_authorize_agree_on_a_canonical_allowlist(
    monkeypatch, profile_path, capsys
):
    monkeypatch.setenv("ASTA_API_KEY", "x")
    assert _triage_recommendation(profile_path, capsys, "asta") == "asta"
    assert _authorize_provider(profile_path, capsys, "asta") == "asta"


def test_triage_refuses_an_unknown_allowlist_entry(monkeypatch, profile_path, capsys):
    """#137: a typo'd --allow used to look like 'no provider fits' and exit 0."""
    monkeypatch.setenv("ASTA_API_KEY", "x")
    assert main(
        ["triage", "--profile", str(profile_path), "--allow", "nosuchprovider"]
    ) == 1
    assert "Unknown provider" in capsys.readouterr().err


def test_an_unknown_stage_is_reported_not_raised(profile_path, capsys):
    """#138: an unknown stage dumped a traceback while an unknown focus did not."""
    assert main(
        ["authorize", "--profile", str(profile_path), "--stage", "nosuchstage"]
    ) == 1
    err = capsys.readouterr().err
    assert "error:" in err
    assert "discovery" in err, "the message must name the available stages"
    assert "Traceback" not in err


def test_an_unknown_focus_and_an_unknown_stage_fail_the_same_way(
    profile_path, capsys
):
    assert main(["triage", "--profile", str(profile_path), "--focus", "nope"]) == 1
    focus_error = capsys.readouterr().err
    assert main(
        ["authorize", "--profile", str(profile_path), "--stage", "nope"]
    ) == 1
    stage_error = capsys.readouterr().err
    assert focus_error.startswith("error:")
    assert stage_error.startswith("error:")


def test_providers_json_paid_flag_agrees_with_the_one_predicate(capsys):
    """#139: the CLI hardcoded {"high", "very_high"} instead of reading PAID_COSTS."""
    from kg_microbe_research import is_paid

    assert main(["providers", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)["providers"]
    assert rows, "no providers reported"
    for row in rows:
        assert row["paid"] is is_paid(row["provider"]), row["provider"]
