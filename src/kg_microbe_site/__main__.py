"""`kg-microbe-site check` -- judge one Mech's built site against the contract."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_fleet.roots import MechRootError, resolve_mech_root
from kg_microbe_site.contract import check_site
from kg_microbe_site.contrast import ContrastFinding, check_stylesheet

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

    # Both site_path and published_root are repository-relative, so the Mech
    # root is resolved even when --site overrides where the pages come from.
    try:
        root = resolve_mech_root(args.mech, claw_root=CLAW_ROOT)
    except MechRootError as exc:
        if args.site is None:
            print(str(exc), file=sys.stderr)
            return 2
        root = None
    site = args.site or (root / capability.settings["site_path"])

    if not site.is_dir():
        print(f"{args.mech}: no site at {site}", file=sys.stderr)
        return 2

    allowed = capability.settings.get("allowed_hosts", ())
    # Walked once and passed in, rather than counted again afterwards: #242,
    # the same duplicate-traversal #231 hid in the corpus reader for months
    # because every corpus it was tried on was too small to notice.
    declared_root = capability.settings.get("published_root")
    published = None
    if declared_root:
        # Relative to the repository, not to the site: TraitMech checks pages/
        # and publishes the whole checkout, so its published_root is ".".
        base = root if root is not None else site
        published = (base / declared_root).resolve()
        if not published.is_dir():
            # Otherwise every reference silently becomes REFERENCE_OUTSIDE_SITE,
            # because nothing can be inside a directory that is not there --
            # a whole-site failure that reads like a whole-site finding.
            print(
                f"{args.mech}: declared published_root {declared_root!r} is not "
                f"a directory ({published})",
                file=sys.stderr,
            )
            return 2
    pages = sorted(site.rglob("*.html"))
    findings = check_site(
        site, allowed_hosts=list(allowed), pages=pages, published_root=published
    )

    # #249: the palette is judged where the text is painted. Every stylesheet
    # the site ships, not only the one named style.css -- a page that carries
    # its own is exactly where an unreviewed palette hides.
    # Walked once and reused, for the reason the block above records: #242.
    # The first version of this walked rglob twice -- once to check and once to
    # count for the summary line -- which is the same defect, reintroduced
    # three lines under the comment warning about it.
    stylesheets = sorted(site.rglob("*.css"))
    contrast: list[ContrastFinding] = []
    for sheet in stylesheets:
        contrast.extend(check_stylesheet(sheet))

    for finding in findings:
        print(finding, file=sys.stderr)
    for entry in contrast:
        print(entry, file=sys.stderr)
    counts = Counter(finding.code for finding in findings)
    counts.update(entry.code for entry in contrast)
    summary = ", ".join(f"{code} {n}" for code, n in sorted(counts.items())) or "clean"
    print(
        f"{args.mech}: {len(pages)} pages and "
        f"{len(stylesheets)} stylesheet(s) under {site}: {summary}"
    )
    return 1 if findings or contrast else 0


if __name__ == "__main__":  # pragma: no cover - console entry point
    sys.exit(main())
