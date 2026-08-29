"""Fetch one source release: retry-bounded, validated, atomically promoted.

Phase 6 item 3 (#132), second half. Generalized from ProteinTraitsMech's
`scripts/fetch_source.py`, which is the strongest of the fleet's fetchers: it
downloads to a sibling temporary file, validates size, digest, magic prefix and
required content, and only then replaces the destination, writing a provenance
sidecar beside it.

Three things changed in the move.

The transport is injectable. PTM shells out to `curl`, so every test of the
validation and promotion logic needs the network and the binary. Here `curl` is
the default transport and nothing else knows about it, which is what lets the
interesting behaviour -- a retry that eventually succeeds, a digest mismatch, a
destination left untouched by a failure -- be exercised offline and
deterministically.

Retries are counted here rather than delegated to `curl --retry`, for the same
reason: a bound nothing can observe is a bound nobody has checked.

And the sidecar is verifiable. Two files cannot be replaced in one atomic step,
so a process that dies between them leaves a payload from this fetch beside a
sidecar from the last one -- provenance that is silently wrong, which is worse
than provenance that is missing. `verify` reads the pair back and reports the
mismatch, so a torn promotion is detectable rather than believed.
"""

from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

__all__ = [
    "DEFAULT_FILE_MODE",
    "CurlTransport",
    "FetchError",
    "FetchPlan",
    "FetchResult",
    "TransportResult",
    "ValidationFailed",
    "fetch",
    "sha256_of",
    "validate",
    "verify",
]

DEFAULT_FILE_MODE = 0o644
SIDECAR_VERSION = 1


class FetchError(RuntimeError):
    """The transfer failed, after every permitted attempt."""


class ValidationFailed(FetchError):
    """The bytes arrived and are not what was asked for."""


@dataclass(frozen=True)
class FetchPlan:
    """What to fetch, and what would make it acceptable."""

    url: str
    destination: Path
    sha256: str | None = None
    min_bytes: int = 1
    contains: Sequence[str] = ()
    prefix: bytes | None = None
    headers: Sequence[str] = ()

    @property
    def sidecar(self) -> Path:
        return Path(f"{self.destination}.fetch.json")


@dataclass(frozen=True)
class TransportResult:
    """What a transport reports after writing bytes to the path it was given."""

    resolved_url: str | None = None
    headers: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class FetchResult:
    bytes: int
    sha256: str
    attempts: int
    metadata: dict[str, object]


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def validate(path: Path, plan: FetchPlan) -> tuple[int, str]:
    """Judge a completed download, returning its size and digest.

    Order matters: size first, because a truncated or empty response is the
    common failure and its message is the clearest; digest next, because it
    subsumes the content checks when a source is pinned.
    """
    size = Path(path).stat().st_size
    if size < plan.min_bytes:
        raise ValidationFailed(
            f"download is {size:,} bytes; expected at least {plan.min_bytes:,}"
        )

    digest = sha256_of(path)
    if plan.sha256 and digest.lower() != plan.sha256.lower():
        raise ValidationFailed(
            f"SHA-256 mismatch: got {digest}, expected {plan.sha256.lower()}"
        )

    if plan.prefix:
        with Path(path).open("rb") as stream:
            actual = stream.read(len(plan.prefix))
        if actual != plan.prefix:
            raise ValidationFailed(
                f"content prefix mismatch: got {actual.hex()}, "
                f"expected {plan.prefix.hex()}"
            )

    if plan.contains:
        content = Path(path).read_bytes()
        for expected in plan.contains:
            if expected.encode("utf-8") not in content:
                raise ValidationFailed(
                    f"download does not contain required text: {expected!r}"
                )
    return size, digest


def _temporary(directory: Path, name: str, suffix: str) -> Path:
    handle, raw = tempfile.mkstemp(prefix=f".{name}.", suffix=suffix, dir=directory)
    os.close(handle)
    return Path(raw)


def _install_mode(path: Path) -> int:
    """Preserve an existing mode, else the public raw-release default."""
    try:
        return stat.S_IMODE(path.stat().st_mode)
    except FileNotFoundError:
        return DEFAULT_FILE_MODE


def _sync_directory(directory: Path) -> None:
    """Make the rename itself durable, not just the bytes it points at."""
    handle = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(handle)
    finally:
        os.close(handle)


def _write_sidecar(path: Path, payload: dict[str, object], mode: int) -> Path:
    temp = _temporary(path.parent, path.name, ".tmp")
    try:
        with temp.open("w", encoding="utf-8") as stream:
            json.dump(payload, stream, indent=2, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temp, mode)
        return temp
    except BaseException:
        temp.unlink(missing_ok=True)
        raise


