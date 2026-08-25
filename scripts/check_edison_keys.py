#!/usr/bin/env python3
"""Discover Edison Scientific API keys and, only when asked, authenticate them.

The canonical fleet manifest decides which Mechs participate in Edison key
discovery. Only explicitly configured checkout roots are inspected; this script
never guesses a sibling-repository layout. Credentials may use either
``EDISON_API_KEY`` in a repository ``.env`` or ``EDISON_PLATFORM_API_KEY`` in
the live environment (the name the Edison SDK reads by default).

It hits the SDK's own auth endpoint — `POST {stage}/auth/login` with
`{"api_key": <key>}` (see edison_client/utils/auth.py `_run_auth`). A 200 with an
`access_token` means the key authenticates; 401/403 means it does not. This is a
pure auth exchange: no research job is created, no credits are spent.

Secrets are NEVER printed — each candidate is identified only by its source(s),
a sha256 prefix, and its length.

Discovery is the default and performs no network requests. Authentication is
an explicit action::

    python scripts/check_edison_keys.py
    python scripts/check_edison_keys.py --apply-network --stage prod

Exit code: in discovery mode, 0 when candidates are found; in network mode, 0
if at least one candidate authenticates and 1 otherwise (2 for configuration or
usage errors).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Mapping, Sequence

from kg_microbe_fleet import FleetManifest, FleetManifestError, load_fleet_manifest
from plugins.repository_settings import (
    RepositoryConfigurationError,
    RepositorySettings,
)

# edison_client/models/app.py Stage enum (API base URLs).
STAGES = {
    "prod": "https://api.platform.edisonscientific.com",
    "staging": "https://staging.api.platform.edisonscientific.com",
    "dev": "https://dev.api.platform.edisonscientific.com",
}

# Env-var names that hold an Edison key somewhere in the fleet.
KEY_VARS = ("EDISON_PLATFORM_API_KEY", "EDISON_API_KEY")

EDISON_DISCOVERY_CAPABILITY = "edison_key_discovery"


def _fingerprint(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()[:12]


def _parse_env_file(path: Path) -> dict[str, str]:
    """Minimal .env reader: KEY=VALUE lines, strips surrounding quotes/space."""
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if key.startswith("export "):
            key = key[len("export "):].strip()
        val = val.strip().strip('"').strip("'")
        if key in KEY_VARS and val:
            out[key] = val
    return out


def discover_candidates(
    manifest: FleetManifest,
    environ: Mapping[str, str] | None = None,
) -> dict[str, list[str]]:
    """Map key value to non-secret sources that carry it.

    Repository ``.env`` files are considered only when the repository declares
    :data:`EDISON_DISCOVERY_CAPABILITY` and its manifest-defined root variable
    is configured. The configured path itself is authoritative.
    """

    env = os.environ if environ is None else environ
    by_value: dict[str, list[str]] = {}

    def add(value: str, source: str) -> None:
        if value:
            by_value.setdefault(value, []).append(source)

    # Live environment (the names actually exported into the session).
    for var in KEY_VARS:
        add(env.get(var, ""), f"env:{var}")

    # Per-repo .env files. RepositorySettings verifies that every configured
    # path is the exact Git worktree and GitHub origin declared by the manifest.
    # An unset checkout root is skipped; a configured-but-wrong root aborts.
    eligible = manifest.with_capability(EDISON_DISCOVERY_CAPABILITY)
    settings = RepositorySettings.from_environment(environ=env, manifest=manifest)
    invalid = {key: settings.invalid[key] for key in eligible if key in settings.invalid}
    if invalid:
        details = "; ".join(f"{key}: {message}" for key, message in invalid.items())
        raise RepositoryConfigurationError(
            f"configured Edison discovery target is untrustworthy: {details}"
        )

    for key in eligible:
        mech = manifest.get(key)
        if key in settings.unconfigured:
            continue
        root = settings.get_target(key).path
        env_path = root / ".env"
        if env_path.is_symlink():
            try:
                env_path.resolve(strict=True).relative_to(root)
            except (FileNotFoundError, ValueError) as exc:
                raise RepositoryConfigurationError(
                    f"{mech.display_name} .env must resolve inside {root}"
                ) from exc
        for var, val in _parse_env_file(env_path).items():
            add(val, f"{mech.display_name}/.env:{var}")

    return by_value


def probe(base_url: str, api_key: str, timeout: float = 30.0) -> tuple[str, str]:
    """POST /auth/login. Returns (verdict, detail). Never echoes the key."""
    req = urllib.request.Request(
        f"{base_url}/auth/login",
        data=json.dumps({"api_key": api_key}).encode(),
        headers={"Content-Type": "application/json", "x-client": "sdk"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode() or "{}")
            if resp.status == 200 and body.get("access_token"):
                return "VALID", f"200, got access_token (len {len(body['access_token'])})"
            return "UNEXPECTED", f"HTTP {resp.status}, no access_token"
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            return "INVALID", f"HTTP {e.code} (rejected)"
        return "ERROR", f"HTTP {e.code}"
    except (urllib.error.URLError, TimeoutError) as e:
        return "ERROR", f"network: {e}"


def main(argv: Sequence[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", choices=STAGES, default="prod")
    network_mode = ap.add_mutually_exclusive_group()
    network_mode.add_argument(
        "--apply-network",
        dest="apply_network",
        action="store_true",
        help="authenticate discovered candidates (explicit opt-in; creates no research job)",
    )
    network_mode.add_argument(
        "--no-network",
        dest="apply_network",
        action="store_false",
        help="discovery only (the default; retained as an explicit safety flag)",
    )
    ap.set_defaults(apply_network=False)
    args = ap.parse_args(argv)

    base_url = STAGES[args.stage]

    try:
        manifest = load_fleet_manifest()
    except FleetManifestError as exc:
        print(f"Unable to load the fleet manifest: {exc}", file=sys.stderr)
        return 2

    eligible = manifest.with_capability(EDISON_DISCOVERY_CAPABILITY)
    if not eligible:
        print(
            f"No Mech enables capability {EDISON_DISCOVERY_CAPABILITY!r}; "
            "refusing an unscoped discovery.",
            file=sys.stderr,
        )
        return 2

    try:
        candidates = discover_candidates(manifest)
    except RepositoryConfigurationError as exc:
        print(f"Unable to trust configured repository roots: {exc}", file=sys.stderr)
        return 2
    if not candidates:
        print(
            "No Edison keys found in the live environment or configured, "
            "capability-enabled Mech roots. Nothing to test.",
            file=sys.stderr,
        )
        return 2

    print(f"Discovered {len(candidates)} distinct key value(s) across the fleet.")
    if args.apply_network:
        print(f"Probing {base_url}/auth/login (auth-only; no job, no credits)\n")
    else:
        print("Discovery-only mode: no authentication requests were made.\n")

    rows = []
    any_valid = False
    for value, sources in sorted(candidates.items(), key=lambda kv: kv[1]):
        fp, length = _fingerprint(value), len(value)
        if not args.apply_network:
            verdict, detail = "—", "(skipped)"
        else:
            verdict, detail = probe(base_url, value)
            any_valid = any_valid or verdict == "VALID"
        rows.append((verdict, fp, length, ", ".join(sources), detail))

    w = max((len(r[3]) for r in rows), default=10)
    print(f"{'VERDICT':<10} {'sha256[:12]':<14} {'len':>4}  {'sources':<{w}}  detail")
    print("-" * (10 + 14 + 4 + w + 30))
    for verdict, fp, length, sources, detail in rows:
        print(f"{verdict:<10} {fp:<14} {length:>4}  {sources:<{w}}  {detail}")

    if args.apply_network:
        print()
        if any_valid:
            print(
                "✓ At least one key authenticates. Configure the intended Mech's "
                "EDISON_API_KEY (or EDISON_PLATFORM_API_KEY alias) from a VALID "
                "source above."
            )
        else:
            print("✗ No candidate authenticated against this stage. Try --stage dev/staging, "
                  "or the key needs to be reissued.")
    return 0 if (not args.apply_network or any_valid) else 1


if __name__ == "__main__":
    raise SystemExit(main())
