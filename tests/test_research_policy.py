"""Contracts for the execution-policy gate.

Three independent conditions govern live use: execution must be explicit,
non-free usage needs quota/billing authorization, and the provider must agree
with the provenance-bound triage plan (or a permitted override).
"""

from __future__ import annotations

import json
import textwrap
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from kg_microbe_research import (
    PROVIDERS,
    PolicyError,
    StaticAvailability,
    StaticProbe,
    authorize,
    load_profile,
    plan_stage,
    requires_usage_authorization,
)
from kg_microbe_research.policy import _TriagePlan
from kg_microbe_research.providers import _load_availability

NO_LOCAL_TOOLING = StaticProbe()

# Configuration and functional availability are distinct. These fixed test
# attestations never contact a provider.
CONFIGURED = {
    "ASTA_API_KEY": "x",
    "OPENAI_API_KEY": "x",
    "CBORG_API_KEY": "x",
    "EDISON_API_KEY": "x",
}
VERIFIED = StaticAvailability(
    {
        name: ("available", "offline test attestation")
        for name in {"asta", "openai", "cborg", "perplexity"}
    }
)


class MutableClock:
    def __init__(self, current: datetime) -> None:
        self.current = current

    def __call__(self) -> datetime:
        return self.current


class MutableAvailability:
    def __init__(self) -> None:
        self.current = ("available", "initial offline attestation")

    def verified_status(self, provider: str) -> tuple[str, str] | None:
        return self.current if provider == "asta" else None

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


@pytest.fixture
def profile(tmp_path: Path):
    path = tmp_path / "deep_research_provider.yaml"
    path.write_text(PROFILE, encoding="utf-8")
    return load_profile(path)


@pytest.fixture
def plan(profile):
    return plan_stage(
        profile,
        "discovery",
        environ=CONFIGURED,
        probe=NO_LOCAL_TOOLING,
        availability=VERIFIED,
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


def test_a_dry_run_of_a_metered_provider_needs_no_usage_authorization(plan):
    """Planning is offline; only live execution consumes provider resources."""
    decision = authorize(plan, provider="openai")
    assert decision.dry_run is True
    assert decision.usage_authorization_required is True


def test_a_free_catalogue_class_does_not_make_an_unimplemented_mock_routable(profile):
    mock_plan = plan_stage(
        profile,
        "discovery",
        environ={**CONFIGURED, "ENABLE_MOCK_PROVIDER": "true"},
        probe=NO_LOCAL_TOOLING,
        availability=VERIFIED,
    )
    assert requires_usage_authorization("mock") is False
    with pytest.raises(PolicyError, match=r"not available \(stub\)"):
        authorize(
            mock_plan,
            provider="mock",
            apply=True,
            override_reason="offline fixture exercise",
        )


# --------------------------------------------------------------------------
# The metered-usage gate
# --------------------------------------------------------------------------


def test_a_live_metered_call_is_refused_without_explicit_usage_authorization(plan):
    with pytest.raises(PolicyError, match="explicit usage authorization"):
        authorize(plan, provider="openai", apply=True)


def test_acknowledging_usage_authorizes_a_live_metered_call(plan):
    decision = authorize(plan, provider="openai", apply=True, acknowledge_usage=True)
    assert decision.live is True
    assert any("acknowledged" in reason for reason in decision.reasons)


def test_a_cost_ceiling_that_admits_the_tier_authorizes_the_call(plan):
    decision = authorize(plan, provider="openai", apply=True, max_cost="very_high")
    assert decision.live is True
    assert any("cost ceiling" in reason for reason in decision.reasons)


def test_a_cost_ceiling_below_the_tier_refuses_the_call(plan):
    with pytest.raises(PolicyError, match="does not admit provider tier very_high"):
        authorize(plan, provider="openai", apply=True, max_cost="medium")


def test_a_ceiling_admits_tiers_at_or_below_itself(profile):
    """`high` must authorize a high-tier provider, not only something cheaper."""
    assert requires_usage_authorization("perplexity")
    assert PROVIDERS["perplexity"].cost == "high"
    extended = plan_stage(
        profile,
        "discovery",
        environ={**CONFIGURED, "PERPLEXITY_API_KEY": "x"},
        probe=NO_LOCAL_TOOLING,
        availability=VERIFIED,
    )
    decision = authorize(extended, provider="perplexity", apply=True, max_cost="high")
    assert decision.live is True


def test_an_unknown_cost_ceiling_is_refused(plan):
    with pytest.raises(PolicyError, match="Unknown cost ceiling"):
        authorize(plan, provider="asta", apply=True, max_cost="cheap")


def test_medium_cost_provider_still_needs_usage_authorization(plan):
    """Relative cost is not evidence that CBORG consumes no quota or credits."""
    assert requires_usage_authorization("cborg") is True
    with pytest.raises(PolicyError, match="explicit usage authorization"):
        authorize(plan, provider="cborg", apply=True)
    decision = authorize(plan, provider="cborg", apply=True, acknowledge_usage=True)
    assert decision.live is True
    assert decision.usage_authorization_required is True


def test_acknowledgement_cannot_override_a_lower_cost_ceiling(plan):
    with pytest.raises(PolicyError, match="cannot override a supplied ceiling"):
        authorize(
            plan,
            provider="openai",
            apply=True,
            acknowledge_usage=True,
            max_cost="medium",
        )


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
        availability=VERIFIED,
    )
    assert not restricted.permits("openai")
    with pytest.raises(PolicyError, match="hard exclusion cannot be overridden"):
        authorize(restricted, provider="openai", apply=True, acknowledge_usage=True)


