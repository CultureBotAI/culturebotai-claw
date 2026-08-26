"""Contracts for the shared provider catalogue, profile loader, and triage.

Every test here is offline and deterministic: configuration, local tooling, and
previously verified availability are injected separately. No test contacts a
provider or depends on the developer's machine.
"""

from __future__ import annotations

import gc
import textwrap
import weakref
from dataclasses import replace
from pathlib import Path

import pytest

from kg_microbe_research import (
    ALL_CAPABILITIES,
    BILLING_CLASSES,
    COST_VALUE,
    CREDENTIALS,
    KNOWN_BLOCKED,
    PROVIDERS,
    SYNTHESIS_VALUE,
    TIME_VALUE,
    ProfileError,
    StaticAvailability,
    StaticProbe,
    build_report,
    canonical_provider,
    credential_status,
    load_profile,
    parse_profile,
    provider_status,
    rank_stage,
    recommendable,
    requires_usage_authorization,
)

NO_LOCAL_TOOLING = StaticProbe()
VERIFIED = StaticAvailability(
    {
        name: ("available", "offline test attestation")
        for name in {"asta", "openai", "perplexity", "cborg", "claude_code"}
    }
)


class WeakSecret(str):
    """A string whose lifetime can prove configuration checks do not cache it."""

    __slots__ = ("__weakref__",)


MINIMAL = textwrap.dedent(
    """\
    mech: TestMech
    target: things
    evidence_policy: cite every claim
    default_focus: primary
    focuses:
      primary:
        label: primary focus
        objective: find things
        source_priorities:
          - literature
        provider_adjustments: {asta: 2}
        stages:
          discovery:
            objective: find
            capabilities: {academic_search: 4, snippets: 2}
            speed_weight: 1
    """
)


def write_profile(tmp_path: Path, text: str = MINIMAL) -> Path:
    path = tmp_path / "deep_research_provider.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def variant(old: str, new: str) -> str:
    """MINIMAL with `old` replaced, refusing a no-op.

    Without this guard a stale indentation in `old` makes the substitution
    silently do nothing, so the "invalid" profile under test is really the
    valid one and every negative assertion passes for the wrong reason.
    """
    if old not in MINIMAL:
        raise AssertionError(f"variant() found no occurrence of {old!r} in MINIMAL")
    return MINIMAL.replace(old, new)


# --------------------------------------------------------------------------
# Catalogue integrity
# --------------------------------------------------------------------------


def test_every_provider_uses_a_known_cost_time_and_synthesis_vocabulary():
    """A typo in any of these scores silently rather than failing (KeyError in _score)."""
    for name, provider in PROVIDERS.items():
        assert provider.cost in COST_VALUE, name
        assert provider.billing in BILLING_CLASSES, name
        assert provider.time in TIME_VALUE, name
        assert provider.synthesis in SYNTHESIS_VALUE, name


def test_provider_dataclass_key_matches_its_name():
    for key, provider in PROVIDERS.items():
        assert key == provider.name


def test_every_alias_resolves_to_a_real_provider():
    from kg_microbe_research import ALIASES

    for alias, target in ALIASES.items():
        assert target in PROVIDERS, alias
        assert canonical_provider(alias) == target


def test_known_blocked_names_are_real_providers():
    for name in KNOWN_BLOCKED:
        assert name in PROVIDERS


def test_credential_table_names_only_real_providers():
    for name in CREDENTIALS:
        assert name in PROVIDERS


def test_all_capabilities_is_derived_not_hand_maintained():
    declared = {cap for provider in PROVIDERS.values() for cap in provider.capabilities}
    assert ALL_CAPABILITIES == declared


def test_canonical_provider_normalizes_spacing_and_case():
    assert canonical_provider("  Claude Code ") == "claude_code"
    assert canonical_provider("EDISON") == "falcon"


# --------------------------------------------------------------------------
# Status: blocked beats configured
# --------------------------------------------------------------------------


def test_a_blocked_provider_reports_blocked_even_with_its_credential_set():
    """The whole point of KNOWN_BLOCKED: falcon returned HTTP 402 while configured."""
    status, reason = provider_status("falcon", {"EDISON_API_KEY": "set"})
    assert status == "blocked"
    assert reason == KNOWN_BLOCKED["falcon"]


def test_credential_status_still_recognises_a_blocked_providers_variables():
    """Otherwise adding a provider to KNOWN_BLOCKED silently drops its alias test."""
    assert credential_status("falcon", {"FUTUREHOUSE_API_KEY": "set"})[0] == "configured"
    assert credential_status("falcon", {})[0] == "unavailable"


