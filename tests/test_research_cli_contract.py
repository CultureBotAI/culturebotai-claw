"""The CLI's machine-readable contract: exit codes, and unsatisfiable flags.

The exit code is the half of this tool's contract a wrapper script actually
reads, and `--no-paid` is the half a Mech tool passes without looking. Both had
drifted from what CLAUDE.md documents (#152, #153).
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest

from kg_microbe_research import PROVIDERS, PolicyInputError
from kg_microbe_research import providers as providers_module
from kg_microbe_research.__main__ import main

FIXTURE = (
    Path(__file__).parent / "fixtures" / "research_profiles" / "culturemech.yaml"
)

# Documented in CLAUDE.md: 0 live authorization, 2 policy refusal, 3 permitted
# dry run. Everything malformed is 1.
LIVE_AUTHORIZED = 0
MALFORMED_INPUT = 1
POLICY_REFUSAL = 2
PERMITTED_DRY_RUN = 3


@pytest.fixture(autouse=True)
def _no_ambient_credentials(monkeypatch):
    for key in (
        "ASTA_API_KEY", "OPENAI_API_KEY", "CBORG_API_KEY", "EDISON_API_KEY",
        "EDISON_PLATFORM_API_KEY", "FUTUREHOUSE_API_KEY", "OPENSCIENTIST_API_KEY",
        "PERPLEXITY_API_KEY", "CONSENSUS_API_KEY", "ENABLE_MOCK_PROVIDER",
    ):
        monkeypatch.delenv(key, raising=False)


def _run(monkeypatch, argv: list[str]) -> int:
    """Run the CLI, converting argparse's SystemExit into its exit code."""
    try:
        return main(argv)
    except SystemExit as exc:  # argparse usage errors
        return int(exc.code or 0)


# --------------------------------------------------------------------------
# #153: exit codes
# --------------------------------------------------------------------------


MALFORMED_INVOCATIONS = {
    "unknown-subcommand": ["nosuchcommand"],
    "missing-required-stage": ["authorize", "--profile", str(FIXTURE)],
    "bad-max-cost-choice": [
        "authorize", "--profile", str(FIXTURE), "--stage", "discovery",
        "--max-cost", "cheap",
    ],
    "unknown-stage": [
        "authorize", "--profile", str(FIXTURE), "--stage", "nosuchstage",
    ],
    "unknown-focus": ["triage", "--profile", str(FIXTURE), "--focus", "nope"],
    "unknown-allow-authorize": [
        "authorize", "--profile", str(FIXTURE), "--stage", "discovery",
        "--allow", "nosuchprovider",
    ],
    "unknown-allow-triage": [
        "triage", "--profile", str(FIXTURE), "--allow", "nosuchprovider",
    ],
    "missing-profile-file": [
        "triage", "--profile", "/nonexistent/deep_research_provider.yaml",
    ],
}


@pytest.mark.parametrize(
    "argv", list(MALFORMED_INVOCATIONS.values()), ids=list(MALFORMED_INVOCATIONS)
)
def test_every_malformed_invocation_exits_one(monkeypatch, argv):
    """argparse exits 2 by default, which this CLI reserves for a policy refusal.

    A caller reading exit 2 as "policy said no, try another provider" must not
    receive it for a typo, a missing argument, or a bad subcommand.
    """
    assert _run(monkeypatch, argv) == MALFORMED_INPUT


def test_a_policy_refusal_is_the_only_thing_that_exits_two(monkeypatch, tmp_path):
    """The one case the docs actually reserve 2 for."""
    monkeypatch.setenv("OPENAI_API_KEY", "x")
    evidence = _evidence(tmp_path, "openai")
    assert _run(monkeypatch, [
        "authorize", "--profile", str(FIXTURE), "--stage", "discovery",
        "--provider", "openai", "--apply",
        "--availability-evidence", str(evidence),
    ]) == POLICY_REFUSAL