def test_a_provider_outside_the_allowlist_cannot_be_named_directly(profile):
    restricted = plan_stage(
        profile,
        "discovery",
        allow=["asta"],
        environ=CONFIGURED,
        probe=NO_LOCAL_TOOLING,
        availability=VERIFIED,
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
        availability=VERIFIED,
    )
    decision = authorize(
        restricted,
        provider="cborg",
        apply=True,
        acknowledge_usage=True,
        override_reason="asta returned no passages for this target",
    )
    assert decision.live is True
    assert any("override:" in reason for reason in decision.reasons)


def test_an_override_cannot_waive_the_no_paid_policy(profile):
    restricted = plan_stage(
        profile,
        "discovery",
        no_paid=True,
        environ=CONFIGURED,
        probe=NO_LOCAL_TOOLING,
        availability=VERIFIED,
    )
    with pytest.raises(PolicyError, match="hard exclusion cannot be overridden"):
        authorize(
            restricted,
            provider="openai",
            apply=True,
            acknowledge_usage=True,
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
            acknowledge_usage=True,
            override_reason="please",
        )


def test_an_unconfigured_provider_is_refused(plan):
    with pytest.raises(PolicyError, match="is not available"):
        authorize(plan, provider="consensus", apply=True)


def test_a_configured_but_unverified_provider_is_refused(profile):
    unverified = plan_stage(
        profile,
        "discovery",
        environ=CONFIGURED,
        probe=NO_LOCAL_TOOLING,
    )
    with pytest.raises(PolicyError, match=r"not available \(configured\)"):
        authorize(unverified, provider="asta", apply=True, acknowledge_usage=True)


def test_an_unknown_provider_is_refused(plan):
    with pytest.raises(PolicyError, match="Unknown provider"):
        authorize(plan, provider="nosuchprovider", apply=True)


def test_an_alias_resolves_before_authorization(plan):
    """`--provider edison` must hit falcon's blocked rule, not fall through."""
    with pytest.raises(PolicyError, match="is blocked"):
        authorize(plan, provider="edison", apply=True, acknowledge_usage=True)


def test_a_plan_with_no_available_provider_refuses_rather_than_recommending(profile):
    empty = plan_stage(profile, "discovery", environ={}, probe=NO_LOCAL_TOOLING)
    assert empty.recommended is None
    with pytest.raises(PolicyError, match="No provider is available"):
        authorize(empty)


