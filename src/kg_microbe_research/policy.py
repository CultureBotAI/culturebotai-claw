"""Execution policy: what it takes before a provider may actually be called.

Today four of the five Mech runners execute a provider unless the caller passes
`--dry-run`, so the *default* action spends credits; only ProteinTraitsMech
defaults to dry-run and requires `--apply`. None of the five has any notion of
authorizing a *paid* call specifically, and none binds execution to the triage
result — `--provider` is accepted verbatim, so a manually named provider
silently escapes both the profile's allowlist and its no-paid filter.

This module is the single gate. Three separate decisions are required before a
billable call happens, and no default supplies any of them:

1. **Live execution** — `apply=True`. Without it the decision is a dry run.
2. **Paid authorization** — for a provider whose cost tier is paid, either an
   explicit acknowledgement or a cost ceiling that admits that tier.
3. **Plan agreement** — the provider must be one the immutable triage plan
   would recommend, or the caller must record an override reason.

Refusal is the default for anything unproven: a blocked or unavailable provider
is never routable, whatever the caller passes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .profile import ResearchProfile
from .providers import (
    COST_VALUE,
    PAID_COSTS,
    PROVIDERS,
    canonical_provider,
    normalize_allowlist,
    unknown_providers,
)
from .triage import LocalProbe, Ranked, rank_stage, recommendable

# Ordered weakest-to-strongest, so a ceiling admits every tier at or below it.
COST_TIERS: tuple[str, ...] = tuple(
    sorted(COST_VALUE, key=lambda tier: COST_VALUE[tier])
)


class PolicyError(RuntimeError):
    """A requested execution is not permitted."""


@dataclass(frozen=True)
class TriagePlan:
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

    @property
    def recommended(self) -> Ranked | None:
        return self.allowed[0] if self.allowed else None

    def row(self, provider: str) -> Ranked | None:
        canonical = canonical_provider(provider)
        return next((row for row in self.ranking if row.provider == canonical), None)

    def permits(self, provider: str) -> bool:
        canonical = canonical_provider(provider)
        return any(row.provider == canonical for row in self.allowed)


def plan_stage(
    profile: ResearchProfile,
    stage: str,
    *,
    focus: str | None = None,
    allow: Sequence[str] | frozenset[str] | None = None,
    no_paid: bool = False,
    environ: Mapping[str, str] | None = None,
    probe: LocalProbe | None = None,
) -> TriagePlan:
    """Rank a stage and freeze the result as the authority for execution."""
    resolved = profile.focus(focus)
    allowlist = normalize_allowlist(allow)
    if allowlist is not None:
        unknown = unknown_providers(allowlist)
        if unknown:
            raise PolicyError(
                f"Unknown provider(s) in allowlist: {unknown}; choose from "
                f"{', '.join(sorted(PROVIDERS))}"
            )
    ranking = rank_stage(resolved, stage, environ=environ, probe=probe)
    return TriagePlan(
        mech=profile.mech,
        focus=resolved.name,
        stage=stage,
        ranking=tuple(ranking),
        allowed=tuple(recommendable(ranking, allow=allowlist, no_paid=no_paid)),
        no_paid=no_paid,
        allowlist=allowlist,
    )


@dataclass(frozen=True)
class Decision:
    """The authorized outcome. `live` is the only field that spends money."""

    provider: str
    mech: str
    focus: str
    stage: str
    live: bool
    paid: bool
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
            "paid": self.paid,
            "reasons": list(self.reasons),
        }


def requires_paid_authorization(provider: str) -> bool:
    """Whether calling this provider needs an explicit paid decision."""
    entry = PROVIDERS.get(canonical_provider(provider))
    return entry is not None and entry.cost in PAID_COSTS


def _ceiling_admits(cost: str, ceiling: str) -> bool:
    return COST_VALUE[cost] <= COST_VALUE[ceiling]


def authorize(
    plan: TriagePlan,
    *,
    provider: str | None = None,
    apply: bool = False,
    acknowledge_paid: bool = False,
    max_cost: str | None = None,
    override_reason: str | None = None,
) -> Decision:
    """Decide whether the requested call may proceed, and in which mode.

    Returns a dry-run `Decision` unless `apply` is set. Raises `PolicyError`
    rather than downgrading to a dry run when a *live* call was explicitly
    requested but is not permitted, so a refused authorization can never be
    mistaken for a successful cheap one.
    """
    if max_cost is not None and max_cost not in COST_VALUE:
        raise PolicyError(
            f"Unknown cost ceiling {max_cost!r}; choose one of: "
            f"{', '.join(COST_TIERS)}"
        )

    reasons: list[str] = []
    if provider is None:
        chosen = plan.recommended
        if chosen is None:
            raise PolicyError(
                f"No provider is available for {plan.mech} {plan.focus}/{plan.stage} "
                f"under the current policy"
                + (" (no-paid)" if plan.no_paid else "")
                + (
                    f" and allowlist {sorted(plan.allowlist)}"
                    if plan.allowlist is not None
                    else ""
                )
            )
        name = chosen.provider
        reasons.append(f"triage recommended {name} for {plan.stage}")
    else:
        name = canonical_provider(provider)
        chosen = plan.row(name)
        if chosen is None:
            raise PolicyError(
                f"Unknown provider {provider!r} (resolved to {name!r}); choose from "
                f"{', '.join(sorted(PROVIDERS))}"
            )

    if chosen.status == "blocked":
        raise PolicyError(
            f"Provider {name} is blocked and cannot be routed to: "
            f"{chosen.status_reason}"
        )
    if chosen.status != "available":
        raise PolicyError(
            f"Provider {name} is not available ({chosen.status}): "
            f"{chosen.status_reason}"
        )

    # A named provider that triage would not have offered is exactly the silent
    # bypass this gate exists to stop: it escapes both the allowlist and the
    # no-paid filter. It is still permitted, but only on the record.
    if provider is not None and not plan.permits(name):
        if not override_reason:
            detail = "the no-paid policy" if (plan.no_paid and chosen.paid) else "triage"
            raise PolicyError(
                f"Provider {name} is not permitted for {plan.mech} "
                f"{plan.focus}/{plan.stage} by {detail}. Supply an explicit override "
                f"reason to route to it anyway."
            )
        reasons.append(f"override: {override_reason}")

    paid = requires_paid_authorization(name)
    if not apply:
        reasons.append("dry run: no provider was called")
        return Decision(name, plan.mech, plan.focus, plan.stage, False, paid, tuple(reasons))

    reasons.append("live execution authorized with --apply")
    if paid:
        if max_cost is not None and _ceiling_admits(chosen.cost, max_cost):
            reasons.append(
                f"paid call authorized by cost ceiling {max_cost} "
                f"(provider tier {chosen.cost})"
            )
        elif acknowledge_paid:
            reasons.append(f"paid call acknowledged (provider tier {chosen.cost})")
        else:
            ceiling = (
                f"; cost ceiling {max_cost} does not admit tier {chosen.cost}"
                if max_cost is not None
                else ""
            )
            raise PolicyError(
                f"Provider {name} bills at cost tier {chosen.cost}. A live call "
                f"needs an explicit paid authorization: acknowledge the charge or "
                f"set a cost ceiling that admits {chosen.cost}{ceiling}."
            )

    return Decision(name, plan.mech, plan.focus, plan.stage, True, paid, tuple(reasons))