def test_an_empty_credential_value_does_not_count_as_configured():
    assert credential_status("asta", {"ASTA_API_KEY": ""})[0] == "unavailable"


def test_local_tooling_status_is_injectable_and_does_not_read_the_machine():
    """Without an injectable probe these two answers vary by developer machine."""
    absent = credential_status("claude_code", {}, NO_LOCAL_TOOLING)
    present = credential_status("claude_code", {}, StaticProbe(executables=frozenset({"claude"})))
    assert absent == ("unavailable", "claude CLI not found")
    assert present == ("configured", "local CLI found")

    assert credential_status("cyberian", {}, NO_LOCAL_TOOLING)[0] == "unavailable"


def test_mock_provider_requires_an_explicit_opt_in():
    assert credential_status("mock", {})[0] == "unavailable"
    assert credential_status("mock", {"ENABLE_MOCK_PROVIDER": "true"})[0] == "configured"
    assert provider_status("mock", {"ENABLE_MOCK_PROVIDER": "true"})[0] == "stub"


def test_injected_evidence_cannot_make_the_unimplemented_mock_routable():
    evidence = StaticAvailability({"mock": ("available", "caller assertion")})
    assert (
        provider_status(
            "mock",
            {"ENABLE_MOCK_PROVIDER": "true"},
            availability=evidence,
        )[0]
        == "stub"
    )


def test_credential_status_never_returns_the_credential_value():
    secret = "super-secret-token"
    status, reason = credential_status("asta", {"ASTA_API_KEY": secret})
    assert status == "configured"
    assert secret not in reason


def test_credential_status_does_not_retain_the_credential_value():
    secret = WeakSecret("ephemeral-super-secret-token")
    reference = weakref.ref(secret)
    environment = {"ASTA_API_KEY": secret}
    assert credential_status("asta", environment)[0] == "configured"
    del environment
    del secret
    gc.collect()
    assert reference() is None


def test_configuration_is_not_functional_availability():
    assert provider_status("asta", {"ASTA_API_KEY": "x"})[0] == "configured"
    assert provider_status("asta", {"ASTA_API_KEY": "x"}, availability=VERIFIED) == (
        "available",
        "offline test attestation",
    )


def test_availability_evidence_does_not_replace_required_configuration():
    assert provider_status("asta", {}, availability=VERIFIED)[0] == "unavailable"


def test_known_blockage_overrides_injected_available_evidence():
    evidence = StaticAvailability({"falcon": ("available", "stale attestation")})
    assert provider_status("edison", {"EDISON_API_KEY": "x"}, availability=evidence) == (
        "blocked",
        KNOWN_BLOCKED["falcon"],
    )


def test_status_apis_canonicalize_aliases():
    assert credential_status("edison", {"EDISON_API_KEY": "x"})[0] == "configured"
    assert provider_status("edison", {"EDISON_API_KEY": "x"})[0] == "blocked"


def test_static_availability_refuses_unknown_or_malformed_evidence():
    with pytest.raises(ValueError, match="unknown provider"):
        StaticAvailability({"nosuchprovider": ("available", "fixture")})
    with pytest.raises(ValueError, match="non-empty reason"):
        StaticAvailability({"asta": ("available", "")})
    with pytest.raises(ValueError, match="availability evidence must be"):
        StaticAvailability({"asta": ([], "fixture")})  # type: ignore[dict-item]
    with pytest.raises(ValueError, match="multiple names resolving"):
        StaticAvailability(
            {
                "falcon": ("blocked", "first"),
                "edison": ("available", "second"),
            }
        )


def test_static_availability_copies_and_freezes_its_mapping():
    source = {"asta": ("available", "fixture")}
    evidence = StaticAvailability(source)
    source["asta"] = ("blocked", "changed later")
    assert evidence.verified_status("asta") == ("available", "fixture")
    with pytest.raises(TypeError):
        evidence.statuses["asta"] = ("blocked", "mutation")  # type: ignore[index]


# --------------------------------------------------------------------------
# Profile validation — the strictness the two laggard copies lacked
# --------------------------------------------------------------------------


def test_a_valid_profile_round_trips(tmp_path):
    profile = load_profile(write_profile(tmp_path))
    assert profile.mech == "TestMech"
    assert profile.default_focus == "primary"
    focus = profile.focus()
    assert focus.name == "primary"
    assert focus.provider_adjustments == {"asta": 2.0}
    assert focus.stages["discovery"].capabilities == {
        "academic_search": 4.0,
        "snippets": 2.0,
    }


