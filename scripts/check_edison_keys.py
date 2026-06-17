#!/usr/bin/env python3
"""Probe which Edison Scientific API key actually authenticates.

The four Mech repos and the shell environment carry *different* Edison
credentials under two different variable names (`EDISON_API_KEY` in the per-repo
`.env` files; `EDISON_PLATFORM_API_KEY` in the live environment — the name the
`edison_client` SDK reads by default). TraitMech's deep-research was reporting a
missing/invalid key; this script settles "which key is functional" empirically.

It hits the SDK's own auth endpoint — `POST {stage}/auth/login` with
`{"api_key": <key>}` (see edison_client/utils/auth.py `_run_auth`). A 200 with an
`access_token` means the key authenticates; 401/403 means it does not. This is a
pure auth exchange: no research job is created, no credits are spent.

Secrets are NEVER printed — each candidate is identified only by its source(s),
a sha256 prefix, and its length.

Usage:
    python scripts/check_edison_keys.py                 # probe PROD
    python scripts/check_edison_keys.py --stage dev     # dev/staging/prod
    python scripts/check_edison_keys.py --no-network    # discover/dedupe only

Exit code: 0 if at least one candidate authenticates, 1 otherwise (2 on usage
error). Intended as a diagnostic; safe to re-run.
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

# edison_client/models/app.py Stage enum (API base URLs).
STAGES = {
    "prod": "https://api.platform.edisonscientific.com",
    "staging": "https://staging.api.platform.edisonscientific.com",
    "dev": "https://dev.api.platform.edisonscientific.com",
}

# Env-var names that hold an Edison key somewhere in the fleet.
KEY_VARS = ("EDISON_PLATFORM_API_KEY", "EDISON_API_KEY")

# Per-repo .env files, relative to the KG-Microbe parent dir (this repo's parent).
REPO_ENVS = {
    "CultureMech": "CultureMech/.env",
    "MIM": "MediaIngredientMech/.env",
    "CommunityMech": "CommunityMech/CommunityMech/.env",
    "TraitMech": "TraitMech/.env",
}


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


def discover_candidates(kg_parent: Path) -> dict[str, list[str]]:
    """Map key VALUE -> list of human-readable sources that carry it."""
    by_value: dict[str, list[str]] = {}

    def add(value: str, source: str) -> None:
        if value:
            by_value.setdefault(value, []).append(source)

    # Live environment (the names actually exported into the session).
    for var in KEY_VARS:
        add(os.environ.get(var, ""), f"env:{var}")

    # Per-repo .env files.
    for repo, rel in REPO_ENVS.items():
        for var, val in _parse_env_file(kg_parent / rel).items():
            add(val, f"{repo}/.env:{var}")

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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", choices=STAGES, default="prod")
    ap.add_argument("--no-network", action="store_true", help="discover + dedupe only; no auth calls")
    args = ap.parse_args()

    # This repo is .../KG-Microbe/culturebotai-claw; siblings live one level up.
    kg_parent = Path(__file__).resolve().parents[2]
    base_url = STAGES[args.stage]

    candidates = discover_candidates(kg_parent)
    if not candidates:
        print("No Edison keys found in env or any repo .env. Nothing to test.", file=sys.stderr)
        return 2

    print(f"Discovered {len(candidates)} distinct key value(s) across the fleet.")
    if not args.no_network:
        print(f"Probing {base_url}/auth/login (auth-only; no job, no credits)\n")

    rows = []
    any_valid = False
    for value, sources in sorted(candidates.items(), key=lambda kv: kv[1]):
        fp, length = _fingerprint(value), len(value)
        if args.no_network:
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

    if not args.no_network:
        print()
        if any_valid:
            print("✓ At least one key authenticates. Point TraitMech's EDISON_API_KEY "
                  "(or an EDISON_PLATFORM_API_KEY alias) at a VALID source above.")
        else:
            print("✗ No candidate authenticated against this stage. Try --stage dev/staging, "
                  "or the key needs to be reissued.")
    return 0 if (args.no_network or any_valid) else 1


if __name__ == "__main__":
    raise SystemExit(main())