def test_cached_evidence_expiry_invalidates_an_existing_plan(profile, tmp_path: Path):
    checked_at = datetime(2026, 8, 25, 12, tzinfo=timezone.utc)
    expires_at = checked_at + timedelta(minutes=1)
    clock = MutableClock(checked_at)
    path = tmp_path / "availability.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "providers": {
                    "asta": {
                        "status": "available",
                        "reason": "offline preflight fixture",
                        "checked_at": checked_at.isoformat(),
                        "expires_at": expires_at.isoformat(),
                        "source": "pytest-static-fixture",
                        "context": "fake account/model on test host",
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    evidence = _load_availability(path, clock=clock)
    expiring_plan = plan_stage(
        profile,
        "discovery",
        environ={"ASTA_API_KEY": "x"},
        probe=NO_LOCAL_TOOLING,
        availability=evidence,
    )
    assert expiring_plan.row("asta").status == "available"  # type: ignore[union-attr]

    clock.current = expires_at
    with pytest.raises(PolicyError, match="evidence expired or changed"):
        authorize(
            expiring_plan,
            provider="asta",
            apply=True,
            acknowledge_usage=True,
        )


def test_changed_evidence_invalidates_an_existing_plan(profile):
    evidence = MutableAvailability()
    mutable_plan = plan_stage(
        profile,
        "discovery",
        environ={"ASTA_API_KEY": "x"},
        probe=NO_LOCAL_TOOLING,
        availability=evidence,
    )

    evidence.current = ("available", "different attestation")
    with pytest.raises(PolicyError, match="evidence expired or changed"):
        authorize(mutable_plan, provider="asta")


def test_an_unknown_allowlist_entry_is_refused_when_planning(profile):
    with pytest.raises(PolicyError, match="Unknown provider"):
        plan_stage(
            profile,
            "discovery",
            allow=["nosuchprovider"],
            environ=CONFIGURED,
            probe=NO_LOCAL_TOOLING,
            availability=VERIFIED,
        )


# --------------------------------------------------------------------------
# The plan is the authority, and it is immutable
# --------------------------------------------------------------------------


def test_the_plan_is_frozen(plan):
    with pytest.raises(Exception):
        plan.no_paid = True  # type: ignore[misc]


def test_an_altered_plan_cannot_forge_a_blocked_provider_as_available(plan):
    falcon = plan.row("falcon")
    assert falcon is not None
    forged_row = replace(
        falcon,
        status="available",
        status_reason="caller says so",
        cost="low",
    )
    forged_ranking = tuple(forged_row if row.provider == "falcon" else row for row in plan.ranking)
    forged = replace(plan, ranking=forged_ranking, allowed=(forged_row,))
    with pytest.raises(PolicyError, match="not created by plan_stage or was altered"):
        authorize(forged, provider="falcon", apply=True, acknowledge_usage=True)


def test_replacing_the_plan_availability_authority_breaks_its_stamp(plan):
    replacement = StaticAvailability({"asta": ("available", "replacement")})
    forged = replace(plan, _availability=replacement)

    with pytest.raises(PolicyError, match="not created by plan_stage or was altered"):
        authorize(forged, provider="asta")


def test_a_hand_built_plan_is_not_an_authorization_authority():
    forged = _TriagePlan(
        mech="TestMech",
        focus="primary",
        stage="discovery",
        ranking=(),
        allowed=(),
        no_paid=False,
        allowlist=None,
        _stamp=0,
    )
    with pytest.raises(PolicyError, match="not created by plan_stage"):
        authorize(forged, provider="nosuchprovider", apply=True)


def test_internal_plan_and_decision_types_are_not_exported():
    import kg_microbe_research

    assert not hasattr(kg_microbe_research, "TriagePlan")
    assert not hasattr(kg_microbe_research, "Decision")


def test_a_whitespace_only_override_reason_is_refused(profile):
    restricted = plan_stage(
        profile,
        "discovery",
        allow=["asta"],
        environ=CONFIGURED,
        probe=NO_LOCAL_TOOLING,
        availability=VERIFIED,
    )
    with pytest.raises(PolicyError, match="Supply an explicit override reason"):
        authorize(
            restricted,
            provider="cborg",
            apply=True,
            acknowledge_usage=True,
            override_reason="   ",
        )


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
