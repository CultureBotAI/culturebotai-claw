"""CLI contracts for `kg-microbe-research`.

The exit codes matter as much as the output: a caller gates a real run on
`authorize`, so only a live authorization may exit zero. A dry-run report exits
three and a policy refusal exits two.
"""

from __future__ import annotations

import json
import textwrap
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from kg_microbe_research.__main__ import main

PROFILE = textwrap.dedent(
    """\
    mech: TestMech
    target: things
    evidence_policy: cite every claim
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

RESULT_PROFILE = textwrap.dedent(
    """\
    mech: CultureMech
    target: culturing media
    evidence_policy: cite every material claim with an exact snippet
    default_focus: primary
    focuses:
      primary:
        label: growth evidence
        objective: find and verify explicit organism-medium growth evidence
        source_priorities:
          - primary cultivation studies
        provider_adjustments: {asta: 20}
        stages:
          discovery:
            objective: find source-backed leads
            capabilities: {academic_search: 4, scientific_literature: 4, snippets: 2}
            speed_weight: 1
          verification:
            objective: independently verify identifiers and quoted evidence
            capabilities: {citation_tracking: 5, scientific_literature: 3, snippets: 2}
            cost_weight: 1
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


@pytest.fixture
def availability_path(tmp_path: Path) -> Path:
    """Strict cached evidence consumed by the real CLI path; no provider call."""
    path = tmp_path / "availability.json"
    checked_at = datetime.now(timezone.utc)
    expires_at = checked_at + timedelta(hours=1)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "providers": {
                    name: {
                        "status": "available",
                        "reason": "offline CLI test attestation",
                        "checked_at": checked_at.isoformat(),
                        "expires_at": expires_at.isoformat(),
                        "source": "pytest-static-fixture",
                        "context": "isolated fake credential and local tooling",
                    }
                    for name in {
                        "asta",
                        "openai",
                        "cborg",
                        "claude_code",
                        "falcon",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_asta_availability(path: Path, *, status: str) -> Path:
    checked_at = datetime.now(timezone.utc)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "providers": {
                    "asta": {
                        "status": status,
                        "reason": f"offline scaffold fixture: {status}",
                        "checked_at": checked_at.isoformat(),
                        "expires_at": (checked_at + timedelta(hours=1)).isoformat(),
                        "source": "pytest-offline-scaffold",
                        "context": "fake ASTA credential; no provider execution",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def result_repository(tmp_path: Path) -> dict[str, Path | str]:
    repository = tmp_path / "CultureMech"
    profile = repository / "conf" / "deep_research_provider.yaml"
    target = repository / "data" / "normalized_yaml" / "offline_medium.yaml"
    profile.parent.mkdir(parents=True)
    target.parent.mkdir(parents=True)
    profile.write_text(RESULT_PROFILE, encoding="utf-8")
    target.write_text(
        "id: CultureMech:000001\nname: Offline medium\n",
        encoding="utf-8",
    )
    availability = _write_asta_availability(
        repository / "availability.json", status="available"
    )
    return {
        "repository": repository,
        "profile": "conf/deep_research_provider.yaml",
        "target": "data/normalized_yaml/offline_medium.yaml",
        "availability": availability,
        "output": "research/runs/offline-result.yaml",
    }


def _scaffold_result_args(layout: dict[str, Path | str]) -> list[str]:
    return [
        "scaffold-result",
        "--repository-root",
        str(layout["repository"]),
        "--profile",
        str(layout["profile"]),
        "--availability-evidence",
        str(layout["availability"]),
        "--target-path",
        str(layout["target"]),
        "--target-id",
        "CultureMech:000001",
        "--target-label",
        "Offline medium",
        "--target-type",
        "growth medium",
        "--question",
        "Which organisms have explicit source-backed growth on this exact medium?",
        "--question-id",
        "question-offline-medium",
        "--allow",
        "asta",
        "--output",
        str(layout["output"]),
    ]


def test_providers_json_lists_the_whole_catalogue(capsys):
    assert main(["providers", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    from kg_microbe_research import PROVIDERS

    assert {row["provider"] for row in payload["providers"]} == set(PROVIDERS)


def test_providers_never_prints_a_credential_value(monkeypatch, capsys):
    monkeypatch.setenv("ASTA_API_KEY", "super-secret-token")
    assert main(["providers", "--json"]) == 0
    captured = capsys.readouterr()
    assert "super-secret-token" not in captured.out
    assert "super-secret-token" not in captured.err


def test_providers_reports_a_credential_as_configured_not_available(monkeypatch, capsys):
    monkeypatch.setenv("ASTA_API_KEY", "x")
    assert main(["providers", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)["providers"]
    asta = next(row for row in rows if row["provider"] == "asta")
    assert asta["status"] == "configured"


def test_providers_combines_configuration_with_cached_availability_evidence(
    monkeypatch, availability_path, capsys
):
    monkeypatch.setenv("ASTA_API_KEY", "x")
    assert (
        main(
            [
                "providers",
                "--availability-evidence",
                str(availability_path),
                "--json",
            ]
        )
        == 0
    )
    rows = json.loads(capsys.readouterr().out)["providers"]
    asta = next(row for row in rows if row["provider"] == "asta")
    assert asta["status"] == "available"
    assert asta["status_reason"].startswith("offline CLI test attestation;")


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


def test_authorize_dry_run_never_exits_as_an_execution_gate(
    monkeypatch, availability_path, profile_path, capsys
):
    monkeypatch.setenv("ASTA_API_KEY", "x")
    assert (
        main(
            [
                "authorize",
                "--profile",
                str(profile_path),
                "--availability-evidence",
                str(availability_path),
                "--stage",
                "discovery",
                "--json",
            ]
        )
        == 3
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["execution_authorized"] is False
    assert payload["mode"] == "dry-run"


def test_authorize_refuses_configuration_without_verified_availability(
    monkeypatch, profile_path, capsys
):
    monkeypatch.setenv("ASTA_API_KEY", "x")
    assert (
        main(
            [
                "authorize",
                "--profile",
                str(profile_path),
                "--stage",
                "discovery",
                "--provider",
                "asta",
                "--apply",
                "--acknowledge-usage",
                "--json",
            ]
        )
        == 2
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["execution_authorized"] is False
    assert "configured" in payload["error"]


def test_authorize_refuses_a_live_paid_call_with_exit_code_two(
    monkeypatch, availability_path, profile_path, capsys
):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    exit_code = main(
        [
            "authorize",
            "--profile",
            str(profile_path),
            "--availability-evidence",
            str(availability_path),
            "--stage",
            "discovery",
            "--provider",
            "openai",
            "--override-reason",
            "exercise the usage gate for a non-primary provider",
            "--apply",
            "--json",
        ]
    )
    assert exit_code == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["execution_authorized"] is False
    assert "usage authorization" in payload["error"]


def test_authorize_permits_the_same_call_once_the_charge_is_acknowledged(
    monkeypatch, availability_path, profile_path, capsys
):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    exit_code = main(
        [
            "authorize",
            "--profile",
            str(profile_path),
            "--availability-evidence",
            str(availability_path),
            "--stage",
            "discovery",
            "--provider",
            "openai",
            "--override-reason",
            "exercise an explicitly selected non-primary provider",
            "--apply",
            "--acknowledge-usage",
            "--json",
        ]
    )
    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["mode"] == "live"
    assert payload["execution_authorized"] is True
    assert payload["usage_authorization_required"] is True


def test_authorize_refuses_an_eligible_fallback_without_an_override_reason(
    monkeypatch, availability_path, profile_path, capsys
):
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    exit_code = main(
        [
            "authorize",
            "--profile",
            str(profile_path),
            "--availability-evidence",
            str(availability_path),
            "--stage",
            "discovery",
            "--provider",
            "openai",
            "--apply",
            "--acknowledge-usage",
            "--json",
        ]
    )

    assert exit_code == 2
    payload = json.loads(capsys.readouterr().out)
    assert "eligible fallback" in payload["error"]
    assert "override reason" in payload["error"]


def test_authorize_refuses_a_blocked_provider(monkeypatch, availability_path, profile_path, capsys):
    monkeypatch.setenv("EDISON_API_KEY", "x")
    exit_code = main(
        [
            "authorize",
            "--profile",
            str(profile_path),
            "--availability-evidence",
            str(availability_path),
            "--stage",
            "discovery",
            "--provider",
            "falcon",
            "--apply",
            "--acknowledge-usage",
            "--json",
        ]
    )
    assert exit_code == 2
    assert "blocked" in json.loads(capsys.readouterr().out)["error"]


def test_authorize_no_paid_is_a_hard_cli_exclusion(
    monkeypatch, availability_path, profile_path, capsys
):
    monkeypatch.setenv("ASTA_API_KEY", "x")
    assert (
        main(
            [
                "authorize",
                "--profile",
                str(profile_path),
                "--availability-evidence",
                str(availability_path),
                "--stage",
                "discovery",
                "--provider",
                "asta",
                "--no-paid",
                "--apply",
                "--acknowledge-usage",
                "--override-reason",
                "caller tries every gate",
                "--json",
            ]
        )
        == 2
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["execution_authorized"] is False
    assert "hard exclusion cannot be overridden" in payload["error"]


def test_malformed_availability_evidence_fails_closed(tmp_path, capsys):
    path = tmp_path / "bad-availability.json"
    path.write_text("not json", encoding="utf-8")
    assert main(["providers", "--availability-evidence", str(path), "--json"]) == 1
    assert "not valid JSON" in capsys.readouterr().err


def test_scaffold_and_validate_result_are_offline_append_only_and_secret_free(
    monkeypatch, result_repository, capsys
):
    secret = "ASTA-SECRET-MUST-NOT-LEAK"
    monkeypatch.setenv("ASTA_API_KEY", secret)

    def provider_execution_is_forbidden(*args, **kwargs):
        raise AssertionError(f"scaffold-result attempted provider execution: {args!r} {kwargs!r}")

    monkeypatch.setattr("subprocess.run", provider_execution_is_forbidden)
    args = _scaffold_result_args(result_repository)
    repository = Path(result_repository["repository"])
    output = repository / str(result_repository["output"])

    assert main(args) == 0
    scaffold_output = capsys.readouterr()
    assert output.is_file()
    original = output.read_bytes()
    document = yaml.safe_load(original)
    assert document["research_version"] == 1
    assert document["status"] == "DRY_RUN"
    assert [run["stage"] for run in document["runs"]] == ["discovery", "verification"]
    assert all(run["mode"] == "DRY_RUN" for run in document["runs"])
    assert all(run["status"] == "DRY_RUN" for run in document["runs"])
    assert all(run["provider_called"] is False for run in document["runs"])
    assert all(run["live_authorized"] is False for run in document["runs"])
    assert all(run["requested_provider"] == "asta" for run in document["runs"])
    assert all(
        assignment["provider"] == "asta"
        for assignment in document["plan"]["stage_assignments"]
    )
    assert secret not in original.decode("utf-8")
    assert secret not in scaffold_output.out
    assert secret not in scaffold_output.err

    assert (
        main(
            [
                "validate-result",
                str(result_repository["output"]),
                "--repository-root",
                str(repository),
                "--verify-snapshots",
            ]
        )
        == 0
    )
    validated = capsys.readouterr()
    assert "OK:" in validated.err
    assert secret not in validated.out
    assert secret not in validated.err

    assert main(args) == 1
    refused = capsys.readouterr()
    assert "append-only" in refused.err
    assert output.read_bytes() == original
    assert secret not in refused.out
    assert secret not in refused.err


def test_scaffold_result_refuses_unavailable_evidence_without_output(
    monkeypatch, result_repository, capsys
):
    secret = "ASTA-UNAVAILABLE-SECRET"
    monkeypatch.setenv("ASTA_API_KEY", secret)
    unavailable = _write_asta_availability(
        Path(result_repository["repository"]) / "unavailable.json",
        status="unavailable",
    )
    result_repository["availability"] = unavailable
    result_repository["output"] = "research/runs/unavailable-result.yaml"

    assert main(_scaffold_result_args(result_repository)) == 1
    captured = capsys.readouterr()
    output = Path(result_repository["repository"]) / str(result_repository["output"])
    assert not output.exists()
    assert captured.err.startswith("error:")
    assert "no provider is available" in captured.err
    assert "made no provider call" in captured.err
    assert "Traceback" not in captured.err
    assert secret not in captured.out
    assert secret not in captured.err


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


def _triage_recommendation(
    profile_path: Path, availability_path: Path, capsys, *allow: str
) -> str | None:
    args = [
        "triage",
        "--profile",
        str(profile_path),
        "--availability-evidence",
        str(availability_path),
        "--json",
    ]
    for name in allow:
        args += ["--allow", name]
    assert main(args) == 0
    report = json.loads(capsys.readouterr().out)
    recommended = report["stages"][0]["recommended_available"]
    return None if recommended is None else recommended["provider"]


def _authorize_provider(
    profile_path: Path, availability_path: Path, capsys, *allow: str
) -> str | None:
    args = [
        "authorize",
        "--profile",
        str(profile_path),
        "--availability-evidence",
        str(availability_path),
        "--stage",
        "discovery",
        "--json",
    ]
    for name in allow:
        args += ["--allow", name]
    code = main(args)
    payload = json.loads(capsys.readouterr().out)
    return payload["provider"] if code == 3 else None


def test_triage_and_authorize_agree_on_an_aliased_allowlist(
    monkeypatch, availability_path, profile_path, capsys
):
    """#136: triage said nothing fit while authorize routed to claude_code."""
    monkeypatch.setenv("ASTA_API_KEY", "x")
    monkeypatch.setattr(
        "kg_microbe_research.providers.SystemProbe.which",
        lambda self, executable: executable == "claude",
    )
    assert (
        _triage_recommendation(profile_path, availability_path, capsys, "claude-code")
        == "claude_code"
    )
    assert (
        _authorize_provider(profile_path, availability_path, capsys, "claude-code") == "claude_code"
    )


def test_triage_and_authorize_agree_on_a_canonical_allowlist(
    monkeypatch, availability_path, profile_path, capsys
):
    monkeypatch.setenv("ASTA_API_KEY", "x")
    assert _triage_recommendation(profile_path, availability_path, capsys, "asta") == ("asta")
    assert _authorize_provider(profile_path, availability_path, capsys, "asta") == ("asta")


def test_triage_refuses_an_unknown_allowlist_entry(monkeypatch, profile_path, capsys):
    """#137: a typo'd --allow used to look like 'no provider fits' and exit 0."""
    monkeypatch.setenv("ASTA_API_KEY", "x")
    assert main(["triage", "--profile", str(profile_path), "--allow", "nosuchprovider"]) == 1
    assert "Unknown provider" in capsys.readouterr().err


def test_authorize_planning_refusal_uses_json_and_exit_code_two(profile_path, capsys):
    assert (
        main(
            [
                "authorize",
                "--profile",
                str(profile_path),
                "--stage",
                "discovery",
                "--allow",
                "nosuchprovider",
                "--json",
            ]
        )
        == 2
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["execution_authorized"] is False
    assert "Unknown provider" in payload["error"]


def test_an_unknown_stage_is_reported_not_raised(profile_path, capsys):
    """#138: an unknown stage dumped a traceback while an unknown focus did not."""
    assert main(["authorize", "--profile", str(profile_path), "--stage", "nosuchstage"]) == 1
    err = capsys.readouterr().err
    assert "error:" in err
    assert "discovery" in err, "the message must name the available stages"
    assert "Traceback" not in err


def test_an_unknown_focus_and_an_unknown_stage_fail_the_same_way(profile_path, capsys):
    assert main(["triage", "--profile", str(profile_path), "--focus", "nope"]) == 1
    focus_error = capsys.readouterr().err
    assert main(["authorize", "--profile", str(profile_path), "--stage", "nope"]) == 1
    stage_error = capsys.readouterr().err
    assert focus_error.startswith("error:")
    assert stage_error.startswith("error:")


def test_providers_json_usage_flag_agrees_with_the_one_predicate(capsys):
    from kg_microbe_research import requires_usage_authorization

    assert main(["providers", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)["providers"]
    assert rows, "no providers reported"
    for row in rows:
        assert row["usage_authorization_required"] is requires_usage_authorization(
            row["provider"]
        ), row["provider"]