@pytest.mark.parametrize(
    "replacement",
    [
        "        capabilities: {academic_search: null}",
        "        capabilities: {academic_search: high}",
        "        capabilities: {academic_search: true}",
    ],
    ids=["null-weight", "string-weight", "bool-weight"],
)
def test_a_non_numeric_capability_weight_is_refused(tmp_path, replacement):
    """MediaIngredientMech and CommunityMech accepted these and crashed inside _score."""
    text = variant("        capabilities: {academic_search: 4, snippets: 2}", replacement)
    with pytest.raises(ProfileError, match="must be a number"):
        load_profile(write_profile(tmp_path, text))


def test_a_null_stage_weight_is_refused(tmp_path):
    text = variant("        speed_weight: 1", "        speed_weight: null")
    with pytest.raises(ProfileError, match="speed_weight must be a number"):
        load_profile(write_profile(tmp_path, text))


def test_an_explicitly_null_provider_adjustments_block_is_refused(tmp_path):
    """`.get(key, {})` returns None for an explicit null, not the default."""
    text = variant("    provider_adjustments: {asta: 2}", "    provider_adjustments: null")
    with pytest.raises(ProfileError, match="provider_adjustments must be a mapping"):
        load_profile(write_profile(tmp_path, text))


def test_a_non_numeric_provider_adjustment_is_refused(tmp_path):
    text = variant("    provider_adjustments: {asta: 2}", "    provider_adjustments: {asta: lots}")
    with pytest.raises(ProfileError, match="must be a number"):
        load_profile(write_profile(tmp_path, text))


def test_an_unknown_capability_is_refused_with_the_known_list(tmp_path):
    """An unknown capability scores 0 for every provider, so it must not load."""
    text = variant(
        "        capabilities: {academic_search: 4, snippets: 2}",
        "        capabilities: {telepathy: 4}",
    )
    with pytest.raises(ProfileError) as excinfo:
        load_profile(write_profile(tmp_path, text))
    assert "telepathy" in str(excinfo.value)
    assert "academic_search" in str(excinfo.value)


def test_an_unknown_provider_adjustment_is_refused(tmp_path):
    text = variant(
        "    provider_adjustments: {asta: 2}", "    provider_adjustments: {nosuchprovider: 2}"
    )
    with pytest.raises(ProfileError, match="unknown provider"):
        load_profile(write_profile(tmp_path, text))


def test_two_aliases_of_one_provider_are_refused(tmp_path):
    """`{edison: 2, falcon: 3}` silently kept whichever survived the dict merge."""
    text = variant(
        "    provider_adjustments: {asta: 2}", "    provider_adjustments: {edison: 2, falcon: 3}"
    )
    with pytest.raises(ProfileError, match="multiple keys resolving"):
        load_profile(write_profile(tmp_path, text))


def test_an_alias_in_provider_adjustments_is_canonicalized(tmp_path):
    text = variant("    provider_adjustments: {asta: 2}", "    provider_adjustments: {edison: 7}")
    profile = load_profile(write_profile(tmp_path, text))
    assert profile.focus().provider_adjustments == {"falcon": 7.0}


def test_a_default_focus_absent_from_focuses_is_refused(tmp_path):
    text = variant("default_focus: primary", "default_focus: missing")
    with pytest.raises(ProfileError, match="default_focus"):
        load_profile(write_profile(tmp_path, text))


def test_a_focus_without_stages_is_refused():
    with pytest.raises(ProfileError, match="non-empty 'stages' mapping"):
        parse_profile(
            {
                "mech": "TestMech",
                "target": "things",
                "evidence_policy": "cite every claim",
                "default_focus": "a",
                "focuses": {"a": {"stages": {}}},
            }
        )


def test_a_non_mapping_profile_is_refused():
    with pytest.raises(ProfileError, match="must be a YAML mapping"):
        parse_profile(["not", "a", "mapping"])


def test_a_missing_profile_file_reports_the_path(tmp_path):
    with pytest.raises(ProfileError, match="Cannot read research profile"):
        load_profile(tmp_path / "absent.yaml")


def test_invalid_yaml_is_reported_as_a_profile_error(tmp_path):
    with pytest.raises(ProfileError, match="not valid YAML"):
        load_profile(write_profile(tmp_path, "focuses: [unclosed\n"))