class CurlTransport:
    """The default transport: one `curl` invocation per attempt.

    Retries are the caller's, not curl's, so `--retry` is deliberately absent.
    """

    def __init__(self, *, connect_timeout: int = 15, max_time: int = 300) -> None:
        self.connect_timeout = connect_timeout
        self.max_time = max_time

    def command(self, plan: FetchPlan, target: Path, headers_file: Path) -> list[str]:
        """The exact invocation, so a test can read it rather than the source.

        `--fail` is what stops an HTTP error page being written out as content.
        `--retry` is absent on purpose: retries are the caller's, counted where
        they can be observed.
        """
        command = [
            "curl", "--fail", "--location", "--silent", "--show-error",
            "--connect-timeout", str(self.connect_timeout),
            "--max-time", str(self.max_time),
            "--dump-header", str(headers_file),
            "--output", str(target),
            "--write-out", "%{url_effective}",
        ]
        for header in plan.headers:
            command.extend(("--header", header))
        command.extend(("--", plan.url))
        return command

    def __call__(self, plan: FetchPlan, target: Path) -> TransportResult:
        headers_file = _temporary(target.parent, target.name, ".headers")
        command = self.command(plan, target, headers_file)
        try:
            completed = subprocess.run(
                command, check=False, capture_output=True, text=True,
                timeout=self.max_time,
            )
            if completed.returncode:
                detail = (
                    completed.stderr.strip() or f"curl exited {completed.returncode}"
                )
                raise FetchError(detail)
            raw = headers_file.read_text(encoding="iso-8859-1", errors="replace")
            return TransportResult(
                resolved_url=completed.stdout.strip() or plan.url,
                headers=_parse_headers(raw),
            )
        except subprocess.TimeoutExpired as exc:
            raise FetchError(
                f"download timed out after {self.max_time} seconds"
            ) from exc
        except FileNotFoundError as exc:  # curl itself is absent
            raise FetchError("curl is not installed") from exc
        finally:
            headers_file.unlink(missing_ok=True)


def _parse_headers(raw: str) -> dict[str, str]:
    """The LAST value for each header, so a redirect chain reports its end."""
    found: dict[str, str] = {}
    for line in raw.splitlines():
        name, separator, value = line.partition(":")
        if separator:
            found[name.strip().lower()] = value.strip()
    return found


Transport = Callable[[FetchPlan, Path], TransportResult]


def fetch(
    plan: FetchPlan,
    *,
    transport: Transport | None = None,
    attempts: int = 4,
    now: Callable[[], datetime] | None = None,
) -> FetchResult:
    """Fetch, validate, and replace the destination only if both succeeded.

    A failure leaves the destination exactly as it was. That is the point of
    downloading to a sibling temporary file: a half-written release in place is
    indistinguishable from a good one until something reads it.
    """
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    transport = transport or CurlTransport()
    now = now or (lambda: datetime.now(timezone.utc))

    destination = Path(plan.destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    sidecar = plan.sidecar
    sidecar.parent.mkdir(parents=True, exist_ok=True)

    destination_mode = _install_mode(destination)
    sidecar_mode = _install_mode(sidecar)

    last: FetchError | None = None
    for attempt in range(1, attempts + 1):
        temp = _temporary(destination.parent, destination.name, ".part")
        sidecar_temp: Path | None = None
        try:
            outcome = transport(plan, temp)
            size, digest = validate(temp, plan)

            metadata: dict[str, object] = {
                "version": SIDECAR_VERSION,
                "attempts": attempt,
                "bytes": size,
                "destination": str(destination),
                "fetched_at": now().isoformat(),
                "requested_url": plan.url,
                "resolved_url": outcome.resolved_url or plan.url,
                "sha256": digest,
            }
            for key in ("etag", "last-modified", "content-type"):
                value = outcome.headers.get(key)
                if value:
                    metadata[key.replace("-", "_")] = value

            sidecar_temp = _write_sidecar(sidecar, metadata, sidecar_mode)
            with temp.open("rb") as stream:
                os.fsync(stream.fileno())
            os.chmod(temp, destination_mode)
            # The payload goes first, and the order matters even though
            # `verify` detects a tear either way. A process that dies between
            # the two renames leaves, in this order, the NEW file beside its
            # old provenance -- the data is right and the record is stale. In
            # the other order it leaves the OLD file beside provenance
            # claiming it is new, so every consumer that reads the file and
            # not the sidecar -- which is most of them -- silently gets last
            # release's bytes.
            os.replace(temp, destination)
            os.replace(sidecar_temp, sidecar)
            sidecar_temp = None
            _sync_directory(destination.parent)
            return FetchResult(size, digest, attempt, metadata)
        except FetchError as exc:
            last = exc
        finally:
            temp.unlink(missing_ok=True)
            if sidecar_temp is not None:
                sidecar_temp.unlink(missing_ok=True)

    raise FetchError(f"giving up after {attempts} attempt(s): {last}") from last


def verify(destination: Path, sidecar: Path | None = None) -> str | None:
    """Check a fetched file against its sidecar; return a complaint or None.

    Two files cannot be replaced in one atomic step, so a process that dies
    between them leaves a payload from this fetch beside a sidecar from the
    last. Silently wrong provenance is worse than missing provenance, and this
    is what makes the difference visible.
    """
    destination = Path(destination)
    sidecar = Path(sidecar) if sidecar else Path(f"{destination}.fetch.json")

    if not destination.is_file():
        return f"{destination} does not exist"
    if not sidecar.is_file():
        return f"{destination} has no provenance sidecar at {sidecar.name}"
    try:
        recorded = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return f"cannot read {sidecar.name}: {exc}"
    if not isinstance(recorded, dict):
        return f"{sidecar.name} is not a JSON object"

    expected = recorded.get("sha256")
    if not expected:
        return f"{sidecar.name} records no sha256"
    actual = sha256_of(destination)
    if actual != expected:
        return (
            f"{destination.name} does not match its sidecar: file is {actual}, "
            f"{sidecar.name} records {expected} -- the pair was written by "
            f"different fetches"
        )
    return None
