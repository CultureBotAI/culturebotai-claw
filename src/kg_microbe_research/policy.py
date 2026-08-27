"""Execution policy: what it takes before a provider may actually be called.

Today four of the five Mech runners execute a provider unless the caller passes
`--dry-run`, so the *default* action spends credits; only ProteinTraitsMech
defaults to dry-run and requires `--apply`. None of the five has any notion of
authorizing a *paid* call specifically, and none binds execution to the triage
result — `--provider` is accepted verbatim, so a manually named provider
silently escapes both the profile's allowlist and its no-paid filter.

This module is the single gate. Three independent conditions govern a call:

1. **Live execution** — `apply=True`. Without it the decision is a dry run.
2. **Usage authorization** — live use of every provider not explicitly classified free
   needs either an explicit quota/billing acknowledgement or a cost ceiling
   that admits its relative tier.
3. **Plan agreement** — the provider must be one the immutable triage plan
   would offer. An ordinary triage/allowlist disagreement needs a recorded
   override reason; the no-paid exclusion is never overridable.

Refusal is the default for anything unproven: a blocked, unavailable, or merely
configured provider is never routable, whatever the caller passes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .profile import ResearchProfile
from .providers import (
    COST_VALUE,
    KNOWN_BLOCKED,
    PROVIDERS,
    AvailabilityEvidence,
    LocalProbe,
    canonical_provider,
    normalize_allowlist,
    requires_usage_authorization,
    unknown_providers,
)
from .triage import Ranked, rank_stage, recommendable

# Ordered weakest-to-strongest, so a ceiling admits every tier at or below it.
COST_TIERS: tuple[str, ...] = tuple(sorted(COST_VALUE, key=lambda tier: COST_VALUE[tier]))


class PolicyInputError(ValueError):
    """An argument to planning is malformed, before any policy question is asked.

    Deliberately NOT a `PolicyError`: the CLI reports a policy refusal as exit 2,
    and a misspelled provider name is a typo, not a decision policy made. A
    caller that reads exit 2 as "policy said no, try another provider" would act
    on a typo as though it were a refusal (#153).
    """


class PolicyError(RuntimeError):
    """A requested execution is not permitted."""


@dataclass(frozen=True)
class _TriagePlan:
    """An immutable triage result for one focus and stage.

    Execution is authorized against this object rather than against the raw
    arguments, so the allowlist and no-paid filter that produced it cannot be
    sidestepped by naming a provider directly.
    """

    mech: str
    focus: str
    stage: str
    ranking: tuple[Ranked, ...]
    allowed: tuple[Ranked, ...]
    no_paid: bool
    allowlist: frozenset[str] | None
    _stamp: int = field(repr=False, compare=False)
    _availability: AvailabilityEvidence | None = field(
        default=None, repr=False, compare=False
    )

    @property
    def recommended(self) -> Ranked | None:
        return self.allowed[0] if self.allowed else None

    def row(self, provider: str) -> Ranked | None:
        canonical = canonical_provider(provider)
        return next((row for row in self.ranking if row.provider == canonical), None)

    def permits(self, provider: str) -> bool:
        canonical = canonical_provider(provider)
        return any(row.provider == canonical for row in self.allowed)


_PLAN_NONCE = object()


def _plan_stamp(
    mech: str,
    focus: str,
    stage: str,
    ranking: tuple[Ranked, ...],
    allowed: tuple[Ranked, ...],
    no_paid: bool,
    allowlist: frozenset[str] | None,
    availability: AvailabilityEvidence | None,
) -> int:
    """Bind a plan to the exact output produced by `plan_stage`.

    This is an in-process provenance guard against accidentally constructing or
    modifying a public dataclass, not a cryptographic authorization token.
    """
    return hash(
        (
            _PLAN_NONCE,
            mech,
            focus,
            stage,
            ranking,
            allowed,
            no_paid,
            allowlist,
            id(availability),
        )
    )


def _validate_plan(plan: _TriagePlan) -> None:
    """Reject hand-built, altered, or catalogue-inconsistent plans."""
    if not isinstance(plan, _TriagePlan):
        raise PolicyError("authorize requires a plan created by plan_stage")
    expected = _plan_stamp(
        plan.mech,
        plan.focus,
        plan.stage,
        plan.ranking,
        plan.allowed,
        plan.no_paid,
        plan.allowlist,
        plan._availability,
    )
    if plan._stamp != expected:
        raise PolicyError("Triage plan was not created by plan_stage or was altered")

    names = tuple(row.provider for row in plan.ranking)
    if len(names) != len(PROVIDERS) or set(names) != set(PROVIDERS):
        raise PolicyError("Triage plan does not contain the canonical provider catalogue")
    if plan.allowlist is not None and unknown_providers(plan.allowlist):
        raise PolicyError("Triage plan contains an unknown allowlist provider")

    valid_statuses = {"available", "configured", "blocked", "unavailable", "stub"}
    for row in plan.ranking:
        provider = PROVIDERS[row.provider]
        static_facts = (
            row.label,
            row.cost,
            row.billing,
            row.time,
            row.synthesis,
            row.source_scope,
            row.best_for,
            row.limitation,
        )
        catalogue_facts = (
            provider.label,
            provider.cost,
            provider.billing,
            provider.time,
            provider.synthesis,
            provider.source_scope,
            provider.best_for,
            provider.limitation,
        )
        if static_facts != catalogue_facts or row.status not in valid_statuses:
            raise PolicyError(f"Triage plan has invalid facts for provider {row.provider}")
        if row.provider in KNOWN_BLOCKED and row.status != "blocked":
            raise PolicyError(f"Triage plan contradicts the blocked status of {row.provider}")

    expected_allowed = tuple(
        recommendable(list(plan.ranking), allow=plan.allowlist, no_paid=plan.no_paid)
    )
    if plan.allowed != expected_allowed:
        raise PolicyError("Triage plan's allowed providers do not match its policy")


def plan_stage(
    profile: ResearchProfile,
    stage: str,
    *,
    focus: str | None = None,
    allow: Sequence[str] | frozenset[str] | None = None,
    no_paid: bool = False,
    environ: Mapping[str, str] | None = None,
    probe: LocalProbe | None = None,
    availability: AvailabilityEvidence | None = None,
) -> _TriagePlan:
    """Rank a stage and freeze the result as the authority for execution."""
    resolved = profile.focus(focus)
    allowlist = normalize_allowlist(allow)
    if allowlist is not None:
        unknown = unknown_providers(allowlist)
        if unknown:
            raise PolicyInputError(
                f"Unknown provider(s) in allowlist: {unknown}; choose from "
                f"{', '.join(sorted(PROVIDERS))}"
            )
    ranking = tuple(
        rank_stage(
            resolved,
            stage,
            environ=environ,
            probe=probe,
            availability=availability,
        )
    )
    allowed = tuple(recommendable(list(ranking), allow=allowlist, no_paid=no_paid))
    stamp = _plan_stamp(
        profile.mech,
        resolved.name,
        stage,
        ranking,
        allowed,
        no_paid,
        allowlist,
        availability,
    )
    return _TriagePlan(
        mech=profile.mech,
        focus=resolved.name,
        stage=stage,
        ranking=ranking,
        allowed=allowed,
        no_paid=no_paid,
        allowlist=allowlist,
        _stamp=stamp,
        _availability=availability,
    )


@dataclass(frozen=True)
class _Decision:
    """A policy outcome. Callers must require `live is True` before execution."""

    provider: str
    mech: str
    focus: str
    stage: str
    live: bool
    cost: str
    billing: str
    usage_authorization_required: bool
    reasons: tuple[str, ...] = field(default=())

    @property
    def dry_run(self) -> bool:
        return not self.live

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "mech": self.mech,
            "focus": self.focus,
            "stage": self.stage,
            "mode": "live" if self.live else "dry-run",
            "cost": self.cost,
            "billing": self.billing,
            "usage_authorization_required": self.usage_authorization_required,
            "reasons": list(self.reasons),
        }


def _ceiling_admits(cost: str, ceiling: str) -> bool:
    return COST_VALUE[cost] <= COST_VALUE[ceiling]


def authorize(
    plan: _TriagePlan,
    *,
    provider: str | None = None,
    apply: bool = False,
    acknowledge_usage: bool = False,
    max_cost: str | None = None,
    override_reason: str | None = None,
) -> _Decision:
    """Decide whether the requested call may proceed, and in which mode.

    Returns a dry-run policy result unless `apply` is set. Raises `PolicyError`
    rather than downgrading to a dry run when a *live* call was explicitly
    requested but is not permitted, so a refused authorization can never be
    mistaken for a successful cheap one.
    """
    _validate_plan(plan)
    if max_cost is not None and max_cost not in COST_VALUE:
        raise PolicyError(
            f"Unknown cost ceiling {max_cost!r}; choose one of: {', '.join(COST_TIERS)}"
        )

    reasons: list[str] = []
    if provider is None:
        chosen = plan.recommended
        if chosen is None:
            raise PolicyError(
                f"No provider is available for {plan.mech} {plan.focus}/{plan.stage} "
                f"under the current policy"
                + (" (no-paid)" if plan.no_paid else "")
                + (f" and allowlist {sorted(plan.allowlist)}" if plan.allowlist is not None else "")
            )
        name = chosen.provider
        reasons.append(f"triage recommended {name} for {plan.stage}")
    else:
        name = canonical_provider(provider)
        if name not in PROVIDERS:
            raise PolicyError(
                f"Unknown provider {provider!r} (resolved to {name!r}); choose from "
                f"{', '.join(sorted(PROVIDERS))}"
            )
        chosen = plan.row(name)
        if chosen is None:
            raise PolicyError(
                f"Unknown provider {provider!r} (resolved to {name!r}); choose from "
                f"{', '.join(sorted(PROVIDERS))}"
            )

    if name in KNOWN_BLOCKED:
        raise PolicyError(
            f"Provider {name} is blocked and cannot be routed to: {KNOWN_BLOCKED[name]}"
        )
    if chosen.status == "blocked":
        raise PolicyError(
            f"Provider {name} is blocked and cannot be routed to: {chosen.status_reason}"
        )
    if chosen.status != "available":
        raise PolicyError(
            f"Provider {name} is not available ({chosen.status}): {chosen.status_reason}"
        )

    # Availability is evidence, not a perpetual property of a frozen ranking.
    # Recheck the exact object used to build the provenance-bound plan so a
    # long-lived process cannot authorize from an expired or changed assertion.
    current_evidence = (
        plan._availability.verified_status(name)
        if plan._availability is not None
        else None
    )
    expected_evidence = (chosen.status, chosen.status_reason)
    if current_evidence != expected_evidence:
        detail = (
            "no current functional evidence"
            if current_evidence is None
            else f"{current_evidence[0]}: {current_evidence[1]}"
        )
        raise PolicyError(
            f"Provider {name} availability evidence expired or changed ({detail}); "
            "rebuild the triage plan"
        )

    # Any explicitly named provider other than the recommendation changes the
    # triage choice, even when it remains in the eligible fallback list. That
    # choice must be explainable in the result plan as an ordinal-1 OVERRIDE;
    # otherwise a caller could silently use a fallback as attempt 1. The
    # no-paid hard exclusion cannot be overridden at all.
    normalized_override = override_reason.strip() if override_reason is not None else ""
    named_override = (
        provider is not None
        and (plan.recommended is None or name != plan.recommended.provider)
    )
    if provider is not None and not plan.permits(name):
        if plan.no_paid and chosen.usage_authorization_required:
            raise PolicyError(
                f"Provider {name} is excluded by the no-paid policy; this hard "
                "exclusion cannot be overridden."
            )
    if named_override and not normalized_override:
        admission = (
            "is an eligible fallback rather than the recommendation"
            if plan.permits(name)
            else "is not permitted by ordinary triage"
        )
        raise PolicyError(
            f"Provider {name} {admission} for {plan.mech} "
            f"{plan.focus}/{plan.stage}. Supply an explicit override reason "
            "to route to it."
        )
    if named_override:
        reasons.append(f"override: {normalized_override}")

    entry = PROVIDERS[name]
    if max_cost is not None and not _ceiling_admits(entry.cost, max_cost):
        raise PolicyError(
            f"Cost ceiling {max_cost} does not admit provider tier {entry.cost}; "
            "an acknowledgement cannot override a supplied ceiling."
        )

    usage_gate = requires_usage_authorization(name)
    if not apply:
        reasons.append("dry run: no provider was called")
        return _Decision(
            provider=name,
            mech=plan.mech,
            focus=plan.focus,
            stage=plan.stage,
            live=False,
            cost=entry.cost,
            billing=entry.billing,
            usage_authorization_required=usage_gate,
            reasons=tuple(reasons),
        )

    reasons.append("live execution authorized with --apply")
    if usage_gate:
        if max_cost is not None:
            reasons.append(
                f"non-free use authorized by cost ceiling {max_cost} "
                f"(provider tier {entry.cost}, billing {entry.billing})"
            )
        elif acknowledge_usage:
            reasons.append(
                f"non-free quota/billing use acknowledged "
                f"(provider tier {entry.cost}, billing {entry.billing})"
            )
        else:
            raise PolicyError(
                f"Provider {name} has billing class {entry.billing} at relative "
                f"cost tier {entry.cost}. A live call needs explicit usage "
                "authorization: acknowledge possible quota/credit consumption or "
                f"set a cost ceiling that admits {entry.cost}."
            )

    return _Decision(
        provider=name,
        mech=plan.mech,
        focus=plan.focus,
        stage=plan.stage,
        live=True,
        cost=entry.cost,
        billing=entry.billing,
        usage_authorization_required=usage_gate,
        reasons=tuple(reasons),
    )
