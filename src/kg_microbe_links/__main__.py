"""`kg-microbe-links taxa` -- do the taxa a Mech's records cite resolve in TaxonMech?"""

from __future__ import annotations

import argparse
import json
import sys

from kg_microbe_fleet import load_fleet_manifest
from kg_microbe_fleet.roots import MechRootError, claw_root, resolve_mech_root
from kg_microbe_links.taxa import TaxonIndex, TaxonLinksError, Verdict, collect

CLAW_ROOT = claw_root()
CAPABILITY = "taxon_links"
BLOCKING = {Verdict.RETIRED.value, Verdict.ABSENT.value, Verdict.MALFORMED.value}


def main(argv: list[str] | None = None) -> int:
    manifest = load_fleet_manifest()
    parser = argparse.ArgumentParser(
        prog="kg-microbe-links",
        description=(
            "Judge every taxon a Mech's records cite, in the slots its manifest "
            "taxon_links declaration names, against what TaxonMech holds: a retired "
            "id, a record, a strain whose nearest ancestor is a record, a rank above "
            "species, a taxon outside TaxonMech's domain, an unplaced metagenome or "
            "unclassified sequence, an unattested microbe, or an id absent from the "
            "pinned taxdump. Reads TaxonMech's checkout only; nothing is fetched. "
            "Deterministic JSON on stdout."
        ),
    )
    parser.add_argument("command", choices=["taxa"])
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--mech", choices=sorted(manifest.mechs))
    target.add_argument("--all", action="store_true", help="every Mech with an enabled declaration")
    parser.add_argument("--root", help="the Mech checkout to read, instead of the configured root")
    parser.add_argument("--taxonmech-root", help="the TaxonMech checkout, instead of the configured root")
    parser.add_argument("--sample", type=int, help="read only the first N records, in sorted order")
    parser.add_argument("--strict", action="store_true",
                        help="exit 1 when any record cites a retired, absent or malformed id, or will not parse")
    args = parser.parse_args(argv)
    if args.all and args.root:
        parser.error("--root names one checkout; it cannot go with --all")

    try:
        taxonmech_root = resolve_mech_root("taxonmech", claw_root=CLAW_ROOT, manifest=manifest,
                                           explicit=args.taxonmech_root)
        index = TaxonIndex(taxonmech_root)
    except (MechRootError, TaxonLinksError) as exc:
        print(str(exc), file=sys.stderr)
        return 2

    keys = sorted(manifest.mechs) if args.all else [args.mech]
    reports: dict[str, dict] = {}
    blocking = False
    for key in keys:
        mech = manifest.mechs[key]
        capability = mech.capabilities.get(CAPABILITY)
        if capability is None or not capability.is_enabled:
            reason = getattr(capability, "reason", "") or "not declared in the manifest"
            if not args.all:
                print(f"{key} declares no taxon links: {reason}")
                return 0
            print(f"{key}: skipped, {reason}", file=sys.stderr)
            continue
        try:
            root = resolve_mech_root(key, claw_root=CLAW_ROOT, manifest=manifest, explicit=args.root)
            report = collect(key, root, list(mech.record_globs), list(capability.settings.get("slots", ())),
                             index, sample=args.sample)
            payload = report.as_dict(index)  # may read the taxdump, which can be missing: still exit 2
        except (MechRootError, TaxonLinksError) as exc:
            print(str(exc), file=sys.stderr)
            return 2
        reports[key] = payload
        verdicts = payload["verdicts"]
        print(f"{key}: {payload['records']} records; "
              + ", ".join(f"{v} {verdicts[v]['occurrences']}" for v in verdicts if verdicts[v]["occurrences"])
              + (f"; {len(payload['unreadable'])} unreadable" if payload["unreadable"] else ""), file=sys.stderr)
        if payload["unreadable"] or any(verdicts[v]["occurrences"] for v in BLOCKING):
            blocking = True
    json.dump(reports if args.all else reports.get(keys[0], {}), sys.stdout, indent=2, sort_keys=True)
    sys.stdout.write("\n")
    return 1 if args.strict and blocking else 0


if __name__ == "__main__":
    sys.exit(main())
