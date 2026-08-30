"""`kg-microbe-site check` -- judge one Mech's built site against the contract."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_fleet.roots import MechRootError, resolve_mech_root
from kg_microbe_site.contract import check_site

CLAW_ROOT = Path(__file__).resolve().parents[2]


def main(argv: list[str] | None = None) -> int:
    manifest = load_fleet_manifest()
    parser = argparse.ArgumentParser(
        prog="kg-microbe-site",
        description=(
            "Check a built site for the things every generated site owes its "
            "readers: a title, a declared language, alt text, headings that do "
            "not skip a level, references that resolve, and no dependency on a "
            "third party to render. Run it on build output -- on template "
            "sources it reports pages the build has not created yet."
        ),
    )
    parser.add_argument("command", choices=["check"])
    parser.add_argument("--mech", required=True, choices=sorted(manifest.mechs))
    parser.add_argument(
        "--site",
        type=Path,
        help="the built site, overriding the manifest's site_path (CI builds "
        "into a directory that does not exist in the checkout)",
    )
    args = parser.parse_args(argv)

    mech = manifest.mechs[args.mech]
    capability = mech.capabilities.get("site_contract")
    if capability is None or not capability.is_enabled:
        reason = getattr(capability, "reason", "") or "not declared in the manifest"
        print(f"{args.mech} declares no site contract: {reason}")
        return 0

    site = args.site
    if site is None:
        try:
            root = resolve_mech_root(args.mech, claw_root=CLAW_ROOT)
        except MechRootError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        site = root / capability.settings["site_path"]

    if not site.is_dir():
        print(f"{args.mech}: no site at {site}", file=sys.stderr)
        return 2

    allowed = capability.settings.get("allowed_hosts", ())
    findings = check_site(site, allowed_hosts=list(allowed))

    for finding in findings:
        print(finding, file=sys.stderr)
    counts = Counter(finding.code for finding in findings)
    pages = sum(1 for _ in site.rglob("*.html"))
    summary = ", ".join(f"{code} {n}" for code, n in sorted(counts.items())) or "clean"
    print(f"{args.mech}: {pages} pages under {site}: {summary}")
    return 1 if findings else 0


if __name__ == "__main__":  # pragma: no cover - console entry point
    sys.exit(main())