def test_source_priorities_must_be_a_list_not_a_string(tmp_path):
    text = variant(
        "    source_priorities:\n      - literature", "    source_priorities: literature"
    )
    with pytest.raises(ProfileError, match="source_priorities must be a list"):
        load_profile(write_profile(tmp_path, text))


def test_requesting_an_unknown_focus_lists_the_known_ones(tmp_path):
    profile = load_profile(write_profile(tmp_path))
    with pytest.raises(ProfileError, match="Unknown focus"):
        profile.focus("nope")


# --------------------------------------------------------------------------
# Triage
# --------------------------------------------------------------------------


def test_ranking_is_deterministic_and_covers_every_provider(tmp_path):
    profile = load_profile(write_profile(tmp_path))
    first = rank_stage(profile.focus(), "discovery", environ={}, probe=NO_LOCAL_TOOLING)
    second = rank_stage(profile.focus(), "discovery", environ={}, probe=NO_LOCAL_TOOLING)
    assert [row.provider for row in first] == [row.provider for row in second]
    assert {row.provider for row in first} == set(PROVIDERS)


def test_ranking_is_sorted_by_descending_fit(tmp_path):
    profile = load_profile(write_profile(tmp_path))
    rows = rank_stage(profile.focus(), "discovery", environ={}, probe=NO_LOCAL_TOOLING)
    assert [row.fit for row in rows] == sorted((row.fit for row in rows), reverse=True)


def test_an_unknown_stage_names_the_available_stages(tmp_path):
    profile = load_profile(write_profile(tmp_path))
    with pytest.raises(ProfileError, match="discovery"):
        rank_stage(profile.focus(), "nosuchstage", environ={})


def test_recommendable_excludes_blocked_unavailable_and_mock(tmp_path):
    profile = load_profile(write_profile(tmp_path))
    rows = rank_stage(
        profile.focus(),
        "discovery",
        environ={
            "ASTA_API_KEY": "x",
            "EDISON_API_KEY": "x",
            "ENABLE_MOCK_PROVIDER": "true",
        },
        probe=NO_LOCAL_TOOLING,
        availability=VERIFIED,
    )
    names = [row.provider for row in recommendable(rows)]
    assert "asta" in names
    assert "falcon" not in names, "blocked despite a configured credential"
    assert "mock" not in names, "mock never supplies real evidence"
    assert "openai" not in names, "no credential configured"


def test_no_paid_conservatively_excludes_every_metered_provider(tmp_path):
    """Relative cost does not decide whether quota or credits can be consumed."""
    profile = load_profile(write_profile(tmp_path))
    rows = rank_stage(
        profile.focus(),
        "discovery",
        environ={"ASTA_API_KEY": "x", "OPENAI_API_KEY": "x", "CBORG_API_KEY": "x"},
        probe=NO_LOCAL_TOOLING,
        availability=VERIFIED,
    )
    names = [row.provider for row in recommendable(rows, no_paid=True)]
    assert names == []
    assert PROVIDERS["cborg"].cost == "medium"
    assert PROVIDERS["cborg"].billing == "metered"
    assert requires_usage_authorization("cborg")


def test_no_paid_filter_retains_a_provider_explicitly_classified_free(tmp_path, monkeypatch):
    """Prove the filter is selective, even though today's only free row is mock."""
    monkeypatch.setitem(
        PROVIDERS,
        "asta",
        replace(PROVIDERS["asta"], billing="free"),
    )
    profile = load_profile(write_profile(tmp_path))
    rows = rank_stage(
        profile.focus(),
        "discovery",
        environ={"ASTA_API_KEY": "x"},
        probe=NO_LOCAL_TOOLING,
        availability=VERIFIED,
    )
    assert [row.provider for row in recommendable(rows, no_paid=True)] == ["asta"]


def test_no_paid_filter_excludes_unknown_billing(tmp_path, monkeypatch):
    monkeypatch.setitem(
        PROVIDERS,
        "asta",
        replace(PROVIDERS["asta"], billing="unknown"),
    )
    profile = load_profile(write_profile(tmp_path))
    rows = rank_stage(
        profile.focus(),
        "discovery",
        environ={"ASTA_API_KEY": "x"},
        probe=NO_LOCAL_TOOLING,
        availability=VERIFIED,
    )
    assert "asta" not in [row.provider for row in recommendable(rows, no_paid=True)]


