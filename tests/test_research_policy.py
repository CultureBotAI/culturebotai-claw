"""Contracts for the execution-policy gate.

Three separate decisions must be present before a billable call is authorized:
live execution, paid authorization, and agreement with the immutable triage
plan. No default supplies any of them, so the assertion that matters most in
this file is how many ways `authorize` refuses.
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from kg_microbe_research import (
    PROVIDERS,
    PolicyError,
    StaticProbe,
    authorize,
    load_profile,
    plan_stage,
    requires_paid_authorization,
)

NO_LOCAL_TOOLING = StaticProbe()

# asta (low cost) and openai (very_high) are both configured, so a single plan
# exercises the free path and the paid path. falcon is configured *and* blocked.
CONFIGURED = {
    "ASTA_API_KEY": "x",
    "OPENAI_API_KEY": "x",
    "CBORG_API_KEY": "x",
    "EDISON_API_KEY": "x",
}

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
def profile(tmp_path: Path):
    path = tmp_path / "deep_research_provider.yaml"
    path.write_text(PROFILE, encoding="utf-8")
    return load_profile(path)


@pytest.fixture
def plan(profile):
    return plan_stage(
        profile, "discovery", environ=CONFIGURED, probe=NO_LOCAL_TOOLING
    )


# --------------------------------------------------------------------------
# Default posture
# --------------------------------------------------------------------------


def test_the_default_decision_is_a_dry_run(plan):
    """Four of the five Mech runners execute unless told not to. This inverts that."""
    decision = authorize(plan)
    assert decision.dry_run is True
    assert decision.live is False
    assert "dry run: no provider was called" in decision.reasons


def test_a_dry_run_of_a_paid_provider_needs_no_authorization(plan):
    """Planning a paid call is free; only executing it is gated."""
    decision = authorize(plan, provider="openai")
    assert decision.dry_run is True
    assert decision.paid is True


def test_apply_alone_authorizes_a_free_provider(plan):
    decision = authorize(plan, provider="asta", apply=True)
    assert decision.live is True
    assert decision.paid is False


# --------------------------------------------------------------------------
# The paid gate
# --------------------------------------------------------------------------


def test_a_live_paid_call_is_refused_without_explicit_paid_authorization(plan):
    with pytest.raises(PolicyError, match="explicit paid authorization"):
        authorize(plan, provider="openai", apply=True)


def test_acknowledging_the_charge_authorizes_a_live_paid_call(plan):
    decision = authorize(
        plan, provider="openai", apply=True, acknowledge_paid=True
    )
    assert decision.live is True
    assert any("acknowledged" in reason for reason in decision.reasons)


def test_a_cost_ceiling_that_admits_the_tier_authorizes_the_call(plan):
    decision = authorize(plan, provider="openai", apply=True, max_cost="very_high")
    assert decision.live is True
    assert any("cost ceiling" in reason for reason in decision.reasons)


def test_a_cost_ceiling_below_the_tier_refuses_the_call(plan):
    with pytest.raises(PolicyError, match="does not admit tier very_high"):
        authorize(plan, provider="openai", apply=True, max_cost="medium")


def test_a_ceiling_admits_tiers_at_or_below_itself(profile):
    """`high` must authorize a high-tier provider, not only something cheaper."""
    assert requires_paid_authorization("perplexity")
    assert PROVIDERS["perplexity"].cost == "high"
    extended = plan_stage(
        profile,
        "discovery",
        environ={**CONFIGURED, "PERPLEXITY_API_KEY": "x"},
        probe=NO_LOCAL_TOOLING,
    )
    decision = authorize(extended, provider="perplexity", apply=True, max_cost="high")
    assert decision.live is True


def test_an_unknown_cost_ceiling_is_refused(plan):
    with pytest.raises(PolicyError, match="Unknown cost ceiling"):
        authorize(plan, provider="asta", apply=True, max_cost="cheap")


def test_medium_cost_providers_are_not_gated_as_paid(plan):
    """cborg/claude_code are medium; gating them would defeat --no-paid's purpose."""
    assert requires_paid_authorization("cborg") is False
    decision = authorize(plan, provider="cborg", apply=True)
    assert decision.live is True
    assert decision.paid is False


# --------------------------------------------------------------------------
# Plan agreement — the silent bypass this gate exists to close
# --------------------------------------------------------------------------


