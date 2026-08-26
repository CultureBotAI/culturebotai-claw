"""Shared deep-research subsystem for the CultureBotAI fleet.

Owns the provider catalogue, focus-profile validation, deterministic triage, and
the execution policy that governs whether a provider may actually be called.
Each Mech keeps its own `conf/deep_research_provider.yaml` focus profile; the
method, the safety rules, and the output contract live here.

Nothing in this package performs network access or reads a credential *value*.
"""

from __future__ import annotations

from .policy import (
    COST_TIERS,
    Decision,
    PolicyError,
    TriagePlan,
    authorize,
    plan_stage,
    requires_paid_authorization,
)
from .profile import (
    Focus,
    ProfileError,
    ResearchProfile,
    Stage,
    load_profile,
    parse_profile,
)
from .providers import (
    ALIASES,
    ALL_CAPABILITIES,
    COST_VALUE,
    CREDENTIALS,
    KNOWN_BLOCKED,
    PAID_COSTS,
    PROVIDERS,
    SYNTHESIS_VALUE,
    TIME_VALUE,
    LocalProbe,
    Provider,
    StaticProbe,
    SystemProbe,
    canonical_provider,
    credential_status,
    is_paid,
    normalize_allowlist,
    provider_status,
    unknown_providers,
)
from .triage import Ranked, build_report, rank_stage, recommendable, score

__all__ = [
    "ALIASES",
    "ALL_CAPABILITIES",
    "COST_TIERS",
    "COST_VALUE",
    "CREDENTIALS",
    "KNOWN_BLOCKED",
    "PAID_COSTS",
    "PROVIDERS",
    "SYNTHESIS_VALUE",
    "TIME_VALUE",
    "Decision",
    "Focus",
    "LocalProbe",
    "PolicyError",
    "ProfileError",
    "Provider",
    "Ranked",
    "ResearchProfile",
    "Stage",
    "StaticProbe",
    "SystemProbe",
    "TriagePlan",
    "authorize",
    "build_report",
    "canonical_provider",
    "credential_status",
    "is_paid",
    "load_profile",
    "normalize_allowlist",
    "parse_profile",
    "plan_stage",
    "provider_status",
    "rank_stage",
    "recommendable",
    "requires_paid_authorization",
    "score",
    "unknown_providers",
]
