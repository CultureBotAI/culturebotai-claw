"""The fleet's single deep-research provider catalogue.

Every Mech previously carried its own copy of this table in
`scripts/deep_research_provider.py`. The five copies agreed on the provider
facts and drifted everywhere else, so this module owns the facts, the status
vocabulary, and the usage-authorization boundary, while each Mech keeps its own focus
profile (see `kg_microbe_research.profile`).

No provider is called here. Values read from recognised credential environment
variables are never returned, retained, or printed; configuration detection
only checks whether such a variable has a non-empty value.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import MappingProxyType
from typing import Any, Protocol


@dataclass(frozen=True)
class Provider:
    """A research provider's fixed, Mech-independent characteristics."""

    name: str
    label: str
    source_scope: str
    synthesis: str
    cost: str
    billing: str
    time: str
    capabilities: frozenset[str]
    best_for: str
    limitation: str


PROVIDERS: dict[str, Provider] = {
    "asta": Provider(
        "asta",
        "Asta",
        "scientific corpus",
        "none",
        "low",
        "metered",
        "fast",
        frozenset({"academic_search", "scientific_literature", "citation_tracking", "snippets"}),
        "fast paper and passage discovery",
        "retrieval packet only; no narrative synthesis",
    ),
    "falcon": Provider(
        "falcon",
        "Edison / Falcon",
        "scientific literature",
        "deep",
        "high",
        "metered",
        "slow",
        frozenset(
            {
                "academic_search",
                "scientific_literature",
                "citation_tracking",
                "synthesis",
            }
        ),
        "scientific evidence synthesis",
        "academic sources only; paid and slower",
    ),
    "openscientist": Provider(
        "openscientist",
        "OpenScientist",
        "PubMed and scientific literature",
        "agentic",
        "high",
        "metered",
        "very_slow",
        frozenset(
            {
                "academic_search",
                "scientific_literature",
                "citation_tracking",
                "synthesis",
                "code_interpretation",
                "hypothesis_tracking",
            }
        ),
        "iterative mechanism and hypothesis research",
        "long-running and PubMed-focused",
    ),
    "claude_code": Provider(
        "claude_code",
        "Claude Code",
        "open web",
        "agentic",
        "medium",
        "metered",
        "slow",
        frozenset(
            {
                "web_search",
                "citation_tracking",
                "synthesis",
                "code_interpretation",
                "structured_databases",
            }
        ),
        "broad web/database source coverage",
        "quality depends on web access and local CLI authentication",
    ),
    "openai": Provider(
        "openai",
        "OpenAI Deep Research",
        "open web",
        "deep",
        "very_high",
        "metered",
        "very_slow",
        frozenset(
            {
                "web_search",
                "citation_tracking",
                "synthesis",
                "code_interpretation",
                "real_time_data",
                "structured_databases",
            }
        ),
        "comprehensive multi-source synthesis",
        "highest cost and long response times",
    ),
    "perplexity": Provider(
        "perplexity",
        "Perplexity",
        "open web",
        "deep",
        "high",
        "metered",
        "slow",
        frozenset(
            {
                "web_search",
                "citation_tracking",
                "synthesis",
                "real_time_data",
                "multi_language",
                "structured_databases",
            }
        ),
        "current web research with source links",
        "less specialized for primary scientific evidence",
    ),
    "consensus": Provider(
        "consensus",
        "Consensus",
        "peer-reviewed literature",
        "summary",
        "low",
        "metered",
        "fast",
        frozenset({"academic_search", "citation_tracking", "scientific_literature"}),
        "quick peer-reviewed evidence checks",
        "limited depth and no general web/database search",
    ),
    "cyberian": Provider(
        "cyberian",
        "Cyberian",
        "agent-selected web and literature",
        "agentic",
        "high",
        "metered",
        "very_slow",
        frozenset(
            {
                "web_search",
                "academic_search",
                "citation_tracking",
                "synthesis",
                "code_interpretation",
                "structured_databases",
            }
        ),
        "custom iterative research workflows",
        "requires local agent tooling and careful authority limits",
    ),
    "cborg": Provider(
        "cborg",
        "CBORG proxy",
        "model-dependent open web",
        "deep",
        "medium",
        "metered",
        "slow",
        frozenset({"web_search", "citation_tracking", "synthesis", "code_interpretation"}),
        "OpenAI-compatible research through the LBL proxy",
        "capabilities depend on the selected proxy model",
    ),
    "mock": Provider(
        "mock",
        "Mock",
        "fixtures",
        "none",
        "low",
        "free",
        "fast",
        frozenset(),
        "future offline executor tests and dry runs",
        "catalogue-only stub; executable mock provider is not implemented",
    ),
    "deeper_med": Provider(
        "deeper_med",
        "DeepER-Med",
        "biomedical databases",
        "agentic",
        "high",
        "unknown",
        "slow",
        frozenset(
            {
                "academic_search",
                "scientific_literature",
                "citation_tracking",
                "synthesis",
                "structured_databases",
            }
        ),
        "future biomedical evidence workflows",
        "stub: no public API is available",
    ),
}

