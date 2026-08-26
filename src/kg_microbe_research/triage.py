"""Deterministic provider ranking and stage assignment.

Scoring is a pure function of the profile and the catalogue; only availability
consults the environment, and it does so through an injectable mapping so tests
never depend on the developer's shell.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .profile import Focus, ProfileError, ResearchProfile, Stage
from .providers import (
    COST_VALUE,
    PAID_COSTS,
    PROVIDERS,
    SYNTHESIS_VALUE,
    TIME_VALUE,
    LocalProbe,
    Provider,
    normalize_allowlist,
    provider_status,
)


@dataclass(frozen=True)
class Ranked:
    """One provider's standing for one stage."""

    provider: str
    label: str
    status: str
    status_reason: str
    fit: int
    score: float
    cost: str
    time: str
    synthesis: str
    source_scope: str
    best_for: str
    limitation: str

    @property
    def paid(self) -> bool:
        return self.cost in PAID_COSTS

    def as_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "label": self.label,
            "status": self.status,
            "status_reason": self.status_reason,
            "fit": self.fit,
            "cost": self.cost,
            "time": self.time,
            "synthesis": self.synthesis,
            "source_scope": self.source_scope,
            "best_for": self.best_for,
            "limitation": self.limitation,
            "paid": self.paid,
        }


def score(provider: Provider, stage: Stage, adjustments: Mapping[str, float]) -> float:
    """The raw, unnormalized fit of one provider for one stage."""
    total = sum(
        weight
        for capability, weight in stage.capabilities.items()
        if capability in provider.capabilities
    )
    total += stage.weight("synthesis_weight") * SYNTHESIS_VALUE[provider.synthesis]
    total += stage.weight("speed_weight") * (5 - TIME_VALUE[provider.time])
    total += stage.weight("cost_weight") * (5 - COST_VALUE[provider.cost])
    total += float(adjustments.get(provider.name, 0.0))
    return total


def rank_stage(
    focus: Focus,
    stage_name: str,
    *,
    environ: Mapping[str, str] | None = None,
    probe: LocalProbe | None = None,
) -> list[Ranked]:
    """Rank every catalogue provider for one stage, best first."""
    if stage_name not in focus.stages:
        # ProfileError, not KeyError: `main` handles the profile-error family, and
        # an unknown *focus* already reports cleanly. A tool whose job is to gate
        # spending must not answer a typo with a traceback.
        raise ProfileError(
            f"Focus {focus.name!r} has no stage {stage_name!r}; choose one of: "
            f"{', '.join(focus.stages)}"
        )
    stage = focus.stages[stage_name]
    raw = {
        name: score(provider, stage, focus.provider_adjustments)
        for name, provider in PROVIDERS.items()
    }
    # `high = 1.0` only replaces a non-positive maximum. It does NOT rescue the
    # case where every score is negative: fit is 0 for all of them either way,
    # so the published ranking collapses. The raw score is retained as a
    # tie-breaker below so the *order* still means something there; a real fix
    # needs min-max rather than max-only normalization (CultureMech#315).
    high = max(raw.values(), default=0.0)
    if high <= 0:
        high = 1.0

    rows = []
    for name, provider in PROVIDERS.items():
        status, reason = provider_status(name, environ, probe)
        rows.append(
            Ranked(
                provider=name,
                label=provider.label,
                status=status,
                status_reason=reason,
                fit=round(100 * max(0.0, raw[name]) / high),
                score=raw[name],
                cost=provider.cost,
                time=provider.time,
                synthesis=provider.synthesis,
                source_scope=provider.source_scope,
                best_for=provider.best_for,
                limitation=provider.limitation,
            )
        )
    return sorted(rows, key=lambda row: (-row.fit, -row.score, row.provider))


def recommendable(
    rows: list[Ranked],
    *,
    allow: Iterable[str] | None = None,
    no_paid: bool = False,
) -> list[Ranked]:
    """The rows a recommendation may be drawn from, in ranked order.

    One place, so the text and JSON paths cannot disagree — the JSON filter used
    to narrow `ranking` while leaving `recommended_available` untouched, so
    `--provider asta --json` recommended `claude_code` out of a document whose
    only ranked provider was asta (CultureMech#290).
    """
    out = [row for row in rows if row.status == "available" and row.provider != "mock"]
    allowlist = normalize_allowlist(allow)
    if allowlist is not None:
        out = [row for row in out if row.provider in allowlist]
    if no_paid:
        out = [row for row in out if not row.paid]
    return out


def build_report(
    profile: ResearchProfile,
    focus_name: str | None = None,
    *,
    allow: Iterable[str] | None = None,
    no_paid: bool = False,
    environ: Mapping[str, str] | None = None,
    probe: LocalProbe | None = None,
) -> dict[str, Any]:
    """A complete, JSON-serializable triage report for one focus."""
    focus = profile.focus(focus_name)
    allowlist = normalize_allowlist(allow)
    stages = []
    for stage_name in focus.stages:
        ranking = rank_stage(focus, stage_name, environ=environ, probe=probe)
        available = recommendable(ranking, allow=allowlist, no_paid=no_paid)
        stages.append(
            {
                "name": stage_name,
                "objective": focus.stages[stage_name].objective,
                "ranking": [row.as_dict() for row in ranking],
                "recommended_available": available[0].as_dict() if available else None,
                "fallback_available": (
                    available[1].as_dict() if len(available) > 1 else None
                ),
            }
        )
    return {
        "mech": profile.mech,
        "target": profile.target,
        "focus": focus.name,
        "focus_label": focus.label,
        "objective": focus.objective,
        "evidence_policy": profile.evidence_policy,
        "source_priorities": list(focus.source_priorities),
        "stages": stages,
    }
