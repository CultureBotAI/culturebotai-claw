"""Shared deep-research subsystem for the CultureBotAI fleet.

Owns the provider catalogue, focus-profile validation, deterministic triage, and
the execution policy that governs whether a provider may actually be called.
Each Mech keeps its own `conf/deep_research_provider.yaml` focus profile; the
method, safety rules, and triage/policy JSON contract live here. The eventual
schema-compliant research result contract does not.

Nothing in this package performs network access. Values read from recognised
credential environment variables are only checked for non-emptiness and are
never returned, retained, or printed.
"""

from __future__ import annotations

from .policy import (
    COST_TIERS,
    PolicyError,
    authorize,
    plan_stage,
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
    AVAILABILITY_EVIDENCE_VERSION,
    BILLING_CLASSES,
    COST_VALUE,
    CREDENTIALS,
    KNOWN_BLOCKED,
    PROVIDERS,
    SYNTHESIS_VALUE,
    TIME_VALUE,
    AvailabilityError,
    AvailabilityEvidence,
    LocalProbe,
    Provider,
    StaticAvailability,
    StaticProbe,
    SystemProbe,
    canonical_provider,
    credential_status,
    load_availability,
    normalize_allowlist,
    provider_status,
    requires_usage_authorization,
    unknown_providers,
)
from .triage import build_report, rank_stage, recommendable, score

__all__ = [
    "ALIASES",
    "ALL_CAPABILITIES",
    "AVAILABILITY_EVIDENCE_VERSION",
    "BILLING_CLASSES",
    "COST_TIERS",
    "COST_VALUE",
    "CREDENTIALS",
    "KNOWN_BLOCKED",
    "PROVIDERS",
    "SYNTHESIS_VALUE",
    "TIME_VALUE",
    "AvailabilityEvidence",
    "AvailabilityError",
    "Focus",
    "LocalProbe",
    "PolicyError",
    "ProfileError",
    "Provider",
    "ResearchProfile",
    "Stage",
    "StaticAvailability",
    "StaticProbe",
    "SystemProbe",
    "authorize",
    "build_report",
    "canonical_provider",
    "credential_status",
    "load_profile",
    "load_availability",
    "normalize_allowlist",
    "parse_profile",
    "plan_stage",
    "provider_status",
    "rank_stage",
    "recommendable",
    "requires_usage_authorization",
    "score",
    "unknown_providers",
]