def test_a_provider_the_no_paid_plan_excludes_cannot_be_named_directly(profile):
    """`--provider openai --no-paid` previously routed to openai regardless."""
    restricted = plan_stage(
        profile,
        "discovery",
        no_paid=True,
        environ=CONFIGURED,
        probe=NO_LOCAL_TOOLING,
    )
    assert not restricted.permits("openai")
    with pytest.raises(PolicyError, match="no-paid policy"):
        authorize(restricted, provider="openai", apply=True, acknowledge_paid=True)


def test_a_provider_outside_the_allowlist_cannot_be_named_directly(profile):
    restricted = plan_stage(
        profile,
        "discovery",
        allow=["asta"],
        environ=CONFIGURED,
        probe=NO_LOCAL_TOOLING,
    )
    with pytest.raises(PolicyError, match="not permitted"):
        authorize(restricted, provider="cborg", apply=True)


def test_an_override_is_permitted_but_recorded(profile):
    """Overriding is allowed; overriding *silently* is not."""
    restricted = plan_stage(
        profile,
        "discovery",
        allow=["asta"],
        environ=CONFIGURED,
        probe=NO_LOCAL_TOOLING,
    )
    decision = authorize(
        restricted,
        provider="cborg",
        apply=True,
        override_reason="asta returned no passages for this target",
    )
    assert decision.live is True
    assert any("override:" in reason for reason in decision.reasons)


def test_an_override_does_not_waive_the_paid_gate(profile):
    """The override covers plan disagreement only — money still needs its own yes."""
    restricted = plan_stage(
        profile,
        "discovery",
        no_paid=True,
        environ=CONFIGURED,
        probe=NO_LOCAL_TOOLING,
    )
    with pytest.raises(PolicyError, match="explicit paid authorization"):
        authorize(
            restricted,
            provider="openai",
            apply=True,
            override_reason="needed for this run",
        )


# --------------------------------------------------------------------------
# Unroutable providers are refused whatever the caller passes
# --------------------------------------------------------------------------


def test_a_blocked_provider_is_refused_even_fully_authorized(plan):
    with pytest.raises(PolicyError, match="is blocked"):
        authorize(
            plan,
            provider="falcon",
            apply=True,
            acknowledge_paid=True,
            override_reason="please",
        )


def test_an_unconfigured_provider_is_refused(plan):
    with pytest.raises(PolicyError, match="is not available"):
        authorize(plan, provider="consensus", apply=True)


def test_an_unknown_provider_is_refused(plan):
    with pytest.raises(PolicyError, match="Unknown provider"):
        authorize(plan, provider="nosuchprovider", apply=True)


def test_an_alias_resolves_before_authorization(plan):
    """`--provider edison` must hit falcon's blocked rule, not fall through."""
    with pytest.raises(PolicyError, match="is blocked"):
        authorize(plan, provider="edison", apply=True, acknowledge_paid=True)


def test_a_plan_with_no_available_provider_refuses_rather_than_recommending(profile):
    empty = plan_stage(profile, "discovery", environ={}, probe=NO_LOCAL_TOOLING)
    assert empty.recommended is None
    with pytest.raises(PolicyError, match="No provider is available"):
        authorize(empty)


def test_an_unknown_allowlist_entry_is_refused_when_planning(profile):
    with pytest.raises(PolicyError, match="Unknown provider"):
        plan_stage(
            profile,
            "discovery",
            allow=["nosuchprovider"],
            environ=CONFIGURED,
            probe=NO_LOCAL_TOOLING,
        )


# --------------------------------------------------------------------------
# The plan is the authority, and it is immutable
# --------------------------------------------------------------------------


def test_the_plan_is_frozen(plan):
    with pytest.raises(Exception):
        plan.no_paid = True  # type: ignore[misc]


def test_the_decision_is_frozen(plan):
    decision = authorize(plan)
    with pytest.raises(Exception):
        decision.live = True  # type: ignore[misc]


def test_the_decision_records_its_target(plan):
    decision = authorize(plan, provider="asta")
    payload = decision.as_dict()
    assert payload["mech"] == "TestMech"
    assert payload["focus"] == "primary"
    assert payload["stage"] == "discovery"
    assert payload["mode"] == "dry-run"
