#!/usr/bin/env python3
"""Render the per-Mech table in PR 897's description from a `kg-microbe-links taxa --all` report.

Purpose: the PR description carries, per Mech, the number of records with at
least one value of each verdict. The first version of that table was typed
from a run that predated the protist rule (culturebotai-claw#905); rendering
it from the saved JSON keeps the table and the run the same thing.
Inputs: the JSON `kg-microbe-links taxa --all` wrote to stdout, as a path.
Outputs: a Markdown table on stdout, plus one line naming any Mech with a
malformed value or an unreadable record.
Serves: culturebotai-claw PR 897. Written 2026-11-07.
"""
from __future__ import annotations

import json
import sys

COLUMNS = ["record", "species_of_strain", "above_species", "outside_domain", "unplaced", "unattested_microbial",
           "retired", "absent"]


def main() -> int:
    reports = json.load(open(sys.argv[1], encoding="utf-8"))
    print("| Mech | records | " + " | ".join(c.replace("_", " ") for c in COLUMNS) + " |")
    print("|---|---:|" + "---:|" * len(COLUMNS))
    for mech in sorted(reports):
        verdicts = reports[mech]["verdicts"]
        print(f"| {mech} | {reports[mech]['records']:,} | "
              + " | ".join(f"{verdicts[c]['records']:,}" for c in COLUMNS) + " |")
    trouble = [m for m in sorted(reports)
               if reports[m]["verdicts"]["malformed"]["occurrences"] or reports[m]["unreadable"]]
    print()
    print("Malformed values or unreadable records: " + (", ".join(trouble) if trouble else "none."))
    return 0


if __name__ == "__main__":
    sys.exit(main())