def test_a_permitted_dry_run_exits_three(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("ASTA_API_KEY", "x")
    evidence = _evidence(tmp_path, "asta")
    code = _run(monkeypatch, [
        "authorize", "--profile", str(FIXTURE), "--stage", "discovery",
        "--availability-evidence", str(evidence), "--json",
    ])
    assert code == PERMITTED_DRY_RUN
    assert json.loads(capsys.readouterr().out)["mode"] == "dry-run"


def test_live_authorization_exits_zero(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("ASTA_API_KEY", "x")
    evidence = _evidence(tmp_path, "asta")
    code = _run(monkeypatch, [
        "authorize", "--profile", str(FIXTURE), "--stage", "discovery",
        "--apply", "--acknowledge-usage",
        "--availability-evidence", str(evidence), "--json",
    ])
    assert code == LIVE_AUTHORIZED
    assert json.loads(capsys.readouterr().out)["execution_authorized"] is True


def test_the_four_documented_codes_are_distinct():
    codes = {LIVE_AUTHORIZED, MALFORMED_INPUT, POLICY_REFUSAL, PERMITTED_DRY_RUN}
    assert len(codes) == 4


# --------------------------------------------------------------------------
# #152: --no-paid must not silently return nothing
# --------------------------------------------------------------------------


def test_triage_says_why_no_paid_returned_nothing(monkeypatch, capsys):
    """`mock` is the only free provider and is never recommended, so the flag
    returns the empty set for every profile, stage, and configuration.

    Reported bare, that is indistinguishable from a misconfigured profile. The
    filter still runs -- it is not short-circuited -- so `--no-paid` remains a
    hard exclusion at the policy layer; only the silence is fixed.
    """
    assert providers_module.no_paid_candidates() == ()
    assert _run(monkeypatch, [
        "triage", "--profile", str(FIXTURE), "--no-paid",
    ]) == MALFORMED_INPUT
    message = capsys.readouterr().err
    assert "--no-paid cannot currently be satisfied" in message
    assert "--max-cost" in message, "the message must say what to use instead"


def test_the_triage_json_payload_carries_the_same_explanation(monkeypatch, capsys):
    """A --json caller must not have to parse stderr to learn this."""
    assert _run(monkeypatch, [
        "triage", "--profile", str(FIXTURE), "--no-paid", "--json",
    ]) == MALFORMED_INPUT
    report = json.loads(capsys.readouterr().out)
    assert "--no-paid cannot currently be satisfied" in report["no_paid_unsatisfiable"]


def test_authorize_explains_an_unsatisfiable_no_paid_in_its_refusal(
    monkeypatch, capsys
):
    """The refusal is still a policy refusal (exit 2) -- it now says why."""
    assert _run(monkeypatch, [
        "authorize", "--profile", str(FIXTURE), "--stage", "discovery",
        "--no-paid", "--json",
    ]) == POLICY_REFUSAL
    error = json.loads(capsys.readouterr().out)["error"]
    assert "no-paid" in error
    assert "--no-paid cannot currently be satisfied" in error


def test_no_paid_remains_a_hard_exclusion_and_is_not_short_circuited(
    monkeypatch, tmp_path, capsys
):
    """The diagnostic must not replace the filter.

    An upfront refusal would have made this safety property -- that --no-paid
    cannot be overridden, even with every other gate satisfied -- unreachable
    from the CLI.
    """
    monkeypatch.setenv("ASTA_API_KEY", "x")
    evidence = _evidence(tmp_path, "asta")
    assert _run(monkeypatch, [
        "authorize", "--profile", str(FIXTURE), "--stage", "discovery",
        "--provider", "asta", "--no-paid", "--apply", "--acknowledge-usage",
        "--override-reason", "caller tries every gate",
        "--availability-evidence", str(evidence), "--json",
    ]) == POLICY_REFUSAL
    assert json.loads(capsys.readouterr().out)["execution_authorized"] is False


def test_a_malformed_allowlist_still_produces_a_json_payload(monkeypatch, capsys):
    """Exit code 1 must not cost --json callers their machine-readable refusal."""
    assert _run(monkeypatch, [
        "authorize", "--profile", str(FIXTURE), "--stage", "discovery",
        "--allow", "nosuchprovider", "--json",
    ]) == MALFORMED_INPUT
    payload = json.loads(capsys.readouterr().out)
    assert payload["execution_authorized"] is False
    assert "Unknown provider" in payload["error"]


def test_the_guard_stands_down_as_soon_as_a_provider_is_classified_free(
    monkeypatch, capsys
):
    """It must track the catalogue, not hardcode a permanent refusal.

    Without this, reclassifying a provider's billing would leave a flag that
    still refuses for a reason that is no longer true.
    """
    monkeypatch.setitem(
        providers_module.PROVIDERS,
        "cborg",
        dataclasses.replace(PROVIDERS["cborg"], billing="free"),
    )
    assert providers_module.no_paid_candidates() == ("cborg",)
    assert _run(monkeypatch, [
        "triage", "--profile", str(FIXTURE), "--no-paid", "--json",
    ]) == 0
    assert "no_paid_unsatisfiable" not in json.loads(capsys.readouterr().out)


def test_no_paid_candidates_never_includes_an_unrecommendable_provider():
    """The satisfiability check and `recommendable` must not disagree."""
    assert providers_module.NEVER_RECOMMENDED
    assert not set(providers_module.no_paid_candidates()) & (
        providers_module.NEVER_RECOMMENDED
    )
    assert "mock" in providers_module.free_providers()
    assert "mock" in providers_module.NEVER_RECOMMENDED


def test_the_satisfiability_error_is_input_not_policy():
    """It must not be a PolicyError, or the CLI would report it as exit 2."""
    assert not issubclass(PolicyInputError, RuntimeError)
    from kg_microbe_research import PolicyError

    assert not issubclass(PolicyInputError, PolicyError)


def _evidence(tmp_path: Path, *names: str) -> Path:
    """Attested-available evidence for `names`, valid for an hour."""
    import datetime

    now = datetime.datetime.now(datetime.timezone.utc)
    stamp = lambda moment: moment.isoformat().replace("+00:00", "Z")  # noqa: E731
    path = tmp_path / "availability.json"
    path.write_text(json.dumps({
        "version": 1,
        "providers": {
            name: {
                "status": "available",
                "reason": "preflight succeeded",
                "checked_at": stamp(now),
                "expires_at": stamp(now + datetime.timedelta(hours=1)),
                "source": "test-preflight",
                "context": "offline contract test",
            }
            for name in names
        },
    }), encoding="utf-8")
    return path


# --------------------------------------------------------------------------
# #155: every command that accepts --no-paid must explain an empty result
# --------------------------------------------------------------------------


def _scaffold_repository(tmp_path: Path) -> Path:
    """A minimal repository the scaffold command will accept."""
    root = tmp_path / "repo"
    (root / "conf").mkdir(parents=True)
    (root / "research").mkdir(parents=True)
    (root / "conf" / "deep_research_provider.yaml").write_text(
        FIXTURE.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (root / "research" / "target.yaml").write_text("id: TEST:1\n", encoding="utf-8")
    return root


def _no_paid_invocation(command: str, tmp_path: Path) -> list[str]:
    if command == "triage":
        return ["triage", "--profile", str(FIXTURE), "--no-paid"]
    if command == "authorize":
        return [
            "authorize", "--profile", str(FIXTURE), "--stage", "discovery", "--no-paid",
        ]
    root = _scaffold_repository(tmp_path)
    return [
        "scaffold-result", "--repository-root", str(root),
        "--profile", "conf/deep_research_provider.yaml",
        "--target-path", "research/target.yaml",
        "--target-id", "TEST:1", "--target-label", "t", "--target-type", "medium",
        "--question", "q", "--output", "research/result.yaml",
        "--availability-evidence", str(_evidence(tmp_path, "asta", "cborg")),
        "--no-paid",
    ]


@pytest.mark.parametrize("command", ["triage", "authorize", "scaffold-result"])
def test_every_no_paid_command_explains_an_unsatisfiable_flag(
    monkeypatch, tmp_path, capsys, command
):
    """One test for all three, because fixing them one at a time is what let
    `scaffold-result` slip after #152 was closed for the other two.

    `scaffold-result` is the worst place to be silent: it reports the empty
    result as "no provider is available for this target", which reads as a
    claim about the research target rather than about a flag.
    """
    monkeypatch.setenv("ASTA_API_KEY", "x")
    monkeypatch.setenv("CBORG_API_KEY", "x")
    assert providers_module.no_paid_candidates() == ()

    code = _run(monkeypatch, _no_paid_invocation(command, tmp_path))

    assert code != 0, f"{command} --no-paid should not succeed while unsatisfiable"
    output = capsys.readouterr()
    combined = output.out + output.err
    assert "--no-paid cannot currently be satisfied" in combined, (
        f"{command} gave no explanation for an empty --no-paid result"
    )
    assert "--max-cost" in combined


@pytest.mark.parametrize("command", ["triage", "authorize", "scaffold-result"])
def test_no_command_mentions_no_paid_when_the_flag_is_not_passed(
    monkeypatch, tmp_path, capsys, command
):
    """The explanation must not leak into unrelated failures."""
    monkeypatch.setenv("ASTA_API_KEY", "x")
    monkeypatch.setenv("CBORG_API_KEY", "x")
    argv = [arg for arg in _no_paid_invocation(command, tmp_path) if arg != "--no-paid"]

    _run(monkeypatch, argv)

    output = capsys.readouterr()
    assert "--no-paid cannot currently be satisfied" not in output.out + output.err
