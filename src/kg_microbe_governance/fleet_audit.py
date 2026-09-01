"""Read-only audit of the five committed Mech governance pins.

The audit deliberately operates on local worktrees.  Callers are responsible
for fetching each Mech before invoking it; this module proves that every root
is the expected repository, is clean, and is exactly at its local
``refs/remotes/origin/main`` before consulting the pinned claw revision.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Optional

from kg_microbe_fleet import load_fleet_manifest

from . import (
    _desired_files,
    _require_clean_worktree,
    _validate_ref,
    _validate_target_repository,
    _verify_canonical_ref,
    load_governance_manifest,
)
from .artifacts.scripts.check_vendored_sync import (
    _SHA_PATTERN,
    MAX_DOWNLOAD_BYTES,
    CanonicalFetchError,
    Consumer,
    GovernanceError,
    GovernanceManifest,
    _git_environment,
    _run_git,
    check_repository,
    fetch_url,
    read_pin,
)


def expected_mechs() -> frozenset[str]:
    """The Mechs the governance manifest is supposed to cover.

    Was `EXPECTED_MECH_COUNT = 5`, a hardcoded fleet size -- a list of one
    number, which is what #131 is removing everywhere else. It would have
    rejected a correct consumer set the day a sixth Mech was declared, and
    accepted a wrong one of the right size today.

    Comparing the two manifests instead is both stale-proof and stricter: the
    failure it is really guarding against is the governance manifest and the
    fleet manifest describing different fleets.
    """
    return frozenset(load_fleet_manifest().mechs)


@dataclass(frozen=True)
class FleetAuditIssue:
    """One machine-readable fleet or repository audit failure."""

    code: str
    message: str
    repository: Optional[str] = None


@dataclass(frozen=True)
class RepositoryAuditResult:
    """Audit evidence and failures for one manifest consumer."""

    key: str
    github: str
    root: Path
    head: Optional[str]
    origin_main: Optional[str]
    pin: Optional[str]
    expected_artifacts: int
    checked_artifacts: int
    issues: tuple[FleetAuditIssue, ...]

    @property
    def ok(self) -> bool:
        """Return whether every repository-level requirement passed."""

        return not self.issues


@dataclass(frozen=True)
class FleetAuditResult:
    """Structured result suitable for rendering by a future CLI."""

    expected_ref: str
    repositories: tuple[RepositoryAuditResult, ...]
    fleet_issues: tuple[FleetAuditIssue, ...] = ()

    @property
    def issues(self) -> tuple[FleetAuditIssue, ...]:
        """Return fleet-wide and per-repository issues in deterministic order."""

        repository_issues = tuple(
            issue for repository in self.repositories for issue in repository.issues
        )
        return self.fleet_issues + repository_issues

    @property
    def ok(self) -> bool:
        """Return whether every declared Mech passed every check."""

        return not self.issues and len(self.repositories) == len(expected_mechs())

    def for_repository(self, key: str) -> RepositoryAuditResult:
        """Return one repository result by canonical consumer key."""

        for repository in self.repositories:
            if repository.key == key:
                return repository
        raise KeyError(key)


def _issue(code: str, message: str, consumer: Consumer) -> FleetAuditIssue:
    return FleetAuditIssue(code=code, message=message, repository=consumer.key)


def _commit_at(root: Path, revision: str) -> str:
    """Resolve one local revision to exactly one full commit identifier."""

    output = _run_git(root, ("rev-parse", "--verify", f"{revision}^{{commit}}"))
    lines = output.splitlines()
    if len(lines) != 1 or not _SHA_PATTERN.fullmatch(lines[0]):
        raise GovernanceError(f"Git revision {revision!r} did not resolve to one commit")
    return lines[0]


def _run_git_bytes(
    root: Path,
    arguments: tuple[str, ...],
    *,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    """Run a bounded, environment-sanitized Git inspection in binary mode."""

    try:
        result = subprocess.run(
            ["git", "--no-optional-locks", "-c", "core.fsmonitor=false", *arguments],
            cwd=root,
            check=False,
            capture_output=True,
            timeout=5,
            env=_git_environment(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise GovernanceError(f"Git committed-tree inspection failed at {root}") from exc
    if check and result.returncode != 0:
        raise GovernanceError(f"Git committed-tree inspection failed at {root}")
    return result


def _head_blob(
    root: Path,
    revision: str,
    relative: str,
) -> Optional[tuple[str, bytes]]:
    """Return the exact Git mode/blob at a proven commit or ``None``."""

    listing = _run_git_bytes(
        root,
        ("ls-tree", "-z", "--full-tree", revision, "--", relative),
    ).stdout
    records = tuple(record for record in listing.split(b"\0") if record)
    if not records:
        return None
    if len(records) != 1 or b"\t" not in records[0]:
        raise GovernanceError(f"Unexpected HEAD tree entry for {relative}")
    metadata, raw_path = records[0].split(b"\t", 1)
    try:
        listed_path = raw_path.decode("utf-8")
        mode, object_type, object_id = metadata.decode("ascii").split(" ")
    except (UnicodeError, ValueError) as exc:
        raise GovernanceError(f"Malformed HEAD tree entry for {relative}") from exc
    if listed_path != relative:
        raise GovernanceError(f"HEAD tree returned an aliased path for {relative}")
    if object_type != "blob":
        raise GovernanceError(
            f"Governed HEAD path is {object_type}, not a file blob: {relative}"
        )
    size_text = _run_git_bytes(root, ("cat-file", "-s", object_id)).stdout.strip()
    try:
        size = int(size_text)
    except ValueError as exc:
        raise GovernanceError(f"Invalid HEAD blob size for {relative}") from exc
    if size < 0 or size > MAX_DOWNLOAD_BYTES:
        raise GovernanceError(
            f"Governed HEAD blob exceeds {MAX_DOWNLOAD_BYTES} bytes: {relative}"
        )
    blob = _run_git_bytes(root, ("cat-file", "blob", object_id)).stdout
    if len(blob) != size:
        raise GovernanceError(f"HEAD blob size changed while reading: {relative}")
    return mode, blob


def _audit_head_governed_files(
    root: Path,
    head: str,
    consumer: Consumer,
    expected_ref: str,
    manifest: GovernanceManifest,
) -> tuple[FleetAuditIssue, ...]:
    """Compare canonical bytes and Git modes directly with the committed tree."""

    issues: list[FleetAuditIssue] = []
    for artifact_id, relative, expected_bytes, expected_mode in _desired_files(
        manifest, consumer, expected_ref
    ):
        try:
            committed = _head_blob(root, head, relative)
        except GovernanceError as exc:
            issues.append(_issue("head_read", str(exc), consumer))
            continue
        if committed is None:
            issues.append(
                _issue(
                    "head_missing",
                    f"Governed path is not tracked at HEAD: {relative}",
                    consumer,
                )
            )
            continue
        git_mode, blob = committed
        if blob != expected_bytes:
            code = "head_pin" if artifact_id == "canonical_pin" else "head_byte_drift"
            issues.append(
                _issue(code, f"Committed bytes differ at HEAD: {relative}", consumer)
            )
        expected_git_mode = "100755" if expected_mode & 0o100 else "100644"
        if git_mode != expected_git_mode:
            issues.append(
                _issue(
                    "head_mode",
                    (
                        f"Committed Git mode for {relative} is {git_mode}; "
                        f"expected {expected_git_mode}"
                    ),
                    consumer,
                )
            )
    return tuple(issues)


def _preflight_repository(
    consumer: Consumer,
    raw_root: Path,
    expected_ref: str,
    pin_path: str,
    expected_artifacts: int,
) -> RepositoryAuditResult:
    """Collect local, network-free evidence for one exact worktree."""

    root = Path(raw_root)
    issues: list[FleetAuditIssue] = []
    head: Optional[str] = None
    origin_main: Optional[str] = None
    pin: Optional[str] = None

    try:
        root = _validate_target_repository(root, consumer)
    except GovernanceError as exc:
        issues.append(_issue("repository", str(exc), consumer))
        return RepositoryAuditResult(
            consumer.key,
            consumer.github,
            root,
            head,
            origin_main,
            pin,
            expected_artifacts,
            0,
            tuple(issues),
        )

    try:
        _require_clean_worktree(root)
    except GovernanceError as exc:
        issues.append(_issue("worktree_not_clean", str(exc), consumer))

    try:
        head = _commit_at(root, "HEAD")
        origin_main = _commit_at(root, "refs/remotes/origin/main")
    except GovernanceError as exc:
        issues.append(_issue("git_revision", str(exc), consumer))
    else:
        if head != origin_main:
            issues.append(
                _issue(
                    "not_origin_main",
                    f"HEAD {head} differs from refs/remotes/origin/main {origin_main}",
                    consumer,
                )
            )

    try:
        pin = read_pin(root, pin_path)
    except GovernanceError as exc:
        issues.append(_issue("pin", str(exc), consumer))
    else:
        if pin != expected_ref:
            issues.append(
                _issue(
                    "unexpected_pin",
                    f"Canonical pin is {pin}; expected {expected_ref}",
                    consumer,
                )
            )

    return RepositoryAuditResult(
        consumer.key,
        consumer.github,
        root,
        head,
        origin_main,
        pin,
        expected_artifacts,
        0,
        tuple(issues),
    )


def _checker_issue(problem: str, consumer: Consumer) -> FleetAuditIssue:
    prefixes = {
        "CANONICAL ERROR:": "canonical",
        "UNSAFE:": "unsafe_path",
        "MISSING:": "missing",
        "ERROR:": "read_error",
        "DRIFT:": "byte_drift",
        "MODE:": "owner_execute_mode",
    }
    code = next(
        (value for prefix, value in prefixes.items() if problem.startswith(prefix)),
        "checker",
    )
    return _issue(code, problem, consumer)


def audit_fleet_pins(
    roots: Mapping[str, Path],
    expected_ref: str,
    *,
    fetch: Optional[Callable[[str], bytes]] = None,
) -> FleetAuditResult:
    """Audit exactly the Mech roots the manifest declares, without mutating them.

    ``expected_ref`` is mandatory so a fleet of consistently stale pins cannot
    pass a coordinated rollout audit.  The optional fetch callable exists solely for
    deterministic offline use; production calls use the standalone checker's
    bounded HTTPS fetcher.

    Local preflight is all-or-nothing.  No canonical bytes are fetched unless
    every declared root has the correct identity, is clean, points exactly at
    its local ``origin/main``, and contains the requested immutable pin.
    """

    expected_ref = _validate_ref(expected_ref)
    manifest = load_governance_manifest()
    consumers = manifest.consumers
    expected = expected_mechs()
    if set(consumers) != expected:
        extra = sorted(set(consumers) - expected)
        missing = sorted(expected - set(consumers))
        detail = ", ".join(
            part
            for part in (
                f"not in the fleet manifest: {', '.join(extra)}" if extra else "",
                f"declared but not a consumer: {', '.join(missing)}" if missing else "",
            )
            if part
        )
        issue = FleetAuditIssue(
            code="fleet_size",
            message=f"Governance and fleet manifests describe different fleets ({detail})",
        )
        return FleetAuditResult(expected_ref, (), (issue,))

    expected_keys = set(consumers)
    actual_keys = set(roots)
    if actual_keys != expected_keys:
        missing = sorted(expected_keys - actual_keys)
        unknown = sorted(actual_keys - expected_keys)
        issue = FleetAuditIssue(
            code="root_set",
            message=(
                "Mech roots must contain exactly the governance consumers "
                f"(missing={missing}, unknown={unknown})"
            ),
        )
        return FleetAuditResult(expected_ref, (), (issue,))

    results = tuple(
        _preflight_repository(
            consumer,
            roots[key],
            expected_ref,
            manifest.pin_path,
            len(manifest.artifacts_for(consumer)),
        )
        for key, consumer in consumers.items()
    )

    resolved_roots = [repository.root for repository in results if repository.head]
    fleet_issues: list[FleetAuditIssue] = []
    if len(resolved_roots) != len(set(resolved_roots)):
        fleet_issues.append(
            FleetAuditIssue(
                code="duplicate_root",
                message="Every governance consumer must use a distinct Git worktree root",
            )
        )

    preflight = FleetAuditResult(expected_ref, results, tuple(fleet_issues))
    if preflight.issues:
        return preflight

    fetcher = fetch or fetch_url
    cache: dict[str, bytes] = {}
    failures: dict[str, GovernanceError] = {}

    def cached_fetch(url: str) -> bytes:
        if url in cache:
            return cache[url]
        if url in failures:
            raise failures[url]
        try:
            content = fetcher(url)
            if not isinstance(content, bytes):
                raise GovernanceError("Canonical fetcher must return bytes")
        except GovernanceError as exc:
            failures[url] = exc
            raise
        cache[url] = content
        return content

    try:
        _verify_canonical_ref(expected_ref, manifest, fetch=cached_fetch)
    except CanonicalFetchError as exc:
        failed = tuple(
            replace(
                result,
                issues=(_issue("fetch", str(exc), consumers[result.key]),),
            )
            for result in results
        )
        return FleetAuditResult(expected_ref, failed)
    except GovernanceError as exc:
        failed = tuple(
            replace(
                result,
                issues=(_issue("canonical_ref", str(exc), consumers[result.key]),),
            )
            for result in results
        )
        return FleetAuditResult(expected_ref, failed)

    checked_results: list[RepositoryAuditResult] = []
    for result in results:
        consumer = consumers[result.key]
        if result.head is None:  # preflight success above proves this invariant
            raise AssertionError("successful fleet preflight must resolve HEAD")
        head_issues = _audit_head_governed_files(
            result.root,
            result.head,
            consumer,
            expected_ref,
            manifest,
        )
        checker_issues: tuple[FleetAuditIssue, ...] = ()
        try:
            checked, problems = check_repository(
                result.root,
                consumer.github,
                fetch=cached_fetch,
            )
        except CanonicalFetchError as exc:
            checker_issues = (_issue("fetch", str(exc), consumer),)
            checked_results.append(
                replace(result, issues=head_issues + checker_issues)
            )
            continue
        except GovernanceError as exc:
            checker_issues = (_issue("checker", str(exc), consumer),)
            checked_results.append(
                replace(result, issues=head_issues + checker_issues)
            )
            continue

        checker_issues = tuple(_checker_issue(problem, consumer) for problem in problems)
        if not checker_issues and checked != result.expected_artifacts:
            checker_issues = (
                _issue(
                    "applicability",
                    (
                        f"Pinned checker evaluated {checked} artifacts; "
                        f"installed manifest expects {result.expected_artifacts}"
                    ),
                    consumer,
                ),
            )
        checked_results.append(
            replace(
                result,
                checked_artifacts=checked,
                issues=head_issues + checker_issues,
            )
        )

    return FleetAuditResult(expected_ref, tuple(checked_results))