PROVIDER_CATALOGUE_VERSION = 1
TRIAGE_CONTRACT_VERSION = 1
TRIAGE_ALGORITHM_ID = "weighted-capability-v1:max-fit-v1:fit-score-name-order-v1"


def _catalogue_sha256() -> str:
    """Digest the public provider facts used when a plan is ranked.

    This is provenance, not an authorization token.  The serialization is
    deliberately explicit and stable so a saved result identifies catalogue
    drift without capturing credentials or machine-local availability.
    """

    payload = {
        name: {
            "label": provider.label,
            "source_scope": provider.source_scope,
            "synthesis": provider.synthesis,
            "cost": provider.cost,
            "billing": provider.billing,
            "time": provider.time,
            "capabilities": sorted(provider.capabilities),
            "best_for": provider.best_for,
            "limitation": provider.limitation,
        }
        for name, provider in sorted(PROVIDERS.items())
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


PROVIDER_CATALOGUE_SHA256 = _catalogue_sha256()

ALIASES = {"edison": "falcon", "futurehouse": "falcon", "claude-code": "claude_code"}

ALL_CAPABILITIES = frozenset(
    capability for provider in PROVIDERS.values() for capability in provider.capabilities
)

COST_VALUE = {"low": 1, "medium": 2, "high": 3, "very_high": 4}
TIME_VALUE = {"fast": 1, "medium": 2, "slow": 3, "very_slow": 4}
SYNTHESIS_VALUE = {"none": 0, "summary": 1, "deep": 2, "agentic": 3}
BILLING_CLASSES = frozenset({"free", "metered", "unknown"})
AVAILABILITY_EVIDENCE_VERSION = 1
MAX_AVAILABILITY_EVIDENCE_LIFETIME = timedelta(hours=24)
AVAILABILITY_CLOCK_SKEW = timedelta(minutes=5)

# Providers whose credential is configurable but which do not actually work,
# with what happened when each was called (CultureMech#284). A credential check
# cannot discover this: "Available" in `deep-research-client providers` means an
# env var is set, nothing more. Without this table the triage tool recommended
# `falcon` as the primary route for every stage while the justfile beside it
# recorded falcon returning HTTP 402 — the tool contradicting its own
# documentation (CultureMech#290).
#
# Remove an entry when the provider is verified working again, rather than
# editing the reason.
KNOWN_BLOCKED: dict[str, str] = {
    "falcon": "HTTP 402 Payment Required (measured CultureMech#284)",
    "cyberian": ("HTTP 500; wraps an agentapi service that is not running (CultureMech#284)"),
}

DEEPER_MED_STUB_REASON = "no public API"
MOCK_UNAVAILABLE_REASON = "set ENABLE_MOCK_PROVIDER=true to expose the catalogue-only stub"
MOCK_STUB_REASON = "catalogue-only mock; executable provider is not implemented"


def _triage_contract_sha256() -> str:
    """Digest every static input that changes provider ranking or admission.

    Availability evidence and credential values are deliberately excluded
    because they are per-plan observations. Their resulting status and reason
    are recorded on every assignment. Credential *names* and expiry policy are
    static admission inputs and are included. The algorithm identifier is an
    explicit versioned review boundary: changing scoring or sorting requires
    changing that identifier and retaining support for the prior contract.
    """

    payload = {
        "algorithm": TRIAGE_ALGORITHM_ID,
        "provider_catalogue_sha256": PROVIDER_CATALOGUE_SHA256,
        "aliases": dict(sorted(ALIASES.items())),
        "known_blocked": dict(sorted(KNOWN_BLOCKED.items())),
        "static_status_reasons": {
            "deeper_med": {"stub": DEEPER_MED_STUB_REASON},
            "mock": {
                "unavailable": MOCK_UNAVAILABLE_REASON,
                "stub": MOCK_STUB_REASON,
            },
        },
        "cost_value": dict(sorted(COST_VALUE.items())),
        "time_value": dict(sorted(TIME_VALUE.items())),
        "synthesis_value": dict(sorted(SYNTHESIS_VALUE.items())),
        "availability_evidence_version": AVAILABILITY_EVIDENCE_VERSION,
        "maximum_availability_lifetime_seconds": int(
            MAX_AVAILABILITY_EVIDENCE_LIFETIME.total_seconds()
        ),
        "availability_clock_skew_seconds": int(AVAILABILITY_CLOCK_SKEW.total_seconds()),
        "credential_names": {
            provider: list(names) for provider, names in sorted(CREDENTIALS.items())
        },
        "recommendable_policy": {
            "available_status": "available",
            "exclude_mock": True,
            "no_paid_requires_billing": "free",
            "configuration_is_not_availability": True,
            "local_probe_providers": ["claude_code", "cyberian"],
        },
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


# Credential variables per provider. Providers resolved by probing the local
# machine instead (claude_code, cyberian) are handled in `credential_status`.
CREDENTIALS: dict[str, tuple[str, ...]] = {
    "asta": ("ASTA_API_KEY",),
    "falcon": ("EDISON_API_KEY", "EDISON_PLATFORM_API_KEY", "FUTUREHOUSE_API_KEY"),
    "openscientist": ("OPENSCIENTIST_API_KEY",),
    "openai": ("OPENAI_API_KEY",),
    "perplexity": ("PERPLEXITY_API_KEY",),
    "consensus": ("CONSENSUS_API_KEY",),
    "cborg": ("CBORG_API_KEY",),
}

TRIAGE_CONTRACT_SHA256 = _triage_contract_sha256()


class LocalProbe(Protocol):
    """How the catalogue discovers locally-installed provider tooling.

    `claude_code` and `cyberian` are resolved by inspecting this machine rather
    than by reading a credential variable, so without this seam their status
    depends on whatever happens to be on the developer's PATH. Injecting the
    probe is what lets local configuration be reported deterministically; see
    `StaticProbe`. Functional availability is separate `AvailabilityEvidence`.
    """

    def which(self, executable: str) -> bool:
        """Whether `executable` is on PATH."""

    def has_module(self, module: str) -> bool:
        """Whether `module` is importable."""


@dataclass(frozen=True)
class SystemProbe:
    """The real machine."""

    def which(self, executable: str) -> bool:
        return shutil.which(executable) is not None

    def has_module(self, module: str) -> bool:
        return importlib.util.find_spec(module) is not None


@dataclass(frozen=True)
class StaticProbe:
    """A fixed answer, for tests and for rendering another host's view."""

    executables: frozenset[str] = frozenset()
    modules: frozenset[str] = frozenset()

    def which(self, executable: str) -> bool:
        return executable in self.executables

    def has_module(self, module: str) -> bool:
        return module in self.modules


SYSTEM_PROBE = SystemProbe()


class AvailabilityEvidence(Protocol):
    """Previously established functional status, without performing a call.

    Configuration and local-tool discovery are deliberately insufficient to
    claim that a provider works. A caller that has a separately obtained health
    result can inject it through this interface. The research package itself
    never performs a provider health probe or provider network access.
    """

    def verified_status(self, provider: str) -> tuple[str, str] | None:
        """Return an attested status and reason, or no evidence for `provider`."""


@dataclass(frozen=True)
class StaticAvailability:
    """Fixed, non-expiring evidence for tests or a trusted ephemeral caller view.

    Allowed evidence statuses are `available`, `blocked`, and `unavailable`.
    The mapping is copied on construction so later caller mutation cannot alter
    a plan between triage and authorization. Persisted evidence must instead be
    loaded with `load_availability`, which retains and rechecks its expiry.
    """

    statuses: Mapping[str, tuple[str, str]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        copied: dict[str, tuple[str, str]] = {}
        for raw_name, result in self.statuses.items():
            if not isinstance(raw_name, str):
                raise ValueError(
                    f"availability evidence provider names must be strings: {raw_name!r}"
                )
            name = canonical_provider(raw_name)
            if name not in PROVIDERS:
                raise ValueError(f"unknown provider in availability evidence: {raw_name!r}")
            if name in copied:
                raise ValueError(
                    f"availability evidence has multiple names resolving to provider {name!r}"
                )
            if (
                not isinstance(result, tuple)
                or len(result) != 2
                or not isinstance(result[0], str)
                or result[0] not in {"available", "blocked", "unavailable"}
                or not isinstance(result[1], str)
                or not result[1].strip()
            ):
                raise ValueError(
                    "availability evidence must be (available|blocked|unavailable, "
                    "non-empty reason)"
                )
            copied[name] = (result[0], result[1].strip())
        object.__setattr__(self, "statuses", MappingProxyType(copied))

    def verified_status(self, provider: str) -> tuple[str, str] | None:
        return self.statuses.get(canonical_provider(provider))


def _system_utc_now() -> datetime:
    """Return the wall clock through an injectable seam used by offline tests."""
    return datetime.now(timezone.utc)


def _normalize_reference_time(value: Any, where: str) -> datetime:
    if not isinstance(value, datetime):
        raise AvailabilityError(f"{where} must return a timezone-aware datetime")
    try:
        offset = value.utcoffset()
        if value.tzinfo is None or offset is None:
            raise AvailabilityError(f"{where} must include a timezone")
        return value.astimezone(timezone.utc)
    except AvailabilityError:
        raise
    except (ValueError, OverflowError) as exc:
        raise AvailabilityError(f"{where} could not be normalized to UTC") from exc


@dataclass(frozen=True)
class _CachedAvailability:
    """Immutable persisted evidence whose expiry is enforced on every lookup."""

    evidence: StaticAvailability
    expires_at: Mapping[str, datetime]
    _clock: Callable[[], datetime] = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        copied = dict(self.expires_at)
        if set(copied) != set(self.evidence.statuses):
            raise ValueError("cached availability expiries must match its providers")
        object.__setattr__(self, "expires_at", MappingProxyType(copied))

    def verified_status(self, provider: str) -> tuple[str, str] | None:
        name = canonical_provider(provider)
        result = self.evidence.verified_status(name)
        if result is None:
            return None
        reference = _normalize_reference_time(
            self._clock(), "availability evidence clock"
        )
        expiry = self.expires_at[name]
        if reference >= expiry:
            return (
                "unavailable",
                f"cached evidence expired at {expiry.isoformat()}; {result[1]}",
            )
        return result


class AvailabilityError(ValueError):
    """A cached availability-evidence document is malformed or unsupported."""


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    """Reject JSON's otherwise silent last-key-wins duplicate behavior."""
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise AvailabilityError(f"duplicate JSON key {key!r}")
        result[key] = value
    return result


def load_availability(
    path: Path,
) -> AvailabilityEvidence:
    """Load strict, caller-supplied cached functional evidence from JSON.

    The package never creates this evidence or performs a provider health probe.
    A trusted wrapper can persist a previous health result using this deliberately
    small versioned shape::

        {"version": 1, "providers": {"asta": {
          "status": "available", "reason": "preflight succeeded",
          "checked_at": "2026-08-25T12:00:00Z",
          "expires_at": "2026-08-25T13:00:00Z",
          "source": "trusted-preflight-v1", "context": "host/account/model label"
        }}}

    Credential values do not belong in this file. Persisted evidence is accepted
    for at most 24 hours, rechecked on every lookup, and must identify its source
    and configuration context; this is a trusted caller boundary, not a
    cryptographic attestation.
    """
    return _load_availability(path)


def _parse_evidence_time(value: Any, where: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise AvailabilityError(f"{where} must be a timezone-aware ISO-8601 string")
    normalized = value.strip()
    if normalized.endswith("Z"):
        normalized = normalized[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
        offset = parsed.utcoffset()
        if parsed.tzinfo is None or offset is None:
            raise AvailabilityError(f"{where} must include a timezone offset")
        return parsed.astimezone(timezone.utc)
    except AvailabilityError:
        raise
    except (ValueError, OverflowError) as exc:
        raise AvailabilityError(f"{where} must be a timezone-aware ISO-8601 string") from exc


def _load_availability(
    path: Path,
    *,
    clock: Callable[[], datetime] = _system_utc_now,
) -> _CachedAvailability:
    """Implementation seam whose clock can be fixed by offline tests."""
    evidence_path = Path(path)
    try:
        text = evidence_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise AvailabilityError(
            f"Cannot read availability evidence {evidence_path}: {exc}"
        ) from exc
    try:
        document = json.loads(text, object_pairs_hook=_unique_json_object)
    except json.JSONDecodeError as exc:
        raise AvailabilityError(
            f"Availability evidence {evidence_path} is not valid JSON: {exc}"
        ) from exc

    if not isinstance(document, dict):
        raise AvailabilityError("availability evidence must be a JSON object")
    if set(document) != {"version", "providers"}:
        raise AvailabilityError(
            "availability evidence must contain exactly 'version' and 'providers'"
        )
    version = document["version"]
    if (
        isinstance(version, bool)
        or not isinstance(version, int)
        or version != AVAILABILITY_EVIDENCE_VERSION
    ):
        raise AvailabilityError(
            f"unsupported availability evidence version {version!r}; expected "
            f"{AVAILABILITY_EVIDENCE_VERSION}"
        )
    entries = document["providers"]
    if not isinstance(entries, dict):
        raise AvailabilityError("availability evidence 'providers' must be an object")

    reference = _normalize_reference_time(clock(), "availability reference time")

    statuses: dict[str, tuple[str, str]] = {}
    expirations: dict[str, datetime] = {}
    for name, entry in entries.items():
        required = {
            "status",
            "reason",
            "checked_at",
            "expires_at",
            "source",
            "context",
        }
        if not isinstance(entry, dict) or set(entry) != required:
            raise AvailabilityError(
                f"availability evidence for {name!r} must contain exactly "
                + ", ".join(repr(key) for key in sorted(required))
            )
        status = entry["status"]
        reason = entry["reason"]
        source = entry["source"]
        context = entry["context"]
        if not all(
            isinstance(value, str) and value.strip() for value in (status, reason, source, context)
        ):
            raise AvailabilityError(
                f"availability evidence for {name!r} status, reason, source, and "
                "context must be non-empty strings"
            )
        if status != status.strip():
            raise AvailabilityError(
                f"availability evidence for {name!r} status must not have surrounding whitespace"
            )
        checked_at = _parse_evidence_time(
            entry["checked_at"], f"availability evidence for {name!r}.checked_at"
        )
        expires_at = _parse_evidence_time(
            entry["expires_at"], f"availability evidence for {name!r}.expires_at"
        )
        # Subtract only after ordering. Adding the allowed skew to
        # `datetime.max` would overflow even though the clock is otherwise a
        # valid timezone-aware value.
        if checked_at > reference and checked_at - reference > AVAILABILITY_CLOCK_SKEW:
            raise AvailabilityError(f"availability evidence for {name!r} is dated in the future")
        if expires_at <= checked_at:
            raise AvailabilityError(
                f"availability evidence for {name!r} must expire after it was checked"
            )
        if expires_at - checked_at > MAX_AVAILABILITY_EVIDENCE_LIFETIME:
            raise AvailabilityError(
                f"availability evidence for {name!r} exceeds the 24-hour lifetime"
            )
        if expires_at <= reference:
            raise AvailabilityError(f"availability evidence for {name!r} has expired")
        audit_reason = (
            f"{reason.strip()}; source={source.strip()}; context={context.strip()}; "
            f"checked_at={checked_at.isoformat()}; expires_at={expires_at.isoformat()}"
        )
        statuses[name] = (status, audit_reason)
        expirations[canonical_provider(name)] = expires_at
    try:
        evidence = StaticAvailability(statuses)
        return _CachedAvailability(evidence, expirations, clock)
    except ValueError as exc:
        raise AvailabilityError(str(exc)) from exc


def canonical_provider(name: str) -> str:
    """Resolve an alias or loosely-spelled name to its catalogue key."""
    key = name.strip().casefold().replace(" ", "_")
    return ALIASES.get(key, key)


def provider_status(
    provider: str,
    environ: Mapping[str, str] | None = None,
    probe: LocalProbe | None = None,
    availability: AvailabilityEvidence | None = None,
) -> tuple[str, str]:
    """Whether this provider can actually be routed to, and why.

    A measured-dead provider reports `blocked` however well its credential is
    configured — that is the whole point, since a configured credential is what
    made `falcon` look routable while returning HTTP 402. Credential recognition
    is still a separate, testable question: see `credential_status`.
    """
    name = canonical_provider(provider)
    if name not in PROVIDERS:
        return "unavailable", f"unknown provider {provider!r}"
    if name in KNOWN_BLOCKED:
        return "blocked", KNOWN_BLOCKED[name]

    configured, reason = credential_status(name, environ, probe)
    if configured in {"stub", "unavailable"}:
        return configured, reason
    if name == "mock":
        return "stub", MOCK_STUB_REASON

    evidence = availability.verified_status(name) if availability is not None else None
    if evidence is not None:
        return evidence
    return "configured", f"{reason}; functional availability is unverified"


def credential_status(
    provider: str,
    environ: Mapping[str, str] | None = None,
    probe: LocalProbe | None = None,
) -> tuple[str, str]:
    """Status from local configuration alone, ignoring whether the provider works.

    Kept separate from `provider_status` so "do we recognise this env var name"
    stays covered for providers that are currently blocked — otherwise adding a
    provider to KNOWN_BLOCKED would silently drop the test that its credential
    aliases are spelled right.
    """
    env = os.environ if environ is None else environ
    resolver: LocalProbe = SYSTEM_PROBE if probe is None else probe
    name = canonical_provider(provider)
    if name not in PROVIDERS:
        return "unavailable", f"unknown provider {provider!r}"
    if name == "deeper_med":
        return "stub", DEEPER_MED_STUB_REASON
    if name == "mock":
        enabled = env.get("ENABLE_MOCK_PROVIDER", "").casefold() in {"1", "true", "yes"}
        return (
            ("configured", "explicitly enabled")
            if enabled
            else (
                "unavailable",
                MOCK_UNAVAILABLE_REASON,
            )
        )
    if name == "claude_code":
        return (
            ("configured", "local CLI found")
            if resolver.which("claude")
            else ("unavailable", "claude CLI not found")
        )
    if name == "cyberian":
        installed = resolver.has_module("cyberian")
        return (
            ("configured", "local package found")
            if installed
            else ("unavailable", "install the cyberian extra")
        )

    keys = CREDENTIALS.get(name, ())
    if any(env.get(key) for key in keys):
        return "configured", "credential configured"
    if not keys:
        return "unavailable", f"no credential is defined for provider {name!r}"
    return "unavailable", f"set {' or '.join(keys)}"


def normalize_allowlist(
    allow: Iterable[str] | None,
) -> frozenset[str] | None:
    """Canonicalize an allowlist so aliases resolve before any filtering.

    Shared by triage and policy. When only `plan_stage` canonicalized, `triage
    --allow claude-code` reported that nothing fit while `authorize --allow
    claude-code` routed to claude_code — the CultureMech#290 failure class
    (one filter, two implementations) in a new place.
    """
    if allow is None:
        return None
    return frozenset(canonical_provider(str(name)) for name in allow)


def unknown_providers(names: Iterable[str]) -> list[str]:
    """The canonical names in `names` that no catalogue entry defines."""
    return sorted({str(name) for name in names} - set(PROVIDERS))


# Providers that are never a recommendation, whatever their status or billing.
# `recommendable` and the --no-paid satisfiability check must agree on this, so
# it is named once rather than spelled `!= "mock"` in each (the #139 lesson).
NEVER_RECOMMENDED = frozenset({"mock"})


def free_providers() -> tuple[str, ...]:
    """Catalogue providers whose billing class is explicitly `free`."""
    return tuple(sorted(name for name, p in PROVIDERS.items() if p.billing == "free"))


def no_paid_candidates() -> tuple[str, ...]:
    """Providers `--no-paid` could ever recommend.

    Empty means the flag is unsatisfiable by construction rather than by
    configuration: every provider a caller could be routed to is metered or of
    unknown billing, so no credential, evidence, or profile can make --no-paid
    produce a recommendation (#152).
    """
    return tuple(name for name in free_providers() if name not in NEVER_RECOMMENDED)


def requires_usage_authorization(provider: str) -> bool:
    """Whether live use needs a separate quota/billing decision.

    This is independent of the relative `cost` score used for ranking. Every
    external provider is conservatively metered; unknown billing also fails
    closed. Only a provider explicitly classified `free` skips this gate.
    """
    entry = PROVIDERS.get(canonical_provider(provider))
    return entry is None or entry.billing != "free"