def test_the_allowlist_narrows_the_recommendation_itself(tmp_path):
    """The JSON path once filtered `ranking` but recommended from the full set."""
    profile = load_profile(write_profile(tmp_path))
    report = build_report(
        profile,
        allow=frozenset({"asta"}),
        environ={"ASTA_API_KEY": "x", "CBORG_API_KEY": "x"},
        probe=NO_LOCAL_TOOLING,
        availability=VERIFIED,
    )
    stage = report["stages"][0]
    assert stage["recommended_available"]["provider"] == "asta"


def test_a_report_with_no_available_provider_recommends_nothing(tmp_path):
    profile = load_profile(write_profile(tmp_path))
    report = build_report(profile, environ={}, probe=NO_LOCAL_TOOLING)
    stage = report["stages"][0]
    assert stage["recommended_available"] is None
    assert stage["fallback_available"] is None


def test_report_is_json_serializable(tmp_path):
    import json

    profile = load_profile(write_profile(tmp_path))
    report = build_report(
        profile,
        environ={"ASTA_API_KEY": "x"},
        probe=NO_LOCAL_TOOLING,
        availability=VERIFIED,
    )
    assert json.loads(json.dumps(report))["mech"] == "TestMech"


def test_build_report_canonicalizes_an_aliased_allowlist(tmp_path):
    """#136 at the library boundary, where the CLI's own normalization cannot mask it.

    `plan_stage` canonicalized its allowlist and `build_report` did not, so the
    same alias produced a recommendation from one and nothing from the other.
    """
    profile = load_profile(write_profile(tmp_path))
    report = build_report(
        profile,
        allow={"claude-code"},
        environ={},
        probe=StaticProbe(executables=frozenset({"claude"})),
        availability=VERIFIED,
    )
    recommended = report["stages"][0]["recommended_available"]
    assert recommended is not None, "the alias must resolve to claude_code"
    assert recommended["provider"] == "claude_code"


def test_recommendable_canonicalizes_an_aliased_allowlist(tmp_path):
    """The alias must name an AVAILABLE provider, or the assertion is vacuous.

    A first draft used `edison`, whose target falcon is blocked and therefore
    filtered out regardless -- so the test passed with the canonicalization
    removed. `claude-code` resolves to an available provider, so the alias has
    to actually resolve for the assertion to hold.
    """
    profile = load_profile(write_profile(tmp_path))
    rows = rank_stage(
        profile.focus(),
        "discovery",
        environ={"ASTA_API_KEY": "x"},
        probe=StaticProbe(executables=frozenset({"claude"})),
        availability=VERIFIED,
    )
    assert [row.provider for row in recommendable(rows, allow={"claude-code"})] == ["claude_code"]


def test_plan_and_report_agree_on_an_aliased_allowlist(tmp_path):
    """The two filters are one implementation; pin that they cannot diverge again."""
    from kg_microbe_research import plan_stage

    profile = load_profile(write_profile(tmp_path))
    probe = StaticProbe(executables=frozenset({"claude"}))
    report = build_report(
        profile,
        allow={"claude-code"},
        environ={},
        probe=probe,
        availability=VERIFIED,
    )
    plan = plan_stage(
        profile,
        "discovery",
        allow=["claude-code"],
        environ={},
        probe=probe,
        availability=VERIFIED,
    )
    assert report["stages"][0]["recommended_available"]["provider"] == (plan.recommended.provider)


# --------------------------------------------------------------------------
# Usage authorization is explicit and independent of relative cost (#139)
# --------------------------------------------------------------------------


def test_every_external_provider_requires_usage_authorization():
    for name, provider in PROVIDERS.items():
        assert requires_usage_authorization(name) is (provider.billing != "free"), name


def test_usage_authorization_resolves_aliases():
    assert requires_usage_authorization("edison") is requires_usage_authorization("falcon")


def test_usage_authorization_fails_closed_for_an_unknown_provider():
    assert requires_usage_authorization("nosuchprovider") is True


def test_every_reported_usage_flag_agrees_with_the_one_predicate(tmp_path):
    """The ranking rows are a third consumer; they must not drift either."""
    profile = load_profile(write_profile(tmp_path))
    rows = rank_stage(profile.focus(), "discovery", environ={}, probe=NO_LOCAL_TOOLING)
    assert rows, "no rows to check"
    for row in rows:
        assert row.usage_authorization_required is requires_usage_authorization(row.provider), (
            row.provider
        )


def test_build_report_refuses_an_unknown_allowlist(tmp_path):
    profile = load_profile(write_profile(tmp_path))
    with pytest.raises(ProfileError, match="Unknown provider"):
        build_report(profile, allow={"nosuchprovider"}, environ={})
