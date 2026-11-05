#!/usr/bin/env python3
"""Prepare one Mech's adoption of the shared quote gate, dry-run first.

Purpose: in an isolated Mech worktree, fetch the abstracts the gate's declared
scope cites, measure what the gate then reports, and optionally record the
residual findings in the Mech's known-findings ledger. It calls the library
functions behind `kg-microbe-evidence-fetch` and
`kg-microbe-evidence --record-known-findings`; it exists only because those
CLIs read the profile from claw's manifest, which enables the Mech in the later
rollout release. PROFILES below is what was prepared; the release declares the
CellStructureMech and HabitatMech entries, and not CultureMech's (#774).
Inputs: --mech, --root (the Mech worktree; its origin identity is verified),
PROFILES, and OPENCLAW_WORKSPACE for the shared lock directory.
Outputs: cache files under the profile's cache_dir and, with --ledger-issue,
the ledger -- both only with --apply and under LockManager -- plus a JSON
summary at --json.
Serves: culturebotai-claw#729. Written 2026-11-03. CultureMech was prepared
here but not adopted: its record_globs name a derived layer (#774, #779).
"""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from kg_microbe_evidence import (
    EvidenceConfig,
    plan_known_findings,
    validate_corpus,
    write_known_findings,
)
from kg_microbe_evidence.fetch import fetch_missing, plan
from kg_microbe_fleet import load_fleet_manifest
from plugins.lock_manager import LockManager
from plugins.repository_settings import RepositoryTarget

LEDGER = "curation/evidence_known_findings.tsv"
COMMON = {"reference_fields": ["reference"], "snippet_fields": ["snippet"],
          "evidence_fields": ["evidence"], "known_findings": LEDGER}
# CultureMech ignores references_cache/, its native tools' local cache, so the
# shared gate's committed sources get their own tracked directory there.
PROFILES = {
    "culturemech": {"cache_dir": "evidence_cache", **COMMON},
    "cellstructuremech": {"cache_dir": "references_cache", **COMMON},
    "habitatmech": {"cache_dir": "references_cache", **COMMON},
}


def summary(report: dict) -> dict:
    residual = Counter(r["verdict"] for r in report["results"]
                       if r["verdict"] not in {"OK", "NO_QUOTE"} and not r.get("known_issue"))
    return {"records": report["records"], "evidence_items": report["evidence_items"],
            "quote_bearing_items": report["quote_bearing_items"],
            "verdicts": {k: v for k, v in report["verdicts"].items() if v},
            "unrecorded_findings": dict(residual), "errors": len(report["errors"]),
            "stale": len(report["stale_known_findings"])}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mech", required=True, choices=sorted(PROFILES))
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--ledger-issue", help="record residual findings, owned by this issue URL")
    parser.add_argument("--json", type=Path, required=True)
    args = parser.parse_args()
    mech = load_fleet_manifest().get(args.mech)
    target = RepositoryTarget(mech.key, args.root.expanduser().resolve(), mech.github)
    target.open()
    root = target.path
    config = EvidenceConfig.from_settings(PROFILES[args.mech])
    before = validate_corpus(root, mech.record_globs, config, missing_ledger_ok=True)
    pmids, dois = plan(before)
    out = {"mech": args.mech, "root": str(root), "profile": PROFILES[args.mech],
           "before": summary(before), "plan": {"pmids": len(pmids), "dois": len(dois)}}
    print(json.dumps({"before": out["before"], "plan": out["plan"]}))
    if args.apply:
        with LockManager().lock(args.mech, "evidence-adoption-729"):
            out["fetch"] = fetch_missing(root, config, before, apply=True, limit=args.limit).as_dict()
        print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in out["fetch"].items()}))
    after = validate_corpus(root, mech.record_globs, config, missing_ledger_ok=True)
    out["after"] = summary(after)
    out["unrecorded"] = [{k: r[k] for k in ("record", "location", "verdict", "reference")}
                         for r in after["results"]
                         if r["verdict"] not in {"OK", "NO_QUOTE"} and not r.get("known_issue")]
    print(json.dumps({"after": out["after"]}))
    if args.ledger_issue:
        ledger = plan_known_findings(after, args.ledger_issue)
        out["ledger"] = {k: (len(v) if isinstance(v, list) else v) for k, v in ledger.items()}
        print(json.dumps({"ledger": out["ledger"]}))
        if args.apply and ledger["rows"]:
            with LockManager().lock(args.mech, "evidence-adoption-729"):
                write_known_findings(root, LEDGER, ledger["rows"])
    args.json.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
